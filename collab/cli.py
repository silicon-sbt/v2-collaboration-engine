"""collab CLI: the company workflow entry (T17).

Entry B (模式 B 公司) is a *workflow runner / CLI* - NOT an MCP server, and not
the DSH workflow tool (a foreground subagent orchestrator without persistence or
budget). This CLI drives the collab engine:

    python -m collab run <tasks.json> [--provider auto] [--mock] [--mode wave] [--report] [--db PATH]
    python -m collab status <run_id> [--db PATH]
    python -m collab report <run_id> [--db PATH]
    python -m collab list [--limit N] [--db PATH]
    python -m collab stop <run_id> [--reason "..."] [--db PATH]

Runs are persisted in the RunStore (default repo/logs/collab_runs.db) so history
and report survive across invocations.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .llm import resolve_llm
from .memory import MemoryStore
from .motion import CollabMotion, MotionStatus, MotionStore
from .runner import get_collab_status, list_collab_runs, run_collaboration, stop_collab
from .runstore import RunStore
from . import __version__


def _data_dir() -> Path:
    """Writable per-user data dir for persistent stores (pip-install friendly).

    Override with COLLAB_HOME; defaults to ~/.collab so a pip-installed
    package never tries to write into site-packages.
    """
    env_home = os.getenv("COLLAB_HOME", "").strip()
    base = Path(env_home) if env_home else Path.home() / ".collab"
    base.mkdir(parents=True, exist_ok=True)
    return base


DEFAULT_DB_PATH = _data_dir() / "logs" / "collab_runs.db"
DEFAULT_MEMORY_DB_PATH = _data_dir() / "logs" / "collab_memory.db"
DEFAULT_MOTION_DB_PATH = _data_dir() / "logs" / "collab_motions.db"

DEMO_TASKS: list[dict[str, Any]] = [
    {
        "id": "a-research",
        "persona_id": "investing",
        "input": "调研：列出市场风险的主要类别",
        "expected_output": "风险清单",
        "allowed_links": ["b-check"],
    },
    {
        "id": "b-check",
        "persona_id": "macroeconomics",
        "input": "基于 a-research 的风险清单，评估宏观应对",
        "expected_output": "宏观应对建议",
        "data_deps": ["a-research"],
        "allowed_links": ["a-research", "c-summary"],
    },
    {
        "id": "c-summary",
        "persona_id": "history",
        "input": "综合 a-research 与 b-check 的观点，给出历史启示",
        "expected_output": "总结",
        "data_deps": ["a-research", "b-check"],
        "allowed_links": ["b-check"],
    },
]


def _store(db: str = "") -> RunStore:
    return RunStore(db if db else DEFAULT_DB_PATH)


def _mem_store(db: str = "") -> MemoryStore:
    return MemoryStore(db if db else DEFAULT_MEMORY_DB_PATH)


def _motion_store(db: str = "") -> MotionStore:
    return MotionStore(db if db else DEFAULT_MOTION_DB_PATH)


def _load_tasks(path: str) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("tasks must be a JSON array (list of task specs)")
    return data


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_run(args: argparse.Namespace) -> int:
    tasks = _load_tasks(args.tasks)
    store = _store(getattr(args, "db", "") or "")
    memory_store = _mem_store(getattr(args, "memory_db", "") or "")
    audit_llm = None
    if getattr(args, "audit_model", None):
        audit_llm = resolve_llm(
            getattr(args, "audit_provider", "") or args.provider,
            model=args.audit_model,
            root_dir=args.root_dir or None,
        )
    light = bool(getattr(args, "light", False))
    run_id = run_collaboration(
        tasks,
        provider=args.provider,
        mock=args.mock,
        mode=args.mode,
        root_dir=args.root_dir or None,
        run_store=store,
        memory_store=memory_store,
        audit_llm=audit_llm,
        light=light,
    )
    print("run_id: " + run_id)
    # One-shot CLI: a background-thread run is killed when the process exits, so
    # `run` always polls to a terminal status (or --timeout), then prints the
    # status and optionally the report. On timeout/not_found it marks the run
    # stopped rather than leaving an orphaned "running" record.
    status: dict[str, Any] = {}
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        status = get_collab_status(run_id, run_store=store)
        if status.get("status") != "running":
            break
        time.sleep(0.5)
    if status.get("status") == "not_found":
        print("error: run not found", file=sys.stderr)
        _print_json(status)
        return 1
    if status.get("status") == "running":
        stop_collab(run_id, reason="cli timeout")
        print("warning: run did not finish within --timeout; marked stopped", file=sys.stderr)
        _print_json(status)
        return 1
    _print_json(status)
    if args.report and status.get("final_report"):
        print("\n--- final_report ---\n" + str(status.get("final_report")))
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Zero-config showcase: run the built-in cross-referencing scenario.

    Defaults to provider auto so a configured key gives real reasoning and a
    missing key gracefully falls back to the free deterministic mock - no
    tasks.json or API key required. Use --provider deepseek for real reasoning,
    --mock to force the offline demo, or --tasks to run your own scenario.
    """
    tasks = DEMO_TASKS
    if getattr(args, "tasks", ""):
        tasks = _load_tasks(args.tasks)
    store = _store(getattr(args, "db", "") or "")
    memory_store = _mem_store(getattr(args, "memory_db", "") or "")
    audit_llm = None
    if getattr(args, "audit_model", None):
        audit_llm = resolve_llm(
            getattr(args, "audit_provider", "") or args.provider,
            model=args.audit_model,
            root_dir=args.root_dir or None,
        )
    provider = args.provider or "auto"
    print("collab 弱去中心化协作引擎 · 快速体验")
    print("-" * 64)
    print("模式: " + args.mode + ("（轻量：跳过经理裁决）" if args.light else ""))
    print("provider: " + provider + "（auto：有 key 用真实模型，无 key 回退 mock）")
    print("任务数: " + str(len(tasks)) + "，跨 persona 协作（产出 → 引用 → 汇总）")
    print("-" * 64)
    run_id = run_collaboration(
        tasks,
        provider=provider,
        mock=args.mock,
        mode=args.mode,
        root_dir=args.root_dir or None,
        run_store=store,
        memory_store=memory_store,
        audit_llm=audit_llm,
        light=args.light,
    )
    status: dict[str, Any] = {}
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        status = get_collab_status(run_id, run_store=store)
        if status.get("status") != "running":
            break
        time.sleep(0.5)
    if status.get("status") == "not_found":
        print("error: run not found", file=sys.stderr)
        return 1
    if status.get("status") == "running":
        stop_collab(run_id, reason="cli timeout")
        print("warning: run did not finish within --timeout", file=sys.stderr)
        return 1
    print("run_id: " + run_id + " · status: " + status.get("status"))
    report = status.get("final_report") or status.get("error") or ""
    print("\n--- final_report ---")
    print(report)
    return 0

def cmd_status(args: argparse.Namespace) -> int:
    _print_json(get_collab_status(args.run_id, run_store=_store(getattr(args, "db", "") or "")))
    return 0


def _summary_view(report: str) -> str:
    """Deliverable-first view: 3-line status summary + task results (outputs)."""
    lines = report.splitlines()
    header = [
        line for line in lines
        if line.startswith("- 任务数") or line.startswith("- 模式") or line.startswith("- 重试恢复")
    ]
    idx = next((i for i, line in enumerate(lines) if line.startswith("## 任务结果")), None)
    body = lines[idx:] if idx is not None else []
    return chr(10).join(["# 交付物摘要"] + header + body)


def cmd_report(args: argparse.Namespace) -> int:
    st = get_collab_status(args.run_id, run_store=_store(getattr(args, "db", "") or ""))
    report = st.get("final_report") or st.get("error") or "(no report yet)"
    if getattr(args, "summary", False):
        print(_summary_view(report))
    else:
        print(report)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    for r in list_collab_runs(run_store=_store(getattr(args, "db", "") or ""))[: args.limit]:
        print(f'{r["run_id"]}\t{r["status"]}\t{r["created_at"]}')
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    _print_json(stop_collab(args.run_id, reason=args.reason))
    return 0


def cmd_cost(args: argparse.Namespace) -> int:
    st = get_collab_status(args.run_id, run_store=_store(getattr(args, "db", "") or ""))
    keys = [
        "cost_usd", "cost_priced_usd", "cost_estimated_usd", "cost_by_persona",
        "memory_tokens", "memory_cost_usd", "memory_share",
        "waste_cost_usd", "waste_tokens", "waste_reasons",
        "retries_that_succeeded", "tasks_that_retried", "recovery_rate",
    ]
    out = {k: st.get(k) for k in keys if st.get(k) is not None}
    if not out:
        print("(no cost data)")
        return 0
    _print_json(out)
    return 0


def cmd_memory_search(args: argparse.Namespace) -> int:
    entries = _mem_store(getattr(args, "db", "") or "").search(args.agent_id, args.query, top_k=args.top_k)
    _print_json([e.to_dict() for e in entries])
    return 0


def cmd_memory_list(args: argparse.Namespace) -> int:
    entries = _mem_store(getattr(args, "db", "") or "").list(args.agent_id)
    _print_json([e.to_dict() for e in entries])
    return 0


def cmd_memory_stale(args: argparse.Namespace) -> int:
    _mem_store(getattr(args, "db", "") or "").mark_stale(args.agent_id, args.entry_id)
    print("marked stale")
    return 0


def cmd_motion_submit(args: argparse.Namespace) -> int:
    participants = json.loads(args.participants) if args.participants else []
    motion = CollabMotion(
        task_id=args.task_id,
        topic=args.topic,
        rationale=args.rationale,
        proposed_participants=participants,
        budget_source=args.budget_source,
    )
    _motion_store(getattr(args, "db", "") or "").add(motion)
    _print_json(motion.to_dict())
    return 0


def cmd_motion_decide(args: argparse.Namespace) -> int:
    store = _motion_store(getattr(args, "db", "") or "")
    cur = store.get(args.motion_id)
    if cur is None:
        print("error: unknown motion", file=sys.stderr)
        return 1
    committee = json.loads(args.committee) if args.committee else None
    try:
        store.decide(args.motion_id, decision=args.decision, decided_by=args.decided_by, reason=args.reason, committee=committee)
    except ValueError as exc:
        print("error: " + str(exc), file=sys.stderr)
        return 1
    _print_json(store.get(args.motion_id).to_dict())
    return 0


def cmd_motion_list(args: argparse.Namespace) -> int:
    status = MotionStatus(args.status) if args.status else None
    motions = _motion_store(getattr(args, "db", "") or "").list(status)
    _print_json([m.to_dict() for m in motions])
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="collab",
        description="collab workflow runner (company mode / 模式 B)",
        epilog="查看子命令帮助：collab <cmd> --help。",
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="submit a company collaboration from a tasks JSON file")
    p_run.add_argument("tasks", help="path to a JSON file containing the tasks array")
    p_run.add_argument("--provider", default="auto")
    p_run.add_argument("--mock", action="store_true")
    p_run.add_argument("--mode", default="wave", choices=["wave", "parallel"])
    p_run.add_argument("--root-dir", default="")
    p_run.add_argument("--report", action="store_true", help="also print the final report")
    p_run.add_argument("--timeout", type=float, default=120.0, help="seconds to wait when --wait/--report")
    p_run.add_argument("--db", default="", help="RunStore db path (default repo/logs/collab_runs.db)")
    p_run.add_argument("--memory-db", default="", help="MemoryStore db path (default repo/logs/collab_memory.db)")
    p_run.add_argument("--light", action="store_true", help="轻量模式：跳过经理裁决（仅硬规则，少一次 LLM）")
    p_run.add_argument("--audit-model", default="", help="auditor/manager 使用的模型（与执行模型不同，增强独立裁决）")
    p_run.add_argument("--audit-provider", default="", help="auditor 使用的 provider（默认同 --provider）")
    p_run.set_defaults(fn=cmd_run)

    p_demo = sub.add_parser("demo", help="零配置快速体验：内置跨 persona 场景，无需 tasks.json / API key")
    p_demo.add_argument("--tasks", default="", help="(可选) 用你自己的 tasks JSON 文件替换内置场景")
    p_demo.add_argument("--provider", default="auto")
    p_demo.add_argument("--mock", action="store_true", help="强制离线 mock（无 key 也可跑）")
    p_demo.add_argument("--mode", default="wave", choices=["wave", "parallel"])
    p_demo.add_argument("--light", action="store_true", help="轻量模式：跳过经理裁决")
    p_demo.add_argument("--audit-model", default="")
    p_demo.add_argument("--audit-provider", default="")
    p_demo.add_argument("--root-dir", default="")
    p_demo.add_argument("--timeout", type=float, default=120.0)
    p_demo.add_argument("--db", default="", help="RunStore db path")
    p_demo.add_argument("--memory-db", default="", help="MemoryStore db path")
    p_demo.set_defaults(fn=cmd_demo)

    p_status = sub.add_parser("status", help="print status of a run")
    p_status.add_argument("run_id")
    p_status.add_argument("--db", default="")
    p_status.set_defaults(fn=cmd_status)

    p_report = sub.add_parser("report", help="print the final report of a run")
    p_report.add_argument("run_id")
    p_report.add_argument("--summary", action="store_true", help="交付物前置：先给 3 行摘要 + 任务结果，不展开审计日志")
    p_report.add_argument("--db", default="")
    p_report.set_defaults(fn=cmd_report)

    p_list = sub.add_parser("list", help="list recent runs")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--db", default="")
    p_list.set_defaults(fn=cmd_list)

    p_stop = sub.add_parser("stop", help="soft-stop a running run")
    p_stop.add_argument("run_id")
    p_stop.add_argument("--reason", default="user requested")
    p_stop.add_argument("--db", default="")
    p_stop.set_defaults(fn=cmd_stop)

    p_cost = sub.add_parser("cost", help="print cost/waste/recovery of a run")
    p_cost.add_argument("run_id")
    p_cost.add_argument("--db", default="")
    p_cost.set_defaults(fn=cmd_cost)

    p_mem = sub.add_parser("memory", help="memory tools")
    mem_sub = p_mem.add_subparsers(dest="memcmd", required=True)
    p_msearch = mem_sub.add_parser("search", help="search an agent memory")
    p_msearch.add_argument("agent_id")
    p_msearch.add_argument("query")
    p_msearch.add_argument("--top-k", type=int, default=5)
    p_msearch.add_argument("--min-score", type=float, default=None)
    p_msearch.add_argument("--candidate-limit", type=int, default=None)
    p_msearch.add_argument("--db", default="")
    p_msearch.set_defaults(fn=cmd_memory_search)
    p_mlist = mem_sub.add_parser("list", help="list an agent memory")
    p_mlist.add_argument("agent_id")
    p_mlist.add_argument("--db", default="")
    p_mlist.set_defaults(fn=cmd_memory_list)
    p_mstale = mem_sub.add_parser("stale", help="mark a memory entry stale")
    p_mstale.add_argument("agent_id")
    p_mstale.add_argument("entry_id")
    p_mstale.add_argument("--db", default="")
    p_mstale.set_defaults(fn=cmd_memory_stale)

    p_mot = sub.add_parser("motion", help="motion tools (FR11 minimal)")
    mot_sub = p_mot.add_subparsers(dest="motcmd", required=True)
    p_msubmit = mot_sub.add_parser("submit", help="submit a meeting motion")
    p_msubmit.add_argument("task_id")
    p_msubmit.add_argument("topic")
    p_msubmit.add_argument("rationale")
    p_msubmit.add_argument("--participants", default="[]", help="JSON array of participant ids")
    p_msubmit.add_argument("--budget-source", default="task", choices=["task", "global"])
    p_msubmit.add_argument("--db", default="")
    p_msubmit.set_defaults(fn=cmd_motion_submit)
    p_mdecide = mot_sub.add_parser("decide", help="approve/reject a motion (reject needs a reason)")
    p_mdecide.add_argument("motion_id")
    p_mdecide.add_argument("decision", choices=["approved", "rejected"])
    p_mdecide.add_argument("--reason", default="")
    p_mdecide.add_argument("--committee", default="", help="JSON array of final participants")
    p_mdecide.add_argument("--decided-by", default="manager")
    p_mdecide.add_argument("--db", default="")
    p_mdecide.set_defaults(fn=cmd_motion_decide)
    p_mlistm = mot_sub.add_parser("list", help="list motions")
    p_mlistm.add_argument("--status", default="", choices=["pending", "approved", "rejected", "merged", "expired"])
    p_mlistm.add_argument("--db", default="")
    p_mlistm.set_defaults(fn=cmd_motion_list)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
