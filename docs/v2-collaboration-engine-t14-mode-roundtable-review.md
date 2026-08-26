# V2 引擎 T14（双模式+全并行，降级版）代码圆桌评审报告

> 日期：2026-08-25 ｜ 对象：collab/graph.py（resolve_mode / run_collab_sync / report）+ tests/test_collab_mode.py
> 方式：轻量圆桌（3 专家：Computing / Philosophy / History，逐个 subagent 只读 tests/test_collab_mode.py 作验收锚点 + 内联接线摘要）。主 agent 综合。
> 结论：approve_with_concerns。实现与规格/测试一致、无重复造轮子、范围克制；已核实 1 项不成立 + 采纳 2 项加固；parallel 为圆桌有意保留的纯标记。

## 1. 三专家意见（简）

### Computing — approve_with_concerns
- 优点：resolve_mode 为纯函数且规则清晰（wave 默认、parallel 仅全无 data_deps、否则回退 wave+note、experimental 只在真 parallel）；run_collab_sync 接线诚实，未引入第二调度器/原子锁。
- 关注：①（low）测试未直接断言 resolve_mode 缺省默认 wave；②（low）仅通过 final_report 间接验证 state 的 eff_mode/experimental/parallel_note。

### Philosophy（experimental 标记是否诚实）— approve_with_concerns
- 优点：resolve_mode 为纯函数、测试覆盖默认/成功/回退/非法四路径；报告标注与说明符合声明意图，全量 121 通过。
- 关注：①（med）现有波调度本就会并行无 data_deps 的独立任务，parallel 只是显式旗标、不改执行路径，报告写「parallel（experimental）」可能暗示新/风险行为，且成功态 note 为空没澄清；②（med）验收只断言 final_report 文本、未直断 state 字段。

### History（范围纪律/过度设计/复用）— approve_with_concerns
- 优点：resolve_mode 逻辑与验收锚点一致；未混入原子锁/第二调度器，token/cost 复用 T10，parallel 仅是纯标记+实验标注，无重复造轮子。
- 关注：①（med）resolve_mode 单测用 dict、run_collab_sync 实际传 Task 对象，data_deps 读取方式若未归一化会埋坑；②（low）parallel 相对 wave 无行为差异，YAGNI 死灵活性风险；③（low）resolve_mode([], "parallel") 空输入按"全空=真 parallel"得到 experimental，语义存疑。

## 2. 共识与决议
- 共识：T14 实现正确、边界清晰、无过度设计；parallel 是圆桌有意保留的**标记**（不改变调度）。
- 已核实（不成立）：run_collab_sync 先 task.to_dict() 转 dict 再传 resolve_mode，故「Task/dict 不一致」担忧不成立。
- 已采纳加固（本期 T14）：
  1. resolve_mode 给 mode 默认 "wave"（缺省即 wave）；
  2. 空任务回退 wave（避免空集被"全无 deps"判成 experimental）。
  3. 补测试：缺省默认 wave、空集 parallel 回退、run_sync 后 state[mode/experimental/parallel_note] 直断。
- 记为已知取舍：parallel 标记已在 resolve_mode 注释/文档明确为「MARKER over existing wave scheduling，不换第二调度器/锁」；experimental 字样保留（未证明独立并行路径的事实声明）。

## 3. 已落地
- collab/graph.py：resolve_mode 默认 wave + 空集回退 + 注释明确 marker。
- tests/test_collab_mode.py：+缺省默认、+空集回退、+state 字段直断；全量 collab 123 通过。

## 4. 结论
approve_with_concerns。T14 可作为 M2 双模式切片合入；已核实 Task/dict 契约、加固默认/空集、补测试；parallel 为纯标记。