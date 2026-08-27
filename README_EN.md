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

## Quick start

```bash
git clone https://github.com/silicon-sbt/v2-collaboration-engine.git
cd v2-collaboration-engine
pip install -r requirements.txt
python -m collab run tasks.json --provider auto --db logs/collab_runs.db
python -m collab report <run_id> --db logs/collab_runs.db
```

`tasks.json` is a JSON array, each item needs at least `id`, `persona_id`, `input`:

```json
[{"id":"t1","persona_id":"computing","input":"Evaluate cost vs benefit","expected_output":"Give a plan"}]
```

## Reliability

- 18 collab tests incl. adversarial verification (inject an error → the system exposes & corrects it).
- ~91% coverage; CI runs on **Python 3.10 / 3.11 / 3.12** daily + on push.
- Self-contained: only `langgraph` + `requests` + stdlib, no other internal modules.

## License

MIT License (see `LICENSE`).
