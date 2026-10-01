# Changelog

All notable changes to this project. Format loosely follows Keep a Changelog;
this project adheres to Semantic Versioning.

## [Unreleased]

### Added
- **A/B non-inferiority harness** (`benchmarks/ab_gate.py`) and the first real V1-vs-V2 evidence
  (`benchmarks/AB_V1_VS_V2.md`, raw runs under `benchmarks/evidence/`): on one topic × 3 repeats the
  engine was 1.33× more expensive and +2.83/25 on a blind, order-swapped judge — the standing
  "never both more expensive and worse" gate passed 3/3, while a cost-saving claim is still unproven.
- **CI packaging smoke job**: builds sdist + wheel, runs `twine check`, installs the wheel into a
  clean venv and runs `collab demo --mock` from outside the checkout.

### Known issues
- **Coordination (manager/arbitration) LLM calls are not cost-accounted.** The report's "total tokens /
  cost" covers only task-execution calls and under-counts real API usage by ~50% (measured: 48–50%).
  Located in `collab/graph.py` (arbitration node) + `collab/costing.py` (summary sums `results` only);
  evidence in `benchmarks/AB_V1_VS_V2.md` §5. Not fixed yet.

### Fixed
- Docs: the READMEs/CHANGELOG no longer claim a PyPI package that is not published — they use the
  git URL / the release wheel, and say so explicitly.
- Chinese README test count corrected (161 → 164).

## [0.1.0] - 2026-09-12

### Added
- **Zero-config demo**: `collab demo` runs a built-in 3-task cross-persona scenario
  (produce → cite → summarise) with no `tasks.json` and no API key (deterministic mock).
- **Examples**: `examples/hello_world.json`, `examples/three_agents.json`,
  `examples/basic_usage.py` (Python-API usage).
- **Packaging**: `pyproject.toml` — installable from source (`pip install .`) or straight from GitHub
  (`pip install "git+https://github.com/silicon-sbt/v2-collaboration-engine.git"`), console script
  `collab`. PyPI publication is still pending.
- **Report run-path label**: the report header states `MOCK` / `REAL:<provider>` so
  "demo vs real" is a verifiable engineering fact, not a README claim.
- **CLI**: `collab --version` + friendlier help.
- **Docs**: bilingual (EN/CN) architecture + execution-flow diagrams.

### Changed
- Default data directory moved to `~/.collab` (override with `COLLAB_HOME`) so a
  pip-installed package never tries to write into site-packages.

### Engine (M1–M3)
- LangGraph wave scheduler, L2 audit, arbitration (hard rules → manager), per-persona
  memory (SQLite Top-K), motion (FR11 minimal), cost / waste / recovery accounting,
  dual mode (wave/parallel), crash-recovery RunStore.
