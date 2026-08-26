# V2 引擎 T23（FR-META 对抗性核验，FR-GAP-5）代码评审报告

> 日期：2026-08-26 ｜ 对象：tests/test_collab_adversarial.py（9 个对抗性用例）+ collab/audit.py（build_audit 负面计数器拒绝，对抗性发现并修正）
> 方式：自审 + 专家视角综合（Computing/Philosophy/History）。结论：approve。

## 1. 交付
- 新增对抗性用例模块，覆盖「制造错误→系统揭出并修正」：
  1. 无效审计（缺结构化字段）→ hard_rules_check 揭出（audit_invalid）。
  2. 显性自相矛盾（同时采用/放弃方案A）→ detect_decision_conflicts 揭出。
  3. 注入负成本 → build_audit 拒绝（**对抗性发现 bug 并修正**）。
  4. kind=fact 无 provenance → MemoryEntry 拒绝（可追问）。
  5. 经理 REVISE 产出 → 仲裁驳回且**不写记忆**（T8 保证）。
  6. 弱矛盾不能覆盖强记忆 → 旧条目保持 active、新弱条目 overridden（防自增强）。
  7. 任务超预算 → FAILED + budget_exceeded（不静默超支）。
  8. 孤儿 run → get_collab_status 归一 failed（不永久 running）。
  9. 记忆成本是子集、不重复计价。
- 全量 collab **156 passed**（=147+9）。

## 2. ⭐ 对抗性发现并修正的真实 bug
- **build_audit 静默 clamp 负成本**：TaskAudit.__init__ 用 max(0.0, cost_usd) 把负成本归零，validate_audit 的 cost_usd<0 检查永不触发——负成本被悄悄吞掉而非揭出。
- **修正**：build_audit 在构造前对 token_usage/prompt_tokens/completion_tokens/cost_usd 原始值做非负硬校验，任一为负立即 ValueError（与 validate_audit 契约一致，且不被 clamp 掩盖）。
- 其余 8 个对抗性用例全部通过，未再暴露系统缺口（现有硬规则/治理/预算/恢复/成本面足以揭出这些错误）。

## 3. 三视角
- **Computing**：对抗性守卫已落地且未误伤既有路径；build_audit 的原始非负校验是「揭出」而非「吞掉」，值得。无过度设计（守卫只在构建处，不在每次调用）。
- **Philosophy**：FR-META「可纠错/可追问」被操作化为「制造错误→系统揭出」；负成本拒绝体现了经济理性不被静默掩盖；REVISE 不写记忆守住「事实不被污染」。
- **History**：与 M2/T8/T20/T22 既有治理面一致（审计硬规则→记忆治理→成本→崩溃恢复），T23 用对抗性用例把这些保证钉住；未重复造轮子。

## 4. 结论
approve。T23 可合入（m2 分支）。9 个对抗性用例覆盖审计/仲裁/记忆/预算/恢复/成本六大面，其中 1 个制造错误暴露了 build_audit 静默 clamp 负成本的缺口并已修正；其余用例证明系统能揭出并修正注入的错误。