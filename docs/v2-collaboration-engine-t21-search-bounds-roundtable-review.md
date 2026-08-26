# V2 引擎 T21（search 分数阈值 + 候选上限，FR-GAP-2）代码评审报告

> 日期：2026-08-26 ｜ 对象：collab/memory.py（MemoryStore.search 增 min_score/candidate_limit；list 增 limit）+ collab/cli.py（memory search --min-score/--candidate-limit）+ tests/test_collab_memory.py
> 方式：自审 + 专家视角综合（Computing/Philosophy/History）。结论：approve_with_concerns。

## 1. 交付
- `search(..., min_score=DEFAULT_MIN_SCORE=1.0, candidate_limit=DEFAULT_CANDIDATE_LIMIT=50, include_stale=False)`：
  - `min_score`：过滤 `s > 0.0 and s >= min_score`；命中低于阈值 → 返回 [] → `build_memory_context([])` 返回 "" → **无强命中不注入**。
  - `candidate_limit`：改用 `self.list(..., limit=candidate_limit)` 以 SQL `LIMIT` 界住「每 agent 候选扫描」为最多 N 条（最近优先），不再 O(N) 全表打分；`None`=不限。
- `MemoryStore.list` 增 `limit: int | None = None`（两分支 SQL 均加 `LIMIT ?`）。
- CLI `memory search` 增 `--min-score`/`--candidate-limit` 透传。
- 测试：`test_search_min_score_gate_no_strong_hit_no_injection`、`test_search_candidate_limit_bounds_scan`；全量 collab **143 passed**（=141+2）。

## 2. 正确性/复用
- 阈值门控与上限都复用 `rag.config.tokenize`（与记忆打分同一 tokenizer，不引入第二套）。
- `list` 的 `limit` 仅影响 search 的候选集，`memory list` CLI 不受影响（不传 limit）。
- 既有 `search(agent_id, query, top_k)` 调用（含 graph executor）现默认被门控/上限，全量测试通过说明未破坏强命中场景。

## 3. ⭐ 实质发现（concerns）
1. **min_score=1.0 可能偏松**：tokenize 按单字切分，score≈overlap×recency×conf，单字重叠在新近/中置信条目约=1.0，即默认会放入「仅 1 个常见字重叠」的弱命中。建议保留可调；若需更强可改归一化 overlap（overlap/query_len）或提高默认，但增复杂度。
2. **candidate_limit 牺牲长尾**：按最近 N 条扫描，若唯一相关记忆较旧（>N 条之外）会被漏掉而误判「无强命中」。这是「有界扫描」的明确代价，已文档化；`candidate_limit=None` 可放开。
3. **默认行为变化**：此前任何词汇命中都会注入；现在默认门控+上限，是 FR-GAP-2 的**有意行为变更**，需在指南说清（新的唯一默认值满足 NFR §7.9）。

## 4. 结论
approve_with_concerns。T21 可合入（m2 分支）。search 具备「无强命中不注入」+ 每 agent 候选上限，且给出了唯一默认值；concerns 为阈值松紧/长尾取舍，均可在运营时调节。