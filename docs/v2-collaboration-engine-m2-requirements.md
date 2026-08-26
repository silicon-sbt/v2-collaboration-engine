# V2 弱去中心化多 Agent 协作引擎：M2 项目需求与实现方案

> 版本：v0.2（已自审 + 圆桌评审，按决议修订）｜日期：2026-08-25
> 上游：docs/v2-collaboration-engine-requirements.md（V2 总需求，M1 已交付）
> 状态：`先落需求与细节，为后续写 M2 做铺垫`；本文件不推 GitHub，待内容完成后再随文档一起上传。
> 仓库：https://github.com/silicon-sbt/agent-roundtable-mcp

---

## 1. 概述：从 M1 到 M2

M1 已交付`模式 B 协作执行的最小闭环`（`collab/` 包，65 测试通过）：

- 异步任务状态机（T1）`pending→running→done/failed/blocked/stopped`
- L2 审计（T2）输入快照 + 摘要双轨 + token 客观核验
- 分波执行子图（T3）`manager → Send fan-out → execute_task → manager 循环 → arbitrate → collect`
- 横向交流（T4）引用锚点 + 指名回应 + 定向投递（allowed_links）
- 分层裁决（T5）硬规则 → 经理暂定；failure_type 分流（audit_invalid / conflict / manager_revise）
- 失败恢复 + 双层预算（T6）transient/manager_revise 重试 1 次；任务 80k / 全局 400k 熔断 + 单任务回滚
- 异步入口（T7）`run_collaboration` → `get_collab_status` / `stop_collab`

**M1 收官的圆桌决议**：M1 只验证了`流程闭环`（128 passed），**未验证经济理性**——成本效率闭环是 M2 的目标。同时 M1 遗留几项明确推迟到 M2 的能力（记忆、FR11、执行依赖评估、双模式开关、全并行原子性）。

M2 的目标不是`再堆功能`，而是**把 M1 从`能跑`推向`可证明它值得跑 / 可控地跑`**，并补齐 M1 明确推迟的能力。核心判断（§10.6 元问题）：V2 与 V1 的本质区别应是**`状态机让协作责任可追溯、可纠错、可追问`**，而非`多了一个状态机`。M2 的一切设计都围绕这个判断展开。

---

## 2. M1→M2 交接（现状盘点，写 M2 前必须对齐）

| M1 能力 | 现状 | M2 缺口 |
| --- | --- | --- |
| token 审计 | `TaskAudit.token_usage`（LLM client `last_usage` 客观字段） | 只记 token，**不记账成本（USD）**，无法`归属到人` |
| 预算 | 任务 `budget_tokens`（80k）+ 全局 `GLOBAL_TOKEN_BUDGET`（400k）事后熔断 | **事后**熔断，无**事前弹性**；超支责任归属（债务 vs 损耗）未定；损耗未显性化 |
| 裁决 | 硬规则 → 经理暂定（`manager_arbitrate`），`failure_type` 分流 | 无`反馈质量`可计算指标；重试是否因反馈而**变好**不可测量 |
| 横向交流 | `CollabMessage`（reply_to/references/receivers），定向投递 | FR11 会议动议权（子 Agent 申请圆桌）未实现 |
| 记忆 | **无** | FR5 跨会话记忆分区 + FR9 治理（M2 重头） |
| 执行依赖 | 数据依赖（data_deps 分波）已实现；**执行依赖**（A 完成触发 B）M1 否决 | M2 评估是否引入（DAG 复杂度 vs 收益） |
| 双模式 | 默认分波调度 | T3 遗留：显式`全并行`开关 + 全并行就绪检查原子性 |
| 持久化 | runner 内存 `_RUNS`（单进程） | M2 持久化（重启不丢 run / 记忆库） |

---

## 3. 目标与非目标

### 3.1 目标（M2 之后，模式 B 具备`可控的、可问责的、有记忆的、成本理性的协作`）

- G1：**跨会话持久记忆**（FR5）：每个子 Agent 有独立、可检索、可治理的记忆分区，注入而非全量拼接。
- G2：**成本可归属、可计价、可显性化**（M1→M2 缺口 ①-⑤）：能回答`这场协作花了多少钱、花在谁身上、其中多少是有效产出、多少是损耗`。
- G3：**事前预算弹性约束**：在任务/申请**发起时**就知道预算边界和责任归属，而非事后结算。
- G4：**FR11 会议动议权**：子 Agent 可申请召集模式 A 圆桌，经理审批、拒绝必带原因、可调整参会方。
- G5：**元问题落地**：给出`协作责任可追溯/可纠错/可追问`的操作性判据，防止 M1 的务实选择被默认为`协作稀释`。
- G6：**补齐 M1 遗留**：双模式开关 + 全并行原子性；执行依赖评估结论。

### 3.2 非目标（M2 之外）

- 不做 MCP 工具化（`run_collaboration`/`manage_tasks`/会议动议工具暴露给 DSH/Claude Code）→ **M3**。
- 不做完全 mesh / 跨进程自治 Agent 网络 / 第二套运行时（沿用 M1 约束）。
- 不做子 Agent 自主拉起其他 Agent 的递归授权。
- **不在 M2 内上线到 DSH/Claude Code**——M2 的交付物是 Python 层机制 + 测试，M3 才接 MCP。

---

## 4. M2 范围（需求条目）

| 编号 | 需求 | 优先级 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| FR5 | 跨会话持久记忆（分区 + 检索/摘要注入） | P0 | 总需求 §4 | 每个子 Agent 独立记忆分区；检索 Top-K + 旧记忆摘要；不拼接全量历史 |
| FR9 | 记忆治理（版本化/陈旧标注/经理可否定） | P1 | 总需求 §4 | 条目带时间戳/来源/置信度；经理可否决或标记过期；防记忆污染 |
| FR11 | 会议动议权（子 Agent 申请圆桌） | P1 | 总需求 §9.5 定稿 | 触发混合 + 二元审批（拒绝必带原因）+ 参会方模型 + 并发批量合并 |
| FR-ECO-1 | 反馈质量可计算代理指标 | P1 | M1 收官缺口① | 不靠 LLM 自评，用可计算代理指标衡量`反馈是否让重试变好` |
| FR-ECO-2 | 成本归属到人的定价 | P0 | 缺口② | token→成本（USD）按 persona/任务归集，可计价 |
| FR-ECO-3 | 事前预算弹性约束 | P0 | 缺口③ | 预算在发起/申请时弹性分配 + 责任归属（债务 vs 损耗） |
| FR-ECO-4 | 损耗显性化 | P1 | 缺口④ | 重试/超支/被裁决打回产生的浪费显式记录、可审计 |
| FR-ECO-5 | 成本归属内化为行动者约束 | P1 | 缺口⑤ | 成本/损耗影响行动者信誉/下次配额，形成内化约束 |
| FR-T3-3 | 双模式开关 | P1 | T3 圆桌遗留③ | 默认分波 + 显式全并行；阈值写审计 |
| FR-T3-4 | 全并行原子性 | P1 | T3 遗留④ | 全并行就绪检查原子性；不证明则标记实验性 |
| FR-EXEC-DEP | 执行依赖（A 完成触发 B）评估 | P2 | M1 否决项 | 给出`做/不做`及实现代价评估 |
| FR-META | 元问题评审（协作本质） | P0 | §10.6 | 给出`协作责任可追溯/可纠错/可追问`操作性判据 |

---

## 5. 逐项详细设计

### 5.1 记忆与持久化（FR5 + FR9）

**目标**：每个子 Agent 有**跨 run** 的独立记忆，执行新任务时**按需注入**，且**可治理、可污染防护**。

#### 5.1.1 记忆分区（Checkpointer）

- **决策**（承接总需求 §7.3）：不把记忆塞进 LangGraph checkpointer 当黑盒；**独立建一个 per-agent 记忆库**（SQLite），按 `agent_id` 分区。理由：LangGraph checkpointer 是 graph 级快照，若按 agent 隔离需额外 thread-key 映射，且把`记忆`与`图运行状态`耦合，不利于检索/摘要/治理。
- **存储模型**（新增 `collab/memory.py`）：

```python
class MemoryEntry:
    id: str                # mem-<uuid>
    agent_id: str          # 记忆归属（persona_id 或 task_id）
    kind: str              # "fact" | "judgment" | "preference" | "todo" | "correction"
    content: str           # 记忆正文
    source: str            # 来源（task id / message id / round 号）
    created_at / updated_at: datetime
    confidence: float      # 0-1（主观+锚点覆盖度，见 5.1.3）
    status: str            # "active" | "stale" | "overridden"（FR9 治理）
    tags: list[str]        # 检索标签（话题/任务关键词）
    links: list[str]       # 关联 memory id（防`事实扩散`的可追溯链）
```

- **写入**：任务 `DONE` 时，从 `TaskAudit.output_summary` / `output_reasoning` 抽取事实与判断写入该 agent 的记忆分区；写锁（线程/事务）防并发。**只抽取值得长期保留的事实/判断/偏好（curation），不把原始长文整体写入，防止记忆膨胀。**
- **检索**（不拼接全量，防平方级膨胀）：给定当前任务的 `input` + `persona_id` + 关联 `tags`，取 Top-K（默认 K=5）。检索打分：关键词重叠 + 来源新旧衰减 + confidence 加权；超阈值才注入。
- **注入**：在 `collab/graph._build_task_prompt` 增加`记忆`段（放在 persona hint 之后、任务输入之前），明确标注`（记忆）`与`（当前任务输入）`边界，避免 agent 把记忆当任务指令。

#### 5.1.2 注入策略与防污染

- **摘要压缩**：旧记忆（>N 条或 >M 天）压缩成摘要条目，正文进 archive；检索优先返回摘要，命中摘要后再按需展开原文（渐进式披露，呼应 DSH 记忆的 progressive disclosure）。
- **防记忆污染（FR9）**：
  - 每条记忆带 `source` + `links`，可回溯到产出记录（**与审计单一事实源挂钩**）。
  - 配置可`过时`：经理可把某记忆标记 `stale`（如`该判断已在新证据下失效`），检索时降权。
  - 冲突检测：新记忆与已有记忆在 `confidence` 高时冲突 → 标记为 `correction`/`overridden`，不静默覆盖。

#### 5.1.3 记忆置信度（承接 T4 圆桌`摘要置信度可验证`）

- 复用 M1 的 `collab.arbitration.compute_anchor_coverage` 概念：记忆的 confidence = 锚点覆盖度（引用的跨任务快照数 / 决策点数） × 时间衰减 × (1 - 被否决次数)。
- **事实层/判断层分离**（T4 圆桌共识）：`kind=fact` 走结构化核验；`kind=judgment` 显式标注依据/时间/性质。检索注入时告知 agent 哪些是`已核验事实`、哪些是`待印证判断`。

#### 5.1.4 持久化

- **记忆库**：SQLite（`collab/memory.db`，默认 gitignored 路径），按 `agent_id` 分区；重启不丢。
- **run 持久化**（FR10 增强）：`runner._RUNS` 目前纯内存（`list_collab_runs`）。M2 把 run 记录 + 结果摘要落 SQLite，`get_collab_status` 支持查询历史 run。**注意**：`Task.from_dict` 已支持时间戳重建（`_parse_dt`），为持久化做好铺垫。

### 5.2 经济理性闭环（FR-ECO-1 ~ 5）

M1 只记了 token。M2 要让成本**可归属、可计价、可显性化、可约束**。

#### 5.2.1 成本归属到人的定价（FR-ECO-2）

- 扩展 `TaskAudit`：新增 `cost_usd`（由 token 数 × 单价得出），以及 `persona_id`（任务默认带）。
  - **定价来源要落地**：`config/agent_llms.json` 只存 provider 链，**不含单价**，不能作为定价来源。M2 需在 `mcp_server/llm_client` 或新增 `config/pricing.yaml` 提供**每千 token 成本表**（按 provider 家族），缺省用保守单价；未知 provider 用`参考成本`（token 换算）。
- 归集：`get_collab_status` / report 增加**按 persona 的成本汇总**（每 persona 花多少、占多少）。
- 统一计价入口：`collab/costing.py`——给定 `provider` + `model` 返回单价；默认用保守单价（防低估），无单价时用 token 数换算的`参考成本`。

```python
def price_tokens(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float
def cost_by_persona(results: list[dict]) -> dict[str, float]
def waste_breakdown(results: list[dict]) -> dict   # 见 5.2.4
```

#### 5.2.2 损耗显性化（FR-ECO-4）

- **区分`有效产出 token`与`损耗 token`**：
  - 有效：最终 `DONE` 且 verdict `ok` 的产出 token。
  - 损耗：a) 被裁决打回（`manager_revise`/`conflict`/`audit_invalid`）的产出 token；b) 重试额外消耗；c) 全局/任务超支部分；d) 被 `stop_collab` 中止的未完成部分。
- 报告新增`损耗明细`：`waste_tokens` / `waste_cost_usd` / `waste_reason`。**这不只是记账**——圆桌 T6 已指出`超支责任归属（债务 vs 损耗）`，M2 要落地。

#### 5.2.3 事前预算弹性约束（FR-ECO-3）

- 现在是事后熔断：`_route_after_manager` 用 `token_total > GLOBAL_TOKEN_BUDGET`（且是波边界语义，同波并行无法中止）。
- M2 引入**事前弹性预算**：
  - 每个任务/每场 run 在**发起前**分配`预算包`（任务配额 + 全局信封），写入 `Task` / run 记录。
  - 预留弹性：给每个任务一个`软上限/硬上限`；**弹性来自`申请-审批`**（子 Agent 需要超预算时申请，经理批不批，见 FR11 预算来源与 FR-ECO-5 内化约束）。
  - **责任归属显式化**：超支时判定是**损耗**（可避免的浪费 → 扣行动者信誉）还是**债务**（必要的深挖成本 → 记为合理超支）。判定依据：是否产出被下游 `DONE` 引用 / 是否通过裁决。
- 实现：`_route_after_manager` 的预算检查从`硬停`改为`分级`（软上限触发预警并审计、硬上限触发熔断），并**在 overspend 记账时写入 cost 与责任标签**。

#### 5.2.4 反馈质量可计算代理指标（FR-ECO-1）

- **问题**：M1 里 `_route_after_manager` 把 `manager_revise` 结果喂回 `retry_feedback` 重试一次，但**无法测量`这次反馈是否真的让重试变好`**。
- **代理指标**（不靠 LLM 自评，可计算）：
  1. `feedback_effectiveness = 重试后 verdict 是否由 FAILED 变 DONE`（可计算）。
  2. `waste_reduction = 重试相对首次消耗的额外 token`（反馈好 → 一次成功、额外 token 少）。
  3. `anchor_coverage_delta = 重试后 coverage - 首次 coverage`（反馈引导补引用 → 置信度上升）。
  4. `reason_specificity`：反馈文本是否包含结构化改进指令（如`引用 xx 快照``明确结论`），用锚点/动词命中率做代理。
- **用法**：这些指标写入审计与报告，作为`经理反馈质量`的客观信号；同时是 FR-ECO-5 行动者约束（反馈质量差 → 经理后续少给该 agent 弹性预算）和后续 M2+ 的`是否值得重试`闸门。
  - **一律标注为近似代理**：确定性最高的是 `feedback_effectiveness`（FAILED→DONE 可计算）；`reason_specificity` 是启发式（动词/锚点命中率），仅作辅助信号，**不作硬规则**。

#### 5.2.5 成本归属内化为行动者约束（FR-ECO-5）

- 给每个子 Agent 一个**信誉/预算分**：`rep = 有效产出率 - 损耗率`，随 run 积累。
- 检索/仲裁/预算分配时，动作者的 `rep` 影响：a) 下次预算弹性额度；b) 是否优先裁决；c) 是否允许发起 FR11 会议动议（低于阈值需更高理由质量）。
- **设计纪律**：信誉只影响**资源与流程**（预算/优先权/动议门槛），**不直接否决**产出质量——质量仍由硬规则+经理裁决，避免`声誉压过事实`。

### 5.3 FR11 会议动议权

> 设计定稿取自总需求 §9.5（2026-08-24 用户确认 + 三方评审），M2 将其落地为机制。

#### 5.3.1 数据模型（新增 `collab/motion.py`）

```python
class MotionStatus(str, Enum):
    PENDING = "pending"   # 已申请，待经理审批
    APPROVED = "approved" # 批准（可调整主题/参会者后批准）
    REJECTED = "rejected" # 拒绝，必须带原因
    MERGED = "merged"     # 与同类动议合并为一个会
    EXPIRED = "expired"   # 超时/超出自由裁量额度未处理

class CollabMotion:
    id: str                # motion-<uuid>
    task_id: str           # 申请方（子 agent）绑定的任务
    topic: str             # 会议主题/目的
    rationale: str         # 申请理由（质量决定重试门槛）
    proposed_participants: list[str]  # 申请方提议的参会者（非全员）
    budget_source: str     # "task" | "global"（预算来源，§9.5 第7点）
    status: MotionStatus
    reviewed_by: str       # 经理 persona
    decision_reason: str   # 审批原因（拒绝必带）
    committee: list[str]   # 经理最终确定的参会方
    outputs: dict          # 产出双份：申请方 + 经理；抄送清单
    created_at / decided_at
```

#### 5.3.2 触发与审批流程

1. **触发（混合）**：事件驱动为主（完成任务里程碑/发现跨领域冲突/需要外部输入）+ 每任务 1 次**自由裁量额度**。
2. **审批（二元）**：经理 `APPROVED`/`REJECTED`；**拒绝必带原因**，否则退回重审（保证可审计、可改进）。
3. **重试**：允许，但**必须给出更好理由**（理由质量高于上次）——用 FR-ECO-1 的 `reason_specificity` 作为客观门槛参考，而非固定冷却期。
4. **参会方**：申请方提议 → 经理增删（`committee`）；产出**申请方 + 经理两份结论**；经理决定**抄送**哪些其他子 agent。
5. **并发**：经理**批量处理 + 同类可合并**（`MERGED`），多个申请一次审一批。
6. **边界**：会议申请是横向交流（点对点）的**补充**，解决不了的问题才申请集体会议。
7. **预算**：申请时指定来源（任务配额 or 全局），经理审批时确认。

#### 5.3.3 图接入

- 新增 `manager` 下的**动议路由**节点：在执行过程中，若 agent 产生动议事件 → 暂存 `motions` state → 经理在波边界批量审批。
  - **执行端触发口**：当前子 Agent 只产出文本，没有`申请开会`通道。M2 需在 executor 结果里增加可选 `motion_request` 字段（topic/rationale/proposed_participants/budget_source），或让 executor 按约定标记触发；经理在波边界收集并批量审批。
- 动议通过后，调用**模式 A 圆桌**（V1 `roundtable` 可复用）产出双份结论，结论以 `CollabMessage` 形态定向投递给 `committee`/抄送方。
- **注意**：M2 只做 Python 层机制；是否暴露为 MCP 工具 → M3。`run_roundtable` 的 `memory/reply_to` 扩展 → M3。

### 5.4 双模式开关 + 全并行原子性（FR-T3-3 / FR-T3-4）

- **双模式**：`run_collab_sync(..., mode="wave"|"parallel")`。默认 `wave`（现状分波，数据依赖安全）；`parallel`=显式全并行（仅当所有任务 data_deps 为空且做了就绪检查）。
- **全并行原子性**：进入 `parallel` 前做**原子就绪检查**——确认所有任务无未满足 `data_deps`、无循环依赖、预算信封足够；检查与启动之间加锁，防止状态被并发改动。**不证明原子性前，`parallel` 标记为实验性**（`experimental=true` 写进审计），默认 `wave`。
- 阈值：把`何时可用 parallel`及其条件写进审计（`mode`, `reason`, `experimental`）。

### 5.5 执行依赖（A 完成触发 B）评估（FR-EXEC-DEP）

- **现状**：`data_deps` 已是`数据依赖`（B 引用 A 的已审计产出，分波保证 A 先终态）。这是**读依赖**。
- **`执行依赖`**是强耦合：A 完成后**触发** B 执行，且 B 可能**修改** A 的产出（写依赖）。这会引入 **DAG 拓扑排序 + 部分结果回滚 + 循环检测**，复杂度和风险显著上升（M1 已否决）。
- **M2 评估结论**（建议，待圆桌确认）：**M2 不引入写依赖**。理由：
  1. M1 的 `data_deps`（读依赖）+ 分波已覆盖`基于他人产出推进`的大部分场景。
  2. 写依赖需要 DAG 拓扑 + 版本化产出，与 M1 的`单任务级回滚 + 结果按 id 合并`冲突（合并会被写依赖破坏）。
  3. 收益不明确（真实协作中`重写他人产出`应走`经理暂定 + 圆桌申诉`而非依赖触发）。
- **若圆桌坚持引入**：最小实现=只做`读依赖的时序触发`（A 终态 → B 进入 ready 队列），不改写依赖；作为 M2 可选 FR。

### 5.6 元问题评审（FR-META）

- **问题**（§10.6）：M1 的务实选择（L2 审计 + 暂定裁决 + 拉模式交流）是否悄悄成为`协作被稀释`的默认前提？V2 与 V1 的本质区别应否是`状态机让协作责任**可追溯、可纠错、可追问**`？
- **M2 给出操作性判据**（每条可检查）：
  - **可追溯**：任意产出可定位到任务、persona、输入快照、引用锚点、token 消耗（M1 已具备 + M2 加成本）。
  - **可纠错**：任一裁决可被硬规则/经理机制修正；重试/回滚可审计（M1 已具备 + M2 加反馈质量指标）。
  - **可追问**：收信方有权追问信源（M1 的`可追问`要求、T4 圆桌的跨任务接口契约锚点）；某人声称的产出事实可否被验证（锚点覆盖度 + 记忆置信度）。
- **落点**：把这三条写成 M2 的**验收判据**（见 §8），并作为 M3 文档的`V2 设计哲学`。

---

## 6. 与 M1 代码的对接点（改代码前必读）

| M2 改动 | 触及 M1 代码 |
| --- | --- |
| 记忆注入 | `collab/graph._build_task_prompt`（新增`记忆`段）；`collab/graph._executor_node_factory`（执行前检索该 persona 记忆） |
| 成本记账 | `collab/models.TaskAudit`（新增 cost_usd/persona_id）；`collab/audit.build_audit`；`collab/graph._collect_node`/`_build_collab_report` |
| 预算弹性 | `collab/graph._route_after_manager`（分级预算）；`collab/graph._budget_stop_node`；`collab/models.Task`（软/硬上限字段） |
| 损耗显性化 | `collab/graph._collect_node` + report；`collab/graph._build_collab_report` |
| 反馈质量指标 | `collab/graph._route_after_arbitrate` / `_manager_node`；`collab/arbitration.manager_arbitrate`（返回结构化反馈）；`collab/graph`（重试前后对比） |
| FR11 动议 | 新增 `collab/motion.py`；`collab/graph`（manager 动议路由节点）；`collab/runner`（动议事件上报） |
| 记忆库/持久化 | 新增 `collab/memory.py`；`collab/runner`（SQLite 落盘）；`collab/models.Task.from_dict` 已支持重建 |
| 双模式/全并行 | `collab/graph.run_collab_sync`（mode 参数）；`collab/graph`（就绪检查节点） |

**硬约束（沿用 M1）**：DSH schema 子集（MCP 工具参数禁用 Optional/anyOf，M2 主在 Python 层，M3 才碰 schema）；三问共享产出记录（审计=裁决=交流引用，勿另建事实源）；Persona/LLM/RAG 复用现有，不新造轮子；改接口必须同步 `AGENT_GUIDE.md`。

---

## 7. M2 任务分解（提议，待圆桌确认）

| 编号 | 任务 | 交付物 | 验收要点 |
| --- | --- | --- | --- |
| T8 | 记忆分区 + 注入 | `collab/memory.py`（MemoryEntry/检索/摘要）；`graph._build_task_prompt` 增记忆段 | 跨 run 召回命中；注入不拼接全量；新测试通过 |
| T9 | 记忆治理（FR9） | stale/overridden 状态；冲突检测；confidence 计算 | 陈旧记忆降权；污染防护用例通过 |
| T10 | 成本归属 + 计价 | `collab/costing.py`；TaskAudit 扩展 cost_usd/persona_id | 按 persona 汇总成本；单价推算正确 |
| T11 | 损耗显性化 + 反馈质量指标 | waste 明细；feedback_effectiveness/reason_specificity 计算 | 重试前后对比可测量；损耗可审计 |
| T12 | 事前预算弹性 + 内化约束 | 预算包/软硬上限；rep 信誉分；责任归属（债务/损耗） | 软上限预警、硬上限熔断；超支责任显式 |
| T13 | FR11 会议动议 | `collab/motion.py`；manager 动议路由节点；复用 V1 圆桌产出双份 | 审批/拒绝带原因/合并/抄送用例通过 |
| T14 | 双模式 + 全并行原子性 | mode 参数；就绪检查原子性；experimental 标记 | wave 默认安全；parallel 就绪检查用例通过 |
| T15 | 执行依赖评估 | 评估结论（做/不做）+ 若做最小实现 | 圆桌确认结论 |
| T16 | 持久化 + 元数据 | memory.db + run 持久化；`get_collab_status` 支持历史 run | 重启不丢；历史查询通过 |

**M2 关键排期判断**：FR-ECO（T10-T12）与记忆（T8-T9）是 P0；FR11（T13）P1；双模式/全并行（T14）P1；执行依赖（T15）P2。**建议先 T8-T12（经济+记忆），再 T13（动议），T14-T16 收尾。**

**范围纪律（自审）**：M2 体量偏大，建议**拆分**——核心（T8-T12：记忆 + 经济理性闭环）先落地验证，延伸（T13 FR11、T14 双模式、T16 持久化）按 PR 分批；T15 只出结论不实现。若 1-1.5 周紧张，FR11 可**单独一个 PR** 或降为 M3。

---

## 8. 验收标准（含元问题判据）

1. **记忆**：同一 persona 两次 run，第二次能召回第一次的记忆且不拼接全量历史；陈旧记忆被降权；无记忆污染（新证据失效后旧判断不再注入）。
2. **成本**：`get_collab_status`/report 能给出按 persona 的成本汇总；单价推算有依据；损耗（重试/超支/打回）显式可审计。
3. **预算弹性**：软上限触发预警并审计、硬上限触发熔断；超支的**责任归属**（债务/损耗）显式写入记录。
4. **反馈质量**：`feedback_effectiveness` / `reason_specificity` 可计算；重试前后 verdict/coverage/额外 token 对比可测量。
5. **FR11**：子 Agent 申请 → 经理批准/拒绝（拒绝带原因）→ 产出双份 → 抄送；同类合并；预算来源指定。
6. **双模式**：默认 wave；parallel 就绪检查原子性通过；parallel 未证明时标 `experimental=true`。
7. **元问题**（FR-META 判据）：**可追溯/可纠错/可追问** 三条均有客观可检查的验证点（M1 已覆盖 + M2 补成本/反馈质量/记忆置信度）。
8. **回归**：M1 collab 65 测试 + V1 全量不回归（仅保留已知 5 个预存在 Windows 路径断言失败）。

---

## 9. 开放问题（M2 定稿前待圆桌决议）

1. **元问题落地形态**：可追溯/可纠错/可追问是否要拉到**报告/审计的固定字段**（而非只作文档哲学）？建议：至少把`可纠错记录（verdict + 打回 + 反馈质量）`和`可追问（信源/锚点）`写入 report。
2. **成本定价精度**：无单价时用`参考成本`是否够？是否引入 `config/agent_llms.json` 的 provider 单价映射（可能缺真实单价）。
3. **事前弹性预算的复杂边界**：软/硬上限的粒度（任务级 vs 波级 vs 全局）与`申请-审批`成本是否值得？会不会把 M1 的简单熔断复杂化。
4. **FR11 是否必须**：M2 范围已很大，FR11 是否需要单独一个 PR / 是否可降到 M3？圆桌需权衡 scope 纪律。
5. **执行依赖（写依赖）**：是否坚持不引入（建议不引入）。
6. **记忆是否进 MCP 工具**：FR5/FR9 的`记忆检索/治理`是否要在 M3 暴露为 MCP 工具（如 `search_memory`/`manage_memory`），M2 只做底层库。

---

## 10. 参考

- docs/v2-collaboration-engine-requirements.md §9.5（FR11 定稿）、§10（圆桌三问）、§10.6（M2 元问题）
- docs/PROJECT_MEMORY.md §3、§6（M1 收官缺口排序）、§3.5（T4 圆桌：摘要置信度）
- collab/models.py / state_machine.py / audit.py / arbitration.py / graph.py / runner.py（M1 实现）
- config/councils/experts.yaml + config/domain_experts/*.yaml（圆桌专家阵容）
---

## 11. 圆桌评审决议（2026-08-25，v0.2）

> 评审报告：docs/v2-collaboration-engine-m2-roundtable-review.md。结论 **approve_with_concerns（5 位专家一致通过但带保留）**。本节决议**对 §4/§7 的优先级与范围做修订，遇冲突以本节为准**。

### 11.1 范围重排（取代 §4/§7 的 P 级）

- **P0 核心（先落地）**：FR-ECO-2（成本归属/定价：补 prompt/completion 拆分 + provider/model + pricing.yaml，priced/estimated 分离）、FR-ECO-4（损耗显性化）、FR-ECO-3（固定软/硬上限分级，**标注波级粒度**，不做申请-审批）、FR-META（既有字段 + attempt_log 落报告；`可追问`另立对抗性核验）、FR5（最小记忆切片）、T16（最小持久化：memory.db + run 摘要 + 历史查询，不落全量 state）。
- **P1 / 最小 / 单独 PR**：FR-ECO-1（保留 FAILED→DONE 并更名 `compliance_effectiveness`，**砍 reason_specificity**；新增不覆盖的 `attempt_log`）、FR11（纯数据层最小动议，完整机制降 M3）、T14（降为 mode 旗标 + experimental + invoke 前预检 + 单次 Send，不做原子锁/第二调度器）、T15（只出结论）。
- **砍/降级（M2.x / M3 / 不实现）**：FR-ECO-5（**只计算并暴露 rep，不设阈值门槛/自动分配**，信誉影响推迟到账簿可靠后）、FR9 完整治理（置信度精算/冲突覆盖/渐进披露/archive/LLM curation 推迟）、FR11 完整机制（manager LLM 审批/V1 圆桌双产出/MERGED/自由裁量额度 → M3 或单独 PR）、T14 原子性机器、记忆完整抽取与 MCP 工具化（M3）。

### 11.2 关键实现决策（写 M2 代码前必须落实）

1. **成本/归集数据来源**：`TaskAudit` 与结果须落 `prompt/completion_tokens` 拆分 + 实际命中的 `provider/model`；未知 provider 写 `unknown price` + 保守默认并标注 `estimated`；report 分列 priced / estimated。**不要留用不上的签名。**
2. **反馈/损耗指标**：新增不覆盖的 attempt 历史（`attempt_log`，`Annotated[list, add]`），记录每次尝试的 status/verdict/coverage/token，否则 feedback/损失指标不可算。
3. **写记忆时机**：统一在**仲裁通过（`verdict.ok`）之后**落库；executor 若在 DONE 就想写，需先标 `provisional`，仲裁通过后再 commit，避免把将被判失败的产出持久化。
4. **记忆最小化**：per-persona SQLite 分区 + Top-K 注入 + `source/links` + 可标 `stale`；`kind` 默认 `judgment`，`kind=fact` 必须带 audit snapshot provenance；置信度用 `coverage × recency` 透明标量（`×(1-被否决)` 待可追踪再加），不混乘不同性质。
5. **tokencost 竞态**：token/成本从 `generate` 返回值取，**不读共享 `llm.last_usage`**（并行分支会互相覆盖）。
6. **§8 验收**：全部改为**可判定最小客观用例**（固定输入→期望记忆 id；成本手算一致；构造样本断言 FAILED→DONE；对抗性注入→系统经 trace/证据/仲裁揭出并修正）。

### 11.3 与 M1 代码的必修对接

- `collab/arbitration.py` 的 `_arbitration_node_factory`（graph.py L502-507）手工用 5 字段重建 `TaskAudit`，**必须同步补 `cost_usd`/`persona_id` 等新增字段**，否则静默丢失；`Task` 加软/硬上限字段也要同步 `__slots__/`__init__/to_dict/from_dict`。
- 新增 `attempt_log` reducer（不按 id 覆盖），否则反馈指标不可算。
- 写记忆与 `_collect_node` 的报告字段联动（成本/损耗/rep 只读展示）。
---

## 12. 重复造轮子核查（复用清单，本轮确认）

按`优先复用仓库已有能力`口径逐条核对。结论：**M2 无实质重复造轮子**，但有 **3 处应`复用而非新造`**、**1 处应`不要强复用`**。

### 12.1 应复用的既有能力（不要新造）

| M2 需要 | 仓库已有能力 | 复用方式 |
| --- | --- | --- |
| 成本数据源（prompt/completion + provider/model） | `mcp_server/llm_client.OpenAICompatLLM` 已暴露 `last_usage={prompt_tokens, completion_tokens, total_tokens}` 与 `model`/`provider_name` | 扩展采集：把 graph.py 的 `_token_usage` 从只读 total 改为读拆分；audit 记录 `model`/`provider_name`。**数据已在客户端上，只需采，无需新造 provider/model 发现层** |
| provider/model 身份 | `llm.providers_api.describe_llm` / `mcp_server.llm_client.provider_status` | 复用之，勿另写 |
| 记忆检索的词法/评分 | `rag.config.tokenize` + `rag.retriever._keyword_score`（关键词重叠） | 复用 tokenize / 关键词重叠评分，**不要重写 tokenizer 或新造一个评分函数**；只在其上加来源新旧 / confidence 权重 |
| 会议动议产出 | V1 `roundtable`（模式 A）+ `CollabMessage` 定向投递 | FR11 结论以 `CollabMessage`+audit 锚点形态产出，**不要另建事实库** |
| 预算逻辑 | `collab/graph._route_after_manager` + `GLOBAL_TOKEN_BUDGET` + `_budget_stop_node` | 在现有分级上加软/硬上限，**不要重建第二套调度器/预算机** |
| run 持久化 | `Task.from_dict` 已支持时间戳重建（`_parse_dt`） | 复用序列化，勿重写 |

### 12.2 明确不要强复用的（避免`为复用而复用`）

- **记忆置信度**不要强绑 `collab.arbitration.compute_anchor_coverage`（其输入是 `output_summary + snapshot_ids`，与记忆 `links` 类型不同）。记忆置信度用 **coverage × recency 透明标量 + 并列 contest_count**（见 §11.2-4），不复用类型不匹配的函数。

### 12.3 明确是新能力、非轮子

- `collab/costing.py` 的 `price_tokens`/`cost_by_persona`：仓库无现成计价（`llm_gateway` 为私有可选依赖，本工作区不存在；`config/agent_llms.json` 只有 provider 链、无价格）。**新加一个 `config/pricing.yaml` 单价表是配置，不是造轮子**；`price_tokens` 簿记函数简单，无可复用替代。
- `collab/memory.py`：per-agent 跨会话记忆是仓库**没有**的新能力（现有 `rag` 是`语料知识`，`roundtable` 是`会议`）。存储用 stdlib `sqlite3` 即可；**不要引入第二套向量库**做记忆检索（沿用 keyword 评分足够，避免额外 chroma 依赖）。


