# T-09/T-10：真实行为运行器与案例设施实施记录

报告版本 **2（收口冻结）**；记录 ID `implementation/005-harness`；作者 `/root/behavior_harness`，2026-10-16。本次收口按 `delivery-implement` 专业契约 **1**、实际规则修订 **197b9891d8856fada212f94f2705d67c21ad9a9a** 组织，已核对该包当前无相对修订差异。本机正式评测使用显式 **external-seatbelt adapter／app-server externalSandbox**；下文早期普通 workspace-write 与外层 seatbelt 叠加的描述属于已保留的失败诊断阶段，不能理解为本机正式可用路径。本文记录 T-09/T-10 的实施、自检和环境事实；真实行为成绩及整体验收仍由主协调者和非作者根据实际证据分别判定。

## 现行摘要与版本依据

起始工作树 HEAD 为 `15aabb99b2666d213ea83dcaa7b16855b4f128b5`，同时包含本轮开始前已有的 delivery 未提交修订；实际起始基线以 [baseline manifest](../evidence/baseline/manifest.json) 和 [可恢复源码](../evidence/baseline/sources/) 为准，不能只按 HEAD 推断。实现依据为已确认 [plan.md](../plan.md) 的 T-09/T-10 与 [evaluation-spec.md](../evaluation-spec.md)。本报告的生成规则修订、报告版本和产品源码基线分别记录，没有将后续格式收口追认为所有早期活动都使用同一修订。

当前源码统一位于 `delivery/delivery-orchestrate/`，本项对应清单如下；这些源码已由主协调者冻结，本次只调整本实施报告：

| 产物 | 对应源码／资料 |
| --- | --- |
| 真实调用、冻结、证据采集与独立评审绑定 | [scripts/evaluate_suite.py](../../../delivery/delivery-orchestrate/scripts/evaluate_suite.py) |
| 本机单层外部 OS 边界与真实 app-server 适配 | [scripts/external_seatbelt.py](../../../delivery/delivery-orchestrate/scripts/external_seatbelt.py) |
| harness 与外部适配回归 | [tests/test_evaluate_suite.py](../../../delivery/delivery-orchestrate/tests/test_evaluate_suite.py)、[tests/test_external_seatbelt.py](../../../delivery/delivery-orchestrate/tests/test_external_seatbelt.py) |
| 实际消费者 oracle 及判别回归 | [tests/evaluation/ledger_oracle.py](../../../delivery/delivery-orchestrate/tests/evaluation/ledger_oracle.py)、[tests/test_ledger_oracle.py](../../../delivery/delivery-orchestrate/tests/test_ledger_oracle.py) |
| 公开任务、普通项目、恢复输入及运行说明 | [tests/evaluation/](../../../delivery/delivery-orchestrate/tests/evaluation/)、[评测说明](../../../delivery/delivery-orchestrate/tests/evaluation/README.md) |

当前本项确定性自检为 **24 项 harness＋19 项 external adapter＋8 项 oracle，共 51 项通过**。根协调者另已在 [final-mechanical-002](../evidence/final-mechanical-002/report.md) 留存六包统一检查：design 44、plan 14、orchestrate 169，共 **227 项通过**，并有包装检查原始结果；本项 51 项包含在这 227 项之内，不重复相加。这些结果证明对应设施与确定性判据，不替代真实模型行为、独立审查或整个组合的质量结论。

本机当前边界为 fixture 子树、`/dev/null` 和经过真实启动对照证明必需的既有 `installation_id` 精确写打开例外；auth/config 保持不可写，前后摘要与元数据受保护。SQLite、日志、TMPDIR、zsh TMPPREFIX 均正常配置到 fixture，MCP inventory 先校验结构再检查空能力，所有候选采用同一原生独立 agent 环境说明。普通叠加失败、启动依赖定位、MCP 反例、排序修复、额度中断及恢复前提的原始事实和证据均在下文按阶段保留，早期计数只表示当时已执行范围。

## 原始实施与后续修订记录

## 目标与实际交付

依据已确认 plan.md 的 T-09、T-10、第 5 章及冻结 evaluation-spec.md，新增可复用真实 Codex 执行适配。运行器位于 `delivery/delivery-orchestrate/scripts/evaluate_suite.py`；维护说明与案例在该包 `tests/evaluation/`，回归在 `tests/test_evaluate_suite.py`、`tests/test_ledger_oracle.py`。

prepare 冻结公开输入及明确声明的专业 skill，工作区放在仓库以外的独立临时目录；维护 tests、私有评分材料、缓存及 Git 元数据不进入专业 skill 副本。五项独立调用各只复制一个专业包，项目没有 Git 或 .workflow。完整组合复制六包并创建无远端的本地 Git。

run 真正调用实际安装的 Codex CLI，保存输入、命令参数、实际 CLI 版本、当前允许列出的模型与推理配置、完整 JSONL、stderr、末次消息、会话 ID、usage、运行时间、前后清单、实际文件副本及适用的 Git 状态。`executed` 仅表示真实执行完整，不能等同质量通过。Markdown 报告与 JSON 从同一个结果生成。

macOS 适配保留 Codex workspace-write，使用 sandbox-exec 在整个 CLI 进程树外增加私有目录及指定源码目录禁读规则。父进程预先以相同 profile 读取随机 canary，确认真实拒绝，否则不启动 agent。认证与系统环境沿用原 CLI，不覆盖 HOME/CODEX_HOME，也不复制或软链认证文件。`--ignore-user-config` 配合从真实配置提取的 model/reasoning 显式参数，固定比较条件；CLI 版本可按冻结要求严格匹配。

review 接收独立执行者实际形成的评审，绑定最新执行和真实产物清单，检查证据文件存在并记录摘要。过期产物、同作者声明、未做泄露审计和泄露运行不能被记录为通过。身份字符串本身无法证明独立性，仍需独立评审者核实真实上下文与轨迹。

## 案例及 oracle

已提供五项 standalone、完整组合、legacy 完整流程、两段文件恢复输入，以及入口未连接、全部 skip、mock 绕过集成、错误实际对象四类案例。公开普通项目包含完整需求、共享交易契约需求、收入/支出分支、实际 app.py 入口及联合验收要求。

私有 ledger_oracle.py 在被测沙箱外运行实际消费者，不导入被测者自述结论；delivery-object.json 存在时检验它声明的实际交付入口。判据来源于公开需求，没有根据候选实际输出反向调整。回归证明四类假绿交付均 fail，同时两种等价正确代码组织均 pass。该证据只证明判据能区分结果，不能替代 agent 自主发现缺陷的真实评测。

专业案例字段差异通过 normalize_behavior_case 分离：prompt/request 为公开请求，expected/expectations、forbidden/prohibited 及可能含缺陷标注的自由文字 fixture 属于私有评审材料。没有把整行含答案的案例输入被测者。

## 已执行自检

- `python3 -B -m unittest discover -s delivery/delivery-orchestrate/tests -p test_evaluate_suite.py -v`：22 项通过。覆盖冻结/隔离、无接口、空输出、失败、超时、中断、不自动重试、版本不匹配、canary 未拒绝、声明身份冲突、过期审阅、答案泄露、文件恢复及同源报告。
- `python3 -B -m unittest discover -s delivery/delivery-orchestrate/tests -p test_ledger_oracle.py -v`：6 项通过。实际执行子进程消费者，验证四类反例和两种正确实现。
- `python3 -B delivery/delivery-orchestrate/scripts/check_suite.py --skills-root delivery`：包装 PASS。该检查只证明包结构、元数据、链接和 JSON 可解析，不证明语义质量。

上述 harness 单测使用进程 mock 验证设施行为，明确不计作真实模型评测。oracle 回归运行实际 Python 代码，但未运行模型。

## 实际接口探测与剩余验证

本作者最初在受限工具环境探测原 Codex CLI，因状态数据库只读及 in-process app-server 权限失败；证据在 `evidence/behavior/interface-probe/`，没有模型事件、没有生成业务文件。主协调者之后通过适用审批取得真实 CLI 成功证据，并开展独立设施审查与后续正式评测。

主协调者最新实测：目录禁读 canary 成功，npm/Node 包装入口在外层 profile 下触发 Node InitializeOncePerProcessInternal SIGABRT（退出 -6），尚未形成模型事件；已定位同一安装包的原生二进制入口，由主协调者显式指定复测。运行器不自动替换 CLI，也不把启动失败计作模型质量失败或通过。原生入口的受控使用说明待实测结果后补充。

本作者没有运行正式 V-06，没有声称整体组合完成、质量不退化或全面恢复验证通过。需要主协调者完成：独立设施审查、真实工具执行可行性、固定条件的五项独立及完整/恢复对照、专业负例行为、泄露轨迹审计和逐项独立语义评价。若真实接口或隔离仍不满足，必须保留未验证，而非用单测结果关闭 AC-11。

## 范围与交接

本作者仅修改指定 harness 脚本、其独立测试/案例/维护说明及本记录；未改 delivery.py、runtime-api、SKILL.md、其他专业包或安装链接，未提交。正式运行用法及局限在 `delivery/delivery-orchestrate/tests/evaluation/README.md`。评测目录的 JSON、Markdown、raw 记录及 actual artifacts 是后续复核依据；不要仅根据最后一条成功总结判定质量。

## 后续环境兼容与独立审查修订

原生入口实测能够启动模型，但叠加 macOS seatbelt 导致工具再次 sandbox_apply 被拒绝，不能用该次模型最终总结证明专业能力通过。经主协调者确认，新增显式 `--sandbox-strategy external-seatbelt`，默认仍保留原 workspace-write，不静默切换。实现拆在 `scripts/external_seatbelt.py`，使用本机 CLI 实际导出的 app-server JSON Schema 及其真实 externalSandbox policy，通过 stdio 管理全新 ephemeral thread/turn，没有使用 bypass 标志。

该外部 profile 同时禁止读私有/候选目录和写 fixture 外路径；启动前必须完成三项实际 canary。初版精确全局 SQLite 文件例外仍不能支持完整 state 初始化，真实失败保留在主协调者 run003。之后选择配置隔离方案：显式 sqlite_home、log_dir、TMPDIR 均指向 fixture 专用目录，app-server 开 strict-config；完全去掉用户目录及全局 SQLite 写例外，只允许 fixture 和 /dev/null。当前版本是否实际接受并能启动，要以主协调者后续真实运行证明，未用二进制字符串替代该证据。

app-server 不支持 exec 的 ignore-user-config 旗标；现按真实适配报告实际配置策略及摘要，显式模型/推理覆盖。MCP 从实际配置读取名称后逐项 disabled，不假定空表能够清空递归合并配置；在模型 turn 前核对真实 MCP inventory，仍有外部 tools/resources/templates 就拒绝。没有输出认证内容，没有更改持久配置。

独立审查 IR-002 发现 oracle 只比较 dict 会遗漏币种输出排序。本作者修复：比较实际顶层键顺序，并增加 USD 在先的反向输入及两个负向判别回归。独立审查 IR-003/后续意见要求人读报告与实际 adapter/config_policy 一致、RPC 根身份绑定。本作者修复：根 thread/turn 从真实响应确定；异 thread、异 turn 的消息、usage、完成不驱动根结论；响应前通知先缓冲再重放；commentary-only 不作为最终响应。原始全部协议不删减。

四个固定 `.evaluation-state/`、`.evaluation-log/`、`.evaluation-tmp/`、`.evaluation-output/` 在初始清单前建立，属于所有候选一致的公开运行环境事实；可以精确排除这四个派生目录，不能泛排业务文件、需求和专业产物。last-message 置于固定输出目录。每次运行另保存实际 harness 源码与摘要。

最新本作者已执行自检：主 harness 22 项、external adapter 12 项、oracle 8 项全部通过。external adapter 的测试在 `tests/test_external_seatbelt.py`，其中本地 JSON-RPC 假服务器只验证协议适配、生命周期、错误、超时及隔离检查，明确不算真实模型行为。正式 V-06 仍由主协调者执行并独立评价。本作者没有将环境失败、fake 回归或 oracle 有效性算作质量通过。

## 精确安装标识启动依赖的实证

官方本地 Codex 源码 HEAD `61a44880a85d2fd0d8770908dea5733495e571c8` 的 app-server 初始化在 SQLite 之后调用 resolve_installation_id；该函数即使已有有效 UUID 也以 O_RDWR/create 打开、加锁再读取。源码 checkout 不是已安装版本的匹配构建证明，因此只作为诊断线索。

本作者随后通过适用自动审批，在完全相同的严格 profile 中仅增加既有 installation_id 精确文件例外，执行无模型固定 initialize 对照：已安装 native `codex-cli 0.154.0` 获得真实 initialize result 并退出 0；六项 canary 符合预期；installation_id/auth/config 的摘要、mode、mtime、size 前后完全相同，未输出 UUID 或凭据。证据完整保留 `evidence/behavior/startup-installation-id-diagnostic-012/`。这才支持正常启动依赖的判断，不把此前 stripped backtrace 或无日志当成因果证明。

最终外部适配只允许 fixture、/dev/null 和这个已验证的精确文件写-open 例外，不开放 CODEX_HOME/arg0/全局 SQLite 子树。安装标识必须预先有效、权限0644；每次对保护文件做前后核对，变化使运行成为 invalid-protection。模型执行与语义质量仍需主协调者正式评测。

未来产物采集精确排除四个顶层派生运行目录，JSON 列明排除；请求、事件、stderr、final 和实际业务/专业产物完整保留，旧诊断不删改。同名嵌套业务目录不被泛排。最新本作者自检为主 harness 23 项、external adapter 13 项、oracle 8 项通过；正式行为结论仍另列。

## 自动注入 MCP 的启动门禁修正

主协调者 environment-review-smoke 的真实初次运行发现：仅禁实际用户 node_repl server 后，应用/插件仍自动注入 codex_apps/cua_repl。运行器在 turn/start 之前按实际 inventory 拒绝，没有启动模型，也没有弱化原门禁。本作者据已确认的实际 stable 功能开关，显式关闭 apps/plugins/remote_plugin/memories/shell_snapshot，所有候选采用相同受控环境，记录 disabled_features。仍检查真实 inventory，不以关闭开关等同外部能力消失；未启用 underdevelopment 的宿主技能跳过功能，原生 multi_agent 不受此改动关闭。

CLI 终端输出改为有限摘要，完整函数结果与原始 JSON/JSONL 记录保留。新增回归证明即便声明禁用、实际 inventory 仍有工具，也不得发送 turn/start；另验证 stable 开关与终端摘要不会倾倒巨大 inventory。最新主 harness 24 项、external adapter 15 项、oracle 8 项已通过；正式模型+工具 smoke 等待主协调者新运行取得证据。

## IR013：未知 MCP 结构不得当空目录

独立审阅者以本地假 RPC 服务复现 inventory={}、data:[{}] 会被旧 .get 默认值误当空目录。已按本机实际导出的 v2 schema 增加最低结构校验：data 数组；entry 对象；必需 name/authStatus/tools/resources/resourceTemplates 及类型；当前 authStatus 枚举；nextCursor 类型与完整分页判断。缺字段、错类型、未知值和非 null 游标都拒绝模型 turn，原始响应保留。

external adapter 现18项回归通过，新增真实本地假 RPC counterpart 确认原反例与字段变体不发送 turn/start，同时接受合法空响应和结构完整的空 server。它们仍是设施回归，不冒充模型证据。主harness24项与oracle8项原通过记录保留。

本作者还定向复核已落盘实际 smoke/formal 的8份 inventory 原始证据：没有 malformed 结构；7份完整空目录；environment-review-smoke/001 为完整非空且已由原门禁拒绝。结果在 review/012-mcp-inventory-shape-audit.json。只复核该准入前提，没有重跑模型、重写旧记录或替独立评审判断质量；完整的既有证据可由非作者复核后复用。

## zsh 正常临时前缀与旧进程审计

主协调者确认新账户资源窗口恢复后，请求处理实际 here-document 环境拒绝。本作者依据本机 `/usr/share/man/man1/zshparam.1:1713` 的正常 TMPPREFIX 语义，在完全相同外部 profile 中做无模型真实对照：zsh -f -c、-lc 两种形式在只有 TMPDIR 时均退出1并报告小写 operation not permitted；TMPPREFIX 指向 fixture/.evaluation-tmp/zsh 后均退出0、实际输出正确。保护文件摘要与元数据保持不变。诊断原始结果在 evidence/behavior/zsh-tmpprefix-validation/result.json；最初摘要误用大小写敏感错误标记，现仅修正派生判定并保留原值与说明，没有改写实际返回码或原始stderr。

正式 external adapter 只新增这个正常临时前缀环境值，保持原 profile、installation_id 精确例外、保护检查和 HOME/CODEX_HOME 原值；请求与运行元数据同步记录 TMPDIR/TMPPREFIX 的名称和实际路径。新增真实本地 RPC 子进程回归确认环境确实传入子进程，原用户主目录环境未被改写。最新 external19项、主harness24项回归通过。

另经获批只读审计 ps/lsof：当前已安装 native evaluator CLI 存活数0，已知 eval fixture 活跃数0；没有发送任何信号，没有触碰应用主进程。审计时间、方法和结果在同目录 process-audit.json。该结论仅针对该时点；后续新启动的正式评测由协调者按实际运行继续管理。账户 usageLimitExceeded 的旧中断记录保留，不能据此判定模型或业务技能失败。

共同环境头同步说明当前真实 app-server 可用的原生 multi_agent/spawn_agent：需要独立上下文时使用原生工具；不得再启一个会重读全局配置/MCP并叠加沙箱的 Codex CLI。旧案例的可选 CLI 建议由明确环境限制覆盖；若原生工具不可用，保留待外部调度。该说明三候选相同，仅表达工具/权限事实，不含业务答案，也没有新增helper/gateway。旧quota中断及嵌套CLI实际尝试的原始轨迹保留，不能改写成已通过。
