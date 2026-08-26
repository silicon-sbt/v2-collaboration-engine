# V2 引擎：M3 入口细则（公司工作流 vs 会议 MCP）

> 日期：2026-08-25 ｜ 性质：动工前细则 ｜ 依据：DSH dsh-tool-workflow / dsh-workflow README（工作流=workflow 工具，JS 编排 subagent，前台/无 checkpoint/无预算）+ 项目 collab 引擎（领域工作流）
> 待确认：§11 的 1 个决策（公司工作流如何被 DSH/Claude Code 消费）。

## 0. 研究结论（为什么这样分）
- DSH「workflow」= `workflow` 工具：模型写 JS，分派 subagent，**前台收集、无 checkpoint 续跑、无 token 预算记账**。
- 项目「公司模式」= **领域工作流引擎**（collab：LangGraph 编排 personas + 记忆/预算/成本/审计/持久化 + 异步提交-轮询-报告）。
- 因此：公司模式**既不该用 MCP server mode 当载体**，**也不适合塞进 DSH 的 `workflow` 工具**。它有自己的工作流引擎入口。

## 1. 两个入口定义
| 入口 | 模式 | 做什么 | 语义/时序 | 载体 |
| --- | --- | --- | --- | --- |
| **入口 A：会议** | 模式 A（圆桌） | 召集圆桌评审/对齐/调研；查 counceils/agents/knowledge | 短、同步、一次即完成；报告落 logs/ | **MCP server**（agent-roundtable，V1 10 工具，保持不改） |
| **入口 B：公司** | 模式 B（协作） | 声明式公司协作：分派→执行→横向交流→仲裁→恢复→预算→记忆→动议 | 长、异步、提交→轮询→取可审计报告 | **工作流引擎入口**（collab 引擎本体，非 MCP、非 DSH workflow 工具） |

## 2. 入口载体（研究校正后）
- **入口 A（会议）＝ MCP server**：`mcp_entry.py --server meeting`，serverName = agent-roundtable（V1 10 工具，零迁移）。这是唯一的 MCP server。
- **入口 B（公司）＝ 工作流引擎入口**：collab 引擎（`run_collaboration` / `get_collab_status` / `list_collab_runs` / `stop_collab` + memory/motion/cost/waste/budget），**不注册为第二个 MCP server**、**不是 DSH `workflow` 工具**。它是领域工作流引擎，由**工作流运行器 / 宿主驱动**（见 §11）。

## 3. 工具清单与归属
### 入口 A：会议（agent-roundtable，V1 10 工具，M3 不新增）
list_councils / list_agents / get_agent / list_knowledge_corpora / search_knowledge / plan_council / run_roundtable / list_reports / read_report / provider_info。
### 入口 B：公司（collab 工作流引擎，M3 交付）
run_collaboration / get_collab_status / list_collab_runs / stop_collab / search_memory / manage_memory / submit_motion / decide_motion / list_motions / collab_cost_report（可选）。

## 4. 命名/注册
- **只注册一个 MCP server（会议）**：DSH cordis.patch.yml + Claude ~/.claude.json 各一条（command=`<python> mcp_entry.py --server meeting`）；工具名 mcp__agent-roundtable__* 不变。
- **公司工作流入口是独立入口**，不新增 mcp.add；由工作流运行器/宿主驱动（见 §11），或作为 CLI/库被宿主调用。
- 共享 .env（key）；会议与公司共用 provider 路由（llm_client）。

## 5. 协议/语义
- **会议（MCP）**：同步短调用；run_roundtable 用 run_in_executor + ctx.report_progress（即时）；结果即报告（logs/）。
- **公司（工作流引擎入口）**：run_collaboration 提交任务（返回 run_id）→ 引擎异步执行（LangGraph 分派/执行/横向/仲裁/恢复/预算/记忆/动议）→ get_collab_status 轮询/检查点 → 取可审计报告。进度/状态由轮询与事件日志承载（不依赖已返回工具 ctx）。**声明式长时工作流**。

## 6. 跨入口协作
- 公司工作流可召集会议（评审/对齐）：入口 B 的动议/评审需求 → 调入口 A run_roundtable（跨入口）。会议产物以 audit 锚点 / CollabMessage 形态回填 B（单一事实源）；会议评审不直接改写公司任务产出。
- 边界：会议=评审/对齐；公司=执行。

## 7. 数据/存储
- 会议：logs/（V1 报告）。
- 公司：runstore（run 摘要+历史）+ memory（per-agent）+ 报告（final_report 摘要，不落全量 state）。

## 8. 验收/测试按入口分
- 会议（V1）：tests/test_mcp_tools.py + DSH/Claude Code 实测；零回退。
- 公司（V2）：tests/test_collab_*.py（127）+ 工作流运行器级测试；DSH schema 校验 + Claude Code 实测。

## 9. 已知边界（与 DSH workflow 工具的差异，故不使用它）
- DSH `workflow` 工具：前台收集、无 checkpoint 续跑、无 token 预算。
- 公司 collab 引擎：异步提交-轮询、RunStore 持久化、预算/成本/审计 —— 这些正是 collab 引擎具备而 DSH `workflow` 工具不具备的。

## 10. 决策说明
按本细则：M3 动工时，mcp_entry.py 只保留 `--server meeting`（会议 MCP，V1）；公司工作流作为**独立工作流引擎入口**交付（collab 引擎 + 一个工作流运行器/宿主驱动），不注册为第二个 MCP server，也不映射到 DSH `workflow` 工具。

## 11. 已拍板（2026-08-25）：公司工作流入口 = 工作流运行器 / CLI（非 MCP）
- **入口 B（公司）**：collab 工作流引擎，**以工作流运行器 / CLI 消费**（如 `python -m collab run <tasks>` + `collab status <run_id>` / `collab report <run_id>`），宿主 agent 以**非 MCP** 方式调用（本地进程/服务）。
- **入口 A（会议）**：MCP server（agent-roundtable），**保留为唯一 MCP**。
- 不被 DSH `workflow` 工具承载（无持久化/预算/异步后台），也**不注册为第二个 MCP server**。