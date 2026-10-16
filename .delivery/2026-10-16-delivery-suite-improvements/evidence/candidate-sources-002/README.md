# Delivery：五项独立能力与交付编排

每项专业能力有自己的内容标准、输入输出和 Markdown 产物。可以直接点名单项，也可以明确选择完整编排；是否组合不改变专业质量标准。

| 入口 | 负责的结果 | 边界 |
| --- | --- | --- |
| [delivery-design](delivery-design/SKILL.md) | 机制、契约、关键决定、验收与设计审阅 | 不表示已经实施或实测 |
| [delivery-plan](delivery-plan/SKILL.md) | 任务、依赖、细化、审查与验证安排，以及计划审阅 | 不维护实际执行状态 |
| [delivery-implement](delivery-implement/SKILL.md) | 实际改动、自检、偏差及交接 | 不替代独立审查 |
| [delivery-review](delivery-review/SKILL.md) | 实际实现的规格与质量审查、问题及复审 | 设计和计划审阅由对应专业能力负责 |
| [delivery-verify](delivery-verify/SKILL.md) | 实际交付对象的逐项符合、不符合和未验证证据 | 不接受风险或宣布全流程结束 |
| [delivery-orchestrate](delivery-orchestrate/SKILL.md) | 选择路线、组织独立执行、接纳证据、恢复与收尾 | 用户明确选择组合才进入 |

## 目录与安装

`delivery/` 是六个 skill 的源码分组；`.delivery/YYYY-MM-DD-主题/` 是使用它们产生的任务材料。两者用途不同。已有同目标目录继续沿用，历史 `docs/delivery/` 与 `.workflow` 不自动迁移。

在仓库根执行：

```bash
bash install-skill.sh delivery/delivery-design
bash install-skill.sh delivery/delivery-plan
bash install-skill.sh delivery/delivery-implement
bash install-skill.sh delivery/delivery-review
bash install-skill.sh delivery/delivery-verify
bash install-skill.sh delivery/delivery-orchestrate
```

安装仍以 basename 命名，客户端使用 `$delivery-plan` 等原名称。安装器会覆盖既有目标，操作前核对它们确实是预期软链；未知实际目录先保留和判断。五包分别可搬到无 Git、无编排器、无兄弟包的项目使用；独立调用默认不提交。

## 使用与恢复

单独请求示例：“仅用 delivery-review 审查这些改动，留存发现，不修复源码。”完整请求示例：“使用 delivery 完整组合实现这个需求，按风险组织独立审查和实际验收，允许本地提交，不 push。”已有有效上游材料直接引用，不强制重写五份文件。

专业正文与证据说明是可读 Markdown。编排 JSON 绑定特定版本，不能成为另一份随意改动的需求真源。新流程明确采用编排契约 2；既有 v1 仍用原规则续接。版本入口、命令与例子见编排包的 [API 导航](delivery-orchestrate/references/runtime-api.md)和[契约 2](delivery-orchestrate/references/runtime-api-v2.md)。

恢复从目标 index、设计/计划、实际活动报告、事件和原始证据开始，核对当前产品与 skill 来源，再选择下一步。未完成命令先查进程和副作用；同操作 ID 不重放，新操作也不能绕过未核查状态。仅有文件、退出码 0 或任务勾选不能表示通过。

## 维护与证据

```bash
python3 -B delivery/delivery-orchestrate/scripts/validate_suite.py --skills-root delivery --output /path/to/new-evidence-directory
```

该脚本运行包结构与确定性回归，保存 JSON、可读报告和原始日志。真实模型行为评测另见[评测说明](delivery-orchestrate/tests/evaluation/README.md)。独立审查、确定性测试、真实模型执行和实际交付对象验证分别留证；通过其中一项不自动覆盖其他项。

更新方法见编排的[维护与升级规则](delivery-orchestrate/references/maintenance.md)。原 task-workflow、design-tech-doc 和 plan-implementation 继续保留；本组不自动修改或同步它们。能力更新涉及必要输入、语义、独立性或门禁时先评估契约和活动流程，不因软链立即生效就让进行中的任务静默换规则。
