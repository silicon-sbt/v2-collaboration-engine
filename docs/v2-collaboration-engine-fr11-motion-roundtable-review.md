# V2 引擎 FR11（会议动议权，纯数据层最小动议）代码圆桌评审报告

> 日期：2026-08-25 ｜ 对象：collab/motion.py + tests/test_collab_motion.py
> 方式：轻量圆桌（3 专家：Computing / Philosophy / History，逐个 subagent 只读 collab/motion.py + 内联接线摘要）。主 agent 综合。
> 结论：approve_with_concerns。数据层核心正确、无重复造轮子、边界清晰；采纳 3 项低风险增强；其余为 M3 边界/已知取舍。

## 1. 三专家意见（简）

### Computing — approve_with_concerns
- 优点：数据层最小且边界清晰（五态 + 校验 + reject 必带 reason + 保持 PENDING 可重试，符合 §9.5）；to_dict/from_dict 往返正确；merge 同类去重合并并标 MERGED，自洽。
- 关注：①（med）apply_decision 只接受 approved/rejected，与规约文本 approve/reject 措辞不一致；②（med）from_dict 对非法 created_at 静默回退 now()，丢原始时间戳；③（med）MotionStore.decide/merge_pending 锁外改引用，与『Thread-safe』声明不符。

### Philosophy（公正/可审计/reject 必带原因）— approve_with_concerns
- 优点：字段校验/状态流转正确，reject 必带原因且拒后保持 PENDING 语义清晰；预算来源白名单、id/时间戳生成与 from_dict 往返稳健；纯数据层未混入 M3。
- 关注：①（high）apply_decision 不要求/不接收 audit_anchor 与 decided_by，approve/reject 可无决策者、无锚点落库，削弱可审计性；②（med）merge 置 MERGED 却只打 decided_at，未记 decider/原因/被吸收 id；③（low）『可重试但需更好理由』在数据层无痕迹。

### History（范围纪律/过度设计/复用）— approve_with_concerns
- 优点：字段/校验/状态正确，reject 必带 reason、出错保持 PENDING；audit_anchor 仅引用审计/CollabMessage，未自建重复事实实体。
- 关注：①（med）MERGED 语义标注 M3 但已实现 merge_same_topic + MERGED 状态，且 merge 后不写 merged_into/锚点；②（med）『可重试但需更好理由』未建模（reject 即终态，同 motion 无法重试）；③（low）MotionStore 线程安全不完整 + add 同 id 静默覆盖。

## 2. 共识与决议
- 共识：FR11 数据层做对、边界克制、未重复造轮子；决策/合并路径的审计锚定（decider、原因、被吸收 id）可强化。
- 已采纳修复（本期 FR11）：
  1. apply_decision：接受 approve/reject 别名；**要求 decided_by**（可审计）；approve 无 committee 时**默认 proposed_participants**；接受可选 audit_anchor 并写入 motion。
  2. merge_same_topic：记录被吸收 id（survivor.outputs[merged_from]）、置 decider=manager + 合并原因（可审计）。
  3. MotionStore.decide/merge_pending：**全程持锁**（线程安全，修复『锁外改引用』）。
- 记为 M3 / 已知取舍（不在本期改）：
  - 『可重试但需更好理由』：retry = 新建动议（M3 语义），数据层不建模 rejection 重试路径。
  - from_dict 非法时间戳静默回退：`_parse_dt` 为共享轻量 helper，保持宽松（已知简化）。
  - MERGED 语义完整处理（manager 如何用合并、产出双份、参会方处理）→ M3；本期只留状态+合并原语。
  - audit_anchor 由上层（M3）在产出时注入；本期 apply_decision 已能写入。

## 3. 已落地
- collab/motion.py：apply_decision 增强、merge 可追溯、decide/merge_pending 持锁。
- tests/test_collab_motion.py：+approve 别名、+decided_by 必带、+committee 默认、+merge 可追溯；全量 collab 115 通过。

## 4. 结论
approve_with_concerns。FR11 纯数据层最小动议可合入；已修审计锚定（decider/原因/被吸收 id）与线程安全；retry/MERGED 完整语义归 M3。