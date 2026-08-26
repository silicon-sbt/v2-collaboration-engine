# V2 引擎 T10（成本归属+计价）代码圆桌评审报告

> 日期：2026-08-25 ｜ 对象：collab/costing.py + TaskAudit cost 字段 + graph 执行器/仲裁/报告接线 + tests/test_collab_costing.py
> 方式：**轻量圆桌**（3 专家：Computing / Philosophy / History，逐个 subagent 仅读 collab/costing.py + 内联接线摘要；紧凑 JSON）。主 agent 综合。
> 结论：**approve_with_concerns**。方向正确、数据源复用到位；采纳 2 项修复，1 项归 T11。

## 1. 三专家意见（简）

### Computing — approve_with_concerns
- 优点：复用 OpenAICompatLLM.last_usage 作为唯一数据源，不新造发现层；保守单价 + 未知 provider 标 estimated、mock 免费。
- 关注：① 单价按 provider 家族、is_estimated 只看 provider 不看 model → 已知 provider 的 premium 模型会被低估且不标 estimated（high）；② cost_by_persona 只聚合带 audit 的结果，failed/重试/budget-exceeded 可能漏算（medium）；③ cost_summary 未分列 priced/estimated（medium）。

### Philosophy（成本透明/公平/可信）— approve_with_concerns
- 优点：每 1K 换算正确、未知 provider 更高默认价 + is_estimated、mock 归零；cost_by_persona 按 persona_id 聚合并带 unknown 兜底。
- 关注：① price_tokens 的 model 参数未用，同一 provider 不同模型价格被抹平（medium）；② is_estimated 未被聚合层暴露，report 仍显示无标注 total_usd，§11.2-1 可能不满足（high）；③ 无 audit 结果被静默跳过、缺失 cost_usd 记 0，failed/重试成本低估（medium）。

### History（范围纪律/过度设计/复用）— approve_with_concerns
- 优点：计价换算正确且保守；复用 last_usage、未新造发现层；costing.py 小而清晰、pricing 可注入。
- 关注：① cost_by_persona 无状态过滤，failed/重试/budget-exceeded 若未写 audit.cost_usd 会漏算（high）；② cost_summary 未带 priced/estimated 分列，§11.2-1 的标注丢失（medium）；③ price_tokens 的 model 参数死参，易误导为已支持 model 级计价（low）。

## 2. 共识与决议
- **共识**：数据源复用正确（last_usage），未重复造轮子；计价/聚合方向对；但存在"model 死参 / §11.2-1 未分列 / 失败重试成本可能漏算"三处需处理。
- **已采纳修复（本期 T10）**：
  1. **model 参数落地**：price_tokens/is_estimated 支持 provider:model 键查找，model 不再死参（可注入 model 级单价）。
  2. **priced/estimated 分列**：cost_summary 增加 priced_usd/estimated_usd/estimated_persona；report 显示"其中估算成本(USD)"与"其中估算按 Persona"。
- **归 T11（损耗显性化，记入待办）**：failed/重试/budget-exceeded 结果的 token 成本未计入（执行器不写 audit.cost_usd）→ 总成本可能低估。这是 T11 损耗显性化的核心，不在 T10 硬改。
- **记为已知简化**：默认单价为 provider 家族级，未覆盖 provider 内 model 分层（除非注入 provider:model）；未知"premium model within known provider"暂按 provider 价并视为 priced（文档标注）。

## 3. 已落地
- collab/costing.py：price_tokens/is_estimated 支持 provider:model；cost_summary 分列 priced/estimated；新增 estimated_by_persona。
- collab/graph.py：report 显示估算成本拆分。
- tests/test_collab_costing.py：+2（model override、priced/estimated split）；全量 collab 94 通过。

## 4. 结论
approve_with_concerns。T10 可作为 M2 成本归属切片合入；已修 model 死参 + §11.2-1 分列；失败/重试成本归因移交 T11。
