# V2 引擎：M2 里程碑收官评审（全量回归 + 自审 + 圆桌）

> 日期：2026-08-25 ｜ 性质：M2 收官 ｜ 方式：全量回归 + 上下文自审 + 轻量 3 专家圆桌（Computing/Philosophy/History）
> 结论：**ready_with_concerns**（可收官；3 条后续需盯）。

## 1. 全量回归
- 命令：python -m pytest tests/ -q → **192 passed / 5 failed / 2 skipped / 1 warning**。
- **5 个失败全部是预存在的 Windows 路径分隔符断言**（knowledge\... vs knowledge/...，在 test_graph / test_rag / test_ingest_source_kind），**与 M2 无关**（V1 平台问题）。
- V2（collab）全绿：本版 collab 套件 **127 passed**。

## 2. 自审（已做并修正）
- 一致性：AGENT_GUIDE / PROJECT_MEMORY 已同步所有 M2 模块（memory/costing/motion/runstore/graph 新接口）。
- 修正：① AGENT_GUIDE 的 runner 三函数签名补 run_store（T16 遗漏）；② collab/__init__.py docstring 补 M2 范围。
- 待办（故意滞后，dtodo）：search score 阈值 + 候选上限（f88501d9）；记忆开销计入成本闭环（6118c50d）。

## 3. M2 圆桌（轻量 3 专家）—— 一致 ready_with_concerns
### 优点（全票）
- **范围克制**：FR11 纯数据层、T15 只出结论、T14 降级标记 experimental、T16 最小持久化；P0 经济理性闭环 + 最小记忆切片确实收敛。
- **审计诚实/防游戏**：写记忆仅在仲裁通过后、attempt_log 不被 _merge_results 覆盖、损耗/债务程序性归类并标注 estimated/provisional、rep 只暴露不设门槛、成本按 persona 报出。
- **演进一致/无重复造轮子**：记忆冲突复用 M1 detect_decision_conflicts、provenance 对齐 audit 快照锚点、audit.cost_usd 核实为非累计。
- 每任务均「自审+轻量圆桌」落档并采纳修复，闭环证据链完整。

### 3 条后续（concerns）
1. **5 个 V1 预存在失败未处理**（medium）：污染「全绿」基线。→ 建议 M3 前快速修复或转 xfail 并挂跟踪单。
2. **记忆开销未计入成本闭环 + search 仍 O(N)/无 score 阈值**（medium-high）：P0「经济理性闭环」对记忆子系统不完整。→ 显式宣示为 **M3 缺口**（见 §4），非隐含于 M2。
3. **元问题「协作未被稀释」无显式裁决**（medium）。→ 见 **§5 FR-META 裁决**。

## 4. 声明：M2 边界（显式缺口）
- **记忆开销计入成本闭环**（记忆检索/注入 token 纳入 costing/waste）→ **M3**（dtodo 6118c50d）。
- **search score 阈值 + 候选上限**（现 O(N) 全表打分）→ **M3/记忆量大时**（dtodo f88501d9）。
- **崩溃后 run 永久 running**（RunStore）→ **M3**。
- **FR11 完整机制**（manager LLM 审批/圆桌双产出/参会方增删/自由裁量额度/MERGED 语义）→ **M3**。
- **执行依赖（写依赖）** → **不引入**（T15 结论）；M3 仅规划「读依赖时序触发」为可选 FR。

## 5. FR-META 裁决（元问题：「协作是否被稀释」）
**结论：不稀释，且已操作化可验证。** V2 与 V1 的本质区别确为「状态机让协作责任可追溯、可纠错、可追问」，而非「多了一个状态机」。
- **可追溯**：任意产出可定位到任务/persona/输入快照/引用锚点/token→成本（M1 审计 + M2 成本/provenance 锚点）。
- **可纠错**：裁决可被硬规则/经理机制修正；attempt_log 保留重试与 recovery_rate；预算/损耗可审计（M1 T5 + M2 T10/T11）。
- **可追问**：产出引用带审计快照锚点（跨任务接口契约锚点）；记忆带 provenance。**强化**「对抗性核验」（制造错误→系统揭出并修正）→ **M3**（已记为准入 M3 的强化项）。

## 6. 结论
M2 **达到收官标准（ready_with_concerns）**：核心交付闭环、范围克制、审计诚实。建议：
- 进 M3 前：**快速处理 5 个 V1 预存在失败**（或 xfail + 跟踪单）、把 **记忆开销计入成本 + search 上界** 列为 **M3 首任务**、**元问题裁决已落档**。
