# v2-collaboration-engine

[English](README_EN.md) | 中文

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)  [![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)  [![CI](https://github.com/silicon-sbt/v2-collaboration-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/silicon-sbt/v2-collaboration-engine/actions/workflows/ci.yml)  [![codecov](https://codecov.io/gh/silicon-sbt/v2-collaboration-engine/branch/master/graph/badge.svg)](https://codecov.io/gh/silicon-sbt/v2-collaboration-engine)  [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)  [![Maintained](https://img.shields.io/badge/Maintained-yes-green.svg)]()  [![Last commit](https://img.shields.io/github/last-commit/silicon-sbt/v2-collaboration-engine)]()

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

### 一键安装（PyPI）

```bash
pip install v2-collaboration-engine
collab demo --mock
```

### 从源码跑

```bash
git clone https://github.com/silicon-sbt/v2-collaboration-engine.git
cd v2-collaboration-engine
pip install -r requirements.txt
python -m collab demo --mock
```

### 零配置体验（不用 API key）

```bash
python -m collab demo --mock
```

跑内置的 3 个跨 persona 任务（产出 → 引用 → 汇总），全程用确定性 mock，离线可用，立刻看到「波次执行 → 审计 → 裁决 → 记忆 → 成本闭环」的报告：

```text
collab 弱去中心化协作引擎 · 快速体验
----------------------------------------------------------------
模式: wave
provider: auto（auto：有 key 用真实模型，无 key 回退 mock）
任务数: 3，跨 persona 协作（产出 → 引用 → 汇总）
----------------------------------------------------------------
run_id: 50fc2259319c · status: done

--- final_report ---
# 协作执行报告

- 任务数: 3
- Token 总消耗: 0
- 模式: wave

## 任务结果

### a-research（investing）— done
- 引用输入快照: N/A
- 关键决策点: 1) 风险清单
- 任务结论: （mock）已生成。这是确定性占位输出，不代表真实模型判断。

### b-check（macroeconomics）— done
- 引用输入快照: a-research
- 关键决策点: 1) 宏观应对建议
- 任务结论: （mock）已生成。这是确定性占位输出，不代表真实模型判断。

### c-summary（history）— done
- 引用输入快照: a-research、b-check
- 关键决策点: 1) 总结
- 任务结论: （mock）已生成。这是确定性占位输出，不代表真实模型判断。
```

> `--mock` 是确定性占位输出，用于看管线怎么跑；要真实推理，配置 `.env` 的 key 后去掉 `--mock`。

![collab demo 报告](https://raw.githubusercontent.com/silicon-sbt/v2-collaboration-engine/master/assets/demo-report.png)

### 用真实模型跑

配置 `.env`（如 `DEEPSEEK_API_KEY=...`）或导出环境变量后：

```bash
python -m collab run examples/three_agents.json --provider deepseek --report
python -m collab report <run_id>
python -m collab cost <run_id>
```

`tasks.json`（或 `examples/` 里的样例）是任务数组，每项至少含 `id`、`persona_id`、`input`：

```json
[{"id":"t1","persona_id":"computing","input":"评估成本与收益","expected_output":"给出方案"}]
```

## 命令一览

| 命令 | 说明 |
| --- | --- |
| `collab demo [--mock] [--provider auto] [--tasks FILE] [--light]` | 零配置快速体验：内置 3 个跨 persona 任务，无需 tasks.json / API key |
| `collab run <tasks> [--provider auto|mock] [--mode wave|parallel] [--light] [--audit-model M] [--audit-provider P] [--db PATH] [--memory-db PATH]` | 提交并阻塞到终态；`--light` 轻量、`--audit-*` 独立裁决 |
| `collab status/report/cost/list/stop <run_id> [--db PATH]` | 状态 / 报告 / 成本 / 列表 / 软停止 |
| `collab memory search|list|stale <agent_id> [--db PATH]` | 记忆检索 / 列表 / 过期（支持 `--min-score`/`--candidate-limit`） |
| `collab motion submit|decide|list [--db PATH]` | 动议提交 / 裁决 / 列表 |

## 可靠性

- **测试**：161 个用例（含 demo/CLI/记忆/动议/恢复）+ 对抗性核验（制造错误→系统揭出/修正）。
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

## 架构图 / 流程图

![V2 架构图](https://raw.githubusercontent.com/silicon-sbt/v2-collaboration-engine/master/assets/v2-architecture-cn.png)

![V2 执行流程图](https://raw.githubusercontent.com/silicon-sbt/v2-collaboration-engine/master/assets/v2-flow-cn.png)

## 贡献

想参与？见 [CONTRIBUTING.md](CONTRIBUTING.md)。提交 bug / 需求 / PR 都欢迎。

## 许可

MIT License（见 `LICENSE`）。

## 致谢

- 感谢原始项目 [`agent_roundtable`](https://github.com/Random-Walk2026/agent_roundtable)（Random-Walk2026）：多 Agent 圆桌与协作审计的思路，是本引擎的重要起点。
- 感谢 **ClaimCheck（CatNebulaaaa）**：用于本项目的开源完整性核查。
