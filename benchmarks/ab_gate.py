"""A/B non-inferiority gate: V1 roundtable (Entry A - meeting) vs V2 collaboration engine (Entry B - company).

Same topic, same persona cards, same model (DeepSeek deepseek-chat), same pricing table.
Measures real token usage / cost / wall time for both arms, then a rubric judge scores the
two final outputs blind under two orderings (position-bias control).

Usage (run from anywhere; both repos are located automatically, or pass --v1-root/--v2-root):
    python benchmarks/ab_gate.py --mock                  # plumbing check, no API cost
    python benchmarks/ab_gate.py --real --repeats 3      # real arms + blind judge per repeat

The V1 arm needs the agent-roundtable-mcp checkout ("Entry A · Meeting"); the V2 arm is
this repo. The judge is the same model as the arms, scoring blind under two orderings.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
WORKSPACE = BENCH_DIR.parent


def _find_root(candidates: list[Path], marker: str) -> Path | None:
    """First existing candidate that carries the marker path (e.g. roundtable/graph.py)."""
    for candidate in candidates:
        if (candidate / marker).exists():
            return candidate.resolve()
    return None


def _default_v1_root() -> Path | None:
    env = os.getenv("AB_V1_ROOT", "").strip()
    if env:
        return Path(env)
    bases = [BENCH_DIR.parent, BENCH_DIR.parent.parent, BENCH_DIR.parent.parent.parent]
    return _find_root([b / "agent_roundtable" for b in bases], "roundtable/graph.py")


def _default_v2_root() -> Path | None:
    env = os.getenv("AB_V2_ROOT", "").strip()
    if env:
        return Path(env)
    if (WORKSPACE / "collab" / "runner.py").exists():
        return WORKSPACE.resolve()
    return _find_root([BENCH_DIR.parent / "v2-collaboration"], "collab/runner.py")


V1_ROOT: Path | None = _default_v1_root()
V2_ROOT: Path | None = _default_v2_root()

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
JUDGE_MODEL = "deepseek-chat"

TOPIC = (
    "一个开源的多 Agent 协作引擎目前已经跑通：任务分派、审计、仲裁、成本归属与报告。"
    "开发资源只有一个开发者、两周时间。下一步应该优先做哪三件事、砍掉什么？"
    "请给出明确的取舍、理由，以及可验证的验收标准。"
)

PERSONAS = ["computing", "philosophy", "history"]

RUBRIC = [
    ("coverage", "覆盖度：是否识别出关键维度与真正的取舍点"),
    ("actionability", "可执行性：建议是否具体、可落地、有优先级"),
    ("argument", "论证质量：依据是否成立、权衡是否清楚、有无逻辑漏洞"),
    ("risk", "反方与风险视角：是否主动指出失败模式与反对意见"),
    ("structure", "结构与清晰度：是否易于阅读和决策"),
]


# --------------------------------------------------------------------------- helpers
def load_deepseek_key() -> str:
    """Read the DeepSeek key the same way the MCP does (~/.dsh/.credentials.yaml)."""
    env = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if env:
        return env
    path = Path(os.path.expanduser("~/.dsh/.credentials.yaml"))
    raw = path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"DEEPSEEK_API_KEY\s*:\s*['\"]?([A-Za-z0-9._\-]{12,})", raw)
    if not match:
        raise SystemExit("no DEEPSEEK_API_KEY in env or ~/.dsh/.credentials.yaml")
    return match.group(1)


def price_usd(prompt_tokens: int, completion_tokens: int) -> float:
    """Price both arms with the V2 engine's own pricing table (fair, single source)."""
    sys.path.insert(0, str(V2_ROOT))
    from collab.costing import price_tokens

    return price_tokens("deepseek", JUDGE_MODEL, prompt_tokens, completion_tokens)


class CountingLLM:
    """Proxy that accumulates objective usage from an inner OpenAI-compatible client."""

    def __init__(self, inner, max_usd: float = 0.0, label: str = "") -> None:
        self.inner = inner
        self.provider_name = getattr(inner, "provider_name", "unknown")
        self.model = getattr(inner, "model", "unknown")
        self.label = label
        self.max_usd = max_usd
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        text = self.inner.generate(prompt)
        usage = getattr(self.inner, "last_usage", None) or {}
        self.calls += 1
        self.prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
        self.completion_tokens += int(usage.get("completion_tokens", 0) or 0)
        self.prompts.append(prompt)
        if self.max_usd and price_usd(self.prompt_tokens, self.completion_tokens) > self.max_usd:
            raise RuntimeError(
                "cost guard tripped for %s: $%.4f > $%.4f (calls=%d)"
                % (self.label, price_usd(self.prompt_tokens, self.completion_tokens), self.max_usd, self.calls)
            )
        return text

    @property
    def last_usage(self) -> dict:
        """Forward the inner client's objective usage.

        The V2 audit reads llm.last_usage for every call; without this the engine's own
        token/cost accounting silently reports 0 for a real run.
        """
        return getattr(self.inner, "last_usage", None) or {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        }

    def stats(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "cost_usd": round(price_usd(self.prompt_tokens, self.completion_tokens), 6),
        }


def make_bench_root(work: Path) -> Path:
    """A V1 root with a 3-persona council and an empty knowledge corpus.

    The upstream knowledge/experts/* corpora are empty in this checkout already, so the
    roundtable arm gets no retrieval hits either way - the comparison is about the
    coordination structure, not about corpus grounding.
    """
    root = work / "v1_bench_root"
    (root / "config" / "councils").mkdir(parents=True, exist_ok=True)
    (root / "config" / "domain_experts").mkdir(parents=True, exist_ok=True)
    for persona in PERSONAS:
        shutil.copy(V1_ROOT / "config" / "domain_experts" / (persona + ".yaml"),
                    root / "config" / "domain_experts" / (persona + ".yaml"))
    cfg = V1_ROOT / "config" / "agent_llms.json"
    if cfg.exists():
        shutil.copy(cfg, root / "config" / "agent_llms.json")
    (root / "knowledge" / "experts").mkdir(parents=True, exist_ok=True)
    (root / "knowledge" / "people").mkdir(parents=True, exist_ok=True)
    for persona in PERSONAS:
        (root / "knowledge" / "experts" / persona).mkdir(parents=True, exist_ok=True)
    (root / "config" / "councils" / "ab_three.yaml").write_text(
        "name: \"ab_three\"\n"
        "description: \"A/B bench council: computing + philosophy + history\"\n"
        "members:\n" + "".join("  - %s\n" % p for p in PERSONAS) + "moderator: \"moderator\"\n",
        encoding="utf-8",
    )
    return root


def persona_card_text(persona) -> str:
    """The same grounding both arms get: V1 renders it from config, V2 receives it in input."""
    return (
        "人格卡：\n"
        "- 名称：%s\n- 角色：%s\n- 世界观：%s\n- 说话风格：%s\n- 优势：%s\n- 弱点：%s\n- 口头禅：%s"
        % (
            persona.name, persona.role, persona.worldview, persona.speaking_style,
            "、".join(persona.strengths), "、".join(persona.weaknesses), "、".join(persona.catchphrases),
        )
    )


# --------------------------------------------------------------------------- arm A (V1)
def run_v1(topic: str, rounds: int, work: Path, max_tokens: int, mock: bool, max_usd: float) -> dict:
    sys.path.insert(0, str(V1_ROOT))
    from roundtable.graph import run_roundtable
    from roundtable.loader import load_council_personas

    bench_root = make_bench_root(work)
    _council, personas = load_council_personas("ab_three", bench_root)

    if mock:
        from llm.providers_api import MockLLM

        llm = CountingLLM(MockLLM(model="mock"), max_usd=max_usd, label="v1")
    else:
        from mcp_server.llm_client import OpenAICompatLLM

        llm = CountingLLM(
            OpenAICompatLLM(api_key=load_deepseek_key(), base_url=DEEPSEEK_BASE_URL,
                            model=JUDGE_MODEL, provider_name="deepseek", max_output_tokens=max_tokens),
            max_usd=max_usd, label="v1",
        )

    started = time.time()
    state = run_roundtable(topic=topic, council_name="ab_three", rounds=rounds, llm=llm,
                           root_dir=bench_root, output_dir=str(work / "v1_logs"))
    elapsed = time.time() - started

    messages = list(state.get("messages", []))
    transcript = "\n\n".join(
        "[%s] %s" % (m.get("speaker", "?"), m.get("content", "")) for m in messages
    )
    return {
        "arm": "A_v1_roundtable",
        "final": state.get("final_summary", ""),
        "transcript": transcript,
        "messages": len(messages),
        "wall_seconds": round(elapsed, 1),
        "personas": [p.id for p in personas],
        "stats": llm.stats(),
    }


# --------------------------------------------------------------------------- arm B (V2)
def run_v2(topic: str, work: Path, max_tokens: int, mock: bool, max_usd: float, timeout_s: int = 900) -> dict:
    """Run the V2 engine through its synchronous entry (the same graph the CLI worker drives).

    run_collab_sync is exactly what run_collaboration's worker thread calls; using it
    directly keeps the full terminal state (per-task output, attempts) that the async
    status digest drops. Cost/waste come from the engine's own accounting helpers.
    """
    sys.path.insert(0, str(V2_ROOT))
    import collab.graph as cg
    from collab.costing import cost_summary, waste_breakdown
    from collab.graph import run_collab_sync
    from collab.runner import _task_from_spec

    sys.path.insert(0, str(V1_ROOT))
    from roundtable.loader import load_persona

    bench_root = make_bench_root(work)
    cards = {p: persona_card_text(load_persona(p, bench_root)) for p in PERSONAS}

    tasks = []
    for persona in PERSONAS:
        tasks.append({
            "id": "p-" + persona,
            "persona_id": persona,
            "input": "%s\n\n话题：%s\n请从你的角色出发给出判断、取舍与理由。" % (cards[persona], topic),
            "expected_output": "一份立场明确的判断：优先做什么、砍掉什么、理由与验收标准。",
        })
    tasks.append({
        "id": "summary",
        "persona_id": PERSONAS[0],
        "input": (
            "你是本次协作的汇总方（相当于圆桌主持人）。话题：%s\n"
            "请综合前面三位专家的产出：找出真正共识、明确分歧、给出最终建议清单"
            "（按优先级排序）与风险提示。" % topic
        ),
        "expected_output": "最终建议清单（含优先级）、分歧说明与风险提示。",
        "data_deps": ["p-" + p for p in PERSONAS],
    })

    if mock:
        from collab.llm import MockLLM

        counting = CountingLLM(MockLLM(model="mock"), max_usd=max_usd, label="v2")
    else:
        from collab.llm import OpenAICompatLLM

        counting = CountingLLM(
            OpenAICompatLLM(api_key=load_deepseek_key(), base_url=DEEPSEEK_BASE_URL,
                            model=JUDGE_MODEL, provider_name="deepseek", max_output_tokens=max_tokens),
            max_usd=max_usd, label="v2",
        )
    cg.resolve_llm = lambda *a, **k: counting  # inject the counting client into the engine path

    started = time.time()
    state = run_collab_sync([_task_from_spec(t) for t in tasks], provider="deepseek",
                            mock=mock, root_dir=str(V2_ROOT))
    elapsed = time.time() - started

    results = list(state.get("results", []))
    attempts = list(state.get("attempts", []))
    summary_result = next((x for x in results if x.get("id") == "summary"), None)
    final = str((summary_result or {}).get("output") or "") or str(state.get("final_report", ""))
    cost = cost_summary(results)
    waste = waste_breakdown(results, attempts)
    engine = {
        "run_path": state.get("run_path"),
        "mode": state.get("mode"),
        "token_total": state.get("token_total", 0),
        "cost_usd": cost["total_usd"],
        "cost_priced_usd": cost["priced_usd"],
        "cost_estimated_usd": cost["estimated_usd"],
        "cost_by_persona": cost["per_persona"],
        "waste_cost_usd": waste["waste_cost_usd"],
        "waste_tokens": waste["waste_tokens"],
        "attempts": len(attempts),
        "results": [{"id": x.get("id"), "status": x.get("status"), "failure_type": x.get("failure_type", "")}
                    for x in results],
        "errors": list(state.get("errors", [])),
    }
    return {
        "arm": "B_v2_collab",
        "status": "done" if all(x.get("status") == "done" for x in results) else "partial",
        "final": final,
        "report": state.get("final_report", ""),
        "wall_seconds": round(elapsed, 1),
        "engine_summary": engine,
        "stats": counting.stats(),
    }


# --------------------------------------------------------------------------- judge
def judge_pair(topic: str, text_a: str, text_b: str, label_a: str, label_b: str, max_tokens: int) -> dict:
    """Score two outputs with a rubric; caller swaps order to control position bias."""
    import requests

    rubric_text = "\n".join("- %s：%s（1-5 分）" % (key, desc) for key, desc in RUBRIC)
    prompt = (
        "你是严格的方案评审专家。下面是同一个问题的两份回答（匿名，只有编号）。\n"
        "话题：%s\n\n"
        "=== 回答 %s ===\n%s\n\n=== 回答 %s ===\n%s\n\n"
        "请按以下维度分别给两份回答打分（整数 1-5，5 最好）：\n%s\n\n"
        "只输出 JSON，格式：{\"scores\": {\"%s\": {\"coverage\": n, ...}, \"%s\": {...}}, "
        "\"winner\": \"%s\"|\"%s\"|\"tie\", \"reason\": \"一句话\"}"
        % (topic, label_a, text_a, label_b, text_b, rubric_text, label_a, label_b, label_a, label_b)
    )
    response = requests.post(
        DEEPSEEK_BASE_URL + "/chat/completions",
        headers={"Authorization": "Bearer " + load_deepseek_key(), "Content-Type": "application/json"},
        json={"model": JUDGE_MODEL, "messages": [{"role": "user", "content": prompt}],
              "temperature": 0, "max_tokens": max_tokens, "response_format": {"type": "json_object"}},
        timeout=300,
    )
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage") or {}
    return {
        "order": label_a + "|" + label_b,
        "raw": content,
        "parsed": json.loads(content),
        "judge_prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "judge_completion_tokens": int(usage.get("completion_tokens", 0) or 0),
    }


# --------------------------------------------------------------------------- replicate
def one_replicate(topic: str, rep_dir: Path, args) -> dict:
    """Run both arms once (sequentially) and score them with a blind, order-swapped judge."""
    rep_dir.mkdir(parents=True, exist_ok=True)
    a = run_v1(topic, args.rounds, rep_dir, args.max_tokens, args.mock, args.max_usd)
    print("  arm A v1:", json.dumps(a["stats"], ensure_ascii=False), "wall=%ss" % a["wall_seconds"], flush=True)
    b = run_v2(topic, rep_dir, args.max_tokens, args.mock, args.max_usd)
    print("  arm B v2:", json.dumps(b["stats"], ensure_ascii=False),
          "engine_token_total=%s wall=%ss" % (b["engine_summary"]["token_total"], b["wall_seconds"]), flush=True)

    (rep_dir / "v1_final.md").write_text(a["final"], encoding="utf-8")
    (rep_dir / "v1_transcript.md").write_text(a["transcript"], encoding="utf-8")
    (rep_dir / "v2_final.md").write_text(b["final"], encoding="utf-8")
    (rep_dir / "v2_report.md").write_text(b.get("report", ""), encoding="utf-8")

    result = {"topic": topic, "rounds": args.rounds, "personas": PERSONAS,
              "arm_a": {k: v for k, v in a.items() if k != "transcript"},
              "arm_b": {k: v for k, v in b.items() if k != "final"}}

    if args.real:
        # pass 1 labels the first text "A" (= v1); pass 2 swaps the order and labels the
        # first text "B" (= v2). Keeping the label -> arm mapping explicit here is what
        # prevents the two passes from being averaged across the wrong arm.
        j1 = judge_pair(topic, a["final"], b["final"], "A", "B", 900)
        j2 = judge_pair(topic, b["final"], a["final"], "B", "A", 900)
        stats = {
            "prompt_tokens": j1["judge_prompt_tokens"] + j2["judge_prompt_tokens"],
            "completion_tokens": j1["judge_completion_tokens"] + j2["judge_completion_tokens"],
        }
        stats["cost_usd"] = round(price_usd(stats["prompt_tokens"], stats["completion_tokens"]), 6)
        result["judge"] = {"pass1": j1, "pass2": j2, "stats": stats}

        arm_scores = {"v1": [j1["parsed"]["scores"]["A"], j2["parsed"]["scores"]["A"]],
                      "v2": [j1["parsed"]["scores"]["B"], j2["parsed"]["scores"]["B"]]}
        summary = {}
        for arm, entries in arm_scores.items():
            summary[arm] = {}
            for key, _desc in RUBRIC:
                vals = [float(e.get(key, 0)) for e in entries]
                summary[arm][key] = round(sum(vals) / len(vals), 2)
            summary[arm]["total"] = round(sum(summary[arm][k] for k, _ in RUBRIC), 2)
        result["scores"] = summary
        result["judge_winners"] = [j1["parsed"].get("winner"), j2["parsed"].get("winner")]

        cost_v1 = a["stats"]["cost_usd"]
        cost_v2 = b["stats"]["cost_usd"]
        q_v1, q_v2 = summary["v1"]["total"], summary["v2"]["total"]
        result["verdict"] = {
            "cost_v1_usd": cost_v1, "cost_v2_usd": cost_v2,
            "cost_ratio": round(cost_v2 / cost_v1, 3) if cost_v1 else None,
            "quality_v1": q_v1, "quality_v2": q_v2, "quality_delta": round(q_v2 - q_v1, 2),
            "engine_token_total_v2": b["engine_summary"]["token_total"],
            "engine_cost_usd_v2": b["engine_summary"]["cost_usd"],
            "gate": "FAIL (more expensive AND worse)" if (cost_v2 > cost_v1 and q_v2 < q_v1) else "PASS (non-inferior)",
        }
        print("  verdict:", json.dumps(result["verdict"], ensure_ascii=False), flush=True)

    (rep_dir / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def _mean(values: list) -> float:
    vals = [v for v in values if isinstance(v, (int, float))]
    return round(sum(vals) / len(vals), 4) if vals else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--max-tokens", type=int, default=900)
    ap.add_argument("--max-usd", type=float, default=0.30)
    ap.add_argument("--out", default="")
    ap.add_argument("--v1-root", default="", help="agent-roundtable-mcp checkout (Entry A baseline)")
    ap.add_argument("--v2-root", default="", help="root of this repo (defaults to the checkout holding collab/)")
    args = ap.parse_args()
    if args.real == args.mock:
        raise SystemExit("pass exactly one of --real / --mock")

    global V1_ROOT, V2_ROOT
    if args.v1_root:
        V1_ROOT = Path(args.v1_root)
    if args.v2_root:
        V2_ROOT = Path(args.v2_root)
    if V1_ROOT is None or not (V1_ROOT / "roundtable" / "graph.py").exists():
        raise SystemExit("V1 checkout not found (needs roundtable/graph.py); pass --v1-root")
    if V2_ROOT is None or not (V2_ROOT / "collab" / "runner.py").exists():
        raise SystemExit("V2 checkout not found (needs collab/runner.py); pass --v2-root")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    work = Path(args.out) if args.out else BENCH_DIR / "runs" / stamp
    work.mkdir(parents=True, exist_ok=True)

    print("topic:", TOPIC[:50], "...")
    print("v1 root:", V1_ROOT)
    print("v2 root:", V2_ROOT)
    print("work dir:", work, "| repeats:", args.repeats)

    results = []
    for i in range(args.repeats):
        print("--- replicate %d/%d ---" % (i + 1, args.repeats), flush=True)
        results.append(one_replicate(TOPIC, work / ("rep%d" % (i + 1)), args))

    if args.real and results:
        agg = {
            "repeats": len(results),
            "cost_v1_usd": _mean([r["verdict"]["cost_v1_usd"] for r in results]),
            "cost_v2_usd": _mean([r["verdict"]["cost_v2_usd"] for r in results]),
            "cost_ratio_mean": _mean([r["verdict"]["cost_ratio"] for r in results]),
            "quality_v1_mean": _mean([r["verdict"]["quality_v1"] for r in results]),
            "quality_v2_mean": _mean([r["verdict"]["quality_v2"] for r in results]),
            "quality_delta_mean": _mean([r["verdict"]["quality_delta"] for r in results]),
            "gates": [r["verdict"]["gate"] for r in results],
            "judge_winners": [r.get("judge_winners") for r in results],
            "scores_v1_mean": {k: _mean([r["scores"]["v1"][k] for r in results]) for k, _ in RUBRIC},
            "scores_v2_mean": {k: _mean([r["scores"]["v2"][k] for r in results]) for k, _ in RUBRIC},
            "engine_token_total_v2_mean": _mean([r["verdict"]["engine_token_total_v2"] for r in results]),
            "total_spend_usd": round(
                sum(r["arm_a"]["stats"]["cost_usd"] + r["arm_b"]["stats"]["cost_usd"]
                    + r["judge"]["stats"]["cost_usd"] for r in results), 6),
        }
        agg["verdict"] = (
            "FAIL (more expensive AND worse)" if (agg["quality_delta_mean"] < 0 and agg["cost_ratio_mean"] > 1)
            else ("PASS (non-inferior)" if agg["cost_ratio_mean"] <= 1 or agg["quality_delta_mean"] >= 0
                  else "INCONCLUSIVE")
        )
        (work / "aggregate.json").write_text(json.dumps(agg, ensure_ascii=False, indent=1), encoding="utf-8")
        print("=== aggregate (" + str(len(results)) + " replicates) ===")
        print(json.dumps(agg, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
