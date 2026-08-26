# V2 引擎 T11（损耗显性化+反馈质量）代码圆桌评审报告

> 日期：2026-08-25 ｜ 对象：collab/costing.py（waste_breakdown/feedback_summary）+ graph.py（attempt_log 接线 + 报告）+ tests/test_collab_waste.py
> 方式：轻量圆桌（3 专家：Computing / Philosophy / History，逐个 subagent 只读 collab/costing.py + 内联接线摘要）。主 agent 综合。
> 结论：**approve_with_concerns**。核心正确（且已核实 audit 成本非累计）；采纳 2 项修复；1 项为已验证正确/已知取舍。

## 1. 三专家意见（简）

### Computing — approve_with_concerns
- 优点：waste_breakdown 复用已有 attempt.cost_usd/audit.cost_usd，不重复计价；把 failed/retry/budget 统一纳入 attempts，修复 T10 漏算；feedback_summary 明确标注为 compliance 代理、按 roundtable 砍掉 reason_specificity。
- 关注：①（high）waste_reasons 不列"重试但最终成功"的先前 attempt（manager_revise 无 failure_type），浪费不可完全审计；②（medium）feedback 在 needed=0 返回 1.0、且"重试10次 vs 1次"等价；③（medium）effective 取 result.audit、total 取 attempts，二者一致性依赖接线。

### Philosophy — approve_with_concerns
- 优点：attempts 是唯一应计费源（success/budget/transient 都进 total），失败/重试不会被静默漏算；reason 用 dict.fromkeys 去重；文档明确 compliance 为 proxy、不宣称真实质量，未重复造轮子。
- 关注：①（high）若 result.audit.cost_usd 是任务级累计，total-effective 会把成功任务的自身重试成本冲掉、损耗被低估；②（medium）waste_reasons 只列 3 种 failure_type + failed 结果，manager_revise 覆盖的先前成功 attempt 与泛型 failure 不进入原因；③（medium）compliance 在 needed=0 返回 1.0、且比例把"重试后最终完成"当合规/质量有效性，易误导。

### History — approve_with_concerns
- 优点：有效/损耗以 attempts 为单一成本真源、把 failed/retry/budget 显性化，确实修复 T10 漏算；docstring 明确"不作为真实质量"且砍 reason_specificity，范围克制。
- 关注：①（high）waste_reasons 忽略无 failure_type 的重试（manager_revise）+ 只输出 'id:type' 字符串、无每条量级，审计性不足；②（high）feedback_summary 在 needed=0 返回 1.0、且名字 compliance_effectiveness 实为恢复率易误导；③（medium）effective(审计) 与 total(attempts) 一致性 + attempt 每条执行分支恰好一条的记录无法在 costing.py 核实。

## 2. 共识与决议
- **共识**：方向正确、修复 T10 漏算、无重复造轮子、范围克制。
- **已核实（好消息）**：executor 的 audit.cost_usd 是**单次执行**成本（build_audit 传当前 attempt 的 cost_usd，未累计），所以 total(attempts) − effective(audit) 是**准确**的损耗——"audit 累计"的担忧不成立。
- **已采纳修复（本期 T11）**：
  1. **feedback_summary→recovery_rate**：更名，needed==0 时返回 None（0 重试≠100% 有效）。
  2. **waste_reasons 结构化 + 覆盖 manager_revise**：reasons 改为 [{id, failure_type, attempt, token_usage, cost_usd}]；用 attempt 序号精确标记"被后续重试覆盖(superseded)/超预算/失败"的 attempt（无 failure_type 的 manager_revise 也被标 superseded）；报告按 id:type($cost) 显示。
- **记为已知取舍**：feedback_summary 是恢复率代理（非质量）；失败/重试损耗在原因清单里按任务级聚合（attempt 级信息已保留在结构化字段，可进一步展开）。

## 3. 已落地
- collab/costing.py：waste_reasons 结构化 + superseded 检测；feedback_summary 更名 recovery_rate + None。
- collab/graph.py：报告格式化结构化原因 + recovery。
- tests/test_collab_waste.py：+superseded、+recovery None；全量 collab 100 通过。

## 4. 结论
approve_with_concerns。T11 可作为 M2 损耗/反馈切片合入；已修 recovery_rate 语义 + waste_reasons 可审计性；audit 成本非累计已核实为准确。
