# 真实行为评测

本目录是维护评测设施，不是专业执行时的输入。`evaluate_suite.py` 真正运行本机 Codex CLI；不提供生产 fake adapter。单元测试使用的进程 mock 只证明运行器如何处理输出，不计作模型能力证据。退出 0 和 `turn.completed` 仅表示执行完整；质量通过必须由独立评审者查看实际产物和轨迹后另行记录。

## 公开输入与私有答案

`fixtures/` 是普通项目；案例 JSON 的 `prompt`、`requirements` 和显式 skill 是公开输入。`ledger_oracle.py`、回归测试中的参考实现、专业案例的 expected/expectations/forbidden/prohibited 是评审材料，不复制进被测工作区。prepare 复制每个声明 skill 的专业内容与脚本，排除维护 tests、缓存和 Git 元数据；把实际加载快照的逐文件摘要写入 sources.json。只有副本参与运行，不读变化中的安装源码。

不同专业案例可调用 `normalize_behavior_case(row)` 显式分离 prompt/request 和 expected/expectations、forbidden/prohibited。自由文字 fixture 注释可能包含缺陷位置，也属于私有材料；应据此构造正常可观察项目，不能把整行案例传给 agent。本目录可执行 manifest 已采用公开字段白名单；不要往 prompt 里添加答案。

被测工作区由 prepare 建在独立系统临时目录，不位于仓库。证据目录保留 workspace 路径，供新会话恢复；原始产物也完整复制进每次运行的 artifacts。工作区不是自动清除的临时日志，评测与复核完成前不要删除。

## 真实运行

在仓库根运行，路径按实际位置替换：

```sh
python3 -B delivery/delivery-orchestrate/scripts/evaluate_suite.py prepare \
  --case delivery/delivery-orchestrate/tests/evaluation/delivery-review-standalone.json \
  --skills-root delivery --variant candidate \
  --output .delivery/当前目标/evidence/behavior/review-001

python3 -B delivery/delivery-orchestrate/scripts/evaluate_suite.py run \
  --output .delivery/当前目标/evidence/behavior/review-001 \
  --cli /实际路径/codex --timeout 900 \
  --private-dir /评审私有目录 \
  --deny-read-dir /仓库绝对路径 \
  --required-isolation filesystem
```

macOS 适配使用 `sandbox-exec` 的 allow-default 加 deny-file-read 规则包住整个 Codex 进程树，再保留 Codex 的 workspace-write 沙箱。父进程先用相同规则读取随机 canary，确认私有目录实际不可读，失败就不启动被测 agent；profile、canary 结果和摘要保存在运行证据中。附加禁读仓库可同时隔离私有答案、其他候选源码及安装软链的真实源。CLI 自身原有用户目录、认证与进程环境保持不变；`--ignore-user-config` 加从真实配置提取的 model/reasoning 显式覆盖用于固定条件，不重新定义 HOME/CODEX_HOME，也不复制认证。

这不是网络隔离或所有机器文件的封闭容器。全局技能 catalog 的描述可能仍可见；是否加载了其他专业内容须审计完整工具轨迹。没有 OS 边界时只能使用 directory 模式，报告明确保留访问隔离限制，不能把需要隐藏答案隔离的自主发现案例计作通过。macOS 沙箱不可用、CLI 不存在、接口报错、未知版本或证据缺失都如实记录，不声称已执行质量验证。

一个候选一个新的 output，baseline 的 skills-root 指向冻结 baseline，legacy 指向冻结的 task-workflow 上级目录，并选 `ledger-legacy-fullflow.json`。standalone 五个 manifest 各只复制一包、无 Git、无 .workflow；fullflow 建本地 Git 以观察提交行为，仓库无 remote。

## 恢复与对照

完整流程用 `ledger-fullflow.json`。中断恢复使用相同案例先 `run --prompt-file .../resume-stage-one.txt`，再从同一个 output `run --prompt-file .../resume-stage-two.txt`。两次都是新的真实 agent 上下文；前后输入、文件、输出和时间分别留存。超时或中断不自动重试；后续恢复必须先检查磁盘和未知副作用，不把盲重跑当恢复。

legacy、baseline、candidate 的共同需求、模型/推理配置、时间预算、工具权限保持一致；独立能力不强迫 legacy 模拟。每个候选的完整与恢复初始各重复两次。需要进一步诊断时保留所有运行，不选最好结果。不得把一次较快但遗漏交付要求的结果判为更好。CLI 的 usage 直接留存，实际模型若不能确认则比较结论保留限制。

## 独立评价与证据

每次 run 留存 prompt、argv、环境说明、CLI 版本、完整 JSONL、stderr、最后输出、会话 ID、usage、前后文件清单、实际文件和 Git 状态（适用时）。最终 JSON 和 Markdown 从同一结果生成。失败、超时、中断、空输出和损坏 JSONL 都不能自动通过；新 run 会使之前质量评价失效。

评审 JSON 的最小示例：

```json
{
  "reviewer": "真实独立上下文标识",
  "author_identities": ["实际实现上下文标识"],
  "verdict": "pass",
  "summary": "逐项依据原始产物判断，并注明适用边界",
  "evidence": ["runs/001/events.jsonl", "runs/001/artifacts/app.py"],
  "run_id": "001",
  "artifact_inventory_sha256": "runs/001/after.json 的实际 SHA256",
  "leakage_audit": "no-leak-observed"
}
```

用 `evaluate_suite.py review --output ... --review ...` 绑定。证据文件必须真实存在且记录摘要，产物改动会拒绝过期评价。脚本可检查声明身份冲突，不能通过身份字符串证明独立性；评审者还必须核实真实执行者、上下文和工具轨迹。`no-leak-observed` 是实际审计结论，不能默认填入；泄露或未完成审计不能通过。评分依据应覆盖需求、实际功能、独立审查、证据、恢复和可读性，不让被测者自评分。

私有确定性 oracle 可在沙箱外执行：`python3 .../ledger_oracle.py --workspace <实际工作区> --output <私有结果路径>`。它只运行实际消费者；delivery-object.json 存在时按其声明选择交付入口。它能检出入口未连接、skip、mock 和错误对象，并接受不同正确代码组织。其回归证明判据有效，不证明 agent 已自主发现缺陷；真实能力须审查 agent 的原始产物。

门禁/版本/未知运行等机制负例由 runtime 维护测试与 CLI 真实拒绝证据覆盖；不能把这些确定性模拟当成自然语言判断能力。专业案例、完整组合和恢复的实际结论写本次任务 evidence，不写进通用模板假装永远通过。

## macOS 不支持沙箱叠加时的显式模式

本次真实探测发现两类环境失败：npm/Node 包装入口被外层 seatbelt 包裹时，Node 初始化 SIGABRT；同一安装包的原生 Codex 能形成模型事件，但它给工具再次应用 seatbelt 时出现 `sandbox_apply: Operation not permitted`。两个失败记录保留，不能算模型质量通过或自主发现失败。

运行器不自动替换入口或降低沙箱。维护者先核实当前安装包确实包含同版本原生二进制，显式提供 `--cli <核实过的原生入口>`，再明确选择 `--sandbox-strategy external-seatbelt`。该模式使用本机 CLI 导出的真实 app-server JSON Schema，确认支持 `externalSandbox`；启动前必须通过私有目录读拒绝、fixture 外写拒绝、fixture 内写成功三项真实 canary，并验证 auth/config 的 O_RDWR 被拒绝、installation_id 的 O_RDWR 可用且保护文件前后不变。任一不满足，不启动模型。

单层外部 profile 同时禁止读私有目录/候选源码，禁止写工作区以外的路径。写范围包含 `/dev/null`、fixture 子树，以及经真实初始化对照证明必需的既有 `~/.codex/installation_id` 精确文件 O_RDWR 例外；没有用户目录子树、arg0 子树或全局 SQLite 写例外。auth/config/活动仓库不能写。该安装标识必须预先是有效 UUID 且 mode 为 0644，评测器不创建或修复它；每次前后核对其与 auth/config 的摘要、mode、mtime、size，任何变化使运行失效，不输出 UUID 或认证内容。通过实际 app-server `--strict-config` 配合显式 `sqlite_home`、`log_dir` 指向 fixture 内专用目录，验证配置是否受当前版本支持；不支持就拒绝执行。TMPDIR 正常指向 fixture 内专用临时目录，不修改 HOME/CODEX_HOME。父进程通过管道在沙箱外留存证据，不给 agent 授予证据仓库写权。

app-server 本机接口没有 exec 的 `--ignore-user-config` 选项。该模式真实加载当前用户配置，记录摘要和显式模型/推理覆盖；读取 MCP server 名称后逐项 `enabled=false`，在启动模型 turn 前查询实际 MCP inventory，发现仍暴露外部 tools/resources 就拒绝执行。服务器凭据不输出；不支持安全引用的名称也明确拒绝，不能静默漏禁用。

完整 RPC 的 requests.jsonl、appserver.jsonl、规范化生命周期 events.jsonl、实际 schema、配置摘要、policy 和所有 canary 结果均留存。`turn/completed` 是实际服务事件，质量仍需独立评审。超时、中断、空流、协议损坏、崩溃或权限失败不自动重试。恢复是根据实际磁盘状态启动一个新临时 thread，不能把上次没有落盘的动作推断成功。

这个模式只用于已由外部 OS 沙箱完整接管执行的场景。它没有使用 `--dangerously-*` 旗标，也不把无边界的执行当替代方式；实际可用结论以本次私有 canary、工具轨迹和专业调用结果为准。外部 profile 仍不是网络隔离；API 连接与原有网络边界如实记录。

四个固定目录 `.evaluation-state/`、`.evaluation-log/`、`.evaluation-tmp/`、`.evaluation-output/` 是评测器派生运行设施，在初始清单之前建立。所有候选收到相同公开环境说明，可以仅按这四个精确路径排除产品变化监测和提交，不能因此排除业务代码、需求或专业产物。Git fixture 通过本地 info/exclude 忽略它们，不修改项目对外的 Git 规则。

app-server 生命周期按 thread/start 与 turn/start 真实响应绑定根 threadId/turnId；子线程、旧turn的完成/消息/usage仍保留原始轨迹，但不能驱动根任务完成。根通知先于turn/start响应到达时先保留，身份确定后重放；只有commentary不作为最终答复。每次运行另保存实际harness源码及摘要，方便复核环境修订，而非只记录不可追溯的“最新版”。

最终适配的真实无模型启动证明见本次任务 `startup-installation-id-diagnostic-012`：六项边界检查符合预期、原生 CLI 0.154.0 返回 initialize 结果并正常退出，installation_id/auth/config 内容与元数据不变。该证明只覆盖启动与边界，模型+工具和组合质量仍需对应运行证据。

未来正式运行的产品快照和 artifacts 只按四个顶层运行设施目录精确排除，不复制 state/log/TMP/output 数据库或缓存；JSON 明列 product_snapshot_excludes。完整请求、JSONL、stderr、最终答复仍在 run 专用原始记录保留，实际业务代码及专业文档全部采集。嵌套业务目录恰好同名不会被泛排，旧诊断记录也不清理或改写。

受控外部模式还显式关闭当前 CLI 已支持的 stable `apps`、`plugins`、`remote_plugin`、`memories`、`shell_snapshot`，所有候选采用相同设置并在结果记录 disabled_features。关闭用户 MCP 名称本身不足以阻止插件自动注入；真实 smoke 曾在启动模型前检出 codex_apps/cua_repl，按原门禁拒绝。现在仍以实际 MCP inventory 无外部 tools/resources/templates 为准，不能仅凭开关声明就放行；未启用 skip_host_skill_discovery 等试验开关，正常的原生 multi_agent 能力保留。

CLI run 只向终端输出 id/status/reason/seconds/output 摘要，防止巨大 MCP 工具目录挤占上下文。函数 API 仍返回完整记录，完整结果、原始协议和 inventory 继续保存 JSON/JSONL；简洁终端输出不等于丢弃证据。

MCP inventory 先校验真实 v2 响应的最低结构，再判断能力为空：data 必须是数组，server 必须有 name/authStatus/tools/resources/resourceTemplates 且类型正确；未知 authStatus、缺失字段和错误类型都不能当空目录。nextCursor 只允许 null/string，任何非 null 游标（包括空字符串）表示完整性尚未证明，禁止启动模型。合法空 data 和结构完整但无能力的 server 可以通过该设施门禁；它们仍不代表模型质量通过。

zsh 的 here-document 不只受 TMPDIR 控制：本机 zshparam 手册说明 TMPPREFIX 默认 `/tmp/zsh`。外部受控模式同时把正常 TMPPREFIX 设置为 fixture `.evaluation-tmp/zsh`，不改变 OS profile、用户主目录或认证边界。真实同 profile 对照已验证 `zsh -f -c` 和 `zsh -lc`：只有 TMPDIR 时 here-document 被拒；增加 TMPPREFIX 后输出正确且保护文件不变。两项临时环境参数及实际路径都写入请求、运行 JSON 与可读报告；旧失败运行保留，不能当作业务 skill 质量失败。

统一公开环境说明还标明当前 app-server 原生 multi_agent/spawn_agent 可用于独立上下文；需要独立执行时优先使用它，而不是另启 Codex CLI。嵌套 CLI 会重读全局配置/MCP，并再次尝试沙箱，故在本受控环境禁止；旧案例可选的嵌套 CLI 建议被此环境事实覆盖。原生独立工具若不可用，保留待外部调度，不得用 bypass、重新开放工具或改名作者替代独立性。三候选使用相同说明，不增加网关/helper，不包含业务解法或私有判据。

新增两个定向专业输入用于补足生成场景之外的审阅能力：`delivery-plan-existing-review.json` 审阅既有计划，`delivery-review-existing-fix.json` 复审既有问题修复。它们的prompt只含公开任务，fixture为普通项目；维护私有构造/评分材料不能复制给被测agent。现成资产和自检不等于已取得真实模型行为成绩。

产品版本比较按运行器实际策略进行：`inventory` 既有规则排除路径中的 `.git` 和 `__pycache__`；`copy_tree` 另忽略 `*.pyc`（以及复制skill时的维护tests）。四个顶层 `.evaluation-*` 目录是额外、显式的运行设施排除，不是所有过滤规则的完整列表；尤其不能宣称inventory忽略所有位置的独立 `.pyc`。评审应使用同一现行清单策略比较，不以原始walk中的缓存文件判定产品漂移；本次没有扩大过滤、清理缓存或改写历史after.json。

## 历史线程元数据隔离与旧结果审计

`sqlite_home` 只改变数据库目标位置，不改变历史来源。官方本机源码 `61a44880a85d2fd0d8770908dea5733495e571c8` 中，`rollout/src/state_db.rs::try_init_with_roots_inner` 仍用原 codex_home 进入 backfill gate；`metadata.rs::backfill_sessions_with_lease` 扫描 sessions 与 archived_sessions，再把提取的线程元数据写入新库。曾实测发现 fixture 新 state_5.sqlite 被回填 361 条历史线程，因此仅声明“新 SQLite、ephemeral thread、关闭 memories”不足以证明历史隔离。

外部受控 profile 现额外禁读原用户 Codex home 的 sessions、archived_sessions、memories/memories_v2、sqlite、log、dictation-history、thread-writer-locks，以及所有全局 SQLite（含任意版本、WAL/SHM）、history.jsonl、transcription-history.jsonl、session_index.jsonl、codex-global-state 正文/备份/临时文件；存在的符号链接真实目标也加入禁读范围。认证、配置的原读取方式与 installation_id 精确 O_RDWR 例外不变，不改 HOME/CODEX_HOME、不复制凭据、不删除历史。

每次 run 使用 `.evaluation-state/run-<run-id>/` 新目录，不重用现有目录，也拒绝 state 目录符号链接。整个 fixture 旧 `.evaluation-state` 树禁止该进程读写，只有当前新子目录例外；SQLite 初始化还需对 state 父目录本身 stat，因此仅允许该单一目录的 metadata，目录列表及旧文件内容仍被拒。这同时保护旧顶层导入库、旧 WAL/SHM、先前 run 子库，不能只新建目录却把污染旧库留作可读输入。旧库和原始运行证据继续保留，不能通过删除旧库获得“干净”的假象。

启动前同一实际 profile 检查现存全局历史入口和旧 fixture state 文件的 open-read 拒绝、旧 state 的 open-write 拒绝，并保留逐项结果。任一意外可读、可写或 probe 不成立都不启动 agent。真实 app-server 初始化、ephemeral thread/start 和 MCP 核查后，在任何 turn/start 前由父评测器只读查询本 run 实际 state 库 `SELECT COUNT(*) FROM threads`：必须恰有一个已初始化库、threads 表存在且行数为 0；缺库、错误 schema、SQL 错误或非零均阻止模型 turn。`startup-state-audit.json` 与结果 JSON 留存路径、计数和范围，不导出历史标题或消息。

无模型设施验证可调用 `external_seatbelt.execute(..., startup_only=True)`：同一正常配置、profile、初始化和空库门禁，成功状态为 initialized，明确不发送 turn/start，不能算 agent 能力成绩。真实探测中曾由历史 canary 捕获 SBPL regex 字面量的双转义错误，修正前未启动模型；真实 OS canary 的作用不能由 Python 正则单测代替。

本修补不追溯改写原轨迹、after.json 或评价，也不把新启动证明回填为旧 run 的隔离证明。旧结果须由非作者审计完整请求、轨迹、实际输入及污染范围，分别判断业务事实和是否可复用；未观察到读历史库不等于旧 OS 隔离充分。无法排除影响时保留限制或按修补后的相同条件重测；任何旧 pass 都不得自动计入新版隔离样本。
