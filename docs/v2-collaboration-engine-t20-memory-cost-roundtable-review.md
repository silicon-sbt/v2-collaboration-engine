# V2 引擎 T20（记忆开销计入成本，FR-GAP-1）代码评审报告

> 日期：2026-08-26 ｜ 对象：collab/models.py + audit.py（TaskAudit 增 memory_tokens）+ graph.py（executor 记录 memory_tokens + 报告行）+ costing.py（memory_summary）+ runner.py（_build_summary 增列）+ cli.py（cost 列表增记忆字段）+ tests
> 方式：自审 + 专家视角综合（Computing/Philosophy/History）。结论：approve_with_concerns。

## 1. 交付
- `TaskAudit` 增 `memory_tokens`（默认 0，__slots__/to_dict/from_dict 恢复均已同步）。
- executor 用项目 tokenizer（`rag.config.tokenize`）对注入的 `memory_context` 计 token，写入 audit + attempts。
- `costing.memory_summary(results)`：记忆 token 是 prompt 成本的一个**子集**（已在 prompt_tokens 里计价过），输出 `memory_tokens`/`memory_cost_usd`（按输入价）/`memory_share`（占总成本比例），**不重复累加**。
- 报告行：`- 记忆开销(USD): $X（N token，占总成本 Y%）`（仅当 memory_tokens>0）。
- run 摘要（`_build_summary`）增 `memory_tokens`/`memory_cost_usd`/`memory_share`（非零才写入）；`collab cost` 输出列表增这三个字段。
- 测试：`test_memory_summary_is_subset_not_addition`、`test_memory_summary_skips_missing_audit`、`test_executor_writes_memory_tokens_into_audit_and_report`；全量 collab **141 passed**（=138+3）。

## 2. 正确性/不重复计价
- memory_cost 仅由 memory_tokens 按输入单价算出，绝不加到 `cost_summary`（cost_usd 仍等于 prompt+completion 全价）。
- TaskAudit 恢复路径（models.from_dict 与 graph 状态重建）都读 `memory_tokens`，旧记录缺失时回落 0。
- memory_tokens 由本地 tokenizer 近似（同为 rag.tokenize，与记忆打分一致），故 memory_cost 是**估算口径**，报告未标注 estimated——这是 concerns 之一。

## 3. ⭐ 实质发现（concerns）
1. **memory_tokens 是本地 tokenizer 代理，不是 LLM token 数**：memory_cost 是近似值，报告宜标注「估算」或不喧宾夺主（当前只在成本行内出现，未改动总计）。
2. **只统计已接受任务的审计**：memory_summary 只读 `results` 的 audit；重试/失败 attempt 的 memory_tokens 虽已写入 attempts，但未纳入 memory_summary（即记忆读取开销在多次尝试时未完全显性化）。
3. **记忆读取本属 prompt 成本**：本次只是「拆分显示」而非新增计费，避免把同一 token 重复计入成本——语义上正确，需在 README/指南里说清是 breakdown。

## 4. 结论
approve_with_concerns。T20 可合入（m2 分支）。记忆开销已可见（独立字段 + 报告行），且**不重复计价**；下一步可选：报告标注「估算」+ 把 attempts 的记忆 token 纳入 memory_summary（跨尝试完整口径），或随 T21 search 上界一起收口。