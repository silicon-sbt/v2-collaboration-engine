# V2 引擎 M3 需求草案——圆桌评审报告

> 日期：2026-08-25 ｜ 对象：docs/v2-collaboration-engine-m3-requirements.md（v0.1）｜ 阵容：轻量 3 专家（Computing/Philosophy/History）+ 主 agent 综合
> 结论：**approve_with_concerns**（方向合理、范围需收敛）。已吸收为 v0.2 §11。

## 1. 各专家意见（简）
### Computing（MCP 可行性/DSH schema/异步）— approve_with_concerns
- 优点：严格遵循 DSH schema 子集（JSON 字符串+标量默认值，规避 Optional/anyOf）；异步 run_in_executor+run_id+轮询与 V1 一致并规划超时。
- 关注：①（high）异步工具返回后再由后台线程调 ctx.report_progress 可能因 MCP 请求已结束而丢失/报错；②（med）FR11 完整机制范围偏大；③（med）tasks 等 JSON 字符串只被 DSH 校验为 type:string，负载内容不受 schema 保护。
### Philosophy（范围纪律/可审计）— approve_with_concerns
- 优点：明列非目标 + V1 向后兼容；工具定义遵守 DSH schema 子集并复用纯函数，支撑可审计。
- 关注：①（high）FR-GAP-4 FR11 完整机制塞进 1-1.5 周 M3 明显撑大；②（med）v0.1 草稿 5 个开放问题未定却宣称全量验收，目标不可审计；③（med）验收标准偏定性（数字正确/文档齐/全量绿）。
### History（演进一致性/范围）— approve_with_concerns
- 优点：以交付里程碑定位 M3 并把范围锚定到 M2 收官 §4 显式缺口，可追溯；非目标清单控制复杂度。
- 关注：①（high）FR11 完整机制体量大、混入 MCP 工具化风险高；②（med）MCP 工具粒度未定（V1 run_roundtable 是否接入/记忆动议是否都 MCP 化）；③（med）5 个 V1 失败"修 vs xfail"与 NFR 全项验收缺少三分类与可执行判定。

## 2. 共识与决议（已入 M3 需求 v0.2 §11）
- **共识**：M3 方向合理、可落地；范围需收敛，异步进度/JSON 负载/验收标准需夯实。
- **采纳**：
  1. **FR11 完整机制 → M3.x 独立 PR**（M3 只做动议最小闭环，挂 MotionStore 纯数据层）。
  2. **异步进度改状态轮询/事件日志**（不依赖已返回工具的 ctx.report_progress）。
  3. **JSON 负载服务端严格校验 + 长度/数量上限**。
  4. **工具粒度分层**：P0=run_collaboration+manage_tasks；P1=记忆/动议（最小）/成本。
  5. **5 个 V1 失败三分类**（真 bug→修/环境→xfail/断言过时→更新）+ NFR 量化验收。

## 3. 结论
approve_with_concerns。M3 需求可定稿（v0.2）；按 §11 决议的范围与约束推进。