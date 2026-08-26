# V2 引擎 M3 收官验收报告（T24：全量验收 + V1 失败三分类 + 文档定稿）

> 日期：2026-08-26 ｜ 分支：m2（M2+M3） ｜ 范围：M3 全部任务 T17–T24
> 结论：**通过（approve）**。全量回归 226 passed / 0 failed / 2 skipped；5 个 V1 预存在失败已完成三分类并修复；M3 全部 8 个任务完成。

## 1. 全量回归结果
- `pytest tests/ -q`：**226 passed, 2 skipped, 0 failed**（1 个无关 pydantic warning）。
- V2 collab 156 passed（T17–T23 全部落地）。

## 2. 5 个 V1 预存在失败三分类（此前基线：5 failed）
| 测试 | 现象 | 分类 | 处置 |
| --- | --- | --- | --- |
| test_rag.test_chunk_expert_markdown_keeps_required_metadata | source_file 断言 `knowledge/.../moat.md`，实得 `knowledge\...\moat.md` | 真 bug | 修 |
| test_rag.test_chunk_person_markdown_tracks_source_kind | 同上（person 路径反斜杠） | 真 bug | 修 |
| test_rag.test_keyword_mock_retriever_works_without_embedding_api_key | 同上（keyword retriever 元数据反斜杠） | 真 bug | 修 |
| test_graph.test_agent_uses_rag_retrieved_context_before_speaking | references 反斜杠 | 真 bug | 修 |
| test_ingest_source_kind.test_ingest_person_source_kind_merges_without_dropping_other_kinds | 合并文本含反斜杠路径 | 真 bug | 修 |

**根因**：V1 生产代码 `rag/chunker._source_file` 用 `str(path.resolve().relative_to(root_dir))` 存 `source_file`/`references` 元数据，Windows 下 `str(Path)` 返回反斜杠，导致 metadata/references 跨平台不一致（POSIX 与 Windows 元数据 key 不同）。**修复**：改用 `Path.as_posix()` 统一为 `/`（POSIX 行为不变，向后兼容），一处修复解决全部 5 个。**未采用** `xfail`（属真实跨平台缺陷而非环境局限）或改断言（断言期望 POSIX 是正确契约）。

## 3. M3 任务完成清单
- T17 公司工作流入口 CLI（approve_with_concerns）
- T18 memory/motion CLI + MotionStore 持久化（approve_with_concerns；记忆同源已补）
- T19 成本/损耗/预算接入 CLI（approve）
- T20 记忆开销计入成本（approve_with_concerns）
- T21 search 阈值+候选上限（approve_with_concerns）
- T22 RunStore 崩溃恢复（approve_with_concerns；另修 get_collab_status 状态覆盖 bug）
- T23 FR-META 对抗性核验（approve；另修 build_audit 负成本 clamp bug）
- T24 全量验收+V1 三分类+文档定稿（本报告）

## 4. 文档
- 本报告 + 各任务 roundtable-review（T17–T23）
- docs/AGENT_GUIDE.md（T17–T23 接口速查）
- docs/PROJECT_MEMORY.md（当前状态 + 各 T 进展/评审 + 踩坑）

## 5. 备注
- `docs/` 与代码均在 m2 分支，尚**未 push**（按要求内容定稿后才发布；本次为定稿，可按需 push origin/m2）。
- M3.x（FR11 完整机制/动议同源接入图/执行依赖读时序）未纳入 M3 主交付，留待后续独立 PR。