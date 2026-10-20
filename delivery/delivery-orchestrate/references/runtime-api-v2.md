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
- 请求契约仍为 2/2。日志容器：旧工作保持 schema 1；新工作第一次写入 snapshot 引用（configure baseline 或 impact inventory）时，在同一个原子写中升为 schema 2。新引擎读 1/2；旧引擎（528dd67）读到 2 会在 load 阶段明确报 `unsupported journal schema`。升级前保留 `runtime/journal.schema1.bak`，回滚恢复到该备份点，schema 2 之后的事件不回带（有损）；不承诺无损降级。
- 活动源码在 `delivery/`，任务材料在 `.delivery/日期-主题/`。已有工作目录不搬迁，历史来源、回执和哈希链不改写。
- runtime/journal.json 是唯一状态真源；runtime/objects 保存来源、证据与 snapshot 不可变对象。status.md 是从 journal 派生的只读视图：生成区在两个标记之间由 `status --write-status` 重写，人工补充区不参与 gate/close 事实判定。runtime/rejected.jsonl 是写命令拒绝的独立追加日志，不进入 journal。
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

首次 configure 前先运行只读 preflight，由协调者确认后把条目写进 `monitor.exclude`：

```bash
python3 -B CLI preflight --work W --project /项目绝对路径 --format json --high-yield-threshold 1000
```

它只做 stat/目录遍历，不读文件内容、不跟随 symlink、不修改 journal；项目或 work 的任一路径组件是 symlink 时直接拒绝，避免 preflight 通过而 init/configure 随后因路径边界失败。候选分依赖/安装目录（`node_modules`、`.venv`、`vendor`、`target` 等）和生成/缓存目录（`dist`、`build`、`.next`、`coverage` 等）；输出路径、文件数、字节数、检测依据、是否达到高收益阈值。生成目录默认标 `confirmation_required`，由协调者确认是否确为可再生产物。未发现的缓存仍会被监控，保持 fail closed。configure 若在 inventory 中看到未排除的高收益依赖/生成目录，只输出 warning 和 preflight 建议，不改变接纳结果。

在途工作补 exclude 的迁移路径：preflight → `change.category=organization` + `previous_config` 重新 configure → 新做 `change_review`。若只有 `monitor.exclude` 变化，且 tasks/reviews/acceptance、requirements、resources、implementation_routes、transition/recovery_transfers、admission_policy、plan/design object_hash、monitor.roots、skill_sources、authorization.scope、design/plan source authors 全部等价，可用 `reuse_gates` 显式复用 design/plan/mapping gate：

```json
{
  "change": {"category": "organization", "reason": "只排除依赖输出", "previous_config": "config-001"},
  "monitor": {"roots": ["."], "exclude": [{"path": "web/node_modules", "reason": "依赖安装输出，不含 vendored 产品源码"}]},
  "reuse_gates": [
    {"kind": "plan_review", "operation_id": "gate-plan-001", "reason": "计划与来源未变"},
    {"kind": "mapping_review", "operation_id": "gate-map-001", "reason": "任务与验收映射未变"}
  ]
}
```

`reuse_gates` 只允许 design_review/plan_review/mapping_review；change_review 必须新做。引擎在生成 `monitor_baseline`、`protected_index`、`reused`、`reused_gates` 之前，用同一准入输入视图比较旧/新配置；`monitor_baseline`、`monitor.exclude`、`actor`、`change.reason/previous_config`、path/quote、reused 标记、mapping 作者、skill pins 等派生/机制字段不参与比较。任一准入输入变化都拒绝复用，不是只检查 tasks/acceptance。任一项不满足时整次 configure 拒绝。

### 可选复杂修复接入：实施子契约 1

实施默认仍由 `delivery-implement` 完成；复杂故障可以选择 `delivery-fix`。顶层请求保持 2/2，fix 专业契约为 1，实施子契约也为 1；三者分别标识不同边界。普通工作不用启用扩展、不加路线、不安装 fix，旧请求继续有效。v1 不接入该扩展。

新 v2 工作可在配置前启用；已有活动工作先按第 6 节合法接纳当前实际编排源码，再显式启用。不能因 plan/authorization 漂移而绕过来源接纳，也不能通过启用消除未核查运行。关闭工作须先 reopen。

```bash
python3 -B CLI enable-fix --work W --input /项目路径/.delivery/日期-主题/admission/enable-fix-001.json --op enable-fix-001
```

```json
{
  "schema_version": 2,
  "contract_version": 2,
  "actor": {"id": "coordinator", "context": "main-session"},
  "implementation_contract_version": 1,
  "reason": "T1 的偶发故障需要专门诊断与多轮修复记录。"
}
```

该命令持久登记 `implementation-protocol` 事件，旧引擎因未知事件拒绝读取，不能忽略新字段后把 fix 当成旧 implement。事件只启用接入语义，不接纳计划、不授权执行、不放行任何 gate。中断后用相同 op 与请求确认原操作，按实际记录续接，不手改 journal。未知子契约版本拒绝。

启用后，configure 可增加以下 `implementation_routes`；键必须是实际任务 ID。没有声明的任务默认 implement。即使显式写 implement 路线，也须先启用该扩展：

```json
{
  "implementation_routes": {
    "T1": {
      "skill": "delivery-fix",
      "bug_id": "BUG-001",
      "bug_path": ".delivery/2026-10-16-settings/fixes/BUG-001-restart-loss"
    },
    "T2": {"skill": "delivery-implement"}
  }
}
```

示例是待合并的配置片段，不是完整请求；实际只保留存在的任务。选用 fix 时还须在 `skill_sources` 增加真实包：

```json
{"name": "delivery-fix", "root": "/实际路径/skills/delivery/delivery-fix", "contract_version": 1}
```

bug_path 相对项目根，遵守普通路径规则。按同一 bug 的既有目录承接，目录中的 `index.md` 只导航，`001/fix.md` 与 `001/evidence/` 等保存该轮材料。任务可以引用此前同 bug 的目录，不能因此重写另一流程 runtime 或历史结论。

新增或改变路线属于正常配置变更：已有配置使用 `change.previous_config` 和实际分类，重新完成适用 mapping/change/plan/design gates。必要来源、未知运行、资源和范围监测门禁继续适用。选用 fix 不降低原验收要求，不能用旧 implement 成功结果直接代替新路线的修复结果。brief/next 返回该任务实际选用 skill、bug 身份和记录位置，执行者仍须读取正文与现场。

fix 的专业报告直接作为实施报告接纳，record 的 kind 仍为 implementation；额外输入示例：

```json
{
  "implementation_skill": "delivery-fix",
  "implementation_authors": [
    {"id": "original-builder", "context": "initial-implementation"},
    {"id": "fixer", "context": "diagnosis-session"}
  ],
  "report": {"path": ".delivery/2026-10-16-settings/fixes/BUG-001-restart-loss/002/fix.md"}
}
```

这仍是完整 record 的附加片段。fix 请求必须明确 `implementation_skill=delivery-fix` 和非空 `implementation_authors`，报告须位于所配 bug_path 下的数字轮次目录，以 `fix.md` 命名；记录绑定实际 fix pin。作者含本次 actor，并如实列出参与当前成果的全部实施者；引擎保守累积历史作者，重配置和转交不能消除。implement 的旧请求无需这两个字段；其他 kind 不接收它们。

协调者核对报告和实际版本，不让专业执行者维护接纳 JSON 或 runtime，也不要求额外 implementation 正文。诊断进行中、未完成修复、缓解效果与修复自检分别表达；非完成结果不能因存在报告而登记 passed。相关独立 review 和来源兼容审阅排除完整实施作者集合，查真实原问题和修复影响；后续 run/verification/close 门槛沿用原规则。

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

新引擎写入的 gate 固定包含 `gate_protocol: 2` 和 `source_hashes`（plan/design 在 gate 时的 config source object hash）。规范顺序是 **configure → gate → implementation**：configure 前编辑 plan/design 允许，configure 绑定编辑后的内容；configure 后、gate 前编辑使 config source stale，gate 的 fresh 校验拒绝，必须重新 configure；gate 后编辑由 `source_hashes` 锚点拦住。

legacy 只适用于第一个 snapshot-ref configure（或第一个 schema 2 事件）之前、**同时缺少** `source_hashes` 和 `gate_protocol` 的旧 gate：用原 config 的 plan/design source object hash 作锚点，原 config sources 必须仍 current，复用或 check 时标记 `legacy: true`。cutoff 之后新增的 gate 缺 `source_hashes`，或带 `gate_protocol: 2` 却缺 `source_hashes`，或带 `source_hashes` 却缺 `gate_protocol: 2`，一律 fail closed（stale/error），不能按 legacy 放过。`check --preclose` 的批准锚点按“最新 passed gate 的 source_hashes → cutoff 前 legacy 锚点 → 无对应 gate 时 configure fallback”取，不能统一退回 configure hash。

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

第一次编辑产品文件前先运行只读 guard：

```bash
python3 -B CLI guard --work W --kind task --target T1 --format json
```

`--kind` 为 task/review/verification（task 映射 implementation）。可选 `--actor`/`--context` 用于核对资源持有者；不提供时若存在写冲突会返回 blocked 并提示补身份。review 还要求提供 actor/context，并与该审查覆盖任务的全部历史实施作者比对；id 或 context 相同即 blocked。guard/status/next 也会反映 configure 捕获的 protected_index 变化。输出 `ready`、`blocked_reasons`、gates、dependencies、resources（含 held_by/claimable）。退出码 0=ready、1=blocked、2=参数/IO 错误。guard 只报告，不批准 gate、不占资源；真正拒绝仍在 record/run/close。`brief --kind implementation` 在 guard 不 ready 时拒绝输出可执行任务卡。`status/next` 同样给出 `ready_to_implement`、`blocked_reason`；被门禁或依赖阻塞的任务列为 blocked。

批量验收可用真正的原子批次：

```bash
python3 -B CLI verify-batch --work W --input /项目路径/.delivery/日期-主题/admission/verify-batch-001.json --op batch-verify-001
```

输入 `{batch_id, items:[...]}`，每个 item 必须有自己的唯一 `op` 和 `config_operation`（必须等于当前配置），`kind` 必须为 verification，其余字段同单条 verify。任一项失败整批拒绝；全部 item op 已存在且请求一致、且都绑定当前配置时幂等返回，部分存在则报不一致；逐项 op 仍是重试键，`batch_id` 不写入事件。一次锁内构造连续事件、一次原子写盘，不产生半批；整批共用一次 inventory 快照。只支持 schema 2 工作；schema 1 继续用单条 verify 或先升级。

manual 验收仍要求逐项真实人工确认；manual pending 不能批量假通过。

record 格式沿用 v1 的 kind/target/actor/report/result/summary/evidence 与可选 issues/resolutions/run_operation/confirmation/supersedes/reason，版本改 2/2，**去掉 skill_revision**。引擎按任务已接纳路线自动绑定实际专业 pin 和执行 pin；fix 的附加字段与报告位置见 [实施子契约 1](#可选复杂修复接入实施子契约-1)。实施不代替审查，审查排除覆盖任务全部历史实施者，问题只能原 owner 凭证据关闭。

```bash
python3 -B CLI record --work W --input /项目路径/.delivery/日期-主题/admission/implementation-001.json --op impl-T1-001
python3 -B CLI run --work W --acceptance A1 --actor verifier --context verification-session --timeout 120 --op run-A1-001
```

run 先持久 run-started，再释放日志锁执行真实 argv（非 shell），结束重新核对产品、配置、监测、资源和实际来源。超时保留输出并杀进程组。命令不是沙箱，先评估副作用。退出 0 仍须验证者报告和新的 verification record；有后续 run 时旧 verdict 过期，不能挑较早成功回执绕过后来的失败。manual 逐项真实人工确认与 limited 的严格例外规则沿用 v1，不新增快捷不适用或未知豁免。

存在 Git 时采集初始已暂存条目内容摘要；后续执行准入检查它们未被替换。非 Git 不依赖 Git。脚本不替用户提交；仓库没有特殊要求时，协调者按功能完整性分批本地提交，不把无关改动混入，永不 push，并保护既有 index、不使用全量暂存。

## 5 范围外变化的明确判断

status/next 显示 unassessed_changes 与 change_set_hash。声明范围内沿用内容指纹；范围外改变先阻止正式推进，不直接全放行或全重验。

configure 的 `monitor_baseline` 和 impact 的 `inventory` 都保存为 content-addressed snapshot 对象，journal 只保留 `{object_hash, entries_hash, entries_count, bytes}`。`entries_hash` 仍是原 canonical(entries) 哈希，`baseline_hash`、`change_set_hash`、`outside_changes` 语义不变；旧 inline `{entries,hash,unsupported}` 继续可读。对象缺失、hash 不匹配或损坏时 fail closed，要求重新 configure/impact，不能当空快照。

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

诊断责任按稳定目标跨配置承接；实施目标还按历史配置中相同 bug 身份关联任务。organization、换执行能力或同 bug 转交本身不解除阻塞。解除须有当前有效报告/事实引用支持的不同事实内容或策略；仅改 outcome、重复或重排同一事实引用不算变化。解除依据后来过期时，原未解决诊断责任重新阻塞；机器只能识别内容/声明变化，策略是否有实质新判断仍须专业核对。

status/check/next/brief/source 均提供可追溯恢复入口；只读视图可选 `--format markdown|json`，同一结果对象生成。init 后未配置明确提示 configure required；日志或对象损坏 fail closed，不删失败事件或重算哈希链“修好”。

## 8 收尾及证据限度

close 请求沿用 v1 的 actor/mode/summary/report/exceptions，版本为 2/2。`report.path` 必须指向 work 目录下固定的 `closeout.md`；它是 close 报告，不是 gate 事实源。close 在同一请求上重跑 `check --preclose` 的阻塞判定，并校验新准入、源漂移、范围外判断、资源、未知运行、诊断和原实施/独立审查/验收门禁；重放已接受的 close op 仍返回原事件。close 后写入拒绝，显式 reopen 留存原 close 事实。

收尾前先运行机械检查：

```bash
python3 -B CLI check --work W --preclose --input /项目路径/.delivery/日期-主题/admission/close-001.json
python3 -B CLI status --work W --write-status
python3 -B CLI doctor --work W
```

`check --preclose` 只读，有阻塞项退出 1。检查必需验收、最新 run、范围外变化、未释放写资源、未知运行、诊断阻塞、来源/pin 漂移、批准后编辑（按 gate source_hashes → cutoff 前 legacy → configure fallback）、证据缺失、孤儿 admission、status.md 一致性和未处置的 rejected 记录。带 `--input` 时复用 close 的同一例外判定；manual pending 不是 failed，不能走 limited；unknown/stale/未运行不能豁免。阻塞项必须修复，孤儿 admission/旧工作缺 status/index 等作为警告列入报告。收尾顺序固定为 `check --preclose`（批准正文 hash 未变）→ `close` → 写 `status.md`/`closeout.md`；close 成功后视图写失败只警告并可重试，不回滚 close。

`status --write-status` 原子替换生成区并保留人工补充区；状态无法评估时 fail closed（返回 2）、保留旧文件、不改 journal。`doctor` 只读诊断：journal/schema、配置状态、gates、unassessed/unsupported、未知运行、未释放写资源、诊断阻塞、skill 来源漂移、status 视图一致性、未匹配 admission（按请求内容 hash，不按文件名；已使用的 verify-batch 按 items 逐项匹配）、rejected 数量/坏行/未处置记录（verify-batch 调用单独计数）、缺失证据、legacy/fallback 锚点，以及 schema 2 工作的 `journal.schema1.bak` 是否可读且属于同一 work。被 CLI 拒绝的写命令追加到 `runtime/rejected.jsonl`（严格 append-only；读取、attempt 计算、追加和 10MB 轮转在同一 runtime lock 下串行，首条稳定 id + attempt + retry_of，错误消息含带引号键脱敏并截断）；只读命令与 guard blocked 不记录。

close 的来源检查覆盖当前计划、审查、验证、已配置设计、任务选用实施能力及当前接纳产物的真实专业来源，包含实际使用的 fix；仅登记而未使用的可选 fix 不因此成为依赖。发现漂移须恢复原包或完成显式 source-update，再按影响复用证据。漂移不自动抹掉历史报告的 pin 或强制全量重跑，但未处置漂移不能进入 complete 或 limited 收尾。

需要从旧 v1 取得新保证，建新 v2 工作，可在 configure.transition 填 `{from_work,journal_hash,reason}`；核对原日志实际 head，但不自动复制其结果或运行回执。旧材料可作为专业输入，不声称当年已满足 v2。

脚本能落实字段、来源、版本、资源声明和失效传播；不能认证真实人类、自然语言完整性、作者真实身份、影响/兼容判断正确性或实测证据充分性。必须结合独立专业检查和真实 agent 组合评测。检查完整性通过不等于交付通过，not-run/unknown 不填成 passed。
