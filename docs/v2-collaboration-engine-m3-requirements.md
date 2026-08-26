# V2 引擎：M3 里程碑项目需求与实现方案

> 版本：v0.3（含「两个入口」设计调整，自审+圆桌后）｜日期：2026-08-25
> 上游：docs/v2-collaboration-engine-m2-requirements.md（M1/M2 已交付）+ docs/v2-collaboration-engine-m2-completion-review.md（M2 收官，含显式 M3 缺口）
> 圆桌：轻量 3 专家（Computing/Philosophy/History）一致 approve_with_concerns；本节决议对 §3/§7/§9 做了收敛。

## 1. 概述：M3 定位
M1/M2 交付了 V2 协作引擎（collab 包），但只在 Python 层。M3 是**交付里程碑**，且**拆成两个入口**（见 §1.1）：
1. **补齐 M2 收官列的 M3 缺口**：记忆开销计入成本闭环、search 上界、RunStore 崩溃恢复、FR-META 对抗性核验。
2. **把 V2 协作引擎作为「工作流入口（公司模式）」交付**：声明式提交公司任务 → 引擎编排 → 轮询/检查点 → 可审计报告。
3. **全量验收**（NFR 全项落地，量化）+ **文档定稿**。

### 1.1 两个入口（设计调整）
| 入口 | 模式 | 定位 | 形态 | 现状 |
| --- | --- | --- | --- | --- |
| **入口 A：MCP（会议）** | 模式 A 圆桌/评审 | 一次性召集会议/评审/调研 | MCP 工具（list_councils / search_knowledge / run_roundtable / ...） | **已有（V1 10 工具）**；M3 只是定位，不新增 |
| **入口 B：工作流（公司）** | 模式 B 协作执行 | 公司化多 agent 协作：分派/执行/横向交流/仲裁/恢复/预算/记忆/动议 | 声明式长时工作流（submit → 轮询 → 取报告），**以工作流运行器/CLI 消费（非 MCP，非 DSH workflow 工具）** | **V2 collab（Python 层）**；M3 交付此入口 |

> 说明：V1（会议）是「MCP 工具」；V2（公司）本质是「长时工作流/编排引擎」。两者不混在同一调用语义下——会议工具短、一次调用即完成；公司工作流长、提交后异步运行并需状态与报告。

## 2. 目标与非目标
### 目标
- G1（MCP）：V2 协作执行、记忆、动议（最小）、成本/损耗/预算经 MCP 调用（DSH / Claude Code 双端）。
- G2（缺口）：记忆开销计入成本；search 有无强命中不注入/候选上限；RunStore 崩溃恢复；FR-META 对抗性核验。
- G3（验收）：NFR 全项量化验收；V1 零回退；5 个预存在 Windows 路径断言三分类处理。
- G4（文档）：AGENT_GUIDE / PROJECT_MEMORY / README_MCP / M2/M3 需求定稿。
### 非目标（M3 不做）
- 不做完全 mesh / 跨进程自治 Agent 网络 / 第二套运行时。
- 不做子 Agent 递归拉起其他 Agent。
- **不做 FR11 完整机制**（manager 审批/圆桌双产出/参会方增删/自由裁量/MERGED）→ **M3.x 独立 PR**；M3 只做动议工具**最小闭环**（挂接 MotionStore 纯数据层）。
- 不做执行依赖（写依赖，T15 已裁定）；「读依赖时序触发」仅列为 M3.x 可选 FR。
- 不改变 V1 圆桌行为（向后兼容）。

## 3. 范围（需求条目；工具粒度 P0/P1/P2；均属**入口 B（公司工作流）**）
> 入口 A（会议/MCP）为 V1 现有 10 工具，M3 不做新增、只做定位与文档；以下 FR-MCP 均为入口 B（公司工作流）的能力。
| 编号 | 需求 | 优先级 | 说明（入口 B） |
| --- | --- | --- | --- |
| FR-MCP-1 | run_collaboration（公司工作流入口） | P0 | tasks JSON 字符串 + provider/mock/mode，异步返回 run_id；定位为「提交公司任务」 |
| FR-MCP-2 | manage_tasks（查询/中止工作流） | P0 | get_collab_status / list_collab_runs / stop_collab；含成本/损耗/恢复、状态轮询 |
| FR-MCP-3 | 记忆工具（公司） | P1 | search_memory / manage_memory（挂接 collab.memory.MemoryStore 底层库） |
| FR-MCP-4 | 动议工具（公司，最小闭环） | P1 | submit_motion / decide_motion / list_motions（挂接 MotionStore 纯数据层；完整机制→M3.x） |
| FR-MCP-5 | 成本/损耗/预算查询（公司） | P1 | get_collab_status 摘要增 cost/waste/recovery；可选 cost_report |
| FR-MCP-6 | 双模式暴露（公司） | P1 | run_collaboration 加 mode（parallel 仅当无 data_deps，标 experimental） |
| FR-GAP-1 | 记忆开销计入成本闭环 | P0 | 记忆检索/注入 token 纳入 costing/waste（M2 收官 §4） |
| FR-GAP-2 | search 分数阈值 + 候选上限 | P1 | 无强命中不注入 + 每 agent 候选上限 |
| FR-GAP-3 | RunStore 崩溃恢复 | P1 | 心跳/超时归一 failed，不永久 running |
| FR-GAP-4 | FR11 完整机制 | **M3.x** | 从 M3 拆出；M3 只做动议最小闭环 |
| FR-GAP-5 | FR-META 对抗性核验 | P2 | 制造错误→系统揭出并修正的验收 |
| FR-VERIFY | 全量验收（NFR 量化） + 5 个 V1 三分类 | P0 | 见 §7 |

## 4. 关键设计约束
### 4.1 DSH schema 子集（沿用）
- MCP 工具参数禁用 Optional/anyOf → 可选参数用 ""/0 默认值。
- 复杂结构（list[dict]）用 **JSON 字符串** + 服务端 json.loads；additionalProperties 必须 boolean。
- 参数一律字符串/标量/boolean；工具名限 [A-Za-z0-9_-]{1,32}。
### 4.2 异步 + 进度（roundtable 修正）
- run_collaboration 用 run_in_executor 跑后台，启动即返 run_id。
- **进度不依赖已返回工具的 ctx.report_progress**（后台线程在工具返回后再上报可能丢失）。改为：**get_collab_status 轮询 / 事件日志**承载进度（worker 把波次完成写进 run 摘要，manage_tasks/tool 轮询读取）。
### 4.3 超时
- DSH toolCallTimeoutMs 调大（真实 LLM 多波）；MCP read_timeout_seconds 调大。
### 4.4 JSON 负载服务端校验（roundtable 补充）
- DSH schema 只校验 tasks 为 type:string；**服务端必须**对 json.loads 结果做严格校验 + 长度/数量上限，非法负载返回明确错误（防畸形/超大/任意键）。

## 5. 工具定义（FR-MCP-1~6）
### 5.1 run_collaboration（async）
`run_collaboration(tasks: str, *, provider="auto", mock=False, mode="wave", root_dir="") -> dict`（tasks JSON 数组，元素 {id, persona_id, input, expected_output?, data_deps?, allowed_links?, budget_tokens?, budget_soft_tokens?}；服务端严格校验 + 限长）。
### 5.2 manage_tasks（sync）
`get_collab_status(run_id) / list_collab_runs(limit=20) / stop_collab(run_id, reason="user requested")`；get_collab_status 摘要含 cost/waste/recovery（FR-MCP-5）。
### 5.3 记忆工具（FR-MCP-3）
`search_memory(agent_id, query, top_k=5)` + `manage_memory(action, agent_id, entry_id="", content="")`（action: get|list|stale；挂接 MemoryStore）。
### 5.4 动议工具（FR-MCP-4 最小闭环）
`submit_motion(task_id, topic, rationale, proposed_participants="[]", budget_source="task")` + `decide_motion(motion_id, decision, reason="", committee="[]")`（reject 必带 reason）+ `list_motions(status="pending")`；挂接 MotionStore/apply_decision。
### 5.5 成本/损耗/预算（FR-MCP-5）
- get_collab_status 摘要增 cost_usd/priced_estimated/waste_cost_usd/waste_reasons/recovery_rate/overspend_kind。
- 可选 `collab_cost_report(run_id)` 返回 cost_by_persona + waste_breakdown + rep_by_persona。

## 6. 与现有代码对接点
| M3 改动 | 触及 |
| --- | --- |
| MCP 工具化 | mcp_server/server.py 增 @mcp.tool；core.py 增 *_impl（薄封装 collab 纯函数） |
| 记忆/动议工具 | collab/memory.py + motion.py（已实现底层库） |
| 成本/损耗 | collab/costing.py（已有） |
| run 持久化 | collab/runstore.py（M2 已落；M3 接崩溃恢复 + MCP 历史查询） |
| DSH schema | 新工具参数字符串/标量/JSON 字符串；服务端校验负载 |

## 7. 验收标准（NFR 全项，量化）
1. **功能**：V2 协作/记忆/动议（最小）/成本经 MCP 可调；异步 run + 轮询；双模式生效。
2. **兼容**：DSH schema 校验通过；Claude Code 实测；V1 圆桌零回退。
3. **成本**：记忆开销计入成本；未知 provider 标 estimated；按 persona 归集；损耗/recovery 正确。
4. **安全**：key 只进 .env；工具不暴露任意路径；记忆默认不进报告。
5. **失败恢复**：RunStore 崩溃恢复（不永久 running）；单点失败可跳过/重试。
6. **并发幂等**：重入去重；写锁。
7. **可观测**：事件日志 + 状态轮询；失败详情可读。
8. **回归**：全量绿。**5 个 V1 预存在失败三分类**（真 bug→修 / 环境问题→xfail / 断言过时→更新断言），各给处置结论，不再以「已知失败」停在基线。
   - **T24 已定稿**：全量 226 passed / 0 failed / 2 skipped；5 个失败**全为同一跨平台真 bug→修**（`rag/chunker._source_file` 用 `Path.as_posix()` 统一 POSIX 分隔符），见 docs/v2-collaboration-engine-m3-completion-report.md。
9. **量化补充**：NA 成本误差上限（如 <=5%）、search 候选上限默认值、崩溃恢复时间窗、恢复率口径等给唯一默认值。

## 8. M3 任务分解（提议）
| 编号 | 任务 | 交付物 | 验收 |
| --- | --- | --- | --- |
| T17 | MCP 工具化（run_collaboration/manage_tasks） | server/core 增工具；异步+状态轮询 | DSH schema + 双端实测 |
| T18 | MCP 记忆/动议（最小）工具 | search_memory/manage_memory/submit_motion/decide_motion/list_motions | 工具可调、底层库复用 |
| T19 | 成本/损耗接入 | get_collab_status 摘要增 + cost_report | 数字正确、estimated 标注 |
| T20 | 记忆开销计入成本（FR-GAP-1） | costing 纳入记忆 token | 记忆成本可见 |
| T21 | search 阈值+候选上限（FR-GAP-2） | memory.search 加阈值+上限 | 无强命中不注入 |
| T22 | RunStore 崩溃恢复（FR-GAP-3） | 心跳/超时归一 failed | 不永久 running |
| T23 | FR-META 对抗性核验（FR-GAP-5） | 对抗性用例 | 制造错误→揭出并修正 |
| T24 | 全量验收 + 5 个 V1 三分类 + 文档（✅） | 验收报告 + 文档定稿 | 全量绿；文档齐 |

**M3 排期**：T17-T18（工具化）P0 先行；T19-T21（成本+search）次之；T22-T23（缺口）随后；T24（验收+文档）收尾。约 1-1.5 周。

## 9. 开放问题（已按圆桌收敛为决议）
1. **FR11 完整机制**：→ **M3.x 独立 PR**（圆桌决议，不纳入 M3 主交付）。
2. **工具粒度**：P0=run_collaboration+manage_tasks；P1=记忆/动议（最小）/成本；不把 V1 run_roundtable 的 V2 召集接入（留 M3.x）。
3. **5 个 V1 失败**：→ §7.8 三分类，逐条给处置。
4. **成本报告形态**：get_collab_status 内嵌摘要为主，cost_report 为可选项。
5. **M3 范围**：已剔除 FR11 完整机制/执行依赖，控制在 1-1.5 周。

## 10. 参考
- docs/v2-collaboration-engine-m2-requirements.md（§11 决议）、m2-completion-review.md（§4 M3 缺口）
- collab/memory.py / costing.py / motion.py / runstore.py / runner.py / graph.py（M2）
- mcp_server/server.py + core.py（V1 FastMCP 模式）
- PROJECT_MEMORY 踩坑（DSH schema/超时/mcp 锁版本）

## 11. 圆桌决议（2026-08-25，v0.3；含「两个入口」设计调整）
- **设计调整（用户提出 + 采纳）**：V1（会议）是 **MCP 工具**；V2（公司）本质是 **长时工作流/编排引擎**。故 M3 拆两个入口：**入口 A = MCP（会议，V1 已有 10 工具，只做定位/文档，唯一 MCP）**；**入口 B = 工作流运行器/CLI（公司，V2 collab 声明式长时工作流，非 MCP、非 DSH workflow 工具，由工作流运行器驱动）**。FR-MCP-1~6 均属入口 B，经工作流运行器/CLI 消费。
- **approve_with_concerns**。已吸收：① FR11 完整机制→M3.x；② 异步进度改状态轮询/事件日志；③ JSON 负载服务端严格校验+限长；④ 工具粒度 P0/P1/P2；⑤ 5 个 V1 失败三分类 + NFR 量化。
- 主交付（入口 B 工作流）：run（提交公司任务）+ manage/status（轮询/中止）+ 记忆/动议最小闭环 + 成本/损耗接入 + 记忆成本计入 + search 上界 + RunStore 崩溃恢复 + 全量验收 + 文档；入口 A（会议）保持 V1。