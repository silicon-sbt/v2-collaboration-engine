# v2-collaboration-engine

[中文](README.md) | English

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)  [![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)  [![CI](https://github.com/silicon-sbt/v2-collaboration-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/silicon-sbt/v2-collaboration-engine/actions/workflows/ci.yml)  [![codecov](https://codecov.io/gh/silicon-sbt/v2-collaboration-engine/branch/master/graph/badge.svg)](https://codecov.io/gh/silicon-sbt/v2-collaboration-engine)  [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)  [![Maintained](https://img.shields.io/badge/Maintained-yes-green.svg)]()  [![Last commit](https://img.shields.io/github/last-commit/silicon-sbt/v2-collaboration-engine)]()

A multi-agent **workflow runner** that turns accountability, cost and auditability into verifiable engineering.

> In one line: `python -m collab run tasks.json` runs a collaboration and the report tells you — who did what, how many tokens/cost, how many times it was sent back, and whether it finally passed.

## Why

Multi-agent is not free. Every collaboration pays an extra "coordination fee" (manager/arbitrator calls, per-step audits, inter-agent messaging, retries). If that doesn't save more redundant work than it costs, multi-agent is "more expensive AND worse".

Our difference is not "one more orchestrator" — it's making **whether the collaboration is worth it and traceable** something you can verify.

## What a report tells you

Run a collaboration and the report gives you:

- **Total token usage** (broken down per role);
- **Cost in USD** (per persona; unknown providers are clearly marked `estimated`);
- **Waste** (tokens/cost from failures, rejections, budget overruns);
- **Recovery rate** (share of retries that succeeded; `N/A` when nothing was retried);
- **Per-task audit conclusions + cited evidence** (traceable, not a black box).

## Core features

- **Wave scheduling**: don't proceed until dependencies align (no "code before design").
- **Layered arbitration**: audit hard-rules + manager provisional verdict; accept or send back (with a reason, retriable).
- **Cost / waste / recovery rate**: the "coordination fee" is accounted, never silently absorbed.
- **Honest memory**: no strong match → no injection, no fabrication; hits carry real source, key facts have anchors.
- **Crash recovery**: a dead run is normalized to failed, not stuck "running".
- **Light / independent audit**: simple tasks can skip the manager re-read; the auditor can use a different model to avoid self-review.

## How it differs

Frameworks like LangGraph, AutoGen, CrewAI and MetaGPT focus on **how to orchestrate**.

We focus on **whether the collaboration is worth it and can be held accountable** — cost, waste, audit and provenance as verifiable engineering.

## Architecture & Flow

![V2 architecture](https://raw.githubusercontent.com/silicon-sbt/v2-collaboration-engine/master/assets/v2-architecture.png)

![V2 execution flow](https://raw.githubusercontent.com/silicon-sbt/v2-collaboration-engine/master/assets/v2-flow.png)

## Quick start

### Install (from GitHub; not on PyPI yet)

```bash
pip install "git+https://github.com/silicon-sbt/v2-collaboration-engine.git"
collab demo --mock
```

Or install the wheel attached to [Releases](https://github.com/silicon-sbt/v2-collaboration-engine/releases):

```bash
pip install v2_collaboration_engine-0.1.0-py3-none-any.whl
```

> **This package is not published to PyPI yet** — `pip install v2-collaboration-engine` does not
> resolve today; this section goes back to that one-liner once it does.

### From source

```bash
git clone https://github.com/silicon-sbt/v2-collaboration-engine.git
cd v2-collaboration-engine
pip install -r requirements.txt
python -m collab run tasks.json --provider auto
python -m collab report <run_id>
```

`tasks.json` is a JSON array, each item needs at least `id`, `persona_id`, `input`:

```json
[{"id":"t1","persona_id":"computing","input":"Evaluate cost vs benefit","expected_output":"Give a plan"}]
```

## Reliability

- 164 tests incl. adversarial verification (inject an error → the system exposes & corrects it).
- ~91% coverage; CI runs on **Python 3.10 / 3.11 / 3.12** daily + on push, plus a packaging
  smoke job (build → twine check → install the wheel in a clean venv → run `collab demo`).
- **A/B evidence** against the roundtable baseline (cost/quality, incl. a measured cost-accounting
  gap): [`benchmarks/AB_V1_VS_V2.md`](benchmarks/AB_V1_VS_V2.md).
- Self-contained: only `langgraph` + `requests` + stdlib, no other internal modules.

## See also

- [`agent-roundtable-mcp`](https://github.com/silicon-sbt/agent-roundtable-mcp): **Entry A · Meeting** — the roundtable MCP server (expert/persona panels, RAG corpora, Markdown reports) callable from DSH / Claude Code / Cursor. This repo focuses on **Entry B · Company** (the collaboration workflow engine).

## License

MIT License (see `LICENSE`).
