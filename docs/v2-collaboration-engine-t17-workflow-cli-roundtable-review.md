# V2 引擎 T17（公司工作流运行器/CLI）代码圆桌评审报告

> 日期：2026-08-25 ｜ 对象：collab/cli.py + collab/__main__.py + runner mode 透传 + tests/test_collab_cli.py
> 方式：轻量圆桌（3 专家：Computing/Philosophy/History，读 collab/cli.py + 内联摘要）。主 agent 综合。
> 结论：approve_with_concerns。定位正确（公司工作流入口=CLI，非 MCP/非 DSH workflow 工具）；采纳 3 项修复。

## 1. 专家意见（简）
### Computing — approve_with_concerns
- 优点：复用 runner/runstore，薄一层；run 阻塞到终态避免进程退出杀后台 run；--db 隔离。
- 关注：① 超时后 return 0 + 进程退出会杀后台 run、RunStore 留孤儿 running；② --wait 冗余失效 flag；③ cmd_list 非 f-string 片段输出字面量。
### Philosophy（工作流入口定位/可审计）— approve_with_concerns
- 优点：定位诚实（非 MCP、非 DSH 工具），run/status/report/list/stop 聚焦；RunStore 持久化 + 跨进程 status/report 可审计。
- 关注：①（high）超时/not_found 后进程退出留下永远 running 的孤儿 run；②（med）cmd_list 字面量 bug。
### History（范围纪律/复用/过度）— approve_with_concerns
- 优点：定位清晰、职责不越界；run/status/report/list/stop 直接映射 runner 函数，未重复编排/存储。
- 关注：①（high）cmd_list f-string 拼接 bug；②（med）--wait store_true+default=True 永远为真且无法关，与 --report 重叠、flag 误导。

## 2. 已采纳修复（本期 T17）
1. **run 始终阻塞到终态**（去掉失效的 --wait）：一进程一跑，run 在进程存活期间完成并落盘，避免进程退出杀后台 run。
2. **cmd_list f-string bug**：`f'{r["run_id"]}	{r["status"]}	{r["created_at"]}'` 正确展开三列。
3. **超时/not_found 处理**：轮询到非 running 即停；not_found 报错返回 1；超时仍 running 则 `stop_collab(reason="cli timeout")` 标记 stopped（不留下孤儿 running run）并返回 1。

## 3. 已知取舍/说明
- CLI `run` 阻塞到完成（非"提交即返回"）：因为后台线程属本进程、进程退出即死，对一次性 CLI 最可靠。真异步托管需常驻服务（M3.x）。
- `stop` 仅对**本进程启动**的 run 有效（后台线程属原进程）；跨进程 stop 不适用（文档已达）。
- `--db` 允许指定 RunStore 路径（默认 repo/logs/collab_runs.db），便于隔离/测试。

## 4. 验证
- tests/test_collab_cli.py 4 用例（run 落盘/status/list/未知/mode 透传）；全量 collab 131 通过。

## 5. 结论
approve_with_concerns。T17 可作为入口 B（公司工作流 CLI）基础合入；已修超时孤儿/字面量/冗余 flag，并明确阻塞语义与跨进程 stop 限制。