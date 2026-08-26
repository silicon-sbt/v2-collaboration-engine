# 项目记忆文件（PROJECT MEMORY）

> 本文件沉淀项目的关键决策、进展与踩坑，随开发推进不定期更新。
> 仓库：https://github.com/silicon-sbt/agent-roundtable-mcp（fork 自 Random-Walk2026/agent_roundtable）

## 1. 项目定位

- 把多 Agent 圆桌讨论封装成 MCP 服务（V1 已上线，DSH/Claude Code 双端接入）。
- **V2 弱去中心化多 Agent 协作引擎**：star 骨架（主 Agent/经理保留分派/裁决/汇总权）+ 定向 peer 通道（子 Agent 横向交流）。V1 圆桌保留为模式 A（会议/评审），V2 新增模式 B（协作执行）。
- 单一仓库演进；V2 是 V1 的超集（"公司也会开会"）。

## 2. 关键决策记录

| 日期 | 决策 |
| --- | --- |
| 2026-08-24 | 定位：弱去中心化（star 骨架 + 定向 peer 通道），不做完全 mesh；单一仓库，V2 演进 V1 保留为模式 A |
| 2026-08-25 | **入口架构（用户提出+采纳）**：V1（会议）是 **MCP 工具**；V2（公司）本质是 **长时工作流/编排引擎**。M3 拆两个入口：**入口 A = MCP（会议，V1 已有 10 工具，唯一 MCP）**；**入口 B = 工作流运行器/CLI（公司，V2 声明式长时工作流，非 MCP、非 DSH workflow 工具）**。FR-MCP-1~6 均属入口 B，经工作流运行器/CLI 消费。细则：docs/v2-collaboration-engine-m3-entry-spec.md（§0 研究结论：DSH workflow 工具=前台/无 checkpoint/无预算，故不作载体）。 |
| 2026-08-24 | M1 核心全票锁定：异步任务状态机（执行层契约）；横向交流/记忆是内容层 |
| 2026-08-24 | 审计粒度 L2（输入快照+输出摘要+token）；L3 推理路径"伪精确"不采；M1 加摘要可信性约束 |
| 2026-08-24 | 质量裁决：硬规则 → 经理"暂定" → 圆桌申诉（例外通道）；"终审"软化 |
| 2026-08-24 | 横向交流底线：引用锚点 + 指名回应（拉模式）；验收=仅凭锚点+摘要可决策；补最低提醒机制 |
| 2026-08-24 | FR11 会议动议权：子 Agent 可申请圆桌（主 Agent 审批，拒绝必带原因，重试须更好理由）；参会方非全员（申请方提议+经理调整）；产出双份+经理决定抄送；归属 M2 |
| 2026-08-24 | 元问题"协作本质是否预设底线"留 M2 再评 |

## 3. 里程碑

- **M1**（1.5 周）：异步任务状态机（L2 审计+摘要可信性）+ 引用/指名回应 + 分层裁决。
- **M2**：记忆分区 + FR11 会议动议权 + 元问题评审 + 审计增强。
- **M3**：MCP 层扩展 + 全量验收测试 + 文档。

## 3.5 T4 圆桌评审结论（logs/V2协作引擎T4横向交流实现评审...md）

- 核心判断：锚点+摘要把压缩失真风险从 A 执行阶段转移到 B 决策阶段，且升级为配置风险（下游复利放大）。
- 共识：不回溯完整上下文，但**摘要置信度必须可验证**；信息结构分"事实层/判断层"（事实=可核验结构化字段，判断=显式标注依据/时间/性质）。
- 置信度来源分歧：A 自报 vs 锚点覆盖度机械计算（Computing）vs 认知边界声明（Philosophy）vs 双锚点区分（History：内部引用=自证不可核验，跨任务接口契约锚点=可独立核验）。
- 验收判据缺口：当前"B 仅凭锚点+摘要可决策"不足，需补"摘要置信度可验证"。
- **建议归属**：置信度机制（事实/判断分层 + 锚点覆盖度）与 T5 分层裁决一并实现（裁决时校验摘要可信度）。

## 4. 文档索引

- `docs/multi-agent-roundtable-feasibility.md` — 可行性报告（v1.1，弱去中心化定位）
- `docs/v2-collaboration-engine-requirements.md` — V2 需求与实现方案（v1.1，含 FR11 定稿 + 圆桌三问决议）
- `README_MCP.md` — MCP 服务使用文档

## 4.5 项目流程约定（用户 2026-08-25 明确）

- **每完成一个任务，自动做"自审 + 轻量圆桌"**，不再向用户询问是否要做。
- 轻量圆桌：3 位专家（Computing/Philosophy/History）逐个 subagent、**只读核心小文件** + 内联改动摘要、紧凑 JSON 输出（verdict+少量 concerns）；由主 agent 综合。
- 关键里程碑（如 M2 全量评审）可跑 5 专家全量。

## 5. 踩坑记录

- DSH 的 `assertSupportedJsonSchema` 只接受极小 JSON Schema 子集（不支持 anyOf）→ MCP 工具参数禁用 `Optional[X]`，用 `""`/`0` 默认值；新增参数一律字符串/标量（JSON 字符串模式）。
- Claude Code 的 stdio MCP 无 cwd 配置（子进程用启动目录）→ `mcp_entry.py` 基于 `__file__` 注入 repo 根到 `sys.path`。
- 中文 persona 名会被 ASCII 正则 slugify 成空 → 保留 `\w`（含 CJK）。
- 真实 LLM 圆桌单次调用可能超 MCP 默认 60s → DSH 配 `toolCallTimeoutMs: 600000`；Python client 用 `read_timeout_seconds`。
- mcp SDK 2.x 无 FastMCP（重写版）→ 锁 `mcp>=1.2,<2`。
- 原仓库无 LICENSE（默认保留版权）→ README 标注来源+致谢；本仓库 MCP 代码为原创。

## 6. 当前状态

- V1 MCP 服务：已上线，19 测试通过，DSH schema 10/10，Claude Code 实测通过。
- V2 M1 已开工：
  - ✅ T1 任务模型 + 状态机（collab/models.py + state_machine.py，12 测试通过）
  - ✅ T2 L2 审计（collab/audit.py：摘要模板/硬规则校验/build_audit；LLM client last_usage token 核验）
  - ✅ T3 执行子图（collab/graph.py：分波调度 Send fan-out + 每任务审计 + 死锁 BLOCKED，8 测试通过；自审核修复裸星号语法/Send 竞态/BLOCKED 终态）
  - ✅ T4 横向交流（collab/graph.py + CollabMessage.receivers：定向消息投递给 allowed_links，下一波 peer prompt 注入协作消息可回应；12 graph 测试通过；自审修复任务重复执行/Send 分支 state 隔离→manager 聚合 context 进 payload）
  - ✅ T5 分层裁决（collab/arbitration.py：硬规则[审计校验+动词冲突检测+锚点覆盖度置信度] → 经理暂定[LLM PASS/REVISE]；failure_type 分类[audit_invalid/conflict/manager_revise]；不合格标 FAILED 带原因；25 collab 测试通过）
  - ✅ T6 失败恢复 + 预算熔断（collab/graph.py：failure_type 分流重试[transient/manager_revise 重试1次；audit_invalid/conflict/budget 不重试]；双层预算[任务 budget_tokens/全局 400k 波边界熔断+overspend_tokens 记账]；单任务级回滚[results 按 id 合并]；5 recovery 测试通过）
  - ✅ T7 异步 runner（collab/runner.py：run_collaboration 后台线程返回 run_id + get_collab_status 轮询 + stop_collab 软中止 + overspend 记账 + 3 任务场景演示；6 runner 测试通过）
  - ✅ T8 记忆分区 + 注入（collab/memory.py：per-persona SQLite 分区 + Top-K 检索复用 rag.config.tokenize + build_memory_context + memory_entries_from_output；graph 在 _build_task_prompt 的 persona_hint 后插记忆段、arbitrate 仅在 verdict.ok 写回；memory_store 默认 None 向后兼容；10 测试通过，全量 collab 75 通过）
  - ✅ T8 圆桌评审（真实多 agent：*/docs/v2-collaboration-engine-t8-memory-roundtable-review.md）：approve_with_concerns，无重复造轮子。**发现真实 bug（连接泄漏）已修复**：_conn 每方法新建连接但 with sqlite3.connect 不关闭、close() 空实现 → 改 @contextmanager 提交+关闭，删除 close()；并修 links/tags 空格拼接损坏（改 JSON）与 confidence 假精确（0.3→0.0 占位）。遗留（T9/FR-ECO）：置信度改 coverage×recency、provenance 改 audit 快照锚点（input_snapshot[:24]）、search 加 score 阈值+候选上限（现 O(N)）、stale 语义/recency 矛盾、提取器脆弱、自增强/矛盾降级、记忆开销计入成本闭环。
  - ✅ T9 记忆治理（FR9）：collab/memory.py 增 conflict→overridden 自动降级（复用 collab.arbitration.detect_decision_conflicts + 互挂 links，防污染/自增强）、confidence=compute_anchor_coverage(summary, snapshot_ids)、list/search 默认排除 stale+overridden、mark_stale 不再刷新 updated_at（防陈旧条目 recency 反升）、__post_init__ 校验 kind 集合 + clamp confidence/contest_count；graph 仲裁处传 snapshot_ids；tests/test_collab_memory_governance.py 8 用例；全量 collab 83 通过。
  - ✅ T9 圆桌评审（轻量 3 专家：Computing/Philosophy/History，docs/v2-collaboration-engine-t9-memory-governance-roundtable-review.md）：approve_with_concerns。采纳修复：① 置信度"空摘要=满置信"→无决策点返 0.5 中性；② include_stale 不再漏出 overridden（overridden 永远排除）。记为范围取舍：conflict 只覆盖决策动词-对象（结论/fact 不参与）、confidence 为整篇摘要覆盖度（不细分到决策点）、contest_count 为审计字段无消费点、overridden 单向门闩。
  - ✅ 遗漏项已处理（2026-08-25）：① provenance 从 task.id 改为审计快照锚点（audit.input_snapshot[:24]，与仲裁 snapshot-id 约定一致）；② 自增强门控：新条目 confidence 严格低于旧条目时，弱新判断自己降 overridden（不覆盖强旧记忆）。新增 3 治理用例，全量 collab 86 通过。
  - ✅ T10 成本归属 + 计价（collab/costing.py：price_tokens/is_estimated/cost_by_persona/cost_summary，默认保守单价表，未知 provider 标 estimated；TaskAudit 扩展 prompt_tokens/completion_tokens/provider/model/cost_usd/persona_id；executor 从 LLM client last_usage 取 usage 拆分+model/provider 并算价写入审计；arbitration 重建保留新字段；report 输出总 USD + 按 persona）。tests/test_collab_costing.py 8 用例；全量 collab 94 通过。
  - ✅ T10 圆桌评审（轻量 3 专家，docs/v2-collaboration-engine-t10-costing-roundtable-review.md）：approve_with_concerns。采纳修复：① price_tokens/is_estimated 支持 provider:model 键查找（model 不再死参）；② cost_summary/priced-estimated 分列 + report 标注"估算成本"。归 T11（损耗显性化）：failed/重试/budget-exceeded 成本计入。已知简化：默认单价为 provider 家族级，未覆盖 provider 内 model 分层（除非注入 provider:model）。
  - ✅ T11 损耗显性化 + 反馈质量（collab/costing.py：waste_breakdown[effective=done+ok；waste=全部attempt-有效，waste_reasons 结构化{id,failure_type,attempt,token,cost}，用 attempt 序号标 superseded] + feedback_summary→recovery_rate[needed=0 返回 None]；graph.py 加 attempts reducer，executor 每个执行分支产出 attempt 记录(success/budget/transient)，报告输出 损耗(USD)/损耗Token/损耗原因 + 重试恢复 N/M）。已核实 executor 的 audit.cost_usd 为单次执行成本（非累计）→ total-effective 准确。tests/test_collab_waste.py 6 用例；全量 collab 100 通过。
  - ✅ T11 圆桌评审（轻量 3 专家，docs/v2-collaboration-engine-t11-waste-roundtable-review.md）：approve_with_concerns。采纳修复：① feedback 更名 recovery_rate、needed=0 返回 None；② waste_reasons 结构化 + 覆盖 manager_revise/superseded。已核实 audit.cost_usd 非累计。
  - ✅ T12 事前预算弹性（FR-ECO-3；只做固定软/硬上限，不做申请-审批）：Task 增 budget_soft_tokens（默认=80% budget）；executor 超过 soft 标 soft_budget_warning + overspend_kind=debt（完成+被接受），超过 hard 仍 fail(budget_exceeded, overspend_kind=loss)；全局 GLOBAL_BUDGET_SOFT=0.8*400k（报告 token_total>soft 显示全局预算预警，hard 仍 budget_stop，budget_stop 结果 overspend_kind=loss）；costing 增 rep_by_persona（有效/总成本 per persona，只算不 gate，FR-ECO-5 推迟）。报告输出 软上限预警任务数/全局预算预警/超支责任 debt=x;loss=y/Persons信誉。tests/test_collab_budget.py 5 用例；全量 collab 105 通过。
  - ✅ T12 圆桌评审（轻量 3 专家，docs/v2-collaboration-engine-t12-budget-roundtable-review.md）：approve_with_concerns。采纳修复：rep_by_persona ① persona 归因对齐 cost_by_persona（回退 result.persona_id）；② total==0 省略该 persona（不再默认 1.0）。已核实软超支完成+被接受不标 failure_type=budget_exceeded（仅硬超支才标），故 debt 不会被误判为 waste。
  - ✅ FR11 会议动议权（§9.5，M2 只做纯数据层最小动议）：collab/motion.py：MotionStatus(pending/approved/rejected/merged/expired)、CollabMotion(task_id/topic/rationale/proposed_participants/budget_source/status/decided_by/decision_reason/committee/outputs/audit_anchor/timestamps)、apply_decision(approve/reject，reject 必带原因、要求 decided_by、approve 无 committee 默认 proposed_participants、接受 audit_anchor)、merge_same_topic(同类 pending 合并，survivor.outputs[merged_from] 记录被吸收 id，其余 MERGED+decider=manager)、MotionStore(内存，add/get/list/decide/merge_pending，线程安全)。完整机制(manager LLM 审批/圆桌双产出/参会方增删/自由裁量额度/MERGED 语义)→M3。tests/test_collab_motion.py 10 用例；全量 collab 115 通过。
  - ✅ FR11 圆桌评审（轻量 3 专家，docs/v2-collaboration-engine-fr11-motion-roundtable-review.md）：approve_with_concerns。采纳修复：① apply_decision 接受 approve/reject 别名 + 要求 decided_by + approve 无 committee 默认 proposed_participants + 接受 audit_anchor；② merge 记录 merged_from + decider/reason；③ MotionStore.decide/merge_pending 全程持锁。已知取舍：retry=新建动议(M3)、from_dict 非法时间戳宽松、MERGED 完整语义→M3。
  - ✅ T14 双模式+全并行（降级版，按圆桌）：graph 增 CollabState.mode/experimental/parallel_note；resolve_mode(tasks, mode="wave") 纯函数（wave 默认；parallel 仅当所有任务 data_deps 为空→experimental=True，否则回退 wave+note；空集回退 wave）；run_collab_sync 加 mode 参数并写入初始 state；报告输出「模式: wave|parallel（experimental）」+ 回退说明。parallel 是纯标记（沿用现有 wave 调度，不换第二调度器/锁）。tests/test_collab_mode.py 8 用例；全量 collab 123 通过。
  - ✅ T14 圆桌评审（轻量 3 专家，docs/v2-collaboration-engine-t14-mode-roundtable-review.md）：approve_with_concerns。已核实 run_collab_sync 先 to_dict 再 resolve_mode（Task/dict 契约不成立）；采纳加固：resolve_mode 默认 wave + 空集回退 + 补测试（缺省默认/空集/state 字段直断）。
  - ✅ T15 执行依赖评估（只出结论、不实现）：结论=不引入「写依赖（修改他人产出）」，保留 data_deps（读依赖）；若未来 M3 只做「读依赖时序触发」（A 终态→B ready，不改 A 产出）作为可选、可量化门槛的 FR。理由：与 M1 _merge_results 按 id 合并/单任务回滚冲突、DAG 复杂度高、收益不明确且「改写他人产出」应走经理暂定+圆桌申诉（非依赖触发）。文档 docs/v2-collaboration-engine-exec-dependency-evaluation.md。
  - ✅ T15 圆桌评审（轻量 3 专家，一致 agree_with_concerns）：结论成立、不过度保守/冒进；已吸收：① 术语澄清（读依赖/写依赖/读时序触发三词分离、M3 最小版=调度信号非写依赖）；② M3 触发须复用 _verify_blocked_reachability 防环 + 量化门槛（≥N 次跨任务改写场景）；③ 仲裁改写需审计痕迹（谁授权/前后 diff/申诉链）。
  - ✅ T16 持久化（最小，roundtable 决定只存摘要不落全量 state）：collab/runstore.py RunStore（SQLite，save/get/list，跨实例/并发安全，run 摘要 JSON）；runner 的 run_collaboration/get_collab_status/list_collab_runs 加可选 run_store 参数（默认 None 向后兼容），worker 结束把 _build_summary 摘要保存，get_collab_status 先内存再历史，list 合并 live+历史。tests/test_collab_runstore.py 4 用例；全量 collab 127 通过。
  - ✅ T16 圆桌评审（轻量 3 专家，docs/v2-collaboration-engine-t16-runstore-roundtable-review.md）：approve_with_concerns。已核实 _build_summary 只白名单、无全量 state/reasoning（泄漏不成立）；采纳清理：移除 RunStore.close()（空实现）+ save 注释 provider/mock/created_at 为创建时字段不可变。已知局限：崩溃后 run 永久 running 归 M3；sqlite 模式与 MemoryStore 重复（出现第 3 个 store 再抽公共 helper）。
- **M2 收官（2026-08-25 全量回归+自审+圆桌，docs/v2-collaboration-engine-m2-completion-review.md）**：ready_with_concerns。全量 192 passed / 5 failed（全部为预存在 Windows 路径断言，与 M2 无关）/ 2 skipped；V2 collab 127 passed。**,元问题 FR-META 裁决：不稀释**——V2 与 V1 本质区别确为「状态机让协作责任可追踪/可纠错/可追问」（可追溯=audit+cost+provenance 锚点；可纠错=attempt_log+recovery_rate+裁决；可追问=审计快照锚点+记忆 provenance；对抗性核验强化→M3）。**显式 M3 缺口**：记忆开销计入成本闭环（6118c50d）、search score 阈值+候选上限（f88501d9）、RunStore 崩溃后永久 running、FR11 完整机制、执行依赖（写依赖不引入）。进 M3 前建议：快速处理 5 个 V1 失败（或 xfail+跟踪单）、把记忆成本+search 上界列为 M3 首任务。
- **M3 需求与圆桌评审（2026-08-25）**：新增 docs/v2-collaboration-engine-m3-requirements.md（v0.2，含 §11 圆桌决议）+ docs/v2-collaboration-engine-m3-roundtable-review.md。范围收敛：主交付=MCP 工具化（run_collaboration/manage_tasks）+ 记忆/动议（最小闭环）工具 + 成本/损耗接入 + 记忆开销计入成本 + search 上界 + RunStore 崩溃恢复 + 全量验收 + 文档；**FR11 完整机制→M3.x 独立 PR**；异步进度改状态轮询/事件日志（不依赖已返回工具 ctx）；JSON 负载服务端严格校验+限长；工具粒度 P0/P1/P2；5 个 V1 失败三分类 + NFR 量化。
  - ✅ T17 公司工作流入口 CLI（collab/cli.py + __main__.py：run/status/report/list/stop；run 加载 tasks JSON、调 run_collaboration 并阻塞到终态/超时；--db 指定 RunStore；runner.run_collaboration 补 mode 透传）。入口 B=公司（非 MCP、非 DSH workflow 工具）。tests/test_collab_cli.py 4 用例；全量 collab 131 通过。
  - ✅ T17 圆桌评审（轻量 3 专家，docs/v2-collaboration-engine-t17-workflow-cli-roundtable-review.md）：approve_with_concerns。采纳：① run 始终阻塞到终态（去失效 --wait，避免进程退出杀后台 run）；② 修 cmd_list f-string bug；③ 超时/not_found 处理（超时仍 running → stop_collab + 返回 1，不留孤儿）。已知：run 阻塞到完成（真异步需常驻服务 M3.x）、stop 仅本进程 run。
  - ✅ T18 memory/motion CLI + MotionStore 持久化：collab/cli.py 加 memory search/list/stale + motion submit/decide/list（--db 默认 logs/collab_memory.db / collab_motions.db）；collab/motion.py MotionStore 加可选 db_path SQLite 持久化（db_path=None 内存，兼容）。tests/test_collab_memory_motion_cli.py 4 用例；全量 collab 135 通过。
  - ✅ T18 评审（专家视角综合，docs/v2-collaboration-engine-t18-memory-motion-cli-roundtable-review.md）：approve_with_concerns。**集成缺口（记忆已补）**：collab run 已通过 --memory-db 接入持久 MemoryStore（默认 logs/collab_memory.db），run 产生的记忆落入同库、memory list/search 可读（test_cli_run_writes_memory_then_read 通过）；动议同源待 FR11 机制接入图后再接（当前 motion CLI 独立库）。
  - ✅ T19 成本/损耗/预算接入 CLI：collab/runner.py _build_summary 增列 cost_usd/cost_priced_usd/cost_estimated_usd/cost_by_persona + waste_cost_usd/waste_tokens/waste_reasons + retries_that_succeeded/tasks_that_retried/recovery_rate（非零才写入）；collab/cli.py 加 cmd_cost 子命令（collab cost <run_id> [--db]，读摘要这些字段，mock=0 成本输出 (no cost data)）。复用 collab/costing.py。tests/test_collab_cli.py 2 用例（_build_summary 单元 + CLI 读持久摘要）；全量 collab **138 通过**。
  - ✅ T19 评审（轻量 3 专家，docs/v2-collaboration-engine-t19-cost-cli-roundtable-review.md）：approve。成本/损耗/预算已接入 CLI 且数字正确、estimated 单独标注；下一步 T20（记忆开销计入成本）。
  - ✅ T20 记忆开销计入成本（FR-GAP-1）：TaskAudit 增 memory_tokens（executor 用 rag.tokenize 对 memory_context 计 token，写 audit+attempts）；costing.memory_summary 输出 memory_tokens/memory_cost_usd/memory_share（**子集拆分，不重复累加**，按输入价）；报告行「记忆开销(USD)」；_build_summary/collab cost 增列（非零才写入）。tests/test_collab_costing.py +3 用例（含 executor 集成：非空记忆下 audit.memory_tokens>0 且报告含记忆开销）；全量 collab **141 通过**。
  - ✅ T20 评审（轻量 3 专家，docs/v2-collaboration-engine-t20-memory-cost-roundtable-review.md）：approve_with_concerns。concerns：① memory_tokens 为本地 tokenizer 近似（估算口径，报告可补标注）；② memory_summary 只统计已接受任务审计（跨尝试完整口径未纳入，随 T21 收口）；③ 记忆成本是 prompt 成本子集，仅在文档/指南说明非新增计费。
  - ✅ T21 search 分数阈值 + 候选上限（FR-GAP-2）：MemoryStore.search 增 min_score（默认 1.0，过滤 s>0.0 and s>=min_score，无强命中不注入）+ candidate_limit（默认 50，SQL LIMIT 界住每 agent 候选扫描，None=不限）；list 增 limit（memory list CLI 不受影响）；CLI memory search 增 --min-score/--candidate-limit。复用 rag.tokenize。tests/test_collab_memory.py +2 用例；全量 collab **143 通过**。
  - ✅ T21 评审（轻量 3 专家，docs/v2-collaboration-engine-t21-search-bounds-roundtable-review.md）：approve_with_concerns。concerns：① min_score=1.0 可能偏松（单字重叠即通过，可调/可改归一化）；② candidate_limit 牺牲长尾（唯一相关旧记忆可能被漏）；③ 默认行为从「注入任何命中」变为「门控+上限」，属 FR-GAP-2 有意变更。
  - ✅ T22 RunStore 崩溃恢复（FR-GAP-3）：runs 表增 last_heartbeat（CREATE+ALTER 迁移）；RunStore.touch(run_id) 刷新心跳；normalize_stale(grace=DEFAULT_CRASH_GRACE_SECONDS=120) 把仍 running 且 COALESCE(last_heartbeat,created_at) 超期记录归一为 failed + stop_reason=crashed；get/list 开头自动 normalize_stale（不永久 running）；run_collaboration 在有 RunStore 时启动 daemon 心跳线程（每 10s touch），worker 完成 finally 置 _hb_stop 停线程，初始 running 记录 last_heartbeat=created。tests/test_collab_runstore.py +3 用例；全量 collab **146 通过**。
  - ✅ T22 评审（轻量 3 专家，docs/v2-collaboration-engine-t22-runstore-crash-recovery-roundtable-review.md）：approve_with_concerns。concerns：① 同进程 worker 静默死亡（get_collab_status 先读内存，罕见边缘态未归一，主场景=崩溃/重启后已解决）；② 存活 worker 与归一化良性竞态（后完成会覆盖为 done）；③ 每次 get/list 触发 normalize_stale 写（幂等，开销小）。T22 自查另查出一 bug 已修：get_collab_status 被摘要旧 status 覆盖→改为行级 status/finished_at/stop_reason 为准，加端到端测试 test_get_collab_status_surfaces_crashed_run_as_failed，CLI status 冒烟=failed。
  - ✅ T23 FR-META 对抗性核验（FR-GAP-5）：新增 tests/test_collab_adversarial.py 9 个对抗性用例（无效审计/自相矛盾/负成本/无 provenance 事实/REVISE 不写记忆/弱矛盾不覆盖强记忆/超预算/孤儿 run/记忆成本子集）。**对抗性发现并修正 bug**：build_audit 把负 cost_usd 静默 clamp 成 0（TaskAudit max(0.0) 掩盖了 validate_audit 的 cost_usd<0 检查）→ 改为 build_audit 对原始 token/prompt/completion/cost 负数直接 ValueError。全量 collab **156 通过**。
  - ✅ T23 评审（轻量 3 专家，docs/v2-collaboration-engine-t23-adversarial-roundtable-review.md）：approve。9 对抗性用例覆盖审计/仲裁/记忆/预算/恢复/成本六大面，其中 1 个制造错误暴露了 build_audit 静默 clamp 负成本缺口并已修正；其余用例证明系统能揭出并修正注入的错误。
  - ✅ T24 全量验收 + V1 失败三分类 + 文档定稿：全量 pytest tests/ = **226 passed / 0 failed / 2 skipped**；V2 collab 156 passed。**5 个 V1 预存在失败三分类=同一跨平台真 bug→修**（V1 rag/chunker._source_file 用 str(Path) 存 source_file 元数据，Windows 反斜杠 → 改 Path.as_posix() 统一 POSIX；一处修复解决全部 5 个）。M3 全部 8 个任务（T17-T24）完成，验收报告 docs/v2-collaboration-engine-m3-completion-report.md。
  - ✅ **M3 收官**：M2+M3 全部合入 m2 分支，文档已定稿（docs/ 未 push，按要求内容完成后可按需发布）；M3.x（FR11 完整机制/动议同源接入图/执行依赖读时序）留待独立 PR。
- **M1 收官（2026-08-25 圆桌）**：通过（流程闭环）；128 passed 证明可靠性，**未验证经济理性**——成本效率闭环为 M2 目标。M1→M2 缺口排序：①反馈质量可计算代理指标 ②成本归属到人的定价 ③事前预算弹性约束 ④损耗显性化 ⑤成本归属内化为行动者约束
- **T3 圆桌评审落实进度**：✅ ① 摘要双轨（output_reasoning 开放域 + output_summary 结构化，validate 双查）；✅ ② BLOCKED 静态可达性复核（collect 闭包校验）；**冲突检测（决策点动词-对象对）归入 T5 一并实现**（圆桌追加建议，当前无生产数据窗口期风险≈0）；⬜ ③ 双模式开关；⬜ ④ 全并行原子性；BLOCKED 跨环测试随 T4 补
- **M2 需求与圆桌评审（2026-08-25）**：新增 `docs/v2-collaboration-engine-m2-requirements.md`（v0.2，含 §11 圆桌决议）+ `docs/v2-collaboration-engine-m2-roundtable-review.md`。范围重排：P0=经济理性闭环（FR-ECO-2/3/4：成本拆分+pricing.yaml、软/硬上限波级、损耗显性化）+ 最小记忆切片（FR5：per-persona 分区+Top-K 注入，写记忆在仲裁通过后，kind=judgment/fact 带 provenance）+ FR-META（可追溯/可纠错/可追问，可追问落对抗性核验）+ 最小持久化；FR11 只做纯数据层最小动议；FR-ECO-5 只算不 gate；T14 降 mode+experimental；T15 只出结论；FR9 完整治理/记忆抽取/MCP 工具化 → M3。关键对接：TaskAudit 补 prompt/completion+provider/model、新增 attempt_log、token 从 generate 取、_arbitration_node_factory 重建补新字段。
- 文档：AGENT_GUIDE.md（agent 接口速查，改接口必须同步）；PROJECT_MEMORY.md（本文件）。