# V2 引擎 T12（事前预算弹性+超支责任+rep 暴露）代码圆桌评审报告

> 日期：2026-08-25 ｜ 对象：collab/costing.py（rep_by_persona）+ graph.py（soft/hard 预算 + overspend_kind + 报告）+ tests/test_collab_budget.py
> 方式：轻量圆桌（3 专家：Computing / Philosophy / History，逐个 subagent 只读 collab/costing.py + 内联接线摘要）。主 agent 综合。
> 结论：approve_with_concerns。预算软/硬与责任接线正确；采纳 1 项 rep 修正；2 项已核实正确/为已知简化。

## 1. 三专家意见（简）

### Computing — approve_with_concerns
- 优点：rep_by_persona 只读、无阈值/无自动分配，符合 FR-ECO-5「只算不 gate」；分母用 attempts 含失败/预算/discard，能反映真实浪费。
- 关注：①（medium）total==0 但 effective>0 时 rep=1.0（数据缺失反而满分）；②（medium）effective 只用 audit.persona_id 未回退 result.persona_id（与 cost_by_persona 不一致）；③（medium）rep 把 debt(超支被接受)计入 effective，超支且被接受者拿满信誉。

### Philosophy — approve_with_concerns
- 优点：rep 确为「只暴露不 gate」；用 done+ok 作分子、全 attempts 作分母，与 waste_breakdown 的 effective 口径一致。
- 关注：①（high）total==0 且 effective>0 → rep=1.0，把数据不一致伪装成「完美信誉」；②（medium）rep 未区分 priced/estimated；③（high）debt(软超支完成)不能被标 failure_type=budget_exceeded，否则 waste/feedback 会误判为 waste——该跨文件前置需确认。

### History — approve_with_concerns
- 优点：rep 纯计算、无 gate；分母含失败/预算执行，比只用 accepted 更真实；口径与 waste_breakdown 一致。
- 关注：①（high）effective 侧 persona 未回退 result.persona_id（与 cost_by_persona 不一致）且 total==0 时给 rep=1.0；②（medium）本文件不含预算软/硬/责任接线，无法在此核实；③（low）rep 重复 cost_by_persona/waste 逻辑且 clamp 会掩盖 effective>total 异常。

## 2. 共识与决议
- 共识：rep_by_persona 方向正确（只算不 gate）；预算软/硬与责任接线（soft 只预警、hard 才 fail/stop；debt=完成+被接受；loss=failed/stopped）与报告波级统计一致。
- 已核实：executor 里「只有硬超支」才写 failure_type=budget_exceeded；「软超支但完成+被接受」的 attempt 是 failure_type=，会被计入 effective 而非 waste → Philosophy 的 cross-file 担忧不成立。
- 已采纳修复（本期 T12）：rep_by_persona ① persona 归因对齐 cost_by_persona（回退 result.persona_id）；② total==0 时省略该 persona（不再默认 1.0），避免「缺数据=满分信誉」。
- 记为已知简化：rep 未区分 priced/estimated；rep 含「被接受的 debt」（超支但被接受仍算有效），作为有效份额信号而非惩罚。
- 范围：FR-ECO-5（rep 用于自动分配/门槛）按 roundtable 决定推迟，T12 只暴露。

## 3. 已落地
- collab/costing.py：rep_by_persona persona 回退 + total==0 省略。
- tests/test_collab_budget.py：+test_rep_omitted_when_no_attempts；全量 collab 105 通过。

## 4. 结论
approve_with_concerns。T12 可作为 M2 预算/责任切片合入；已修 rep 缺数据满分与归因一致性；debt/loss 接线已核实正确。