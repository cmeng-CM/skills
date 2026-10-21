# Delivery 运作机制与目录说明

本文说明当前 delivery 组合如何选择路线、如何记录状态、每个目录和文件负责什么，以及哪些结论不能从文件表面推断。具体命令字段以 [编排契约 2](delivery-orchestrate/references/runtime-api-v2.md) 为准；本文讲机制和目录职责。

适用基线：delivery 契约 2，当前仓库提交 b4ef72a。旧的契约 1 工作按其原规则续接，不在本文展开。

## 1. 一句话模型

Delivery 不是一条自动流水线，而是三层组合：

1. **专业能力**：design、plan、implement、review、verify、fix 分别对结果负责；
2. **编排器**：判断是否需要组织依赖、门禁、审查、验收和恢复，并维护状态；
3. **任务材料目录**：存放设计、计划、审阅、实施、验收和运行账本。

专业 Markdown 是语义依据，准入 JSON 是机器可读的投影，journal 是执行状态真源。三者不能互相替代。

## 2. 两层目录

### 2.1 delivery/ 是能力包

~~~text
delivery/
├── README.md                 总入口、安装、路线选择
├── ARCHITECTURE.md           本文：机制与目录职责
├── delivery-design/          技术方案与设计审阅
├── delivery-plan/            实现计划与计划审阅
├── delivery-implement/       实际实施与自检
├── delivery-fix/             可选：复杂故障诊断与授权修复
├── delivery-review/          实现代码/交付物的独立审查
├── delivery-verify/          按验收要求取得证据
└── delivery-orchestrate/     编排、状态、门禁、恢复、收尾
~~~

每个能力包都是独立的 skill 包，包含：

| 路径 | 作用 |
|---|---|
| SKILL.md | 触发范围、工作协议、退出条件；是实际行为规则 |
| agents/openai.yaml | 客户端隐式调用配置；不等于能力本身 |
| references/ | 该能力的契约、标准、示例、工作规则 |
| assets/ | 报告模板、交接模板、计划模板等 |
| scripts/ | 可执行检查器或编排引擎；没有脚本的包不强行添加 |
| tests/ | 确定性测试或行为案例；存在不等于已实际运行 |

delivery 的七个包不要求同时安装，也不要求目标项目有 Git 或编排器。专业包可以独立使用；只有需要持续状态、门禁、依赖和恢复时才进入 orchestrate。

### 2.2 .delivery/ 是任务工作区

~~~text
.delivery/YYYY-MM-DD-主题/
├── index.md                  纯导航：目标、边界、产物入口
├── design.md                 当前设计正文
├── plan.md                   当前实现计划正文
├── admission/                候选准入输入和请求快照
├── design-reviews/           设计审阅报告
├── plan-reviews/             计划审阅报告
├── mapping-reviews/          设计/计划→准入配置的映射审阅报告
├── change-reviews/           material change 的授权与变更审阅
├── implementation/           各任务的实施报告和证据
├── review/                   实现代码/交付物的审查报告
├── verification/             验收记录、运行输出、逐项结论
├── evidence/                 可选的原始证据汇总
├── refs/                     设计稿、截图、外部参考
├── fixes/BUG-.../            可选复杂故障的多轮记录
├── runtime/                  编排引擎独占状态
│   ├── journal.json          事件哈希链，状态真源
│   ├── objects/              内容寻址对象库
│   ├── lock                  写锁
│   ├── rejected.jsonl        被拒绝的写操作
│   └── journal.schema1.bak   schema 1 回滚备份
├── status.md                 由 journal 生成的派生视图
└── closeout.md               收尾报告
~~~

不是每个任务都需要全部文件。小型专业任务可以只有设计/计划/实施报告；完整编排才需要 admission、runtime、status 和 closeout。

## 3. 权威顺序

| 对象 | 谁写 | 是否权威 | 说明 |
|---|---|---|---|
| 用户目标、设计、计划正文 | 用户/专业能力 | 语义依据 | 已 gate 的版本冻结，不再改写 |
| admission/config-*.json | 协调者/执行者 | 候选输入 | 可能包含未接纳或被拒候选 |
| journal 的 configure 事件 | 编排引擎 | **当前配置的权威** | 当前生效配置看最新 configure，不看目录里最新文件 |
| runtime/journal.json | 编排引擎 | **执行状态权威** | 事件链、门禁、记录、运行、收尾 |
| runtime/objects/ | 编排引擎 | 内容证据 | 按哈希存储，journal 引用 |
| status.md | 引擎生成 | 派生视图 | 当前状态摘要，不是第二份真源 |
| index.md | 人/协调者 | 导航 | 不会自动更新，可能过期 |
| 审阅/实施/验收报告 | 专业能力 | 证据 | 只有被 record/gate 接纳后才进入状态 |
| closeout.md | 协调者 | 收尾报告 | 不是验收证据本身 |

最重要的区分：

- 最新 config 文件 ≠ 当前配置；
- index.md ≠ 状态；
- status.md ≠ 门禁；
- 报告存在 ≠ gate/record 已通过；
- implementation passed ≠ acceptance passed。

## 4. 一次完整交付怎么走

### 4.1 选路线

- 局部、可独立验证的开发：直接用 implement；
- 根因不明或反复失败的复杂故障：用 fix，可只诊断或授权修复；
- 需要多任务依赖、阶段门禁、独立审查、验收和恢复：进入 orchestrate；
- 只问答、讨论、学习或明确限定单项结果：不自动进入完整编排。

编排不是“任务大就必须用”，也不是“用了就自动保证质量”。它解决的是状态、依赖、证据和恢复问题。

### 4.2 设计与计划

1. design 写机制、契约、决策、验收和失败路径；
2. 按风险进行独立设计审阅；
3. plan 写任务、依赖、审查/验收安排和命令；
4. 做计划审阅；
5. 把正文映射为 admission config，做映射审阅；
6. material change 做变更审阅。

设计、计划、映射、变更对应四个准入 gate：

- design_review
- plan_review
- mapping_review
- change_review

这四个 gate 不是实现代码审查。实现代码审查是后面的 review record，不能互相替代。

### 4.3 configure 与 gate

~~~text
preflight → init → configure → gate → implementation
~~~

- configure 只保存候选准入；不代表批准；
- configure 采集设计/计划来源、skill pins、monitor baseline、任务/审查/验收图、requirements、资源和变更分类；
- gate 读取实际报告，记录 passed/failed、actor/context、config_operation、source hashes；
- 只有必要 gate 当前通过后，任务才能推进；
- 来源、范围、任务、验收、requirements、resources 或路线变化，会使相关 gate/记录失效；organization-only 变化只在准入输入等价时允许 reuse_gates，change_review 仍要新做。

### 4.4 实施

1. 读 brief，确认范围、必需来源和验收归属；
2. 第一次编辑前运行 guard，并记录结果；
3. 需要写资源时 claim；
4. 实际修改产品文件；
5. 写实施报告和证据；
6. 用 record 登记 implementation；
7. release；
8. 如果改了范围外文件，先做 impact 判断，再重新 record。

guard 是流程检查，不阻止直接编辑；真正的拒绝在 record/run/close。单写者、资源冲突和审查期间不编辑被审文件仍需人工遵守。

### 4.5 审查

- delivery-review 独立审查实际代码/交付物；
- 审查者不能是实现者；
- 审查报告写规格符合性、实现质量、证据和未覆盖项；
- 实现审查用 record(kind=review)，不是 design/plan/mapping/change gate；
- 复审只查原问题、修复影响和版本差异；高风险任务保留一次整体终审；
- 没有独立审查能力时，保留待审，不放行依赖它的收尾。

### 4.6 验收

- 声明为 command 的验收可以用 run 捕获真实命令输出；
- 退出码 0 不等于语义通过；验证者要对照 criteria 判断；
- 人工项必须逐项确认，不能只写“已检查”；
- 证据不足保留 unknown，不能把未知写成通过；
- verify-batch 可以一次原子登记多项验收；
- verification record 与 implementation record 是两种不同状态。

### 4.7 收尾

~~~text
status/check → check --preclose → close → status/closeout/index
~~~

- preclose 只读检查当前实施、独立审查、验收、资源、未知运行、来源漂移等；
- close 会重跑同一套阻塞判定，并写 close 事件；
- close report 固定为 work 下的 closeout.md；
- limited 只允许已实证失败、有具体用户授权的例外；未知/过期/失败不能豁免；
- close 后修改需要 reopen，不能拿旧 close 证明新版本。

## 5. runtime 事件机制

### 5.1 事件格式

journal 是一个只能追加的事件链。每个事件大致包含：

~~~json
{
  "seq": 18,
  "at": "2026-10-20T08:05:08Z",
  "kind": "record",
  "op": "impl-T-01-003",
  "payload": {},
  "request_hash": "...",
  "previous": "...",
  "hash": "..."
}
~~~

- previous 指向上一个事件；
- hash 由事件内容计算，检测意外损坏或链不一致；
- request_hash 用于幂等重放；
- 相同 op 重放返回原事件，不重复写；
- 事件链不是签名，不能抵抗拥有写权限的恶意管理员。

### 5.2 主要事件类型

| kind | 作用 |
|---|---|
| init | 建立工作区 |
| configure | 接纳候选配置，保存当前绑定 |
| gate | 记录 design/plan/mapping/change 审阅结果 |
| resource | claim/release 文件/能力资源 |
| record | 实施、实现审查、验收、诊断等结果 |
| impact | 范围外变化的影响判断，可使旧记录失效 |
| run-started / run | 执行验收命令，捕获真实输出 |
| close / reopen | 收尾与重开 |
| source-update | 更新 skill/source pin |
| run-investigation / run-resolution | 未完成运行、旧命令不再适用时的调查与承接 |
| attempt | 复杂故障诊断的尝试记录 |
| implementation-protocol | 可选 fix 子契约的接入记录 |

具体命令和字段以 [runtime-api-v2](delivery-orchestrate/references/runtime-api-v2.md) 为准；不要手写 journal。

### 5.3 对象库

runtime/objects 用 SHA-256 内容寻址：

- 报告、证据、snapshot 内容各存一个对象；
- 相同内容只存一份；
- 文件没有扩展名，按哈希寻址；
- journal 只保存 object_hash、bytes 和 path，不把全文重复塞进事件；
- 对象被 journal 引用后不可随意删除，否则 doctor/check 会 fail closed。

对象多不等于模型成本高。模型只读 brief、报告和证据；对象库是本地内容存储。当前 work 会被 inventory 排除，不会反复扫描 runtime 自身。

## 6. 文件职责明细

### 6.1 admission/

| 文件 | 作用 |
|---|---|
| authorization.md | 用户授权、范围、边界和原话；不是 gate 结果 |
| config-NNN.json | 候选准入：任务、审查、验收、requirements、来源、资源、change、monitor、skill pins |
| gate-*.json | gate 请求快照；对应 journal 的 gate 事件 |
| resource-*.json | claim/release 请求快照 |
| implementation-*.json | record 请求快照 |
| impact-*.json | 范围外变化判断请求快照 |

注意：config 目录里可能有被拒候选或旧候选；当前配置以 journal 最新 configure 事件为准。

### 6.2 implementation/

每个任务一份或以上报告，例如：

- implementation/T-01.md：脚本/改动阶段；
- implementation/T-01-ddl-execution.md：实际执行 DDL 的记录；
- implementation/T-01.evidence.txt：原始检查输出或摘要；
- implementation/T-01-impact.md：范围外变化判断。

record 事件只引用这些文件并保存哈希，不把全文写进 journal。

### 6.3 review/ 与 *-reviews/

- design-reviews/：设计审阅；
- plan-reviews/：计划审阅；
- mapping-reviews/：设计/计划→admission config 的映射审阅；
- change-reviews/：material change 的授权和变更审阅；
- review/：实现代码/交付物的独立审查。

前四类对应 gate；最后一类对应 record(kind=review)。不要把实现审查报告放到 design-reviews/ 冒充设计 gate。

### 6.4 verification/ 与 evidence/

- verification/：按 A-XX 或批次保存验收结论、命令输出、人工确认和 unknown；
- evidence/：可选的原始证据汇总；
- run 的输出也会进入对象库/报告引用；
- 验收记录必须能追溯到实际对象和实际命令，不能只写“已通过”。

### 6.5 status.md / index.md

status.md：

- 由 status --write-status 生成；
- 包含 lifecycle、config、gates、tasks、reviews、verification、unassessed、unknown runs、resources 等；
- 人工补充区不参与门禁；
- 可能过期，journal 才是真源。

index.md：

- 只做导航：目标、边界、设计/计划/报告入口；
- 不复制状态表；
- 不会自动更新，升版/新增报告后要手动同步；
- index 过期不代表 journal 过期，但会影响下一位执行者。

### 6.6 closeout.md

- close 请求指定的固定报告路径；
- 说明完成范围、证据、未验证项、残余风险；
- 不是 gate 事实源，不能替代 verification 记录。

## 7. 四个 gate 与实现审查

| 名称 | 审什么 | 产物 | 由谁负责 |
|---|---|---|---|
| design_review | 设计机制、契约、边界、失败路径 | design-reviews/NNN.md | design 能力/独立审阅者 |
| plan_review | 任务、依赖、验收命令、执行顺序 | plan-reviews/NNN.md | plan 能力/独立审阅者 |
| mapping_review | 设计/计划/授权是否被 admission config 真实完整承接 | mapping-reviews/NNN.md | 独立映射审阅 |
| change_review | material change 的授权、审计链、是否降低验收 | change-reviews/NNN.md | 独立变更审阅 |
| implementation review | 实际代码/交付物是否符合规格、质量是否足够 | review/NNN.md | delivery-review |

mapping_review 不是“代码映射”。它检查 requirements 的来源摘录、tasks/acceptance 覆盖、依赖图、未确认决策、授权和配置一致性。它和 plan_review 可能有重叠，但一个审计划本身，一个审计划有没有被配置正确接住。

## 8. 可选审查协议 2

默认仍是旧的 review 方式。只有显式设置 review_protocol=2 才启用批次协议：

- 需要 Git worktree；
- 首次 configure 捕获不可变 base_commit，后续重配置继承；
- 每个任务恰属一个非 whole 批次，恰有一个 whole final；
- final 直接依赖所有批次；
- 批次一次逻辑审查，独立批次可只读并行；
- review record 必须带 review_commit/base_commit；
- final 校验批次 passed、commit 祖先、HEAD、干净工作树、非空 diff；
- final 审查者排除实现者和历史批次审查者；
- 批次重录或 final 后新提交会使 final stale；
- 不支持 Git 或旧 review 记录没有 review_commit 时，不能静默复用。

协议 2 只减少实现审查的重复，不替代 design/plan/mapping/change gate，也不替代验收。

## 9. 范围外变化与恢复

### 9.1 impact

如果实际改动超出任务 scope：

1. 先形成变化清单；
2. 用 impact 记录每个路径/目标的影响判断；
3. 相关旧记录可被 invalidated_operations 失效；
4. 未评估的变化使 unassessed_changes > 0，阻塞推进；
5. 不能把“影响未知”写成“无关”。

### 9.2 恢复

- 中断先查 status/check/next 和 journal；
- 未完成 run 先查进程、副作用和实际输出，不能直接重放；
- 旧命令不再适用时，用 run-investigation 调查，再用 run-resolution 承接责任；
- 不能删除失败事件、重算哈希链或伪造回滚；
- schema 1 → 2 的回滚靠 journal.schema1.bak，且有损；schema 2 之后的事件不回带；
- doctor 检查 admission、状态视图、拒绝日志、证据缺失、回滚点等问题。

## 10. 一个任务完成时记录什么

以 T-01 为例，典型顺序是：

~~~text
resource claim-T-01
record impl-T-01-001
resource release-T-01
impact impact-T-01-001          # 改了 scope 外的 schema.sql
resource claim-T-01-003
record impl-T-01-003             # 当前有效实施记录
resource release-T-01-003
~~~

当前 record 里包含：

- target=T-01、result=passed、actor/context；
- config_operation；
- report.path 和 object_hash；
- evidence 路径和 object_hash；
- 该任务 scope 的 snapshot；
- skill pin、orchestrate pin；
- summary。

同时会生成/引用：

- implementation/T-01-ddl-execution.md；
- implementation/T-01-ddl-execution.evidence.txt；
- admission/implementation-T-01-ddl.json；
- runtime/objects 中的内容对象；
- status.md 中 T-01 的状态。

但如果 A-01 还没有 verification record，那么：

- T-01 implementation passed 成立；
- T-01 acceptance passed 不成立；
- 不能把 status 里的 T-01: passed 直接说成任务验收完成。

## 11. 不自动记录的内容

- 每条 shell 命令和每次工具调用；
- status/check/brief/guard/next/doctor 等只读命令；
- 聊天过程、模型推理；
- 报告正文本身（只存路径和哈希，正文在对象库）；
- 自动 commit/push；
- 自动执行 DDL、部署或其他外部副作用。

需要保留的详细命令和输出，应由执行者写入实施/验收报告及 evidence 文件，再让 record/run 引用。

## 12. 当前边界与使用注意

1. gate 记录报告路径和对象哈希，但不解析报告正文。报告是否真的覆盖当前 config/版本，仍需审阅者和协调者核对；旧报告挂到新 gate 是可能发生的流程错误。
2. index.md 不会自动更新。升版、换 gate、执行 DDL 后要手动同步导航和边界。
3. implementation passed 与 acceptance passed 必须分开看；status 里 T-01 passed 不自动等于 A-01 passed。
4. 已 gate 的 design/plan 不要直接改头部状态；改正文会改变 source hash，使 gate stale。用 index/status/附注同步“已批准/已执行”。
5. gate 的 source hash 只证明绑定了哪个文件版本，不证明报告内容正确。
6. .delivery 默认不纳入 Git；交接时要同时提供仓库和任务目录，不能只拷目录。
7. 没有物理备份时，“记录基线行数”不等于可恢复备份；DDL/数据变更要有独立授权和恢复路径。
8. review_protocol=2 是显式 opt-in；默认配置没有启用。
9. 编排器不替用户批准业务范围、风险例外或不可逆操作；这些必须由用户确认并留证。

## 13. 检查与验证入口

常用只读入口：

~~~bash
python3 -B delivery/delivery-orchestrate/scripts/delivery.py status --work <工作目录>
python3 -B delivery/delivery-orchestrate/scripts/delivery.py check --work <工作目录>
python3 -B delivery/delivery-orchestrate/scripts/delivery.py next --work <工作目录>
python3 -B delivery/delivery-orchestrate/scripts/delivery.py doctor --work <工作目录>
~~~

维护检查：

~~~bash
python3 -B delivery/delivery-orchestrate/scripts/validate_suite.py \
  --skills-root delivery --output /path/to/evidence
~~~

validate_suite 只证明包结构和确定性回归，不证明真实模型行为、独立审查或实际交付验收。

## 14. 使用原则

- 先读正文，再看 config；先看 journal，再看 status；先看报告，再看 gate。
- 不手改 journal、objects、源代码快照或已批准正文。
- 不用 index 代替状态，不用 status 代替门禁，不用报告存在代替验收。
- 不用“任务大”强制编排，也不用“改动小”绕过既有门禁。
- 质量由专业判断、独立审查、机械检查和实际验收共同保证；任何一项都不能单独宣称交付完成。

## 15. 质量-成本组合的固定顺序

当前 delivery 组合新增以下运行约定：

- design 冻结后才送 plan/mapping/change gate；
- 高风险跨边界改动必须有真实入口可执行合同包；合同产物缺失/不可执行才阻断，红测预期失败不阻断；合同测试作者不能是实现者；
- 功能任务（小/中/大）的 acceptance 必须有独立 verifier；未声明 acceptance 的机械/文档维护才可自检；
- final whole review 在独立验收之后执行，读取完整交付和验收证据；final 审查者排除实现者、历史批次审查者和 verifier；
- unknown 未获有限交付授权时阻塞 close，但不阻塞 final；
- 大型 Git 多任务建议显式设置 review_protocol=2；引擎不隐式默认；
- batch review 只对含代码且达到最小变更/风险阈值的批次单独进行，小批并入相邻批；记录 review yield；
- 试点按 [metrics.md](delivery-orchestrate/references/metrics.md) 记录阶段耗时、请求级 token、first-pass/unknown 和 finding 归因；没有价格表只报 token，不报金额。

这些是当前组合的规则，不改变 journal 状态机；没有相应记录时仍以 journal 和报告为准。
