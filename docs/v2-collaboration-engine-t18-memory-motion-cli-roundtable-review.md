# V2 引擎 T18（memory/motion CLI 子命令 + MotionStore 持久化）代码评审报告

> 日期：2026-08-25 ｜ 对象：collab/cli.py（memory/motion 子命令）+ collab/motion.py（MotionStore 持久化）+ tests/test_collab_memory_motion_cli.py
> 方式：自审 + 专家视角综合（subagent 编排数次触发 token/运行失败，改为上下文内评审）。结论：approve_with_concerns。

## 1. 交付
- collab/cli.py：memory search/list/stale + motion submit/decide/list（--db 可指定库，默认 repo/logs/collab_memory.db / collab_motions.db）。
- collab/motion.py：MotionStore 加可选 db_path SQLite 持久化（db_path=None=内存，向后兼容）；跨 CLI 调用可读。
- tests/test_collab_memory_motion_cli.py 4 用例；全量 collab 135 通过。

## 2. 正确性/复用
- memory 直接复用 MemoryStore；motion 复用 MotionStore/apply_decision；MocionStore.e decide 对 reject 无原因会报错（CLI 返回 1）；无重复造轮子、未过度设计。

## 3. ⭐ 实质发现（集成缺口，下一步）
- CLI 的 memory/motion 工具用独立默认库；`collab run` 未把这两个库接入 `run_collaboration` 的 memory/motion 链路 → run 产生的记忆/动议**不会**进 CLI 默认库，`memory/motion` 子命令读不到。
- 建议：给 `run_collaboration` 增 memory/motion 接入（或 CLI run 默认用 logs/collab_memory.db / collab_motions.db 作为引擎持久库），使三者同一数据源。

## 4. 结论
approve_with_concerns。T18 可合入（m2 分支）；memory/motion 工具可用、MotionStore 持久化清楚；下一步补「run 与 memory/motion 同一数据源」的集成。