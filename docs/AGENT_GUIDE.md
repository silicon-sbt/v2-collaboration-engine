# AGENT_GUIDE（Agent 接口速查）

> **给 Agent 看的精简接口文档**：接这个代码库的 Agent（包括未来的你）先读本文件，不要翻长文档（省 token）。
> 完整背景见：`docs/multi-agent-roundtable-feasibility.md`（可行性）、`docs/v2-collaboration-engine-requirements.md`（V2 需求）、`docs/PROJECT_MEMORY.md`（决策记录）。
> 更新规则：**新增/修改任何接口、数据模型、约定时，必须同步更新本文件**（见文末"如何更新"）。

## 1. 代码地图

```text
仓库根/
├── mcp_entry.py                 # MCP server 入口（cwd 无关，基于 __file__ 注入 repo 根）
├── mcp_server/                  # V1 MCP 服务（FastMCP 封装）
│   ├── server.py                # 工具注册（10 个工具）+ 进度上报
│   ├── core.py                  # 工具实现（纯函数，可单测）
│   ├── llm_client.py            # .env 加载 + OpenAI 兼容客户端（重试）+ provider 解析
│   └── __main__.py              # python -m mcp_server 入口
├── collab/                      # 【V2】协作引擎（模式 B），M1 起新增
│   ├── models.py                # Task / TaskStatus / TaskAudit / CollabMessage【T1 已完成】
│   ├── state_machine.py         # 任务状态机（合法转移校验）【T1 已完成】
│   ├── audit.py                 # 【T2】L2 审计：摘要模板 + 硬规则校验 + build_audit
│   ├── graph.py                 # 【T3-T6】分波执行 + L2 审计 + 横向交流 + 裁决 + 失败恢复/熔断
│   ├── recovery 相关            # 重试（failure_type 分流）+ 双层预算（overspend_tokens 记账）
│   ├── arbitration.py           # 【T5 已完成】分层裁决（硬规则+冲突检测+置信度+经理暂定+failure_type）
│   ├── memory.py                # 【T8-T9】per-agent 跨会话记忆（SQLite 分区+检索+注入+写回；治理：conflict→overridden、confidence=coverage、stale 不刷高 recency）
│   ├── costing.py               # 【T10-T12】token→USD 计价 + 按 persona 归集 + 损耗显性化/恢复率 + rep（复用 last_usage 拆分）
│   ├── motion.py                # 【FR11】会议动议权（纯数据层最小动议：CollabMotion/MotionStatus/apply_decision/merge_same_topic/MotionStore；完整机制→M3）
│   ├── runstore.py              # 【T16】run 摘要持久化（SQLite：save/get/list；跨实例/并发安全；只存摘要+历史查询）
│   ├── runner.py                # 【T7/T16】异步入口：run_collaboration / get_collab_status / stop_collab / list_collab_runs（+mode/run_store）
│   ├── cli.py                   # 【T17】公司工作流入口 CLI：run/status/report/list/stop（非 MCP、非 DSH workflow 工具）
│   └── __main__.py              # 【T17】python -m collab 入口
├── roundtable/ llm/ rag/        # 原项目核心（V1 圆桌状态机、LLM 适配、RAG）
├── config/                      # 圆桌/persona/council 配置
├── docs/                        # 文档（本文件 + 可行性 + 需求 + PROJECT_MEMORY）
└── tests/                       # pytest（test_mcp_tools.py 为 V1；test_collab_*.py 为 V2）
```

## 2. 核心数据模型

### 2.1 V2 协作引擎（collab 包）

```python
class TaskStatus(str, Enum):
    PENDING = "pending"      # 已创建未执行
    RUNNING = "running"      # 执行中
    DONE = "done"            # 成功产出（终态）
    FAILED = "failed"        # 执行失败（可重试→RUNNING）
    BLOCKED = "blocked"      # 阻塞（依赖未就绪/经理挂起，可解阻→RUNNING）
    STOPPED = "stopped"      # 经理中止（终态）

class Task:
    id: str                   # 唯一标识
    persona_id: str           # 执行者（persona id）
    input: str                # 任务指令/输入
    expected_output: str      # 期望产出描述（裁决依据）
    data_deps: list[str]      # 数据依赖（可引用的其他任务 id）
    allowed_links: list[str]  # 可横向交流的对象（task id，M1 硬编码）
    budget_tokens: int        # 本任务 token 配额（默认 80_000）
    budget_soft_tokens: int   # 【T12】软上限预警阈值（默认=budget_tokens*0.8；超过仅预警不失败，hard 仍 bldg->budget_exceeded）
    status: TaskStatus        # 当前状态
    audit: TaskAudit | None   # L2 审计记录

class TaskAudit:              # L2 审计（输入快照/摘要双轨/token）
    input_snapshot: str       # 任务入参快照（回滚重放用）
    output_summary: str       # 结构化摘要（机器核验轨）：引用输入快照 / 关键决策点 / 任务结论（硬规则校验）
    output_reasoning: str     # 开放域推理轨（原始输出，防填表诱导；语义一致性交 T5 经理裁决）
    token_usage: int          # token 消耗（从 LLM client last_usage 取，客观字段，勿信自报）
    prompt_tokens / completion_tokens: int   # 【T10】usage 拆分（同 last_usage，勿信自报）
    provider / model: str     # 【T10】实际命中的 provider/model（来自 LLM client，未知 provider 价=估计）
    cost_usd: float           # 【T10】成本（price_tokens 按 provider 单价；未知 provider 用保守默认并标 estimated）
    persona_id: str           # 【T10】成本归属到人（来自任务 persona_id）
    started_at / finished_at: datetime

# 摘要生成：collab.audit.render_summary_template(snapshot_ids, decisions, conclusion)
# 校验：collab.audit.validate_audit(audit) / build_audit(...)（不合格即抛 ValueError）
# token 核验：OpenAICompatLLM.last_usage（每次 generate 后刷新；Mock 无 usage 时按 0）

class CollabMessage:          # 横向交流消息（T4）
    id: str
    task_id: str              # 归属任务
    speaker: str              # 发言 persona id
    reply_to: str | None      # 指名回应目标（消息 id）
    references: list[str]     # 引用锚点（依赖任务的 audit 快照ID）
    receivers: list[str]      # 投递目标任务 id（来自发送方 allowed_links，定向非广播）
    content: str              # 结构化产出摘要（锚点+摘要，验收判据=接收方可仅凭它决策）
    epistemic_tags: list[str] # 认识论标签（复用 V1）

# 横向交流机制（T4）：任务完成后自动把产出摘要作为消息投递给 allowed_links 的 peers；
# 下一波 peer 的 prompt 注入"协作伙伴的消息"段（可回应/反驳/采纳）；
# incoming 匹配三路：reply_to=本任务 / 本任务在 receivers / 本任务被 references 引用。
```

### 2.2 V1 圆桌（roundtable 包，已稳定，勿改结构）

```python
RoundtableMessage: round/speaker/speaker_id/role/type/content/references/epistemic_tags/llm_provider/llm_model
Persona: id/name/role/worldview/speaking_style/strengths/weaknesses/catchphrases/llm_config/rag_expert_name/agent_type/profile
RoundtableState: topic/round/max_rounds/council_name/messages/round_summaries/final_summary/log_path
```

## 3. 关键接口签名

### 3.1 MCP 工具（V1，10 个，已上线）

`list_councils` / `list_agents` / `get_agent` / `list_knowledge_corpora` / `search_knowledge` / `plan_council` / `run_roundtable` / `list_reports` / `read_report` / `provider_info`

- `run_roundtable(topic, council="experts", rounds=2, mock=false, provider="auto", model="", api_key="", base_url="", context="", add_personas="", adjust_personas="", output_dir="logs", temperature=0.7, max_output_tokens=4096)`
  - `add_personas`/`adjust_personas`：JSON 字符串（DSH schema 约束，勿改类型）；`context` 注入第 0 轮消息。
- 工具参数硬约束：**一律字符串/标量/boolean，禁止 `Optional[X]`**（DSH 的 assertSupportedJsonSchema 拒绝 anyOf）。

### 3.2 V2 协作引擎（M1 起逐步新增）

```python
collab.runner.run_collaboration(
    tasks: list[dict],        # 任务定义数组（id/persona_id/input/expected_output/data_deps/allowed_links）
    *,
    provider="auto", mock=False, root_dir=None,
) -> str                     # 返回 task_id（异步，M1 用 manage_tasks 查询）

collab.runner.run_collaboration(tasks: list[dict], *, provider='auto', mock=False, root_dir=None, run_store=None) -> str  # 启动，返回 run_id（后台线程；T16 可选持久化 run 摘要）
collab.runner.get_collab_status(run_id, *, run_store=None) -> dict   # 轮询：running/done/failed + 结果摘要（含 overspend_tokens；先内存后历史）
collab.runner.stop_collab(run_id, reason) -> dict  # 软中止（标记 stopped，强杀 M2）
collab.runner.list_collab_runs(*, run_store=None) -> list  # 合并 live+历史（T16 持久化）

# T3 已实现（同步入口，T7 将包异步）：
collab.graph.run_collab_sync(tasks: list[Task], *, provider="auto", mock=False, root_dir=None, memory_store=None, mode="wave") -> CollabState
    # T14 mode：default wave；parallel=experimental（仅当所有任务 data_deps 为空，否则回退 wave）；纯标记不换调度
    # 返回 state：tasks（原始定义）/results（按 id 的执行结果，含 audit）/final_report
collab.graph.build_collab_graph(llm, *, root_dir=None, memory_store=None) -> CompiledStateGraph
    # 图：START→manager→(分波 Send)→execute_task→manager 循环→全终态→collect→END
    # 调度：data_deps 依赖的任务等依赖终态后执行（分波）；循环依赖/跨环依赖→BLOCKED
    # 关键：LangGraph Send 分支 state 隔离 → manager 聚合依赖产出+incoming 进 payload context，
    #       executor 只读 payload（勿改回跨分支读 state，否则任务看不到依赖结果）
    # 横向：执行后自动发结构化摘要给 allowed_links peers（receivers），下一波 peer 收到协作消息

# T8-T9 记忆（collab/memory.py）：
collab.memory.MemoryStore(db_path) -> per-agent SQLite 分区（add/search/list/mark_stale/get；add 内置 conflict→overridden 治理）
collab.memory.build_memory_context(entries) -> 注入 prompt 的「（记忆）...（记忆结束）」段
collab.memory.memory_entries_from_output(task, audit, snapshot_ids=None) -> 从已通过审计提取 judgment 记忆（confidence=coverage）
    # 注入：_build_task_prompt 在 persona_hint 之后、任务输入之前插 memory_context（来自 store.search(persona_id, 任务输入)）
    # 写回：arbitrate 节点仅在 verdict.ok 时写记忆（把将被判失败的产出排除在跨 run 记忆之外）
    # 治理(T9)：add 时检测「决策动词-对象」冲突（复用 collab.arbitration.detect_decision_conflicts），
    #   命中且新条目 confidence>=旧条目 → 旧条目置 overridden + contest_count+1 + 互挂 links（防污染/自增强）；
    #   若旧条目更强 → 新条目自己置 overridden（自增强门控：弱新判断不得覆盖强旧记忆）；
    #   list/search 默认排除 stale+overridden；mark_stale 不再刷新 updated_at；
    #   __post_init__ 校验 kind 集合 + clamp confidence[0,1]；provenance=审计快照锚点（input_snapshot[:24]）
    # 置信度：confidence=覆盖度（compute_anchor_coverage(summary, snapshot_ids)），recency 在检索 _score 里叠加（勿硬绑到记忆条目）
    # 复用：分词用 rag.config.tokenize；冲突/覆盖度复用 collab.arbitration（勿新造）
    # 注意：memory_store 默认 None；不传则无注入无写回（向后兼容，现有测试不受影响）

# T5 分层裁决：
collab.arbitration.hard_rules_check(task, audit, snapshot_ids=None) -> Verdict
    # 硬规则：audit 校验 + 动词-对象冲突检测（高熵动词）+ 锚点覆盖度置信度
    # failure_type 由硬规则层确定性赋值：audit_invalid / conflict / （manager_revise 由 graph 层）
collab.arbitration.manager_arbitrate(llm, task, audit, *, root_dir=None) -> (verdict, reason)
    # 经理暂定：LLM 判断产出是否满足 expected_output；无 expected_output 或 mock 时 pass
collab.arbitration.detect_decision_conflicts(*texts) -> list[Conflict]
collab.arbitration.compute_anchor_coverage(summary, snapshot_ids) -> AnchorCoverage
# Verdict 字段：task_id/ok/reasons/conflicts/coverage/manager/manager_reason/failure_type
# 图接线：全终态 → arbitrate 节点 →（有可重试 FAILED 回 manager）→ collect；results 按 id 合并

# T6 失败恢复 + 预算（graph.py）：
#   重试：transient/manager_revise 重试 1 次（attempts 上限 2）；audit_invalid/conflict/budget_exceeded/global_budget 不重试
#   双层预算：任务 budget_tokens（80k 默认）；全局 GLOBAL_TOKEN_BUDGET=400k，manager 路由波边界检查，
#   超限 → budget_stop 节点 STOPPED 剩余任务 + overspend_tokens 记账（波内超支额，可审计）
#   单任务级回滚：_merge_results 按 id 覆盖（失败→重试→成功覆盖旧结果）
#   注意：全局熔断是波边界语义（同波并行无法中途中止）

# T10 成本（collab/costing.py）：
collab.costing.price_tokens(provider, model, prompt_tokens, completion_tokens, pricing=None) -> float  # USD，未知 provider 用保守默认
collab.costing.is_estimated(provider, pricing=None) -> bool  # 未知 provider 标 estimated
collab.costing.cost_by_persona(results) -> dict[str, float]   # 按 persona 归集 audit.cost_usd
collab.costing.cost_summary(results) -> {"total_usd", "per_persona"}
    # 数据源：OpenAICompatLLM.last_usage（prompt/completion/total）+ model/provider_name（已在 client 上，勿新造发现层）
    # executor 把 usage 拆分 + provider/model + cost_usd + persona_id 写入 TaskAudit；report 输出总成本 + 按 persona

# T11 损耗/恢复（collab/costing.py + graph attempts）：
collab.costing.waste_breakdown(results, attempts) -> {effective_*, waste_*, waste_reasons:[{id,failure_type,attempt,token_usage,cost_usd}]}
collab.costing.feedback_summary(attempts, results) -> {tasks_that_retried, retries_that_succeeded, recovery_rate|None}
    # attempt_log：graph CollabState 增加 attempts(reducer add)，executor 每个执行分支(success/budget_exceeded/transient)都产出 attempt 记录
    # waste=全部attempt成本-有效(done+ok)成本；waste_reasons 用 attempt 序号标"superseded/transient/budget/失败"（含 manager_revise 无 failure_type）
    # feedback 更名 recovery_rate：needed=0 返回 None（0 重试≠100%）；一个任务多次重试与一次等价
    # 报告输出 损耗(USD)/损耗Token/损耗原因(id:type($cost)) + 重试恢复 N/M(recovery X)
    # 注意：executor 的 audit.cost_usd 是单次执行成本（非累计），故 total-effective 准确

# T12 预算弹性/责任/rep（Task.budget_soft_tokens + costing.rep_by_persona + graph)：
    # 软上限：task_token_total>budget_soft_tokens → 结果 soft_budget_warning=True + overspend_kind=debt（完成+被接受），不失败
    # 硬上限：>budget_tokens → fail(budget_exceeded, overspend_kind=loss)；全局 GLOBAL_BUDGET_SOFT=0.8*400k 仅预警，hard 才 budget_stop(loss)
collab.costing.rep_by_persona(results, attempts) -> {persona: 有效/总成本}
    # rep 只算不 gate（FR-ECO-5 推迟）；total==0 省略该 persona；persona 归因回退 result.persona_id
    # 报告输出 软上限预警任务数/全局预算预警/超支责任 debt=x;loss=y/Persons信誉(有效/总成本)

# FR11 会议动议（collab/motion.py，纯数据层最小动议）：
collab.motion.CollabMotion(task_id, topic, rationale, proposed_participants, budget_source) -> 动议
collab.motion.apply_decision(motion, decision=approve/reject, decided_by, reason, committee=None, audit_anchor="") -> motion
    # reject 必带原因否则 ValueError；approve 无 committee 默认 proposed_participants；要求 decided_by
collab.motion.merge_same_topic(motions) -> 同类 pending 合并（其余 MERGED），survivor.outputs[merged_from] 记录被吸收 id
collab.motion.MotionStore() -> 内存注册表（add/get/list/decide/merge_pending，线程安全）
    # 完整机制（manager LLM 审批/圆桌双产出/参会方增删/自由裁量额度/MERGED 语义）→ M3

# T14 双模式（graph.resolve_mode / run_collab_sync(..., mode)）：
collab.graph.resolve_mode(tasks, mode="wave") -> (eff_mode, experimental, parallel_note)
    # wave 默认；parallel 仅当所有任务 data_deps 为空→experimental=True，否则回退 wave+note；空集回退 wave
    # parallel 是纯标记（沿用现有 wave 调度，不换第二调度器/锁，圆桌决定）；报告输出「模式: wave|parallel（experimental）」

# T15 执行依赖：结论=不引入写依赖（T15 只出结论）
    # data_deps 为读依赖（分波调度，M1 已实现）；「改他人产出」走经理暂定+圆桌申诉（非依赖触发）
    # 未来 M3 可选做「读依赖时序触发」（A 终态→B ready，不改 A 产出），需复用 _verify_blocked_reachability 防环 + 量化门槛

# T16 持久化（collab/runstore.py + runner 接线）：
collab.runstore.RunStore(db_path) -> SQLite 运行历史（save/get/list，跨实例重开）
collab.runner.run_collaboration(tasks, *, ..., run_store=None) -> run_id  # T16：可选持久化 run 摘要
collab.runner.get_collab_status(run_id, *, run_store=None) -> dict        # 先内存 _RUNS，再历史 run_store
collab.runner.list_collab_runs(*, run_store=None) -> list                 # 合并 live + 历史
    # 只存摘要(_build_summary：task_count/statuses/token/cost/final_report)，不落全量 state/reasoning
    # run_id/created_at/provider/mock 为创建时字段不可变；崩溃后永久 running 归 M3

# T17 公司工作流入口 CLI（collab/cli.py，非 MCP、非 DSH workflow 工具）：
python -m collab run <tasks.json> [--provider auto] [--mock] [--mode wave] [--report] [--db PATH]   # 提交并阻塞到终态/超时，落 RunStore
python -m collab status/report/list/stop <run_id> [--db PATH]
    # run 阻塞到完成或超时；超时仍在 running → stop_collab(reason="cli timeout") 并返回 1（不孤儿）
    # stop 仅对本进程启动的 run 有效；--db 指定 RunStore（默认 repo/logs/collab_runs.db）

# T18 memory/motion CLI（collab/cli.py）：
python -m collab memory search|list|stale <agent_id> [--db PATH]     # 复用 MemoryStore；默认 logs/collab_memory.db
python -m collab motion submit|decide|list [--db PATH]               # 复用 MotionStore/apply_decision；默认 logs/collab_motions.db
    # MotionStore 增可选 db_path SQLite 持久化（db_path=None=内存，向后兼容）；reject 必带 reason
    # 记忆同源已补：collab run 通过 --memory-db 传入持久 MemoryStore（默认 logs/collab_memory.db），run 产生的记忆落入同库，memory list/search 可读
    # 动议同源待 FR11 机制接入图后再接（当前 motion CLI 独立库）

# T19 cost/损耗/预算接入 CLI（collab/costing.py + runner._build_summary + cli.cmd_cost）：
python -m collab cost <run_id> [--db PATH]     # 读摘要 cost/waste/recovery 字段；mock(0 成本)输出 (no cost data)
    # _build_summary 增列 cost_usd/cost_priced_usd/cost_estimated_usd/cost_by_persona、waste_cost_usd/waste_tokens/waste_reasons、retries_that_succeeded/tasks_that_retried/recovery_rate
    # 仅在非零时写入（0 成本/0 损耗/无重试不输出）；estimated 区分未知 provider

# T20 记忆开销计入成本（FR-GAP-1，collab/costing.py memory_summary + graph/audit/runner/cli）：
  # TaskAudit 增 memory_tokens（executor 用 rag.tokenize 对 memory_context 计 token）；costing.memory_summary 输出 memory_tokens/memory_cost_usd/memory_share
  # 记忆成本是 prompt 成本的子集（已在 prompt_tokens 计价），只拆分显示、不重复累加；_build_summary/collab cost/报告行 均可见（非零才输出）
  # 注意：memory_tokens 为本地 tokenizer 近似（估算口径）；memory_summary 只统计已接受任务审计（跨尝试完整口径未纳入，随 T21 收口）

# T21 search 分数阈值 + 候选上限（FR-GAP-2，collab/memory.py MemoryStore.search）：
  # search(..., min_score=1.0, candidate_limit=50)：min_score 过滤 s>0.0 and s>=min_score (无强命中不注入)；candidate_limit 用 SQL LIMIT 界住每 agent 候选扫描（最近优先，None=不限）
  # list 增 limit 参数（memory list CLI 不受影响）；CLI memory search 增 --min-score/--candidate-limit 透传
  # 唯一默认值：min_score=1.0、candidate_limit=50（满足 NFR §7.9）；默认行为变更=既门控又上限，需在指南说明

# T22 RunStore 崩溃恢复（FR-GAP-3，collab/runstore.py + runner.py）：
  # runs 表增 last_heartbeat（CREATE+ALTER 迁移）；RunStore.touch(run_id) 刷新心跳；normalize_stale(grace=DEFAULT_CRASH_GRACE_SECONDS=120) 把仍 running 且 COALESCE(last_heartbeat,created_at) 超期的记录归一为 failed + stop_reason=crashed
  # run_collaboration 在有 RunStore 时启动 daemon 心跳线程（每 10s touch），worker 完成在 finally 置 _hb_stop 停线程；初始 running 记录 last_heartbeat=created 作基线
  # get/list 开头自动 normalize_stale → 任何状态/列表查询都恢复孤儿 running（不永久 running）；唯一默认值 grace=120s（NFR §7.9）

# T23 FR-META 对抗性核验（FR-GAP-5，tests/test_collab_adversarial.py）：
  # 9 个对抗性用例：无效审计被 hard_rules 揭出；自相矛盾被 detect_decision_conflicts 揭出；负成本被 build_audit 拒绝；kind=fact 无 provenance 被拒；REVISE 产出不写记忆；弱矛盾不能覆盖强记忆；超预算 FAILED+budget_exceeded；孤儿 run 归一 failed；记忆成本=子集不重复计价
  # 对抗性发现的 bug 已修：build_audit 对原始 token/prompt/completion/cost 负数直接 ValueError（不再被 TaskAudit clamp 吞掉，与 validate_audit 契约一致）

# T24 全量验收 + V1 失败三分类 + 文档定稿（M3 收官）：
  # 全量 pytest tests/ = 226 passed / 0 failed / 2 skipped；V2 collab 156 passed
  # 5 个 V1 预存在失败同源=rag/chunker._source_file 用 str(Path) 存 source_file 元数据（Windows 反斜杠）→ 改 Path.as_posix() 统一 POSIX；分类=真 bug→修（非 xfail/非断言过时）
  # 验收报告 docs/v2-collaboration-engine-m3-completion-report.md；docs 与代码均在 m2 分支，未 push（内容定稿后可按需发布）
```

## 4. 硬约定（改代码前必读）

1. **DSH schema 约束**：MCP 工具参数禁用 `Optional`/`anyOf` → 可选参数用 `""`/`0` 默认值；`list[dict]` 参数用 **JSON 字符串**（schema 的 additionalProperties 必须是 boolean）。
2. **新增参数必须字符串/标量**；复杂结构走 JSON 字符串 + `json.loads`。
3. **测试命令**：`python -m pytest tests/ -q`（V1 19 个 + V2 collab 测试）；DSH 兼容校验用 TS 脚本 `assertSupportedJsonSchema`（见 PROJECT_MEMORY 踩坑）。
4. **M1 范围纪律**：不做 MCP 工具化（M3）、记忆/FR11（M2）、执行依赖（M2）。
5. **三问共享产出记录**：审计记录 = 裁决依据 = 交流引用，单一事实源，勿各建一套。
6. **Persona/LLM/RAG 复用现有**，不新造轮子。
7. **圆桌评审负载**：跑多专家"圆桌"评审时，**勿让多个 subagent 并行且各自读多个大文件**（如同时读 memory.py + graph.py + 测试 + 需求文档）——会因 context 过载被上层中止（表现为卡住、报 `[object Object]`、长时间无返回）。做法：让每个评审 agent **只读 1 个核心小文件**（或把核心逻辑**内联成精简上下文**），并**收紧输出**为紧凑结构化 JSON（verdict + 少量 concerns），避免拖出 100KB+ 长文。日常评审用 3 专家 + 内联摘要即可，关键里程碑（如 M2 全量）再跑 5 专家全量。参考：2026-08-25 并行 5 专家各读 4 文件被中止，改逐个跑通，全量评审还揪出连接泄漏 bug。

## 5. 如何更新本文件

- 新增/修改 `collab/` 或 `mcp_server/` 的接口、数据模型、状态机时，同步更新对应小节；
- 新增包/文件时更新"代码地图"；
- 新增硬约束时追加到第 4 节；
- 大决策/踩坑进 `docs/PROJECT_MEMORY.md`（本文件只放"接代码要用的信息"）。
