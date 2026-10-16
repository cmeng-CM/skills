# Delivery 组合准入、变化判断与恢复详细设计

## 1 定位、依据与边界

- 文档版本：1.1，2026-10-16；状态：T-02 详细设计，按 DR-001/DR-002 修订，待定向独立复核；不能据此声称已经实现或通过验证。
- 作者：`contract_runtime`；实际上下文：`/root/contract_runtime`。本文作者不能担任本文的独立设计审查者。
- 授权：用户已批准本目标 `plan.md` 完整执行，质量优先、独立审查和真实组合测试、本地提交、不 push。该批准不授权降低验收要求。
- 依据：本目标 `plan.md` 的 U1—U8、M1—M4、B1—B11、AC-02/05/06/07/08；`evidence/baseline/sources/delivery-orchestrate/` 为修改前的可恢复来源。活动源码已迁到 `delivery/delivery-orchestrate/`。
- 当前事实：旧引擎严格接受契约 1；来源变更和声明范围内内容变更可使结果过期；actor 排除历史实施者；运行回执与验收结论分离；已有单一日志、不可变对象、操作 ID 与关闭恢复机制。
- 增量：增加 v2 强制前置审阅、映射复核、变更分类、范围外变化判断、真实 skill 来源绑定、资源交接和诊断；保留原有任务/审查/验收图，不再创建第二套阶段状态机。
- 排除：自然语言自动批准、身份认证、分布式锁、常驻 worker、自动 push、外部命令回执导入、自动重写旧日志、节点拆分血缘迁移。

五个专业 skill 继续以自己的 Markdown 标准为权威。设计审阅归 design，计划审阅归 plan，实际实现审查归 review；编排器只控制何时需要谁的结论以及如何绑定它。此次补充解释、反例和交接要求，没有改变五项原有独立输入输出的必要条件时，专业语义契约保持 1；编排准入由 1 升为 2。

## 2 版本分发与兼容

### 2.1 三种版本不要混为一谈

| 层次 | 本次处理 |
| --- | --- |
| 日志容器 schema | 继续为 1，保持既有哈希链和对象存储；事件 payload 可依据工作契约分发 |
| 编排请求 schema / contract | v1 请求仍为 1/1；v2 请求为 2/2；不接受混合组合或未知数字 |
| 五项专业契约、skill 修订 | 各自独立；本次专业契约默认 1；实际修订由文件采集，不用手填字符串冒充 |

`init --contract-version 2` 创建 v2 工作，init payload 保存 `contract_version: 2`，该值进入请求摘要。省略参数仍创建 v1，确保现有 CLI 调用不静默改变规则；新编排说明必须明确使用参数 2。无此字段的历史 init 是 v1。`delivery.py` 在验证日志容器后，根据 init 选择 v1/v2 分支；v1 的原 `Engine` 方法、请求严格性和已有测试保持。v2 行为可放 `delivery_v2.py`，通过有限继承复用对象、锁、图检查和原始记录校验；避免复制全部旧引擎。新增模块只属于 orchestrate 包。

v1 工作只能接纳 v1 请求，v2 工作只能接纳 v2 请求；不能用一次 configure 把同一日志升级。旧关闭记录能读取，旧活动流程能继续使用 v1。需要新保证时新建关联 v2 工作：`configure.transition` 引用旧工作相对路径、旧日志末事件哈希和说明，重新审阅/接纳；不自动导入旧运行回执和结果，不把 v1 的通过写成 v2 通过。旧证据可作为专业检查输入，原记录不动。

加载时拒绝未知工作版本、不合法事件/字段、对象损坏和链断裂；错误不创建部分事件。旧 v1 没有新保证，状态输出必须明确 `contract_version: 1`，不渲染成已满足 v2 门禁。

### 2.2 源码目录迁移

包内相对路径和 skill 名称不变；工作目录身份仍由原 project/work 绑定。只有 skill 源路径从根目录变到 `delivery/`，不应视为产品语义变化。历史命令保存原文；旧活动配置确实引用已失效入口时必须重接纳或显式采用可恢复旧来源，不能修改历史命令、事件或摘要。此次不搬迁任何历史任务目录。

## 3 v2 配置与前置准入

### 3.1 configure 的确切扩展

v2 保留原 `actor/plan/design?/authorization/mapping_reason/tasks/reviews/acceptance/reuse?` 语义，不接受手填 `skill_revision` 字段，传入即按未知字段拒绝。真实来源由引擎采集 pins；专业报告可以有可读修订说明，但不是请求字段或来源证明。新增字段如下；除标明可选外均必需。

| 字段 | 结构和含义 |
| --- | --- |
| `source_authors` | 对象：`plan`、`mapping` 为非空 actor 数组；有 design 时还须 `design`；每个 actor 为 `{id, context}`。配置者自动并入 mapping 作者，历史作者按来源种类取并集，不得重新配置删除历史作者来伪造独立性 |
| `requirements` | 非空数组，每项 `{id, source:{path,quote}, tasks:[id], acceptance:[id]}`。id 工作内稳定、唯一；来源须为绑定的计划/设计/授权来源；任务和验收必须存在，列表非空，并核对验收覆盖关联任务 |
| `admission_policy` | `{plan_review: bool, design_review: bool, reason: string, scale: "small"|"large", significant_replan: bool}`。mapping_review 恒为必需，不能设 false。large、significant_replan 任一为真则 plan_review 必须真；design_review 为真时必须有设计来源。设计风险/规模分类由专业判断，脚本只防止显式分类与布尔值矛盾 |
| `change` | `{category:"initial"|"within_grant"|"organization"|"material", reason, previous_config?:op, authorization?:{path,quote}}`。首次只能 initial，后续必须绑定上个 config；material 必须给当前具体授权摘录，且由变更门禁复核 |
| `monitor` | `{roots:[project-relative paths], exclude:[{path,reason}]}`；首版 roots 固定 `["."]`，引擎自动排除 `.git` 和当前 work，当前 work 内来源/报告仍单独逐文件绑定；额外排除只限明确生成物/缓存或其他任务/评测的派生记录目录，须逐项理由并验证不是当前 work 的父目录、产品或 context_scope 的祖先/后代、已绑定真实需求/配置/来源文件的祖先/自身；不能排除整个 `.delivery` 或把真实代码/配置当派生物；不根据 `.gitignore` 自动忽略 |
| `skill_sources` | 非空数组 `{name, root, contract_version}`，root 为读取时可用的绝对规范目录，name 必须是六项合法名字之一且唯一；必须包含 orchestrate，以及该工作实际要接纳的专业类型 |
| `resources` | 可选，默认 `[]`；数组 `{id, mode:"read"|"write", tasks:[id]}`。路径资源 id 使用 `path:<project-relative path>`；其他资源如 `git-index`、`test-db:fixture`、`generated:api` 使用稳定名字 |
| `transition` | 可选；`{from_work, journal_hash, reason}`，只记录有依据的新旧关联，不复用旧状态 |

所有新增源、摘录、报告均用现有安全相对引用并存不可变对象。skill_sources 为外部可读源码目录的专用入口，不能因此放宽普通项目来源/产品路径的防穿越、禁软链约束。安装软链先由调用方解析为真实包根；包内软链拒绝。

requirements 的来源正文是权威；这一清单是准入映射的一部分。脚本能发现清单引用失效、空覆盖、缺 ID，不能知道正文里还有一条被故意漏出清单的要求。独立 mapping_review 必须逐条反查完整正文，明确未映射项为零；真实评测用“正文要求被漏掉但 JSON 自洽”的反例证明这一步有效，不能把 schema 合法当语义通过。

### 3.2 configure 不等于准入通过

configure 写入不可变新配置和初始监测清单，状态为 `admission: pending`。它不立即授权实施接纳、执行命令或收尾。已有旧配置结果只有按原 reuse 校验并通过本次全部新门禁后才可生效；默认不复用。任何重新配置都必须重新做 mapping_review，不能让旧报告通过只替换摘要自动生效。

新 CLI：`gate --work W --input admission/gate-001.json --op gate-001`。请求为：

```json
{
  "schema_version": 2,
  "contract_version": 2,
  "config_operation": "configure-002",
  "kind": "mapping_review",
  "actor": {"id": "independent-reviewer", "context": "fresh-review-context"},
  "report": {"path": ".delivery/DATE-topic/plan-reviews/002.md"},
  "result": "passed",
  "summary": "逐项反查正文、覆盖关系与配置，未发现遗漏或改变含义。",
  "evidence": [{"path": ".delivery/DATE-topic/evidence/mapping-check.md"}]
}
```

kind 为 `plan_review|design_review|mapping_review|change_review`；result 为 `passed|failed|unknown`；报告、摘要和非空 evidence 必需。gate payload 保存配置 op、完整配置摘要、来源对象引用和实际 gate actor；同类当前配置最后一条 gate 生效，不能选择早期 passed 绕过后续 failed。新结论以新操作 ID 留存，历史结论不删除。

- plan_review 排除当前及历史 plan 作者相同 id 或 context；design_review 同理。
- mapping_review 排除当前及历史 plan/design/mapping 作者；可与专业计划审阅在同次真实活动中产生同一份报告，但必须分列两个明确结论、分别登记两个 gate。
- change_review 由 mapping 的同一独立审阅者完成也可；排除提出该配置映射的作者。category 不是 initial 时必需，核查是否在原授权内；material 还须具体变更授权来源。within_grant 与 organization 不机械重复索要用户批准，但必须有判断依据。
- 身份是可追溯声明，不是认证；协调者仍须识别未登记的真实作者。不得通过改名、换 skill 或重建上下文谎报独立性。

gate 的报告、证据、来源任一变化即 stale。当前必需 gate 未全部 passed，所有 `record`、`run`、`close` 都拒绝；status/next/gate/configure/来源恢复等诊断操作仍可用。`limited` 也不能豁免这些前置门禁。

## 4 范围外变化与定向失效

### 4.1 清单与差异

configure 对监测范围生成文件清单：相对路径、类型、内容 SHA-256、可执行位；目录存在性、删除与新增均可比较。监测清单只保存摘要，不将整个项目再次复制入对象库。符号链接只记录链接文本和类型，不跟随；相关产品范围仍沿用原来拒绝软链的规则。特殊文件（FIFO、设备、socket 等）只 lstat 保存类型/模式等元数据，绝不打开读取；权限错误同样收集路径级 unreadable 诊断，不跟链接、不等待特殊文件、不因单个条目阻塞扫描。`unsupported_entries` 或 unreadable 未处置时阻止执行准入；可删除/替换为可监测普通文件，或确认是无关派生物后 configure 加入有理由且通过上述重叠检查的排除。impact 的 unrelated 不能代替有效监测或永久豁免不支持条目；status/next/configure 等恢复入口可用。

每次 status/next/record/run/close 都重新比较监测范围；变更发生在已声明 task.scope 或 context_scope 内，沿用原内容指纹失效。发生在其他文件则生成 `unassessed_changes`，包含 before/after 与稳定 change_set_hash。未判断时阻止执行类准入和收尾。初始既有脏文件进入基线，不把它们误认成本流程新变更。

新 CLI：`impact --work W --input ... --op ...`；输入包含版本、config_operation、actor、`change_set_hash`、report、非空 evidence、`decisions` 数组。每条 decision 为 `{paths:[...], effect:"unrelated"|"related", targets:[{kind,id}], reason}`。kind 使用原 `implementation|review|verification`。必须精确覆盖本次所有范围外变化，每个路径一次，禁止未知或遗漏路径；related 至少一个现有目标，unrelated 的 targets 必须为空。引擎在锁内重算清单并校验摘要，变化又发生时拒绝过期判断。

### 4.2 失效不可逆转为“原来通过”

impact 事件绑定该变化集、判断来源、判定人和完整新清单。related 路径加入目标的有效 context；该目标当前结果及图上依赖它的结果失效，整体审查覆盖受影响任务时也失效。事件保存确切 `invalidated_operations`；后续无关变化或新 passed 判断不能取消历史失效标记，只能用新的专业活动和新 record 重新取得通过。新的记录绑定新增 context 当前内容。

unrelated 只推进监测基线，不失效无关结果；判断报告或证据变化会撤回该判断的有效性，对应变化重新待判断。再次编辑已判断文件会形成新的变化集，需要新判断，不能复用旧 reason。

声明范围内的正常产品修改不能被 impact 标成 unrelated 来绕过原指纹；scope/context 的变化必须 configure 重接纳。影响范围是否正确由专业审阅判断，脚本只落实已判断的作用范围及依赖传播。不会默认全放行，也不会默认全项目重验。

## 5 实际 skill 来源、修订变化与恢复

### 5.1 采集规则

读取每个 skill_sources 包根内普通文件，排除 `.git`、`__pycache__`、`.DS_Store` 和 Python 字节码；按相对路径排序，保存文件路径、内容 SHA、可执行位和对象内容，合成树摘要。必须有 SKILL.md；name 与 frontmatter 一致，专业声明契约与输入一致。根路径只记录来源位置，树摘要不包含机器绝对路径，因此原样搬迁可识别为路径变化。

配置保存 `skill_pins`，每个 pin 包含 name、contract_version、tree_hash、source_root 和文件对象清单。record/gate 保存活动实际使用的 pin；客户端声明不能替代采集；报告仍可说明使用方式和上下文。

**实际执行包绑定（DR-002）**：v2 在进程内以入口 `delivery.py` 的实际 `__file__` 定位包根，同时获取实际加载的 v2 模块 `__file__`；二者必须位于同一真实 orchestrate 包，且模块相对路径、文件字节与该包采集清单一致。configure 的 orchestrate root 必须是这个执行包根，拒绝“运行 B、请求声明 A”，即使 A 合法、名字相同也不接受。此后执行类准入、gate 和 source-update 重新采集实际执行包，并比较有效 orchestrate pin 的树摘要；不以 sys.argv、当前目录或请求 root 代替。其他专业包按其声明路径采集，实际是否按其指令执行仍属专业活动证据边界。

合法原样迁移/恢复：在新真实目录执行该包的 delivery.py，全部实际模块来自同包，树摘要与原 pin 相同；路径不同但规则相同，可通过 path_only 重绑定。若执行包字节不同，只允许 status/check/next/source 等诊断以及专门 source-update 兼容接纳入口；普通 record/run/close 拒绝。source-update 的 orchestrate new_root 必须正是当前实际执行包，兼容判断绑定旧 pin 和新执行树，不允许运行第三份规则。v1 仍按其原契约续接，不追加事后 pin 保证；输出必须显式标明它缺少 v2 执行来源保证。

`source --work W` 输出当前 pin、当前实际目录摘要及差异；`source --work W --restore NAME --destination PROJECT_RELATIVE_DIR` 只向当前 work 下新的空目录恢复该 pin 普通文件，拒绝覆盖、软链及工作目录外写入。恢复是导出可恢复来源，不直接执行脚本，不改变 pin 或日志。命令可用恢复后的旧编排包继续工作。

### 5.2 更新处理

恢复时逐项检查实际来源。相同树摘要的纯路径变化用 `source-update` 事件重新绑定来源根，保留原 pin；不要求专业报告重做。不相同的修订形成 `skill_drift`：阻止使用该新来源接纳对应活动；orchestrate 漂移阻止所有执行类准入及 close。旧报告和旧 close 的历史事实仍按原 pin 解释，不因磁盘 skill 更新倒写成错误。

`source-update --work W --input ... --op ...` 请求包含版本、config_operation、name、old_tree_hash、new_root、decision、actor、report、evidence、reason、affected_targets。decision 为 `path_only|compatible|incompatible`。

- path_only：树摘要必须完全相同，affected_targets 为空；独立性不新增要求。
- compatible：契约相同且受引擎支持；独立复核报告明确输入输出、质量门槛和行为变化，不能只说“版本兼容”。报告 actor 不能是本次配置 mapping 作者，涉及编排器时也不能是本次实现作者。引擎真实采集新根并保存新 pin、兼容判断和可恢复对象；affected_targets 为明确需要重新确认的目标，按第 4 章失效规则处理，可为空但必须说明依据。已经产生的旧报告保持各自原 pin。
- incompatible：保存受阻事实，不切换活动 pin；source/诊断提示使用原来源继续，或新建关联工作重新接纳。未知专业契约直接拒绝启用，不把报告文字当兼容适配器。

不做自动原地升级；不因 HEAD 没变就忽略未提交源码变化。未恢复原来源、未有有效兼容决定，不能用新指令接纳结果。来源更新事件的报告/证据必须维持有效，失效时相关新来源恢复待确认。专业 skill 单独调用不依赖这套命令，仍自行在正式文档记录实际修订。

## 6 上下文、资源交接与修复诊断

### 6.1 任务简报是派生视图

新增 `brief --work W --kind implementation|review|verification --target ID [--format markdown|json]`。从同一状态对象生成，包含目标/边界、需求及原文路径、完整必需约束引用、前置门禁、相关任务与验收、必读来源、当前 pin、作者排除、可写范围、资源、报告位置、现有问题和下一步。

不复制成为另一份可编辑任务真源，不按字数裁掉必需约束；资料太多时列出完整索引并提示分段读取。报告写入者仍负责阅读来源全文。brief 缺配置时输出 `configure required` 和恢复入口，不能生成空白任务假装可执行。

status/next 保留原结构并新增 `contract_version/admission/skill_drift/unassessed_changes/resources/diagnostics`。诊断统一为 `{code, target?, sources:[], evidence_needed:[], next_action}`；Markdown 与 JSON 使用同一对象，不能重复判定。check 继续只证明机械完整性。

### 6.2 资源协调

新增 `resource --work W --input ... --op ...`，输入为版本、actor、action=`claim|release`、非空 resources 数组和 reason。claim 追加持久事件；同一资源多 read 可并存，有 write 则冲突；路径祖先与子路径相交也冲突。release 只能释放自己持有的资源，不能让旁人强制覆盖；异常持有者需同身份核查进程和副作用后明确释放并记录。日志锁只保护本工作，资源协议不充当系统级互斥或跨项目认证。

任务 scope 默认视为该实施的写资源；共享数据库、index、生成物由计划额外声明。执行/正式接纳时检查覆盖活动所需资源属于 actor、没有冲突。run 可在内部保留其命令资源直到完成；崩溃留下 run-started 与资源占用，恢复时必须核查，不能自动重跑/释放。资源释放不能将未知运行变成已完成。资源模式固定如下，避免正常独立审查或 close 自锁：

| 活动 | 所需模式与交接 |
| --- | --- |
| implementation 接纳 | 该任务 scope 为 write；计划额外资源按声明模式；实施者持有后接纳，结束明确 release |
| review、inspection/manual verification | 覆盖产品及 context 为 read；不继承实施者的 write 要求，自己 claim read，允许多个只读者并行 |
| command run | 被测产品/context 默认为 read；计划声明该命令会写的共享测试库/生成物等按 write；run 期间持有，已完成可明确释放 |
| close | 不要求 coordinator 拥有实施者/审查者的旧锁；核对没有未交还的相关 write、无未知运行和有效快照。可与仍有效的只读 claim 共存，不创建永久 claim |

任务资源中的 write 对实施活动适用；专业只读活动默认降为 read。确有写副作用的验证命令必须在计划明确资源及写权限，不能以只读审查身份改产品。所有资源释放事件仍保留，作者独立性不因 release 消失。

Git 只读检测可采集初始暂存条目及内容摘要，存在 Git 时资源说明必须包含 `git-index`；非 Git 项目不依赖 Git。引擎不自动 commit，协调者提交前比较保护清单与实际暂存，逐文件纳入授权内容；不自动全暂存、清空或覆盖既有 index。真实评测包含用户已有 staged 文件，验证其字节和暂存内容保留。

### 6.3 修复收敛记录

新增 `attempt --work W --input ... --op ...`，保存版本、actor、config_operation、target、`failure_key`、`facts:[source references]`、`strategy`、`outcome:"failed"|"changed"|"unknown"`、report。failure_key 是稳定根因/问题 ID 的判断，不由脚本自动猜自然语言相似性。

同一目标和 failure_key 连续两次失败，且事实对象摘要集合与 strategy 均未变化时，state 加 `diagnosis_required`。继续实施/运行前需新 attempt 明确新事实或新策略并给实际证据；仅改策略文字仍须协调者/独立审阅核查真实性，脚本不证明策略有效。该诊断不关闭问题、不豁免审查、不将失败变通过。问题关闭仍由原 owner 的证据化 resolutions 完成，允许不同但满足 required property 的实现。

### 6.4 未完成运行的核查与重试接纳（DR-001）

`run-started` 没有对应 run 完成事件时，旧运行永远保留 `incomplete/unknown`，不伪造退出码或补造成功回执。未有效解除时，它阻止同验收的新 run，以及覆盖其任务或依赖该验收的 record；close 也阻止。无关任务可以继续；release 任何资源都不能解除该阻塞。

新增 `resolve-run --work W --input ... --op ...`，产生 `run-resolution` 事件。输入严格包含版本、actor、`run_operation`、report、非空 evidence、`decision:"safe_to_retry"|"unresolved"`、reason。必须引用真实未完成 run-started；safe_to_retry 的专业报告必须查明命令/子进程已停止、实际副作用和测试数据是否需要隔离/清理，以及为何本次新执行安全。脚本不证明这些自然语言事实，但保存判断人、原始证据、原 run 身份、当前配置/来源与相关产品快照、监测变化集；无实际证据或 run 未知时拒绝。

最新有效 safe_to_retry 仅允许使用**新的** run op 重新执行；旧 op 仍返回旧 run-started，不改历史。新 run payload 记录 `recovery_operation`，指向解除事件；新的验证结论只能用新真实 run。仅有 safe_to_retry 不足以 close：必须有基于该解除的合法替代新 run，且新 verification verdict 通过并满足其余门禁，close/后续 record 才可忽略被这条有效替代链覆盖的旧 unknown 阻塞。旧运行的历史状态仍为 incomplete/unknown；替代链或解除依据失效时，旧 unknown 再次参与阻塞。resolve-run 自身不释放旧资源，持有者核查后另行 release。unresolved 只记录仍受阻，不能解除门禁。

解除报告/证据、配置或相关产品在新运行前改变，解除变 stale，重新阻止；新 run 及依赖该解除的结果也必须追溯有效解除，不能靠稍后删除证据保持通过。已经合法完成的新 run 无须再重做旧运行核查，但其接纳链内的解除依据仍需完整且当前。对无实际进程可查询的崩溃，报告必须说明剩余不确定性；不能据进程不可见推断没有副作用。

## 7 事件、操作顺序和阻断语义

新增持久事件仅为 `gate`、`impact`、`source-update`、`resource`、`attempt`、`run-resolution`；configure/record/run-started/run/close/reopen 沿用原类别。每个新增请求有 schema_version/contract_version、actor、op，严格字段、真实源绑定、对象完整性检查和同请求重试幂等；不同请求复用 op 拒绝。只读 source/brief 不落事件。

`assert_v2_ready(activity,target)` 是所有 record/run/close 共用入口，至少核对：活动未关闭、配置来源当前、必需 gate 当前通过、相关 skill pin 可用、无待判断范围外变化、没有适用诊断阻塞、无未核查未知运行、资源约束满足；然后调用原先依赖、独立性、问题、回执和产品指纹校验。close 额外核对所有目标与新门禁，limited 无权跳过前置要求。status 使用同一计算生成阻塞原因。

| 情况 | 结果 |
| --- | --- |
| 缺审阅/证据、尚无 verdict、未知运行副作用 | pending/unknown，拒绝需通过它的动作 |
| 已知失败/阻断发现 | failed/blocked，保留失败历史，修复后新记录 |
| 来源/对象版本变化 | stale，定位变更来源和重新接纳入口 |
| 日志损坏、路径越界、未知 schema/字段、过期 change_set | 命令错误且非零；不写“成功”事件 |
| run-started 后进程中断 | 同 op 重试返回未完成事件，不再运行；仅 release 仍拒绝，新 op 必须先有有效 run-resolution 和资源交接 |
| close 后新事实 | 显式 reopen；旧 close 不覆盖；真正新目标建新 work |

先持久化 run-started，再释放日志锁执行命令，结束重新取锁确认来源/监测清单/资源；执行期间变化不能产生有效通过回执。不得为了新门禁放宽旧 run 的前后产品相同、命令成功与逐项语义验收分离的限制。

## 8 实施切片与验证

1. T-05：版本路由、v2 configure 和 gate、requirements/source_authors/change 校验；先证明缺 gate 连 record/run/limited close 都进不去，再做正向完整流。
2. T-06：监测清单、impact 绑定、失效操作集合及 context 扩展；通过相关/无关变化、判断后再编辑和 pass→fail→pass 案例。
3. T-07：实际包采集、pin、source 导出、更新判断；原 v1 回归保持原规则，恢复原包与纯迁移正例。
4. T-08：同源诊断/brief、资源 claim/release 与 attempt；恢复不依赖聊天/agent 存活，异常运行不盲重试。

共享引擎只由一个作者顺序修改；专业内容作者及真实行为评测作者按明确接口并行，不共同写相同文件。新增实现测试进入 orchestrate/tests；真实 agent case 与 harness 单独运行，不将 unittest 数量当成整体质量证明。

| 验证范围 | 必须有的反例与正例 | 证明限度 |
| --- | --- | --- |
| v1 兼容 | 原全部回归；历史已关/活动续接；CLI 原默认；未知版本拒绝 | 证明既定接口与样本，不证明所有自然语言规则 |
| 前置准入 | 缺必需审阅、同 id/context、删历史作者、后续 failed、report 修改、漏映射要求；单次专业+映射分别登记；合法局部变更不重复问用户 | 脚本反例加独立语义评测，不能只测字段 |
| 变化影响 | scope 外共享配置相关→定向失效；无关→复用；旧判断 hash 过期；判断证据变；新文件/删除/可执行位/链接类型；不可把 scope 内变化标无关 | 监测只覆盖本地声明范围，外部环境仍需专业证据 |
| skill 更新 | 同路径内容变但 HEAD 未变；相同树迁移；执行包 B 声明 A 拒绝、混载模块拒绝、原样恢复旧包可继续；缺对象；未知契约；兼容/不兼容；新来源报告过期；恢复后真实续接 | 摘要证明内容，不证明改动语义兼容 |
| 资源与恢复 | read 并行/write 冲突/祖先路径冲突；异常持有不自动释放；已有 staged 文件保护；init 未配置；run 完成未 verdict；run-started 未回执；仅 release 不能重试、有证据解除后新 op、解除依据改变再阻塞；重复失败需新诊断 | 非系统沙箱，未知参与者必须由协调者识别 |
| 完整组合 | design→plan→前置独立 review+mapping→实施→独立实现审查→真实验证→close；故障修复、范围外变化、重启恢复、新 skill 修订 | 原始轨迹、文件及独立评分留存；未跑就写 not-run |

所有专业产物为可读 Markdown；机器接纳 JSON 保留字段语义和实际证据路径；状态、brief、评测汇总提供同源可读视图。最终交付需独立实现审查与真实组合测试，本文及机械检查不能替代它们。

## 9 风险与需报告事项

- 规模/风险/授权范围、遗漏正文要求、专业影响和兼容性判断不能由摘要自动证明；用独立审阅和负例真实评测覆盖，不追加伪认证字段。
- 项目全树监测可能有成本；首版先测代表性工作区，保留明确生成物排除和一次统一采集复用，不以性能为由静默忽略未知文件。
- 不支持旧日志原地升级，换取历史和活动 v1 不被改写；需要新保证采用关联 v2 工作重新接纳，这是本次计划 M4 的具体实现。
- 当前没有需要扩展用户授权的新范围决定。若实现发现必须削弱门禁、改变独立输入输出、覆盖真实安装目录或无法完成真实评测，应保留事实并报告，不自行宣称已完成。

修订记录：v1.1 按独立检查 DR-001 增加未知运行解除事件与证据有效性，按 DR-002 绑定实际加载执行包；同时明确 v2 不接收 skill_revision、监测排除/特殊条目恢复及各活动资源模式。待同一独立审阅者定向复核，未写运行时源码。
