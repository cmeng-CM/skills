# Delivery：专业交付能力与编排

五项基础能力（设计、规划、实施、审查、验证）、可选的复杂修复能力，以及一个把她们组织成完整交付的编排器。每项能力对自己的结果负责，普通对应请求即可自然使用，无需点名；质量由专业判断、独立审查和机械门禁共同保障。

机制细节（目录职责、事件、门禁、状态权威关系）见 [ARCHITECTURE](ARCHITECTURE.md)；各能力的实际行为规则以对应 SKILL.md 为准，本文件只负责选路和入口。

## 1. 什么时候用什么

| 你的情况 | 用什么 |
| --- | --- |
| 局部改动、可独立验证 | `delivery-implement`（轻路径，一份简短实施记录即可） |
| 根因不明、反复失败的复杂故障 | `delivery-fix`（可只诊断，或授权修复） |
| 多任务依赖、阶段门禁、独立审查与验收、需要可恢复的交付状态 | `delivery-orchestrate`（完整编排） |
| 技术设计 / 实现规划本身 | `delivery-design` / `delivery-plan`（单项使用不自动进入编排） |
| 只问答、讨论、学习 | 不启动任何流程 |

任务难、文件多、用到多个技能，都不单独构成编排理由；编排解决的是状态、依赖、证据和恢复问题。

**硬特征路由**：出现下列任一特征——不可逆 DDL 或删除数据、生产环境部署/发布/配置变更、权限/RLS/密钥口径变更、多批外部授权窗口——要么进入编排，要么在目标 `index.md` 留一行「硬特征命中 + 不编排理由 + 时间」，不静默走轻路径。走了轻路径的硬特征任务有**最小证据集**：外部动作留痕（DDL/部署原文与授权）、验收独立性（非实施会话产出，或明标自检）、部署差异清单、批准留痕；缺项补齐或在实施记录写明原因。

**成本规则**：向子代理派发的提示首行固定环境自检命令，失败立即终止不进正文；部署、批量验收、大型复审等可清单化交接的阶段优先切子代理或新会话执行——长会话尾段每次请求重复支付全上下文 cache read。编排路径 close 前需产出 `metrics/`（或写 `metrics/UNAVAILABLE.md` 说明不可得原因）。

## 2. 能力一览

| 入口 | 负责的结果 | 边界 |
| --- | --- | --- |
| [delivery-design](delivery-design/SKILL.md) | 机制、契约、关键决定、验收与设计审阅 | 不表示已经实施或实测 |
| [delivery-plan](delivery-plan/SKILL.md) | 任务、依赖、细化、审查与验证安排，以及计划审阅 | 不维护实际执行状态 |
| [delivery-implement](delivery-implement/SKILL.md) | 实际改动、自检、偏差及交接 | 不替代独立审查；不产生验收结论 |
| [delivery-fix](delivery-fix/SKILL.md) | 复杂 bug 的证据化诊断、授权修复、多轮记录 | 可选能力，不替代审查与验收 |
| [delivery-review](delivery-review/SKILL.md) | 实际实现的规格与质量审查、问题及复审 | 存在未闭环发现时结论必须附条件清单 |
| [delivery-verify](delivery-verify/SKILL.md) | 实际交付对象的逐项符合、不符合、未验证证据 | 前置未满足只能取「未验证」，不得取「符合」 |
| [delivery-orchestrate](delivery-orchestrate/SKILL.md) | 选路线、组织独立执行、接纳证据、恢复与收尾 | 同一目标不能两个引擎同时控制 |

## 3. 任务材料放哪

- `delivery/` 是能力包（本目录）；`.delivery/YYYY-MM-DD-主题/` 是使用它们产生的任务材料目录，同目标沿用、跨日不改名。
- 目录内各文件的职责见 [ARCHITECTURE §2.2](ARCHITECTURE.md)：`index.md` 纯导航（例外仅三类单行留痕）、`runtime/journal.json` 是编排状态真源、`status.md` 是派生视图、`implementation/`、`review/`、`verification/`、`metrics/` 分别放各能力报告与统计。
- `.delivery/`、`.workflow/` 只保存在本地，不纳入 Git；历史 `docs/delivery/` 与 `.workflow` 不自动迁移。

## 4. 安装

在仓库根执行：

```bash
./skill install delivery-design delivery-plan delivery-implement \
  delivery-review delivery-verify delivery-orchestrate
# 需要复杂 bug 诊断与修复时另装
./skill install delivery-fix
```

安装名沿用包目录 basename。七包均为软链安装、即时生效，在途任务是否换用新规则按[维护规则](delivery-orchestrate/references/maintenance.md)判断。正确链接保持不动，缺失补链，同名外部链接或内容冲突时报冲突不覆盖。各专业包可独立搬到无 Git、无编排器的项目使用。

## 5. 一次编排交付的生命周期

~~~text
选路线（硬特征核对）→ design → plan → configure → gate → 实施（guard/claim/record）
  → 独立审查（review record，条件清单闭环）→ 独立验收（run/verify-batch，前置满足列）
  → final whole review（读取验收证据）→ check --preclose → close（需 metrics/ 或 UNAVAILABLE.md）
~~~

- 首次配置前跑只读 `preflight`；第一次编辑产品文件前跑 `guard`；执行状态用 `status --write-status` 写 `status.md`。
- 收尾顺序固定 `check --preclose` → `close`（报告固定为 work 下 `closeout.md`）；`doctor` 只读体检；`verify-batch` 一次原子登记多项验收。
- 复杂故障经 fix 接入须显式启用实施子契约，轮次与证据放 `fixes/BUG-标识-简述/`，详见 [API 契约 2](delivery-orchestrate/references/runtime-api-v2.md)。
- 恢复从目标 index、设计/计划、活动报告、事件与原始证据开始；仅有文件存在、退出码 0 或勾选不能表示通过。

编排契约当前为 2；既有 v1 工作按原规则续接，不静默升级。命令与例子见 [API 导航](delivery-orchestrate/references/runtime-api.md)与[契约 2](delivery-orchestrate/references/runtime-api-v2.md)。

## 6. 耗时与 token 统计

~~~bash
# 从 ZCode 会话库导出请求级 usage（Claude Code / Codex 为后续扩展）
python3 -B delivery/delivery-orchestrate/scripts/export_session_usage.py \
  --sessions <会话ID> --since <ISO> --until <ISO> > usage.csv
# 汇总到任务目录 metrics/
python3 -B delivery/delivery-orchestrate/scripts/collect_metrics.py \
  --work <任务目录> --usage usage.csv --map task_phase_map.csv --output <任务目录>/metrics
~~~

无价格表时只报 token，不报金额；共享会话窗口只能给 allocated 口径。口径详见 [metrics.md](delivery-orchestrate/references/metrics.md)。

## 7. 维护与证据

```bash
python3 -B delivery/delivery-orchestrate/scripts/validate_suite.py --skills-root delivery --output /path/to/evidence
```

结构检查与确定性回归之外，独立审查、真实模型行为评测（见[评测说明](delivery-orchestrate/tests/evaluation/README.md)）、实际交付对象验证分别留证，互不替代。能力更新涉及必要输入、语义、独立性或门禁时先评估契约与在途流程，不因软链即时生效就让进行中的任务静默换规则。原 `task-workflow` 独立保留，本组不自动修改其引擎、门禁或运行状态。

## 8. 快速示例

- 轻路径："用 delivery-implement 改这个模块并自检，留一份简短实施记录，本地提交不 push。"
- 完整编排："用 delivery 完整组合实现这个需求，按风险组织独立审查和实际验收，允许本地提交，不 push。"
- 单项能力："仅用 delivery-review 审查这些改动，留存发现，不修复源码。"
- 仅诊断："仅用 delivery-fix 诊断这个 bug，不改产品。"
