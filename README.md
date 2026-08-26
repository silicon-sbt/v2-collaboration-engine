# v2-collaboration-engine

独立的弱去中心化多 Agent 协作引擎（公司工作流运行器 / CLI）。

> 定位：**入口 B = 公司**。本引擎是声明式长时工作流运行器，以 `python -m collab` 驱动；
> **不是** MCP 工具，也**不是** DSH workflow 工具。V1（会议=MCP）由上游 `roundtable/mcp_server` 提供，与本引擎分离。

## 特性

- **波次调度（wave scheduler）**：并行波执行 + 收集 + 再调度，直到所有任务终态。
- **分层裁决**：L2 审计硬规则（`validate_audit`）→ 经理临时裁决（`manager_arbitrate`），接受/打回。
- **失败恢复**：打回/瞬时失败重试，报告含恢复率（recovery_rate）+ 软/硬预算上限。
- **成本/损耗透明化**：prompt/completion 拆分计价、按 persona 归集、损耗 USD/token、estimated 标注。
- **双模式**：`wave`（默认）/ `parallel`（experimental，仅当任务无 data_deps）。
- **记忆**：per-persona SQLite 分区、Top-K 检索（score 阈值 + 候选上限）、provenance 锚点、T9 治理（矛盾降级/防自增强）。
- **动议**（FR11 最小）：`CollabMotion`/`MotionStore`，approve/reject/merge，可 SQLite 持久化。
- **持久化与崩溃恢复**：RunStore 存摘要 + 心跳 + 孤儿 run 归一 failed。
- **非劣闸门**：面向「省下的冗余 token > 多花的协调 token」，拒绝「更贵且更差」。
- **轻量模式**（`--light`）：跳过经理裁决（仅硬规则），少一次 LLM 复核，适合单文件/单人任务。
- **交付物前置**（`report --summary`）：先给 3 行摘要 + 任务结果，审计/成本日志折叠。
- **独立裁决**（`--audit-model/--audit-provider`）：让 auditor/manager 用不同模型，避免同一模型自审自批。

## 要求

- Python 3.10+
- 依赖：`langgraph`、`requests`（`pip install -r requirements.txt`）

## 快速开始

```bash
python -m collab run tasks.json --provider auto --db logs/collab_runs.db
python -m collab status <run_id> --db logs/collab_runs.db
python -m collab report <run_id> --db logs/collab_runs.db
python -m collab cost <run_id> --db logs/collab_runs.db
```

`tasks.json` 是任务数组，每项至少含 `id`、`persona_id`、`input`：

```json
[{"id":"t1","persona_id":"computing","input":"评估成本与收益","expected_output":"给出方案"}]
```

## 命令一览

| 命令 | 说明 |
| --- | --- |
| `collab run <tasks> [--provider auto|mock] [--mode wave|parallel] [--light] [--audit-model M] [--audit-provider P] [--db PATH] [--memory-db PATH]` | 提交并阻塞到终态（公司工作流入口；`--light` 轻量、`--audit-*` 独立裁决） |
| `collab status/report/cost/list/stop <run_id> [--db PATH]` | 状态/报告/成本/列表/软停止 |
| `collab memory search|list|stale <agent_id> [--db PATH]` | 记忆检索/列表/过期（search 支持 `--min-score`/`--candidate-limit`） |
| `collab motion submit|decide|list [--db PATH]` | 动议提交/裁决/列表（FR11 最小） |

## 模块结构

- `collab/graph.py`：LangGraph 波次图层评审/执行图。
- `collab/audit.py`：L2 审计构造与硬规则校验。
- `collab/arbitration.py`：硬规则 + 经理裁决 + 决策冲突/锚点覆盖。
- `collab/memory.py`：per-persona SQLite 记忆 + 检索 + 治理。
- `collab/motion.py`：动议纯数据层。
- `collab/costing.py`：计价/成本归集/损耗/恢复率/记忆成本。
- `collab/runstore.py`：RunStore 持久化 + 崩溃恢复。
- `collab/runner.py`：run_collaboration / get_collab_status / list_collab_runs + 心跳。
- `collab/cli.py`：公司工作流 CLI（`python -m collab`）。
- `collab/tokenize.py` / `persona.py` / `llm.py`：自研 tokenizer / persona 提示 / LLM client（自包含，无上游依赖）。

## 与上游的关系

本引擎**自包含**：`collab/` 与全部测试对 `roundtable/mcp_server/rag/config/llm/llm_gateway` 零 import。
外部依赖仅 `langgraph`、`requests` + 标准库。

## 口径说明

- **恢复率**：`recovery_rate = 成功重试的任务数 / 需要重试的任务数`（重试口径，非「首次尝试通过率」）；无重试时为 `None`，报告渲染为 `N/A`。
- **记忆诚实化**：无命中时 `MemoryStore.search` 返回 `[]`，`build_memory_context([])` 为空串 → **不注入**；命中片段带真实 score 与来源，不插值填充。
- **成本**：未知 provider 标 `estimated`；记忆成本是 prompt 成本的子集拆分，不重复累加。

## 许可

MIT License（见 `LICENSE`）。
