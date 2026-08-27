# v2-collaboration-engine

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)  [![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)  [![CI](https://github.com/silicon-sbt/v2-collaboration-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/silicon-sbt/v2-collaboration-engine/actions/workflows/ci.yml)  [![codecov](https://codecov.io/gh/silicon-sbt/v2-collaboration-engine/branch/master/graph/badge.svg)](https://codecov.io/gh/silicon-sbt/v2-collaboration-engine)

把多 Agent 协作的「**责任、成本、可审计性**」落成可验证工程的**工作流运行器**。

> 一句话：`python -m collab run tasks.json` 跑一次协作，报告告诉你——谁做的、花了多少 token 和钱、被打回几次、最后成没成。

## 为什么需要它

多 Agent 不是免费午餐：每个协作任务都会多花一份**协调费**（经理/仲裁角色、每步审计、角色间传话、失败重试）。如果这些没省下更多冗余工作，多 Agent 就是「**更贵且更差**」——双输。

我们的差异化不是“再堆一层编排器”，而是把「**协作到底值不值、能不能追责**」算清楚、可回查。

## 一份报告能告诉你什么

跑一次协作，报告会给出：

- **总 token 消耗**（按角色归集）；
- **成本 USD**（按 persona 拆分；未知供应商明确标注「估算」）；
- **损耗**（失败 / 打回 / 超预算的 token 与成本）；
- **恢复率**（重试成功的占比；无重试记 `N/A`）；
- **每步任务的审计结论 + 引用依据**（可回查，不是黑盒）。

## 核心特性

- **波次调度**：依赖没对齐就不往下走，避免「设计没定就写代码」的错序。
- **分层裁决**：审计硬规则 + 经理临时裁决，接受或打回；打回留痕、可重试。
- **成本 / 损耗 / 恢复率**：把「协调费」算成账，不静默吞掉；失败能看见、能算清楚。
- **记忆诚实**：没有强命中就不注入、绝不编造；命中的片段带真实来源，关键事实有锚点。
- **崩溃恢复**：跑挂的任务归一为失败，不会一直「运行中」。
- **轻量 / 独立裁决**：简单任务可跳过经理复核；审查者可用不同模型，避免“自己写自己审”。

## 和同类框架的差异

很多框架解决「**怎么编排**」——LangGraph（图状态机）、AutoGen（多 Agent 对话）、CrewAI（角色 crew）、MetaGPT（需求→代码）。

我们解决的是「**这协作值不值、能不能追责**」：把成本、损耗、审计、来源做成可验证的工程。

（它们各有长处；我们的差异化在「可审计 + 成本透明 + 责任可追溯」。）

## 快速开始

```bash
git clone https://github.com/silicon-sbt/v2-collaboration-engine.git
cd v2-collaboration-engine
pip install -r requirements.txt
python -m collab run tasks.json --provider auto --db logs/collab_runs.db
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
| `collab run <tasks> [--provider auto|mock] [--mode wave|parallel] [--light] [--audit-model M] [--audit-provider P] [--db PATH] [--memory-db PATH]` | 提交并阻塞到终态；`--light` 轻量、`--audit-*` 独立裁决 |
| `collab status/report/cost/list/stop <run_id> [--db PATH]` | 状态 / 报告 / 成本 / 列表 / 软停止 |
| `collab memory search|list|stale <agent_id> [--db PATH]` | 记忆检索 / 列表 / 过期（支持 `--min-score`/`--candidate-limit`） |
| `collab motion submit|decide|list [--db PATH]` | 动议提交 / 裁决 / 列表 |

## 可靠性

- **测试**：18 个 collab 测试 + 对抗性核验（制造错误→系统揭出/修正）。
- **覆盖率约 91%**，CI 每天定时 + push，跑 **Python 3.10 / 3.11 / 3.12** 三种版本。
- **自包含**：除标准库外仅依赖 `langgraph`、`requests`，不依赖其他内部模块。

## 口径说明

- **恢复率**：`成功重试的任务数 / 需要重试的任务数`（重试口径）；无重试为 `None`，报告渲染为 `N/A`。
- **记忆**：无命中时返回空、不注入；命中带真实分数与来源，不插值填充。
- **成本**：未知 provider 标 `estimated`；记忆成本是 prompt 成本的子集拆分，不重复累加。

## 模块结构

- `collab/graph.py`：LangGraph 波次图层评审/执行图。
- `collab/audit.py` `collab/arbitration.py`：审计构造 + 硬规则 + 经理裁决。
- `collab/memory.py` `collab/motion.py`：per-persona 记忆 + 动议。
- `collab/costing.py`：计价 / 成本归集 / 损耗 / 恢复率 / 记忆成本。
- `collab/runstore.py` `collab/runner.py`：持久化 + 崩溃恢复 + 心跳。
- `collab/cli.py`：`python -m collab` 工作流 CLI。
- `collab/tokenize.py` `persona.py` `llm.py`：自包含 tokenizer / persona 提示 / LLM client。

## 贡献

想参与？见 [CONTRIBUTING.md](CONTRIBUTING.md)。提交 bug / 需求 / PR 都欢迎。

## 许可

MIT License（见 `LICENSE`）。

## 致谢

- 感谢原始项目 [`agent_roundtable`](https://github.com/Random-Walk2026/agent_roundtable)（Random-Walk2026）：多 Agent 圆桌与协作审计的思路，是本引擎的重要起点。
- 感谢 **ClaimCheck（CatNebulaaaa）**：用于本项目的开源完整性核查。
