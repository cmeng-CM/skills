# 基线与评测协议实施记录

版本 1；2026-10-16；作者 `/root`，上下文 `implementation-controller`。生成能力：delivery-implement，专业契约 1；实际规则来源为本目标 `evidence/baseline/sources/delivery-implement/`。这是 T-01 实施与自检记录，不是独立审查或最终验收。

已保存 HEAD、53 个 delivery 文件、439 个保护对象的摘要、原工作树差异、12 个安装软链和原暂存区差异摘要。六包及原 task-workflow 的实际来源另有可恢复快照。归属见 `evidence/baseline/manifest.json`；旧状态和原用户修改未清理。

`evaluation-spec.md` 已在机制修改前留存三候选比较、硬性负例、公开输入/私有答案隔离、重复策略与证据标准。用户实施授权逐字保存于 `authorization.md`。

迁移后的诊断基线：design 44、plan 14、orchestrate 63 项原回归全部通过，原始结果在 `evidence/baseline/tests/`。该结果只证明修改前的确定性基线，不证明组合质量。

真实 CLI 的普通沙箱探测失败，批准后的隔离调用成功，产生实际 turn.completed/usage；两种结果分别保留，见 `evidence/behavior/interface-probe/` 与 `interface-probe-approved/`。正式评测仍待 harness 独立检查及集成后执行。

未完成：后续契约、能力增强和真实组合验证。稳定控制引擎为本目标留存 v1 源码，候选引擎不管理自身改造账本。
