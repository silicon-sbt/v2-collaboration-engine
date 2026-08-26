# V2 引擎 M2 需求草案——圆桌评审报告

> 日期：2026-08-25 ｜ 评审对象：docs/v2-collaboration-engine-m2-requirements.md（v0.1）｜ 阵容：experts 圆桌（macroeconomics / investing / computing / philosophy / history）+ moderator
> 结论：**approve_with_concerns（5 位专家一致通过但带保留，无人否决）**

## 1. 共识（全票）

1. 方向正确：M2 应以「可证明值得跑 / 可控地跑」为核心，**经济理性闭环 + 最小记忆 + 元问题验收**是主轴。
2. **当前范围过大，必须拆分**：G1–G6 六目标 12 条 FR 一次绑定，违背 M1「一条里程碑闭一条循环」的增量纪律。
3. **FR11 不进入 M2 核心**：只做纯数据层最小骨架，或降 M3 / 单独 PR；已通过的完整动议（manager LLM 审批 + V1 圆桌双产出）不做。
4. **FR-ECO-5（rep/内化约束）不得作为自动分配器**：只计算/展示或砍掉，避免顺周期紧缩与游戏化。
5. **成本计价签名与 M1 数据模型冲突**：TaskAudit 只有 total_tokens，缺 prompt/completion 拆分与 provider/model；必须补记录或用混合单价并标注「估算」。
6. **反馈指标依赖 per-attempt 历史但 _merge_results 覆盖首指标**：需新增不覆盖的 `attempt_log`，否则 feedback_effectiveness / anchor_coverage_delta 不可算。
7. **写记忆时机须在仲裁通过（verdict.ok）之后**：否则会把「仲裁后将被判失败」的产出持久化造成跨 run 记忆污染。
8. **记忆只做最小切片**：per-agent 分区 + Top-K 注入 + source/links + 可标 stale；置信度精算/冲突覆盖/渐进披露/archive/LLM curation 全部推迟。
9. **执行依赖（写依赖）不引入**，只出做/不做结论。
10. **双模式/全并行降级**：现有波调度已并行独立任务，原子锁/第二调度器是伪需求；降为 mode 旗标 + experimental + invoke 前预检。
11. **未知 provider 成本要显式标注 unknown price / estimated**，run 持久化只落摘要与检索字段。

## 2. 分歧点与倾向

- **元问题判据形态**：覆盖度/锚点字段 vs 对抗性核验（制造错误→系统揭出并修正）。倾向：可追溯/可纠错落既有字段+attempt_log+指标；「可追问」另立对抗性核验协议，并从验收拆出「随记忆完成」。
- **经济理性是否要价值侧**：macro 主张加 cost/有效产出比率；多数主张仅成本侧进 P0。倾向：报告侧加只读价值锚点（cost/DONE-ok-task、cost/coverage-point）并标注近似，不进分配。
- **债务 vs 损耗定性**：确定性规则（下游引用/通过裁决→债务） vs 需人类/圆桌定性。倾向：程序性归类 + provisional 标注，最终定性交人类/圆桌。
- **记忆 kind=fact 可信度**：需携带 audit snapshot provenance；agent_id 统一 persona 分区。
- **反馈指标命名**：feedback_effectiveness→compliance_effectiveness（测程序合规，非质量）。

## 3. 关键决议（resolutions）

| 项 | 决议 |
| --- | --- |
| M2 核心命题 | 收敛为「经济理性闭环 + 元问题验收 + 最小记忆 + 最小持久化」 |
| FR-ECO-2 | 补 prompt/completion 拆分 + provider/model + pricing.yaml（未知 provider 打 unknown+conservative 并标 estimated）；report 分列 priced/estimated |
| FR-ECO-3 | 只做固定软/硬上限分级（标注波级粒度），不做申请-审批；申请-审批并入 governance 推 M3 |
| FR-ECO-4/5 | 损耗明细+报告；rep 只计算并暴露，不设阈值门槛/自动分配 |
| 债务 vs 损耗 | 程序性归类 + provisional 标注，定性交人类/圆桌 |
| FR-ECO-1 | 保留 FAILED→DONE 并更名 compliance_effectiveness；砍 reason_specificity；新增 attempt_log |
| FR5/FR9 | 最小切片：per-persona SQLite 分区 + Top-K 注入 + source/links + 可标 stale；kind 默认 judgment、fact 带 audit provenance；置信度用 coverage×recency；写记忆在仲裁通过后 |
| FR11 | M2 只做纯数据层最小动议（CollabMotion + 拒必带原因 + 同类合并 + 测试 + 结论锚 audit/CollabMessage）；完整机制降 M3/单独 PR |
| T14 | 降级为 mode 旗标 + experimental + invoke 前预检 + 单次 Send；不做原子锁/第二调度器；token/cost 从 generate 返回取 |
| T15 | 只出结论（不引入写依赖） |
| 持久化 | 只落 memory.db + run 摘要 + 检索字段 + 历史查询，不落全量 state |
| §8 验收 | 全部改为可判定最小客观用例 |

## 4. 范围建议（scope_recommendation）

- **核心（P0，先落地）**：FR-ECO-2 成本归属/定价、FR-ECO-4 损耗显性化、FR-ECO-3 固定软/硬上限（波级）、FR-META、FR5 最小记忆切片、T16 最小持久化。
- **延伸（P1/最小/单独 PR）**：FR-ECO-1（compliance_effectiveness，砍 reason_specificity）、FR11 纯数据层最小动议、T14 mode+experimental+预检、T15 只出结论。
- **砍/降级（M2.x/M3/不实现）**：FR-ECO-5 自动信誉分配（只算不 gate）、FR9 完整治理、FR11 完整机制、T14 原子性机器、记忆完整抽取与 MCP 工具化（M3）。

## 5. 待用户定夺（open_questions）

1. 「可追问」是否接受以对抗性核验协议作 M2 验收？
2. 成本计价取「prompt/completion 拆分+provider/model（精确）」还是「总 token×混合单价（近似标注）」？M1 是否为此改 audit 数据结构与重建路径？
3. 记忆 agent_id 统一 persona 分区，task 仅作 source？
4. 债务/损耗是否接受「程序性归类+待归因标注，定性交人类/圆桌」？
5. kind=fact 带 provenance 后是否保留独立检索价值？
6. T14 降级后 parallel 是否需要波内取消能力？
7. 若只有 1-1.5 周，FR11 最小动议是否纳入 M2 还是整块降 M3？
8. §8 验收全部改为可判定最小客观用例是否接受？

## 6. 各专家判定

| 专家 | 视角 | 判定 | 一句话建议 |\n| --- | --- | --- | --- |\n| Macroeconomics | 成本/经济理性 | approve_with_concerns | 拆 M2，先做测量层+最小基础设施；FR-ECO-5 只作诊断，FR11 最小骨架或 M3 |\n| Investing | 成本归属/预算弹性 | approve_with_concerns | P0 收窄为成本归属/损耗/预算弹性 + 最小持久化 + 最小记忆；FR-ECO-5 改为展示/预警；FR11 全量降 M3 |\n| Computing | 架构/可靠/过度设计 | approve_with_concerns | 方向对但大幅收缩；砍 FR-ECO-5、FR11 降 M3、reason_specificity 砍；修写记忆时机/audit 重建/成本拆分/token 竞态四硬伤 |\n| Philosophy | 元问题/认识论 | approve_with_concerns | 砍/降 FR-ECO-5 内化约束与 T14；债务/损耗与反馈质量改透明记录不冒充真值；可追问落为对抗性核验 |\n| History | 范围纪律/工程务实 | approve_with_concerns | 收敛为经济理性闭环+元问题验收+最小持久化；FR-ECO-5 只记账不施加影响；新增 attempt_log 使反馈指标可算 |
