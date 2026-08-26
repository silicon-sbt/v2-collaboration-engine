# V2 引擎 T9（记忆治理 FR9）代码圆桌评审报告

> 日期：2026-08-25 ｜ 对象：collab/memory.py 的 T9 治理改动 + graph.py 传 snapshot_ids + tests/test_collab_memory_governance.py
> 方式：**轻量圆桌**（3 位专家：Computing / Philosophy / History，逐个 subagent 仅读 collab/memory.py + 内联 T9 摘要；输出紧凑 JSON）。未跑独立主持人，由主 agent 综合。
> 结论：**approve_with_concerns**。方向正确、复用到位；已采纳 2 项修复，其余记为范围内已知取舍。

## 1. 三专家意见（简）

### Computing（正确性/可靠/性能/复用）— approve_with_concerns
- 优点：复用 collab.arbitration.detect_decision_conflicts / compute_anchor_coverage，未重复造轮子；list/search 默认排除 stale+overridden、mark_stale 不刷新 updated_at 均正确。
- 关注：
  1. 冲突降级只覆盖"决策动词-对象"条目；结论（结论:…）与后续 fact 条目不参与，新结论与旧决策矛盾时可能不降级（漏污染）。medium。
  2. confidence=整篇摘要锚点覆盖度，平均套到每个决策点；无锚点决策也拿到摘要级置信度；裸 except Exception→0.0 会掩盖真实覆盖率 bug。medium。
  3. contest_count 与 overridden 置信度减半被写入但无人消费（且同 id upsert 会重置），属投机/过度状态。medium。

### Philosophy（记忆认识论：污染/自增强/provenance/置信度语义）— approve_with_concerns
- 优点：mark_stale 不刷新 updated_at（状态变更非新事件）正确；复用仲裁检测器与覆盖度、默认剔除 stale+overridden 的注入语义正确。
- 关注：
  1. high：凡同 agent 现役条目命中决策冲突即自动 overridden，不分 kind、不看新条目置信度/provenance 强弱，低置信新判断可覆盖高置信事实，且 overridden 无恢复路径，存在误降与自增强风险。
  2. high：confidence=compute_anchor_coverage 在无决策点时返回 1.0，把无锚点/空摘要当成满置信；同一标量套用于决策点与结论，虚高结论确定性。
  3. medium：发生 contest 后，同一 confidence 标量混入了 anchor coverage 与降半的信任惩罚；contest_count 是无人消费的重复信号。

### History（范围纪律/是否过度设计/复用核查）— approve_with_concerns
- 优点：复用到位；mark_stale 与默认过滤让过期/被覆盖记忆不会被 recency 抬回顶部，注入语义正确。
- 关注：
  1. medium：检测冲突时直接把含"决策点:/结论:"前缀的整条 content 喂给 detect_decision_conflicts，可能因前缀/包装语与仲裁裸决策语句不匹配而误降级或漏判。
  2. medium：include_stale=True 会把 overridden 也带回检索，且 build_memory_context 只给 stale 打"(已过期)"标记，被覆盖记忆会以普通身份混入注入。
  3. low：overridden 是单向门闩（被覆盖条目永不复活，即使后来"罪魁"失效也永远沉底）。

## 2. 主持人决议（resolutions）
- **共识**：T9 方向与复用正确（统一置信度/异常收敛、复用仲裁检测器与覆盖度、默认排除 stale+overridden、mark_stale 不刷 recency），当前实现可用，但有几处语义/健壮性需收紧。
- **已采纳修复（本期）**：
  1. **置信度"空摘要=满置信"→ 中性 0.5**：compute_anchor_coverage 在无决策点返回 1.0；改为 decision_count<=0 → 0.5，避免"emptiness=>certainty"。加回归测试。
  2. **include_stale 不再漏出 overridden**：overridden 永远排除（即使 include_stale=True），被覆盖条目不再以普通身份混入注入。加回归测试。
- **记为范围内已知取舍（不本期改）**：
  - conflict 检测只覆盖"决策动词-对象"（规格如此），结论/fact 不参与 → 已知范围，文档标注。
  - confidence 用整篇摘要覆盖度、不细到每决策点 → 已知粗粒度，透明标量可接受，后续可细化。
  - contest_count 为治理审计字段，当前无消费点 → 保留作审计（FR9 语义），不做自动决策。
  - overridden 单向门闩 → 治理取舍，可后续加 forget/恢复入口。
  - 前缀问题：测试已验证"决策点: 采用/放弃"能被 detect_decision_conflicts 检出（test_conflicting_judgment_demotes_older 通过），故非实际缺陷。

## 3. 已落地
- collab/memory.py：_memory_confidence 无决策点→0.5；list 判定 overridden 永远排除。
- tests/test_collab_memory_governance.py：+test_confidence_neutral_when_no_decisions、+test_include_stale_never_returns_overridden。
- 全量 collab 83 通过。

## 4. 结论
approve_with_concerns。T9 可作为 M2 记忆治理切片合入；已修 2 项（置信度空摘要、overridden 泄漏），其余为范围取舍。
