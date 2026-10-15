# 本地编排状态与门禁 API（契约 1）

`scripts/delivery.py` 使用 Python 3 标准库和 POSIX `flock`，支持 macOS/Linux。本脚本管理本地状态、证据绑定与机械门禁，不调用模型、不解析自然语言计划、不执行 Git 提交或 push。五个能力 skill 不依赖脚本；编排者阅读其 Markdown 产物后才生成以下接纳 JSON。

Markdown 是需求、专业判断和证据说明的权威来源；JSON 是绑定该版来源的准入快照。修改计划正文后必须重新接纳，不能只修改 JSON 来改变任务或验收要求。`mapping_reason` 说明映射依据；脚本检查引用存在、摘录匹配、指纹和结构，不证明映射语义真实。

## 1. 保存位置与统一约定

- 工作目录：项目内 `docs/delivery/YYYY-MM-DD-主题/`，或用户明确指定的项目内目录。
- 脚本独占 `runtime/`。唯一状态真源是 `runtime/journal.json`：带序号和前项哈希的事件日志；`runtime/objects/<sha256>` 保存源文件、产品文件、报告和原始输出的不可变内容。状态通过日志派生，无另一份实时状态文件。
- 接纳 JSON 可以保存在工作目录的 `admission/`；这是编排工作材料，不要求各能力产出 JSON。每轮正式报告留存新 Markdown 文件，不覆盖前轮事实。
- CLI 的 `--work` 是调用时可解析的路径；JSON 中所有 `path`、`scope`、`context_scope` 均相对项目根目录。拒绝绝对路径、`..` 和经过任何符号链接的路径；引用必须是项目内普通文件，不能引用 `runtime/` 或 `.git`。
- 产品 `scope` 支持文件、尚不存在的文件和目录树；目录树绑定其中全部文件、新增/删除、目录存在性和可执行位。目录树排除自身工作目录和 `.git`。直接把工作目录或 `.git` 声明为产品范围会拒绝。
- `scope: ["."]` 可绑定整个项目，但会包括工作目录以外的报告或测试输出，应谨慎使用。建议声明实际产品目录及共享依赖；不能为使证据保持有效而故意漏掉相关文件。
- 审查、验收可用 `context_scope` 添加不属于任务产物但影响结论的共享规范、配置和测试代码。引用的报告及证据另外逐文件绑定。
- `schema_version`、`contract_version` 当前仅接受整数 `1`，未知版本/字段及缺少必需字段均拒绝。契约不兼容时先升级接入规则；不能只改版本号绕过检查。
- `skill_revision` 是实际使用 skill 的可恢复提交或内容指纹说明；有未提交改动必须记录对应快照。脚本保存该声明，但不证明其出处。产品版本由实际文件内容绑定，不能只填 HEAD。
- `actor: {"id": "稳定参与者身份", "context": "实际执行上下文标识"}`。同参与者应一直使用同 ID、同上下文不得换名伪造独立性；脚本拒绝审查者 ID **或** context 与覆盖任务任何已知历史实施者重复。未登记的实际实施者也必须在编排接纳前识别和排除。
- 所有写命令有 `--op` 操作 ID。同 ID、同请求返回原事件，不重复写入或运行命令；同 ID 不同请求拒绝。修改内容、开始新一轮活动使用新 ID，不复用旧 ID。

工作目录内的 `runtime/` 虽自动排除产品指纹，仍要检查完整性。哈希链用于检测意外损坏与不一致，不是签名或抗恶意管理员篡改的安全边界。应与正常项目备份一起保存。

## 2. 初始化和接纳计划

以下 `P`、`W` 为示例，替换为真实绝对路径；本脚本不会替你编写方案、计划或授权来源。

```bash
python3 /path/to/delivery-orchestrate/scripts/delivery.py init \
  --project /project --work /project/docs/delivery/2026-10-15-settings \
  --title '设置保存与重启恢复' --op init-settings
python3 /path/to/delivery-orchestrate/scripts/delivery.py configure \
  --work /project/docs/delivery/2026-10-15-settings \
  --input /project/docs/delivery/2026-10-15-settings/admission/plan-001.json \
  --op admit-plan-001
```

完整的最小计划接纳示例：

```json
{
  "schema_version": 1,
  "contract_version": 1,
  "actor": {"id": "coordinator", "context": "main-session"},
  "skill_revision": "delivery-plan@可恢复修订及差异快照",
  "plan": {
    "path": "docs/delivery/2026-10-15-settings/plan.md",
    "quote": "T1：保存设置并恢复"
  },
  "design": {
    "path": "docs/delivery/2026-10-15-settings/design.md",
    "quote": "重启后恢复上次保存的设置"
  },
  "authorization": {
    "path": "docs/delivery/2026-10-15-settings/decisions.md",
    "quote": "可以，直接执行吧，直到执行完成",
    "scope": "本次设置保存与恢复任务；允许按任务本地提交，不 push"
  },
  "mapping_reason": "逐项读取方案验收要求和已确认计划，将 T1 对应到整体审查 R1、自动行为验证 A1 和人工交互验证 A2。",
  "tasks": [
    {"id": "T1", "scope": ["src/settings", "tests/settings"], "depends": []}
  ],
  "reviews": [
    {"id": "R1", "tasks": ["T1"], "whole": true, "context_scope": ["docs/settings-contract.md"]}
  ],
  "acceptance": [
    {
      "id": "A1", "tasks": ["T1"], "required": true,
      "method": "command",
      "command": ["python3", "-B", "-m", "unittest", "discover", "-s", "tests/settings"],
      "criteria": "保存设置后重新创建进程，恢复值与最后一次成功保存一致；损坏输入按方案处理。",
      "environment": "项目声明的本地 Python 运行环境与隔离测试数据",
      "context_scope": ["pyproject.toml"],
      "waivable": false,
      "depends": [{"kind": "review", "id": "R1"}]
    },
    {
      "id": "A2", "tasks": ["T1"], "required": true,
      "method": "manual",
      "criteria": "用户在已安装应用中保存、退出、重启后确认设置恢复。",
      "environment": "本次交付的已安装应用与实际用户环境",
      "waivable": false
    }
  ]
}
```

`design` 可省略，计划需在正文说明适用需求依据。授权引用可以指向真实用户消息的逐字留存，必须记录来源位置/上下文；不得生成不存在的批准。示例摘录仅演示格式，不能直接当成其他任务授权。

每个任务必须有审查和至少一项必需验收归属，至少一项 `whole: true` 审查覆盖所有任务。`depends` 是对象数组：`kind` 可为 `implementation`、`review`、`acceptance`，`id` 指向该类别稳定 ID。实施依赖要求对方实施已完成，审查/验收依赖要求对应门禁通过。审查和验收默认依赖覆盖任务的实施完成；可额外声明 `depends`。脚本将三类节点放入同一图检查循环，不允许任务等待一个反过来依赖它的验收。

方法为 `inspection` 时使用人工或模型实际检查产物的记录和具体证据，不允许假装执行过自动命令；方法为 `manual` 时通过结论还必须有逐项真实人工确认。`required: false` 的项仍留存结果，但不属于必需验收门禁。`waivable` 默认 `false`；不能在发现失败后擅自将硬约束改为可豁免。

## 3. 接纳实施、审查和验证结果

```bash
python3 /path/to/delivery-orchestrate/scripts/delivery.py record \
  --work /project/docs/delivery/2026-10-15-settings \
  --input /project/docs/delivery/2026-10-15-settings/admission/implementation-001.json \
  --op implement-T1-001
```

实施接纳示例：

```json
{
  "schema_version": 1,
  "contract_version": 1,
  "skill_revision": "delivery-implement@实际修订",
  "kind": "implementation",
  "target": "T1",
  "actor": {"id": "implementer-a", "context": "implementation-session-a"},
  "report": {"path": "docs/delivery/2026-10-15-settings/implementation/001.md"},
  "result": "passed",
  "summary": "按批准范围实现设置持久化与恢复；已完成报告列出的自检，人工验收仍由 A2 承担。",
  "evidence": [{"path": "docs/delivery/2026-10-15-settings/evidence/self-check-001.txt"}],
  "issues": [],
  "resolutions": []
}
```

实施的 `passed` 仅表示本任务产物满足声明的实施交接条件，并不代表审查/验收通过。`failed` 表示已知未满足，`unknown` 表示缺少必要判断依据。失败或未知也保留正式报告，不为了接纳而声称成功。门禁未满足时，可以先留存 Markdown 报告；脚本拒绝将其接纳为违反依赖顺序的正式执行结果。

审查接纳示例（同样使用 `record` 命令与新 `--op`）：

```json
{
  "schema_version": 1,
  "contract_version": 1,
  "skill_revision": "delivery-review@实际修订",
  "kind": "review",
  "target": "R1",
  "actor": {"id": "reviewer-b", "context": "independent-review-session-b"},
  "report": {"path": "docs/delivery/2026-10-15-settings/review/001.md"},
  "result": {"spec": "passed", "quality": "failed"},
  "summary": "规格覆盖完整，但损坏文件恢复路径存在阻断问题 F1。",
  "evidence": [{"path": "docs/delivery/2026-10-15-settings/evidence/repro-F1.txt"}],
  "issues": [
    {"id": "F1", "summary": "损坏文件导致启动退出", "severity": "high", "blocking": true, "tasks": ["T1"]}
  ]
}
```

审查两项结论各取 `passed|failed|unknown`。`severity` 描述影响程度，`blocking` 描述当前门禁，两者独立。正文需要包含触发、实际证据、影响和建议；JSON 的简述不能替代正文。问题 ID 在工作目录内唯一，新报告引用旧问题，不重复创建同 ID。

修复后重新记录实施；复审保持原问题 ID，给出显式解决证据。结论改变时必须注明 `supersedes` 为被替代记录的操作 ID，并说明 `reason`：

```json
{
  "schema_version": 1,
  "contract_version": 1,
  "skill_revision": "delivery-review@实际修订",
  "kind": "review",
  "target": "R1",
  "actor": {"id": "reviewer-b", "context": "independent-review-session-b"},
  "report": {"path": "docs/delivery/2026-10-15-settings/review/002.md"},
  "result": {"spec": "passed", "quality": "passed"},
  "summary": "复查 F1 及修复影响，损坏数据按约定回退，整体范围检查完成。",
  "evidence": [{"path": "docs/delivery/2026-10-15-settings/evidence/recheck-F1.txt"}],
  "supersedes": "review-R1-001",
  "reason": "实施修复后，直接复现原触发条件并检查相关恢复路径。",
  "resolutions": [
    {"id": "F1", "reason": "原条件已恢复为规定行为", "evidence": [{"path": "docs/delivery/2026-10-15-settings/evidence/recheck-F1.txt"}]}
  ]
}
```

不能用后续空白 `passed` 吞掉尚未解决的阻断问题。只有原发现类别和目标可以解决该问题；实现者不能替独立审查者关闭审查发现。仍有效的历史解决证据可继续生效，后续同基线报告不必复制全部解决记录；产物或解决证据变化会使对应解决结论重新待确认。

同一缺陷因产品/证据变化而失去解决依据时，原 ID 自动恢复为待确认的 `open`，继续在原目标复审并以该 ID 给出新的解决证据。如果原解决证据仍有效，但另一个触发条件发现了新发生的问题，使用新 occurrence ID（如 `F1-R2`），在正文明确关联原 `F1`、新触发和影响；不能重复创建同一 ID 或改写原发现。首版不支持显式修改已有问题内容或跨审查目标迁移问题：重新规划必须保留已有问题的 owner 和关联任务 ID，`configure` 会拒绝移除这些身份，避免历史问题无人可处理。调整分组时可保留原目标用于复审并增设新整体审查；新的独立目标另建关联工作目录。

### 自动命令与语义判断分离

```bash
python3 /path/to/delivery-orchestrate/scripts/delivery.py run \
  --work /project/docs/delivery/2026-10-15-settings \
  --acceptance A1 --actor verifier-c --context verification-session-c \
  --timeout 120 --op run-A1-001
```

从项目根目录执行接纳时声明的 argv，`shell=False`。保存标准输出、标准错误、退出码、超时情况和执行前后内容指纹。命令可以执行项目代码，需事先审查其副作用；脚本不是命令沙箱。超时杀掉本次进程组并保存已捕获输出。长命令由调用方按工具规范异步等待，不用超长阻塞工具调用。

命令退出 0 不自动形成验收通过。验证者读取输出并逐项判断后，保存 Markdown 验证报告，再接纳：

```json
{
  "schema_version": 1,
  "contract_version": 1,
  "skill_revision": "delivery-verify@实际修订",
  "kind": "verification",
  "target": "A1",
  "actor": {"id": "verifier-c", "context": "verification-session-c"},
  "report": {"path": "docs/delivery/2026-10-15-settings/verification/001.md"},
  "result": "passed",
  "summary": "读取原始运行输出，确认有效测试覆盖持久化、重启恢复和损坏输入处理；结果符合 A1。",
  "evidence": [{"path": "docs/delivery/2026-10-15-settings/evidence/coverage-A1.md"}],
  "run_operation": "run-A1-001"
}
```

`run_operation` 必须对应当前配置中当前验收项的真实已完成运行。命令、环境或要求变化后不能沿用旧接纳。执行改变了被验证产品、来源配置变化、前后版本不一致、非零退出或超时均不能支持 `passed`。`unknown` 在环境缺失且没有可运行条件时可不填 `run_operation`，但要有缺口报告和证据。命令输出保存于对象库，可通过返回事件的 `stdout.object_hash`、`stderr.object_hash` 定位原始字节，不要求再复制一份可变文本。

独立 `delivery-verify` 已有报告可作为专业判断与历史证据输入，但首版不支持把外部执行记录导入为本引擎的可信 run。接纳 `command` 方法的通过结论，仍须取得本引擎真实运行回执；不能把既定方法改为 `inspection` 来绕过此条件。重跑前先评估命令副作用、成本、环境和权限：可安全重复且处于授权范围时再执行；不适合重复时保留已有报告与接纳缺口，按受阻状态交付说明，不能为了满足脚本而无评估重跑。未来如增加外部回执导入，须另行设计来源真实性、前后版本与环境绑定，不在首版伪造。

如果引擎在命令执行后、完成事件落盘前崩溃，日志保留 `run-started`。同操作 ID 重试只返回该事件，**不自动再次执行**。先检查命令是否仍在运行及其副作用，再决定是否以新操作 ID重新运行；未完成运行不能支持通过。进程崩溃前创建的无引用对象不改变状态；首版不自动清理，保留诊断和恢复空间。

### 人工验收

`manual` 的通过结果还必须包括：

```json
{
  "confirmation": {
    "path": "docs/delivery/2026-10-15-settings/evidence/user-confirmation-001.md",
    "quote": "我已在安装后的应用中验证 A2，退出再启动后设置保留。",
    "acceptance": "A2",
    "by": "实际确认者",
    "role": "human"
  }
}
```

把该字段加入完整 verification 记录，删除 `run_operation`，目标改为 A2，并使用对应报告。脚本核对项级目标、来源摘录和 `role`；不能鉴别人类真实性。编排者必须核验真实消息/人工记录，不得由模型生成确认文字冒充人工验收。缺少确认只能保持未验证。

独立验证报告可以说明“有依据不适用”，但编排不能将其转换成技术 `passed`。先核对该项是否属于已授权范围：确属排除项时在方案/计划保留排除依据及真实决定，再 `configure` 重新接纳适用的验收集合；只改变 `required` 来规避失败不合法。尚未取得范围决定或依据不足时，保持 `unknown` 并记录缺口。首版不提供 `not_applicable` 快捷结果，防止验证者自行取消验收要求。

## 4. 查看、收尾与重新打开

```bash
python3 /path/to/delivery-orchestrate/scripts/delivery.py status --work /project/docs/delivery/2026-10-15-settings
python3 /path/to/delivery-orchestrate/scripts/delivery.py check --work /project/docs/delivery/2026-10-15-settings
python3 /path/to/delivery-orchestrate/scripts/delivery.py next --work /project/docs/delivery/2026-10-15-settings
```

- `status` 派生实施、审查、验收和问题状态。`stale` 是版本/证据待重新确认，`blocked` 是依赖或阻断问题未满足，均不被改写成业务失败。
- `check` 只检查日志和对象完整性，并报告来源是否过期，**不是语义审查或交付通过**。
- `next` 给出机械上可推进和被阻断的目标；不是自动调度器。先阅读对应正文再执行。

全部通过的收尾请求：

```json
{
  "schema_version": 1,
  "contract_version": 1,
  "actor": {"id": "coordinator", "context": "main-session"},
  "mode": "complete",
  "summary": "实施、独立整体审查和全部必需验收均具备当前证据；未解决事项已在交付报告说明。",
  "report": {"path": "docs/delivery/2026-10-15-settings/delivery.md"},
  "exceptions": []
}
```

```bash
python3 /path/to/delivery-orchestrate/scripts/delivery.py close \
  --work /project/docs/delivery/2026-10-15-settings \
  --input /project/docs/delivery/2026-10-15-settings/admission/close-001.json --op close-001
```

收尾检查全部当前实施、全部独立审查（含整体）、全部必需验收和未解决阻断问题。带限制交付使用 `mode: "limited"`，并逐项给出：

```json
{
  "schema_version": 1,
  "contract_version": 1,
  "actor": {"id": "coordinator", "context": "main-session"},
  "mode": "limited",
  "summary": "A1 的已知限制经用户明确接受；失败结论保留，其余必需门禁通过。",
  "report": {"path": "docs/delivery/2026-10-15-settings/delivery.md"},
  "exceptions": [
    {
      "acceptance": "A1",
      "scope": "本次明确版本的在线环境交付",
      "risk": "离线操作不能完成恢复，详见验证报告",
      "authorization": {
        "path": "docs/delivery/2026-10-15-settings/evidence/exception-A1.md",
        "quote": "我接受本次 A1 的在线环境限制及离线不可用风险，按所列版本交付。",
        "by": "实际授权用户",
        "role": "human"
      },
      "issues": ["V1"]
    }
  ]
}
```

该例仅在 A1 已事先依法定/项目约束被声明为 `waivable: true`、当前验收为有证据的 `failed` 时有效；上面的完整计划样例将 A1 设为不可豁免，因此不能直接拿此例让它收尾。不能豁免 `unknown`、`pending`、`stale`、硬性要求，也不能豁免失败的独立审查。首版刻意保守：例外仅针对验收阶段的已知不符合；需要改变方案/范围时先走正式变更接纳。

`issues` 精确列出该验收项已知并获接受的阻断问题，无则 `[]`。原失败和问题不会被改成通过或已修复。默认可选验收未通过不阻止完整收尾，但其中已登记的阻断问题仍必须解决或具备合法例外。

close 事件保存当时完整状态、版本绑定和授权证据。关闭后禁止新增配置、运行或记录，必须显式重新打开：

```bash
python3 /path/to/delivery-orchestrate/scripts/delivery.py reopen \
  --work /project/docs/delivery/2026-10-15-settings \
  --reason '发现与原交付同范围的新证据，需要重验受影响项' --op reopen-001
```

原 close 事件不改写。`status.closure.state` 表示当时收尾事实；当前文件改变会影响实时派生状态，不能据此倒写历史结论。真正的新目标应新建关联工作目录，不通过 reopen 把范围无限扩展。

## 5. 来源更新、显式重接纳与恢复

计划/设计/授权文件变化时，旧配置立即过期。新 `configure` 必须重新核对正文，给出完整映射、实际修订与理由。默认旧结果不自动进入新配置。

确认目标定义、产物范围、依赖、验收方法/环境/要求均未变，且原报告、证据和产品仍有效时，可以在完整 configure 请求中添加：

```json
{
  "reuse": [
    {"operation_id": "implement-T1-001", "reason": "核对新旧正文，仅调整无关说明，T1 的范围、依赖和当前产物未变。"},
    {"operation_id": "review-R1-002", "reason": "R1 覆盖、独立性和结论依据未变，复查证据仍适用。"},
    {"operation_id": "verify-A1-001", "reason": "A1 的要求、环境、方法和产品完全未变，原运行及逐项判断仍有效。"}
  ]
}
```

`operation_id` 引用 **record** 的操作 ID，不是 run ID。每个目标至多指定一条现行结果，且必须是当前配置中该目标最新的已接纳结果；不能选择较早通过记录绕过后来的失败或发现。脚本核对对应结构、内容快照和原始证据；它同时保留该明确重接纳目标仍有效的历史解决记录。任何变化涉及被复用目标的结构，或产品/证据已经变化，均拒绝复用。来源文字语义是否未变仍须编排者实际核对；理由不能替代检查。未复用的范围继续保持待执行，不要求无关范围全部重跑。

恢复时先运行 `check` 和 `status`，核对真实来源、当前目录及尚未完成的运行。日志或不可变对象损坏时 fail closed，不能删除失败事件、重算哈希链来“修好”；从可信完整备份恢复，或者新建明确关联的工作目录并重新核验。首版不提供自动迁移、自动回滚、垃圾回收、任意历史编辑或旧 `.workflow` 数据导入功能。

## 6. 能力边界

此版本机械检查不等于语义保证，仍依赖编排者识别以下事实：来源授权是否真实、范围是否完整、人工确认是否真实、actor 是否真实独立、运行输出是否证明验收、报告是否遗漏缺陷、环境描述是否符合实际。命令执行前后快照不是对整个项目的事务隔离；应避免同时修改同一范围。跨项目交付、符号链接产品、外部系统状态与不可恢复的 skill 修订需单独安排可信证据，不能把本地目录指纹当成这些事实的证明。

可使用 `python3 -B -m unittest discover -s delivery-orchestrate/tests -v` 执行边界回归。测试覆盖了状态和门禁行为，仍需实际 agent 产出审查、代表性组合使用与后续持续回归；不能仅凭测试数量宣称拆分后质量完全等价。
