# 本地编排准入与恢复 API（契约 2）

v2 是显式选择的新工作契约。Python 标准库脚本管理来源、门禁、证据及恢复，不调用模型，也不执行 Git 提交或 push。Markdown 是需求和专业判断真源；接纳 JSON 只绑定已读取的那一版来源。字段合法、摘要一致或退出码 0 都不是语义通过。

## 1 版本、目录与运行入口

```bash
python3 -B /绝对路径/skills/delivery/delivery-orchestrate/scripts/delivery.py init \
  --project /项目绝对路径 --work /项目绝对路径/.delivery/2026-10-16-settings \
  --title '设置保存与恢复' --contract-version 2 --op init-001
```

后文以 `CLI` 指以上真实 `delivery.py` 路径、`W` 指已有目标工作目录。每个写命令必须使用唯一 `--op`；同 op 同完整请求重试返回原事件，不再执行，改请求却沿用 op 拒绝。

- 省略 init 的 contract-version 仍创建 v1，保护已有调用。v1 请求 1/1、v2 请求 2/2；未知或混用版本拒绝。
- 日志容器 schema 保持 1，init payload 标识工作契约；不能修改日志字段把 v1 改成 v2。
- 活动源码在 `delivery/`，任务材料在 `.delivery/日期-主题/`。已有工作目录不搬迁，历史来源、回执和哈希链不改写。
- runtime/journal.json 是唯一状态真源；runtime/objects 保存来源及证据不可变对象。状态、brief、Markdown 是派生视图。
- 普通 path、scope、context_scope 均相对项目根，拒绝绝对路径、`..`、软链和 runtime/.git 引用。skill_sources 的绝对真实包根为专用读取入口，不放宽普通项目路径。
- 同一工作只有一个协调者接纳状态，参与者按资源分工。actor 包含稳定 `id` 和本次实际 `context`，不改名或借旧上下文伪造独立性。

## 2 配置是待准入快照

```bash
python3 -B CLI configure --work W --input /项目路径/.delivery/日期-主题/admission/config-001.json --op config-001
```

最小完整示例（替换路径、来源与身份后使用，示例摘录不是其他任务授权）：

```json
{
  "schema_version": 2,
  "contract_version": 2,
  "actor": {"id": "coordinator", "context": "main-session"},
  "plan": {"path": ".delivery/2026-10-16-settings/plan.md", "quote": "T1 保存设置并在重启后恢复"},
  "authorization": {"path": ".delivery/2026-10-16-settings/decisions.md", "quote": "可以，按计划直接执行", "scope": "本次设置保存与恢复，本地提交不 push"},
  "mapping_reason": "读取完整计划，将保存与实际消费者重启恢复映射到 T1、R1、A1。",
  "tasks": [{"id": "T1", "scope": ["src/settings", "tests/settings"], "depends": []}],
  "reviews": [{"id": "R1", "tasks": ["T1"], "whole": true}],
  "acceptance": [{"id": "A1", "tasks": ["T1"], "required": true, "method": "command", "command": ["python3", "-B", "-m", "unittest", "discover", "-s", "tests/settings"], "criteria": "实际消费者重新启动后恢复最后成功保存值，损坏数据按方案处理。", "environment": "隔离测试数据、本次项目环境", "waivable": false}],
  "source_authors": {"plan": [{"id": "planner", "context": "planning-session"}], "mapping": [{"id": "coordinator", "context": "main-session"}]},
  "requirements": [{"id": "REQ1", "source": {"path": ".delivery/2026-10-16-settings/plan.md", "quote": "重启后恢复"}, "tasks": ["T1"], "acceptance": ["A1"]}],
  "admission_policy": {"plan_review": true, "design_review": false, "reason": "大任务首次实施，需要独立计划审阅；无新高风险设计。", "scale": "large", "significant_replan": false},
  "change": {"category": "initial", "reason": "首次接纳已授权目标。"},
  "monitor": {"roots": ["."], "exclude": []},
  "skill_sources": [
    {"name": "delivery-orchestrate", "root": "/实际路径/skills/delivery/delivery-orchestrate", "contract_version": 2},
    {"name": "delivery-design", "root": "/实际路径/skills/delivery/delivery-design", "contract_version": 1},
    {"name": "delivery-plan", "root": "/实际路径/skills/delivery/delivery-plan", "contract_version": 1},
    {"name": "delivery-implement", "root": "/实际路径/skills/delivery/delivery-implement", "contract_version": 1},
    {"name": "delivery-review", "root": "/实际路径/skills/delivery/delivery-review", "contract_version": 1},
    {"name": "delivery-verify", "root": "/实际路径/skills/delivery/delivery-verify", "contract_version": 1}
  ],
  "resources": []
}
```

schema 严格，不接受手填 skill_revision。五项专业报告可用文字说明实际修订，但 v2 真实采集源文件及可执行位、树摘要和可恢复对象。专业包的 references/delivery-contract.md 与编排 contracts.md 保留“当前版本为 **数字**”的可读契约声明，采集时核对实际声明；未知专业契约拒绝启用。

可选 design 为 `{path,quote}`；有设计须 source_authors.design 和设计 pin，风险要求独立设计审阅时 design_review 设 true。plan_review/design_review/significant_replan 必须为 bool。large 或 significant_replan 强制 plan_review。mapping_review 恒为必需，不能关掉。

requirements 逐条绑定来源摘录、任务和验收；它不是自动需求提取器。结构自洽仍可能漏正文，因此独立映射审阅必须反查全文。每任务仍须审查和必需验收、整体审查覆盖所有任务，三类节点联合检查依赖环，沿用 [v1 图与验收规则](runtime-api.md)。

monitor.roots 首版固定 `["."]`。自动排除 `.git` 和当前 work，但 work 内专业来源/报告仍单独绑定；不能一概排除 `.delivery`。额外 exclude 是 `{path,reason}` 数组，仅限明确缓存/生成物或其他隔离任务派生材料，不得重叠真实产品、context 或需求来源，也不得包含当前 work 的父目录。不使用 gitignore 静默忽略未知文件。

## 3 独立门禁之后才能推进

configure 成功只证明接纳结构存在；record、run、close（包括 limited）在当前必需 gate 未通过时全部拒绝。调用：

```bash
python3 -B CLI gate --work W --input /项目路径/.delivery/日期-主题/admission/gate-001.json --op gate-plan-001
```

```json
{
  "schema_version": 2,
  "contract_version": 2,
  "config_operation": "config-001",
  "kind": "plan_review",
  "actor": {"id": "independent-planner-reviewer", "context": "fresh-plan-review"},
  "report": {"path": ".delivery/2026-10-16-settings/plan-reviews/001.md"},
  "result": "passed",
  "summary": "核查目标覆盖、可实施性、联合依赖、阶段消费者及验证归属，无阻断遗漏。",
  "evidence": [{"path": ".delivery/2026-10-16-settings/evidence/plan-review.md"}]
}
```

kind 为 plan_review/design_review/mapping_review/change_review，result 为 passed/failed/unknown。相同 kind 最新记录生效，不能绕过后续失败选早期通过。报告、证据、来源变化令结论 stale。gate 保存的实际编排 pin，以及 plan/design 审阅对应专业 pin，必须仍属于有效来源链；兼容证据失效后，即使恢复旧包，也不能把新版生成的审阅当成旧版审阅。补齐有效兼容链或按有效来源重新审阅才可继续。无关专业包的 pin 不使该 gate 过期。

plan_review 排除所有历史 plan 作者；design_review 同理；mapping_review 排除所有历史 design/plan/mapping 作者；change_review 排除 mapping 作者。相同 id **或** context 都不独立。配置者自动加入 mapping 作者；重新配置不会删除原作者。专业计划和映射可同次独立检查、共用一份有分项结论的报告，但须分别登记两个 gate，实施 review 不接管它们。

重配置必须 change.previous_config 指向上一配置，category 为 within_grant/organization/material，并需独立 change_review。前两者不机械重问用户，但报告要核查原授权；material 需具体新授权 `{path,quote}`。已知结构性弱化（取消必需验收、放开 waivable、把 command 改成其他方法）不能标局部组织调整，必须 material 加具体授权。自然语言是否真的降低要求仍需独立审阅。

旧结果默认不进入新配置；显式 reuse 除原始记录/目标结构/证据/产物不变外，v2 还核对紧邻上一配置里的真实 latest rebound 是否当前有效。不得回溯更早原事件绕过上一配置的 impact 失效；来源文字合法细化仍允许 ignore_config 的明确重接纳。原专业 pin 与恢复链按实际原配置追溯，本次新 gate 仍需满足。上一配置已知相关 context 保守继承，并纳入排除重叠检查；不自动迁移其 owner，需保留稳定目标或关联新工作。默认未知运行先在原配置核查恢复；来源已变且需要新计划时，显式使用第 7 节恢复子契约 2 的调查与 recovery_transfers。不能用重配置抹掉未完成副作用。

## 4 资源、实施、实现审查与验证

每项专业活动先读取 brief 和全文来源，再明确 claim。路径资源的祖先/子路径也会冲突。资源是本工作内合作协议，不能约束未登记外部进程。

```bash
python3 -B CLI brief --work W --kind implementation --target T1 --format markdown
python3 -B CLI resource --work W --input /项目路径/.delivery/日期-主题/admission/resource-001.json --op claim-T1
```

```json
{
  "schema_version": 2,
  "contract_version": 2,
  "actor": {"id": "builder", "context": "implementation-session"},
  "action": "claim",
  "resources": [{"id": "path:src/settings", "mode": "write"}, {"id": "path:tests/settings", "mode": "write"}],
  "reason": "本轮实施写范围已分配，结束后明确交还。"
}
```

action 为 claim/release；read 可并行，任一 write 冲突拒绝。返回同稳定 id 的新恢复 context 可明确释放旧持有资源；不能代其他 id 强制释放。释放不证明未知命令安全。计划 resources 可补 `{id,mode,tasks}`，如共享测试库或 git-index。

- implementation：覆盖 scope 默认 write；按计划额外资源。
- review、inspection/manual verification：覆盖产品/context 默认 read，不要求继承实施者写锁；多读者可并存。
- command run：产品/context 默认 read，计划明确会写的共享资源按 write；命令结束后明确 release。
- close：不要求协调者持有前面作者的锁，但所有 write 已交还；正常 read claim 可共存。

record 格式沿用 v1 的 kind/target/actor/report/result/summary/evidence 与可选 issues/resolutions/run_operation/confirmation/supersedes/reason，版本改 2/2，**去掉 skill_revision**。引擎自动绑定实际专业 pin 和执行 pin。实施不代替审查，审查排除覆盖任务全部历史实施者，问题只能原 owner 凭证据关闭。

```bash
python3 -B CLI record --work W --input /项目路径/.delivery/日期-主题/admission/implementation-001.json --op impl-T1-001
python3 -B CLI run --work W --acceptance A1 --actor verifier --context verification-session --timeout 120 --op run-A1-001
```

run 先持久 run-started，再释放日志锁执行真实 argv（非 shell），结束重新核对产品、配置、监测、资源和实际来源。超时保留输出并杀进程组。命令不是沙箱，先评估副作用。退出 0 仍须验证者报告和新的 verification record；有后续 run 时旧 verdict 过期，不能挑较早成功回执绕过后来的失败。manual 逐项真实人工确认与 limited 的严格例外规则沿用 v1，不新增快捷不适用或未知豁免。

存在 Git 时采集初始已暂存条目内容摘要；后续执行准入检查它们未被替换。非 Git 不依赖 Git。脚本不替用户提交；协调者仍需按授权逐文件提交、保护既有 index，不使用全量暂存或 push。

## 5 范围外变化的明确判断

status/next 显示 unassessed_changes 与 change_set_hash。声明范围内沿用内容指纹；范围外改变先阻止正式推进，不直接全放行或全重验。

```bash
python3 -B CLI impact --work W --input /项目路径/.delivery/日期-主题/admission/impact-001.json --op impact-001
```

请求包含版本、actor、config_operation、当前 change_set_hash、report、非空 evidence、decisions。每条 decision：

```json
{"paths": ["shared/settings.cfg"], "effect": "related", "targets": [{"kind": "implementation", "id": "T1"}], "reason": "真实消费者读取该共享配置，改变恢复行为。"}
```

所有外部变更路径恰好覆盖一次。related 必须指定目标；unrelated 的 targets 必须空。锁内重新比较，变化再次发生拒绝旧判断。相关路径加入有效 context，失效相应结果及依赖范围，留存确切失效 op；不能用后续无关判断撤回历史失效。新专业活动和 record 才可恢复通过。

判断报告/证据变会重新待判断；新完整判断可从当前有效 baseline 重新接纳，事件绑定 baseline_hash。仅覆盖失效祖先之后增量的旧后代不能越过缺口；历史失效 op 不复活，已判相关的 context 在本次配置内保守保留。后续再编辑同路径也需要新判断。特殊文件不打开、不跟 symlink；unsupported/unreadable 显示具体路径并阻塞，删除/替换或配置合法派生物排除后可恢复；unrelated 不能永久豁免无法监测的真实输入。

## 6 skill 来源更新与可恢复副本

```bash
python3 -B CLI source --work W --format markdown
python3 -B CLI source --work W --restore delivery-orchestrate --destination .delivery/日期-主题/pinned-orchestrate
```

恢复只写 work 下新的目录，拒绝覆盖或进入 runtime，不执行导出的脚本。使用副本中的 delivery.py 可按原包继续；入口及实际加载模块必须同包，当前文件也必须与进程加载时字节一致。运行 B 不能配置声明 A。原样迁移树摘要不变，路径可不同。

source-update 输入：版本、actor、config_operation、name、old_tree_hash、new_root、decision、report、非空 evidence、reason、affected_targets。decision：

| 值 | 条件与结果 |
| --- | --- |
| path_only | 新旧树完全相同，affected_targets 必须空，仅重新绑定位置 |
| compatible | 支持且相同契约；实际差异和行为经独立核查，actor 不得是配置 mapping 作者，编排更新还排除历史实施者；采集新 pin，明确受影响目标定向失效 |
| incompatible | 保存阻塞事实，不切换活动 pin；恢复旧规则或关联新工作重新接纳 |

orchestrate 的 new_root 必须为当前实际执行包，不能由第三份规则声称切换到另一份。兼容判断的证据过期使其新来源和对应新记录待确认；可从当前有效旧 pin 提交新的完整独立复核恢复。只有经有效证据连接的旧 pin→新 pin 链生效，依赖失效祖先的增量后代不能绕过缺口。旧报告仍按原 pin 解释。未知专业契约直接拒绝启用。四种版本（skill 修订、语义契约、文档版本、产品版本）分别保留，源文件摘要不证明语义兼容。

source-update 是来源评估，可以在 plan/authorization 已变化时绑定当前不可变 config_operation，先独立接纳实际修复包，再调查中断。它不接纳新计划、不执行命令、不解除业务准入门禁；独立性、真实执行包和原 pin 检查仍适用。

## 7 未知运行、持续失败与恢复

run-started 没有完成回执时，同 op 不重跑；新 op 也不能仅因释放资源而运行。相关 record/run 和 close 受阻，无关任务可继续。

```bash
python3 -B CLI resolve-run --work W --input /项目路径/.delivery/日期-主题/admission/resolve-run-001.json --op investigate-run-001
```

输入：版本、actor、run_operation、report、非空 evidence、decision=`safe_to_retry|unresolved`、reason。报告必须实际调查进程、子进程、副作用和隔离/清理必要性。safe_to_retry 保存调查人、来源与产品快照，只允许新 op 真实重跑；旧 run 永远仍 unknown。调查证据或相关版本变则解除过期重新阻塞。

仅 safe_to_retry 不能 close；必须有绑定 recovery_operation 的替代真实 run、通过的新 verification verdict 及其余门禁，才忽略旧 unknown 的阻塞。旧事实不改写；解除/替代链失效重新阻塞。替代回执严格归原 acceptance owner；共享任务的其他验收虽受副作用条件约束，不能抢走它的恢复身份。连续中断时，新真实 run 用 recovery_operations 绑定该 owner 的全部有效调查，保留单数末项供旧记录读取；每个根调查证据都要有效，不能只保留最后一次解除。合法重配置按解除所属配置解释已完成历史链，计划/产品后续合法变化不制造新的历史未知；调查与 verdict 原始证据、来源链仍必须有效。真正证据过期允许在当前配置重新调查并产生新的替代运行；重配置必须保留历史未知运行的验收 owner 和任务覆盖，不能孤立其恢复入口。原资源另行交还，不能拿过程核查伪造成功回执。

### 恢复子契约 2：旧命令不再适用时转接当前计划

以上未声明 recovery_contract_version 的请求仍是恢复子契约 1，不静默改变其含义。显式在 resolve-run 输入增加 `recovery_contract_version: 2`，decision 改为 `safe_to_replan|unresolved`，进入子契约 2。顶层请求仍为 schema_version/contract_version 2/2；此处版本只控制恢复协议。新记录类型 `run-investigation` 会被旧引擎拒绝，不能用旧引擎忽略转接后继续操作。活动包更新仍须 source-update 接纳，不直接改 init/journal。

来源 stale 时可以保存该调查，因为调查绑定旧 run 和不可变配置、观察当前现场，而不是宣布旧授权仍有效。先确认原进程及子进程已停止、副作用已查清、必要隔离/处置完成；实际报告和非空 evidence 必填。`safe_to_replan` 仅表示可以重新规划，不能重放旧命令或收尾。报告保存当前产品快照、全树观察摘要及实际编排 pin；未支持的现场条目不能声明 safe。调查不确定使用 unresolved。

准备新计划和真实授权后调查，在 configure 中显式承接所有尚未完成的责任：

```json
"recovery_transfers": [
  {"recovery_contract_version": 2, "run_operation": "interrupted-A1", "investigation_operation": "investigate-A1-002"}
]
```

每项必须引用紧邻旧配置下对原 run 的最新、当前有效 safe_to_replan 调查；遗漏、重复、失效或 unresolved 拒绝。验收 owner 和原任务覆盖保留，新方法仍为 command，不取消必需性或放宽例外。新配置仍需 plan/mapping/change 等适用独立 gate；改变或撤销命令必须对应真实授权并接受变更审阅。验收改名、拆分及取消责任不在此最小转接接口支持范围，不能用换 ID 绕过。

新配置可组织授权内工作；新的 run 自动绑定原调查，执行新配置的当前命令，并须取得当前 passed verification 才允许 close。旧 run 永远仍 incomplete/unknown；调查或新配置存在都不算通过。调查证据、编排来源或相关现场变化会阻塞后续执行，需要按当前现场重新调查并明确重新转接，不能引用过期调查。已经完成有效替代和验收的历史链不因后来合法重规划重复要求旧命令，但其真实证据仍须有效。失败验证、缺少 verdict、其他 owner 的通过和 limited 都不能替代当前责任的通过。

attempt 命令保存版本、actor、config_operation、target=`{kind,id}`、failure_key、非空 facts 引用、strategy、outcome=`failed|changed|unknown`、report。相同根因连续两次失败且事实摘要/策略不变，diagnosis_required 阻止原样循环；新事实/策略应有实质证据，不能只改文字、自动豁免或关闭问题。

status/check/next/brief/source 均提供可追溯恢复入口；只读视图可选 `--format markdown|json`，同一结果对象生成。init 后未配置明确提示 configure required；日志或对象损坏 fail closed，不删失败事件或重算哈希链“修好”。

## 8 收尾及证据限度

close 请求沿用 v1 的 actor/mode/summary/report/exceptions，版本为 2/2。它同时校验新准入、源漂移、范围外判断、资源、未知运行、诊断和原实施/独立审查/验收门禁。close 后写入拒绝，显式 reopen 留存原 close 事实。

需要从旧 v1 取得新保证，建新 v2 工作，可在 configure.transition 填 `{from_work,journal_hash,reason}`；核对原日志实际 head，但不自动复制其结果或运行回执。旧材料可作为专业输入，不声称当年已满足 v2。

脚本能落实字段、来源、版本、资源声明和失效传播；不能认证真实人类、自然语言完整性、作者真实身份、影响/兼容判断正确性或实测证据充分性。必须结合独立专业检查和真实 agent 组合评测。检查完整性通过不等于交付通过，not-run/unknown 不填成 passed。
