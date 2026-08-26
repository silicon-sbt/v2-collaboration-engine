# V2 引擎 T16（持久化，最小）代码圆桌评审报告

> 日期：2026-08-25 ｜ 对象：collab/runstore.py + collab/runner.py 持久化接线 + tests/test_collab_runstore.py
> 方式：轻量圆桌（3 专家：Computing / Philosophy / History，逐个 subagent 只读 collab/runstore.py + 内联接线摘要）。主 agent 综合。
> 结论：approve_with_concerns。核心正确（只存摘要、无泄漏、跨实例/并发安全）；已核实 1 项不成立 + 采纳 2 项低风险清理；1 项记为已知局限。

## 1. 三专家意见（简）

### Computing — approve_with_concerns
- 优点：每调用提交+关闭连接、WAL+busy_timeout、按 run_id 原子 upsert、只落 summary JSON（不含全量 state），跨实例重开/并发分支安全；API 简洁、_row_to_record 容错、无连接泄漏。
- 关注：①（med）save 的 ON CONFLICT 未更新 provider/mock；②（low）与 MemoryStore 的 sqlite 连接骨架重复、易漂移；③（low）close() 空实现、_init_schema 每次重跑建索引。

### Philosophy（持久化诚实/是否泄漏）— approve_with_concerns
- 优点：只落紧凑摘要（task_count/各任务状态/token与成本/final_report），无全量 state 与 reasoning，未过度存储；每调用提交+关闭、WAL+busy_timeout、跨实例/并发安全；UPSERT 保留 created_at。
- 关注：①（med）进程在 run 开始后崩溃，run_store 会永久保留 status=running，无法诚实体现中断；②（low）close() 空操作但 API 宣称管理连接生命周期；③（low）sqlite 模式与 MemoryStore 重复。

### History（范围纪律/过度设计/复用）— approve_with_concerns
- 优点：schema 只含 summary JSON 列+短连接，未落全量 state，范围克制；save UPSERT、list 支持 status/limit/排序、get 单查，接口够用；按调用建连+WAL+busy_timeout+row_factory+with conn 自动提交/回滚。
- 关注：①（med）无法只凭 runstore.py 确认 _build_summary 白名单；②（low）save 冲突更新时 provider/mock/created_at 仅创建写入且无注释；③（low）与 MemoryStore 的 sqlite 模式重复（当前抽公共属过度设计）。

## 2. 共识与决议
- 共识：T16 持久化正确、范围克制、无泄漏；只存摘要不存全量 state；并发与跨实例安全。
- 已核实（不成立）：_build_summary 只白名单字段（run_id/status/时间戳/error + task_count/statuses/token/cost/final_report），**不含全量 state 或 reasoning**，泄漏担忧不成立。
- 已采纳清理（本期 T16）：
  1. 移除 RunStore.close()（空实现、死代码）。
  2. save 注释明确 provider/mock/created_at 为**创建时字段、不可变**（upsert 只刷新 status/finished_at/stop_reason/summary）。
- 记为已知局限（不在本期改）：进程崩溃后 run 永久 status=running —— 崩溃恢复/心跳标记超出"最小持久化"，归 M3/后续，不入本期启发式。
- 复用/memory 模式重复：当前两个 sqlite store 抽公共属过度设计；若出现第三个再抽共享 helper（History/Computing 一致）。

## 3. 已落地
- collab/runstore.py：移除 close()、save 注释创建字段不可变。
- tests/test_collab_runstore.py：4 用例（roundtrip/cross-instance/persist summary/historical get/list merge）；全量 collab 127 通过。

## 4. 结论
approve_with_concerns。T16 可作为 M2 持久化切片合入；已核实摘要白名单、清理空 close()、注释创建字段不可变；崩溃恢复归 M3。