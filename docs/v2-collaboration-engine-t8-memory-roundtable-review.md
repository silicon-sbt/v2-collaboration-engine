# V2 引擎 T8（per-agent 记忆）代码多 Agent 圆桌评审报告

> 日期：2026-08-25 ｜ 对象：collab/memory.py + collab/graph.py 的 memory 接线 + tests/test_collab_memory.py
> 方式：真实多 agent 圆桌（experts 阵容：Macroeconomics / Investing / Computing / Philosophy / History，逐个 subagent + moderator）。先前 workflow/并行 subagent 因"5 agent 同时读 4 个大文件"过载被中止，本轮改为逐个跑通。
> 结论：approve_with_concerns。主持人确认一个真实 bug（连接泄漏），已现场修复；另有两项已修；其余项记录为 T9/后续。

## 1. 真实 bug：连接泄漏（已修复）

- 现象：_conn() 每方法新建一个 sqlite3 连接，但调用方用「with sqlite3.connect(...) as conn:」——sqlite3 连接上下文管理器只 commit/rollback，不关闭连接；close() 又是空实现。因此每次 add/search/list/mark_stale/get/_init_schema 都泄漏一个 fd/句柄。在 LangGraph Send 并行分支长跑下会锁库/耗尽句柄，与文档宣称的"跨并行分支安全"矛盾。
- 修复：把 _conn 改为 @contextmanager，内部 with conn:（提交/回滚）并在 finally: conn.close()；删除空 close()。所有调用点走 with self._conn() as conn:，现为"提交且关闭"。

## 2. 数据完整性：links/tags 序列化（已修复）

- 现象：add 用空格 join 存 links/tags，_rows_to_entries 用空格 split 读回；与 schema 默认 '[]'（JSON 风格）不一致。含内部空格的标签/链接（如 'task: summarize'）round-trip 会被拆裂。
- 修复：改为 json.dumps / json.loads（空列表存 '[]'），保证往返一致。

## 3. confidence 假精确（已修复）

- 现象：memory_entries_from_output 把所有 judgment 的 confidence=0.3；经 _score 的 conf=min(1.5,max(0.5,1+0.3))=1.3 后为常数，对排序无区分度，却冒充"透明置信度"。
- 修复：改回 0.0（与 dataclass 默认一致），并明确其为未校准占位；排序由 overlap×recency 决定。

## 4. 待后续（T9 / FR-ECO，记录不阻塞合入）

- 检索成本：search 每任务对全量 agent 记忆 O(N) 打分，且每任务无条件注入至多 5 条。建议加 score 阈值门控（无强命中不注入）+ 每 agent 候选上限/容量/TTL（不引入第二向量库）。
- stale 语义：mark_stale 会把 updated_at 刷成当前时间，使 include_stale 下刚过期条目 recency 反而靠前；_score 注释声称的"0 分兜底"与 search 的 s>0 过滤自相矛盾。建议 stale 不刷新 recency，语义二选一。
- 提取器脆弱：_extract_decision_points 依赖 output_summary 固定行前缀 + [0-9]+) 正则，格式漂移会静默写 0 条。建议改读结构化字段或容错解析 + 对"通过但零抽取"告警。
- 自增强/矛盾降级：先前通过的判断以静态置信无限期注入，后续矛盾无法自动降权，是记忆污染/自增强根因。建议冲突时把旧条目置 stale/overridden 并挂 links。
- 边界/死代码：__post_init__ 未校验 kind 取值集合、未把 confidence clamp 到 [0,1]；kind=fact 目前无生产者（潜伏能力）；_CORRECTION 未用常量。
- 复用：overlap 打分与 rag.retriever._keyword_score 是"复用想法而非函数"，建议抽共享 helper 或直接复用。

## 5. 各专家关键意见（简）

- Macroeconomics：成本纪律好（stdlib-only、无第二向量库）；但 O(N) 检索 + 每任务固定注入成本无界且收益未验证。approve_with_concerns。
- Investing：记忆价值未证明前不应默认开启（现状 memory_store=None 正确）；provenance/confidence 属"未校准估值"。approve_with_concerns。
- Computing：正确性/并发/复用基本达标；但连接泄漏是硬伤、links/tags 空串损坏、stale 语义矛盾。approve_with_concerns。
- Philosophy：fact 强制 provenance、"非任务指令"边界、不做 LLM 抽取方向对；但 confidence 假精确、provenance=task.id 非独立可核验锚点、自增强风险。approve_with_concerns。
- History：范围纪律好（最小切片、未过度设计）；重复造轮子核查通过（复用 tokenize、未硬绑 compute_anchor_coverage、未引第二向量库）。approve_with_concerns。

## 6. 结论

approve_with_concerns。T8 作为 M2 记忆基础切片可合入；已修连接泄漏/序列化/confidence 三项；其余作为 T9/FR-ECO 跟踪项。验证：全量 collab 75 测试通过。

## 7. 采纳修复清单（已落地）

- collab/memory.py：_conn 改为提交+关闭的 contextmanager；删除空 close()；links/tags 用 JSON 序列化；confidence 占位 0.0；新增 import json 与 from contextlib import contextmanager。
