# Delivery 组合优化与目录迁移

目标：承接已确认计划，完成六个 delivery skill 的质量增强、兼容演进、真实行为评测与源码目录迁移。

用户已明确授权实施，原话见 [authorization.md](authorization.md)。任务材料保存在本目录；`delivery/` 是源码分组目录。实际推进由留存稳定 v1 引擎和 runtime 维护，候选新引擎在隔离环境测试；本文仅导航。

- [详细修改计划](plan.md)：范围、任务、依赖、脚本分工、审查与验收、恢复和变更要求。
- [计划机械检查](evidence/plan-check.json)：有限的结构检查结果，不代表实施或质量验收。
- [规划来源快照](evidence/planning-inputs/README.md)：实际使用的 delivery-plan 内容及可恢复摘要清单。
- [独立计划初审](plan-reviews/001.md)及[定向复核](plan-reviews/002.md)：两个验收/评测边界问题及引用错误已在计划中修订；不代表实施或用户批准。
- [详细设计](design.md)、[设计初审](design-reviews/001.md)及[复核](design-reviews/002.md)：未知运行解除和实际执行来源绑定的设计检查。
- [冻结评测协议](evaluation-spec.md)：质量判据、比较对象和答案隔离；真实结果另行留存。
- [基线实施](implementation/001-baseline.md)、[迁移实施](implementation/002-migration.md)、[专业规范实施](implementation/003-professional.md)、[评测设施实施](implementation/005-harness.md)。
- [迁移独立检查](review/001-migration.md)、[专业包独立检查](review/002-professional.md)、[验证工具复核](review/003-validator-recheck.md)。
- [计划细化与控制映射审阅](plan-reviews/003-refinement-and-mapping.md)：发现保留，修订配置依次保存于 admission；以实际定向复核为准。
- [控制映射复核](plan-reviews/004-mapping-recheck.md)、[契约实施](implementation/009-contracts.md)与[迁移边界复核](implementation/010-migration-recheck.md)。
- [核心恢复与复用定向复核](review/009-core-reuse-recheck.md)、[集成导航审查](review/010-integration.md)、[评测器严格接口复核](review/012-harness-shape-recheck.md)：各报告明确其范围，均不替代真实组合质量结论。
- [案例资产实施](implementation/011-case-assets.md)与[统一机械检查](evidence/final-mechanical/report.md)：保留实际命令和原始日志，后续来源变化按账本重新判断。
- [覆盖缺口独立定位](review/016-coverage-gap.md)、[真实执行条件说明](evidence/behavior/execution-notes.md)：明确已有证据、待补反例、环境事故与正式接纳时点。
- [定向专业案例冻结](evidence/behavior/focused-case-assets/report.md)、[正文映射案例](evidence/behavior/mapping-case-preflight-002/asset-report.md)、[重复失败交接案例](evidence/behavior/repeated-failure-case-preflight/asset-report.md)：资产和自检不能代替真实模型成绩。
- [本轮交付与验证边界](summary.md)、[用户最新收敛要求](verification/convergence.md)、[最终247项检查](evidence/final-mechanical-003/report.md)：不再扩大测试，未验能力留实际任务验证。
- [全部运行状态清单](verification/behavior-observations.json)、[本机原始证据留存](evidence/README.md)：保留失败和限制，不把prepared计作执行。
- [新增独立审查027](review/027-independent-fresh-audit.md)、[两项修复决定](repairs/FR-001-FR-002/plan.md)、[修复实施与必要验证](implementation/017-fr001-fr002.md)、[独立定向复审028](review/028-fr001-fr002-recheck.md)：FR-001/FR-002 修复及其有限证据，不替代原全套验收。

依据：本会话已确认的独立调用、编排管理、质量优先、内容留存与本地提交边界，以及 2026-10-16 对当前仓库和安装入口的只读核查。本文仅导航，不维护另一份执行状态。
