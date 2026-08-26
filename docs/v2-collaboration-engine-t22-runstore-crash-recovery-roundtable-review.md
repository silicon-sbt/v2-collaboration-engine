# V2 引擎 T22（RunStore 崩溃恢复，FR-GAP-3）代码评审报告

> 日期：2026-08-26 ｜ 对象：collab/runstore.py（last_heartbeat 心跳列 + touch + normalize_stale + get/list 归一）+ collab/runner.py（worker 心跳线程 + _hb_stop）+ tests/test_collab_runstore.py
> 方式：自审 + 专家视角综合（Computing/Philosophy/History）。结论：approve_with_concerns。

## 1. 交付
- RunStore 增 last_heartbeat 列（CREATE + ALTER TABLE 迁移存量库）；save 可写、_row_to_record 读回、touch(run_id) 刷新心跳。
- normalize_stale(crash_grace_seconds=DEFAULT_CRASH_GRACE_SECONDS=120)：把仍 running 且 COALESCE(last_heartbeat, created_at) 早于截止窗口的记录归一为 failed + stop_reason=crashed (heartbeat expired) + finished_at=now；get/list 开头调用 → 任何状态/列表查询都自动恢复「崩溃后永久 running」。
- run_collaboration：有 run_store 时启动 daemon 心跳线程，每 _HEARTBEAT_INTERVAL_SECONDS=10s touch；worker 完成时在 finally 置 _hb_stop 停线程；初始 running 记录写 last_heartbeat=created 作基线。
- 测试：test_normalize_stale_marks_crashed_run_failed、test_normalize_stale_keeps_fresh_running、test_touch_keeps_running_alive；全量 collab 146 passed（=143+3）。

## 2. 正确性/复用
- 心跳仅在有 RunStore 时运行；daemon 线程 + _hb_stop 事件在 worker 完成/异常/提前返回时都会 set（finally），无泄漏。
- 归一化用 COALESCE(last_heartbeat, created_at)：新创建但尚未首跳的 running 记录以 created_at 作基线，不会秒判 failed。
- ISO-8601 UTC +00:00 字符串字典序比较（created_at/last_heartbeat/cutoff 同一格式）一致成立；迁移存量库用 ALTER TABLE ADD COLUMN，无破坏。

## 3. ⭐ 实质发现（concerns）
1. **同进程 worker 静默死亡**：get_collab_status 先读内存 _RUNS，若 worker 线程异常退出但进程仍在，状态仍是 running 且不会走到 store.get 归一化；不过该 window 只影响「进程存活但 run 线程死」这一罕见边缘态，FR-GAP-3 主场景（崩溃/重启后不永久 running）已解决。
2. **存活 worker 与归一化的竞态**：心跳停更 >120s 被归一为 failed 后，若该 worker 其实还活着并稍后完成，会再次 save 覆盖为 done——这是良性竞态（任务真完成了）。
3. **每次 get/list 触发一次写**：normalize_stale 在每次读取执行 SELECT（有变化才 UPDATE），幂等且开销小；若需可改为「查询时惰性判定不落库」。

## 4. 结论


## 5. 附：自查额外发现并修复
- **get_collab_status 状态覆盖 bug**：`base.update(stored["summary"])` 会被摘要里旧的 `status="running"` 覆盖行级 status，导致归一化后的崩溃 run 在状态查询中仍显示 running。已修复：行级 status/finished_at/stop_reason 为准（summary 后再强制覆盖）。新增端到端测试 `test_get_collab_status_surfaces_crashed_run_as_failed`；CLI `collab status` 冒烟确认 `status=failed` + `stop_reason=crashed`。
approve_with_concerns。T22 可合入（m2 分支）。孤儿 running 持久记录经查询自动归一为 failed，满足 FR-GAP-3「不永久 running」+ NFR §7.9 唯一默认值（grace=120s）；concerns 为同进程边缘态/良性竞态/写开销，可后续打磨。