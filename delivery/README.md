# Delivery：五项基础能力、可选复杂修复与交付编排

每项专业能力有自己的内容标准、输入输出和 Markdown 产物。可以直接点名单项，也可以明确选择完整编排；是否组合不改变专业质量标准。

技术设计与实现规划统一由 `delivery-design`、`delivery-plan` 承担，普通对应请求即可使用，单项请求不自动启动完整编排。旧 `design-tech-doc`、`plan-implementation` 已退役；已有历史产物与记录保留。

| 入口 | 负责的结果 | 边界 |
| --- | --- | --- |
| [delivery-design](delivery-design/SKILL.md) | 机制、契约、关键决定、验收与设计审阅 | 不表示已经实施或实测 |
| [delivery-plan](delivery-plan/SKILL.md) | 任务、依赖、细化、审查与验证安排，以及计划审阅 | 不维护实际执行状态 |
| [delivery-implement](delivery-implement/SKILL.md) | 实际改动、自检、偏差及交接 | 不替代独立审查 |
| [delivery-fix](delivery-fix/SKILL.md) | 复杂 bug 的证据化诊断、授权修复、自检和多轮记录 | 可选实施能力，不替代独立审查与验收 |
| [delivery-review](delivery-review/SKILL.md) | 实际实现的规格与质量审查、问题及复审 | 设计和计划审阅由对应专业能力负责 |
| [delivery-verify](delivery-verify/SKILL.md) | 实际交付对象的逐项符合、不符合和未验证证据 | 不接受风险或宣布全流程结束 |
| [delivery-orchestrate](delivery-orchestrate/SKILL.md) | 选择路线、组织独立执行、接纳证据、恢复与收尾 | 用户明确选择组合才进入 |

## 目录与安装

`delivery/` 包含五项基础专业能力、可选的 `delivery-fix` 和编排 skill；`.delivery/YYYY-MM-DD-主题/` 是使用它们产生的任务材料。两者用途不同。已有同目标目录继续沿用，历史 `docs/delivery/` 与 `.workflow` 不自动迁移。

项目根目录的 `.delivery/`、`.workflow/` 只保存在本地，不纳入 Git。取消既有跟踪不删除本地材料，也不改写历史提交。

在仓库根执行：

```bash
./skill install delivery-design delivery-plan delivery-implement \
  delivery-review delivery-verify delivery-orchestrate
# 需要复杂 bug 诊断与修复时另装
./skill install delivery-fix
```

安装名称沿用包目录 basename，客户端使用 `$delivery-plan` 等原名称。正确链接保持不动，缺失时补链；同名外部链接或实际内容报冲突并保留，不覆盖删除。各专业包分别可搬到无 Git、无编排器、无兄弟包的项目使用；独立调用默认不提交。

## 使用与恢复

单独请求示例：“仅用 delivery-review 审查这些改动，留存发现，不修复源码。”完整请求示例：“使用 delivery 完整组合实现这个需求，按风险组织独立审查和实际验收，允许本地提交，不 push。”已有有效上游材料直接引用，不强制重写五份文件。复杂故障可直接请求“仅用 delivery-fix 诊断并修复这个 bug”；用户只要求诊断时不自动修改产品。普通任务不要求安装或使用 fix。

专业正文与证据说明是可读 Markdown。编排 JSON 绑定特定版本，不能成为另一份随意改动的需求真源。新流程明确采用编排契约 2；既有 v1 仍用原规则续接。版本入口、命令与例子见编排包的 [API 导航](delivery-orchestrate/references/runtime-api.md)和[契约 2](delivery-orchestrate/references/runtime-api-v2.md)。

组合中的实施任务默认使用 `delivery-implement`；根因不明、偶发或反复修复失败的故障可以选择 `delivery-fix`，也可从原实施任务转交。fix 产物直接作为该任务的实施报告接纳，再进入原有独立审查和验收，不重复生成 implementation 正文。编排契约仍为 2，fix 的可选接入须显式启用实施子契约 1，详见 [可选复杂修复接入](delivery-orchestrate/references/runtime-api-v2.md#可选复杂修复接入实施子契约-1)。

同一 bug 的所有轮次与证据放在 `.delivery/创建日期-主题/fixes/BUG-001-问题简述/`，由 `index.md` 导航，`001/fix.md`、`001/evidence/` 等按轮次保存。跨日期、会话、agent 和复发沿用 bug 目录；新任务引用既有目录，不复制历史。审查与验证仍保存各自报告；正式接纳绑定具体轮次而不是最新入口。

恢复从目标 index、设计/计划、实际活动报告、事件和原始证据开始，核对当前产品与 skill 来源，再选择下一步。未完成命令先查进程和副作用；同操作 ID 不重放，新操作也不能绕过未核查状态。仅有文件、退出码 0 或任务勾选不能表示通过。

## 维护与证据

```bash
python3 -B delivery/delivery-orchestrate/scripts/validate_suite.py --skills-root delivery --output /path/to/new-evidence-directory
```

该脚本运行包结构与确定性回归，保存 JSON、可读报告和原始日志。真实模型行为评测另见[评测说明](delivery-orchestrate/tests/evaluation/README.md)。独立审查、确定性测试、真实模型执行和实际交付对象验证分别留证；通过其中一项不自动覆盖其他项。

更新方法见编排的[维护与升级规则](delivery-orchestrate/references/maintenance.md)。原 task-workflow 继续独立保留，本组不自动修改其引擎、门禁或运行状态。能力更新涉及必要输入、语义、独立性或门禁时先评估契约和活动流程，不因软链立即生效就让进行中的任务静默换规则。
