# Changelog

All notable changes to this project. Format loosely follows Keep a Changelog;
this project adheres to Semantic Versioning.

## [0.1.0] - 2026-09-12

### Added
- **Zero-config demo**: `collab demo` runs a built-in 3-task cross-persona scenario
  (produce → cite → summarise) with no `tasks.json` and no API key (deterministic mock).
- **Examples**: `examples/hello_world.json`, `examples/three_agents.json`,
  `examples/basic_usage.py` (Python-API usage).
- **Packaging**: `pyproject.toml` — `pip install v2-collaboration-engine`, console script `collab`.
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
