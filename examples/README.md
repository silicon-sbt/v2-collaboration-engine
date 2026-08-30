# examples

可直接喂给 `python -m collab run <file>` 的任务样例。

## 零配置快速体验（连 API key 都不用）

```bash
python -m collab demo --mock
```

这一条命令会跑内置的 3 个跨 persona 任务（产出 → 引用 → 汇总），
全程用确定性 mock 输出，离线可用，立刻看到波次执行/审计/仲裁/记忆/成本闭环的报告。

## 用样例文件跑

### 最小 2 任务 -> 并行流
```bash
python -m collab run examples/hello_world.json --mock --report
```

### 3 任务跨 persona 协作（data_deps 依赖链）
```bash
python -m collab run examples/three_agents.json --mock --report
```

## 用 Python API 跑（编程方式）

```bash
python examples/basic_usage.py
```

直接用 `run_collaboration` 在 Python 里跑（默认 mock，离线），打印 run_id + 报告。

## 用真实模型跑

配置好 `.env`（例如 `DEEPSEEK_API_KEY=...`）或导出环境变量后，去掉 `--mock`：

```bash
python -m collab run examples/three_agents.json --provider deepseek --report
```

- `--provider auto`（默认）会在检测到 key 时用真实模型，否则回退 mock。
- `--light` 跳过经理裁决（仅硬规则），少一次 LLM 调用。
- `--mode parallel` 并行执行（experimental）。

## 字段说明

每个任务对象最低只需 `id`、`persona_id`、`input`。可选：

- `expected_output`: 期望交付物（用于审计对照）。
- `data_deps`: 本任务依赖哪些任务 id 的结果（引用）。
- `allowed_links`: 本任务可横向引用/协作的其他任务 id。

