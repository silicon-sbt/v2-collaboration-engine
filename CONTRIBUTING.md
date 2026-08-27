# Contributing to v2-collaboration-engine

感谢你关注！这是一个独立的弱去中心化多 Agent 协作引擎（通过 `python -m collab` 运行），MIT 许可。任何修复、功能、文档都受欢迎。

## 如何贡献

- **报 bug / 提需求**：开 Issue，说明「期望 vs 实际」，尽量附上 `collab` 命令、`tasks.json` 和报告。
- **改代码**：fork → 分支 → 实现 → 补/调测试 → 开 PR。
- **改文档**：README/注释，保持 README 自包含、不掺内部黑话。

## 开发环境

```bash
git clone <repo-url>
cd v2-collaboration-engine
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest tests/ -q
```

## 跑一个 demo

```bash
python -m collab run tasks.json --provider mock --db logs/collab_runs.db
python -m collab report <run_id> --db logs/collab_runs.db
```

## 约定

- Python 3.10+，公共 API 加类型标注。
- **保持自包含**：不要引入对 `roundtable` / `mcp_server` / `rag` / 上游模块的依赖——引擎只能依赖 `langgraph`、`requests` + 标准库。
- **测试**：任何改动都要让 `python -m pytest tests/ -q` 全绿（含 CLI 测试，CI 每天定时跑）。
- **提交信息**：祈使式，如 `feat: ...`、`fix: ...`、`docs: ...`。
- **PR 清单**：跑过测试、控制改动范围、说清「做了什么/为什么」、有关联 issue 就引用。

## 许可

贡献即表示同意你的贡献以 MIT License 发布（见 `LICENSE`）。
