# 控制配置 005 独立定向审查

**结论：可以应用 control-config-005；本次变化只调整机械证据输出位置并显式复用当前仍有效的八项实施，没有降低计划语义或提前接纳未完成验证。** 本报告不代替新机械运行、真实组合质量评审或整体交付。

2026-10-16；复核者 `/root/independent_delivery_review`。非本次配置/计划/实施报告作者；只写本审查及检查证据，不应用配置、不修改账本。版本与逐字段差异见 [checks](005-control-checks.json)，实际稳定 v1 状态见 [status](005-control-status.json)。读取状态前后 journal SHA-256 相同。

比较 004→005 全部 JSON 字段，变化恰为：

- V-01 command 第 7 项输出目录从 evidence/final-mechanical 改为 evidence/final-mechanical-002，其他命令参数、任务、依赖、覆盖、专业范围与验收原文均未变。
- mapping_reason 说明留存旧机械输出、新环境重跑、T-03 重新核对及 V-06/V-07 尚待证据。
- reuse 从一项扩展为八项，并更新复用理由；没有复用审查/验证结论。

实际留存稳定 v1 引擎当前读取 configuration=current、config_operation=configure-control-004。八项 passed 操作与 005 reuse 集合完全相等：T-01-001、T-02-001、T-03-003、T-04-001、T-05-001、T-06-001、T-07-001、T-08-001（均带 implement- 前缀）。T-09—T-11、R-all 与 V-01—V-07 均 pending，符合仍在完成设施/正式行为评测的实际阶段；旧 run-V-01-001 的 exit 0 未冒充当前验证接纳。

T-03-003 是 configure-control-004 下真实新 record，绑定 implementation/012-environment-boundary.md、final-boundary-002.json 和独立边界审查；没有把过期 T-03 原结果直接改 passed。本次另外以原 baseline manifest 的 protected 清单重新核对当前磁盘：439 项中 437 字节一致，变化仅根 CLAUDE.md 与 README.md，无缺失；12 个安装链接仍为软链并解析到 delivery 对应包。与报告的保守迁移边界复核一致。此边界核查不要求重复执行实际搬迁，也不凭目录快照证明新的专业/环境语义。

005 不改计划与来源路径、7 验证组覆盖和先后关系；前期独立门禁由人工报告留据的 v1 表达限制继续成立。新输出目录能保留原真实机械结果，后续须实际运行得到新来源对应结果；本审查没有预先认定新增测试数或新命令已经通过。正式行为、V-06、整体独立审查及 V-07 仍需真实产物，不能被八项复用或新机械通过抵扣。
