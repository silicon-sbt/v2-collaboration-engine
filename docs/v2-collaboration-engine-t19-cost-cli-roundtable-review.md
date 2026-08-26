# V2 引擎 T19（成本/损耗/预算接入 CLI）代码评审报告

> 日期：2026-08-26 ｜ 对象：collab/runner.py（_build_summary 增列）+ collab/cli.py（cmd_cost + p_cost 子命令）+ tests/test_collab_cli.py
> 方式：自审 + 专家视角综合（Computing/Philosophy/History 三视角，in-context）。结论：approve。

## 1. 交付
- get_collab_status 摘要（_build_summary）增列成本/损耗/恢复：`cost_usd`/`cost_priced_usd`/`cost_estimated_usd`/`cost_by_persona`、`waste_cost_usd`/`waste_tokens`/`waste_reasons`、`retries_that_succeeded`/`tasks_that_retried`/`recovery_rate`。
- `python -m collab cost <run_id> [--db PATH]`：读摘要这些字段；无可用数据（mock=0 成本）输出 `(no cost data)` 并返回 0，不报错。
- 复用 collab/costing.py（cost_summary / waste_breakdown / feedback_summary），未新增计价逻辑。
- 测试：`test_build_summary_includes_cost_waste_recovery`（单元）+ `test_cli_cost_reads_persisted_summary`（CLI 读持久摘要）；全量 collab **138 passed**（138 = 136 + 2 新增）。

## 2. 正确性/复用
- 摘要只在**非零**时写入：cost_total>0 才写成本组；waste>0 才写损耗组；tasks_that_retried>0 才写恢复组。避免 0 成本/0 损耗/无重试时输出误导字段。
- `cost` 子命令按 `st.get(k) is not None` 过滤，残缺摘要也能渲染。
- 成本字段与 costing 返回键名一一对应，无错位。

## 3. 三视角
- **Computing**：实现薄、复用 costing 纯函数；空/残缺状态安全（.get 兜底）；`get_collab_status` 对 live run（状态未 done）也会算 cost/waste，行为一致不炸。无过度抽象。
- **Philosophy**：把「成本/损耗/恢复」在**运行器摘要层**显性化，而非只在报告文本里——符合可观测/可审计初衷；estimated 单独字段区分未知 provider，诚实标注不确定性。
- **History**：与既有 costing（T10-12）、runstore（T16 只存摘要）约定一致：runstore 只落 `_build_summary` 摘要，T19 扩展正好补齐成本维度，无 schema 变更冲突。

## 4. 结论
approve。T19 可合入（m2 分支）。成本/损耗/预算已接入 CLI 且数字正确、estimated 单独标注；下一步 T20（记忆开销计入成本）。