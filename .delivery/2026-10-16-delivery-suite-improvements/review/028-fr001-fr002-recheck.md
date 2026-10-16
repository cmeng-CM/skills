# FR-001 / FR-002 独立定向复审

**规格符合性：本次两项修复满足原问题的关闭条件，FR-001、FR-002 均复审确认解决。实现质量：在这两项修复及直接影响范围内，未发现新的阻断问题。** 恢复调查不再要求旧来源保持当前，但并未成为验收豁免：新配置仍需独立准入、新的真实命令与 passed verification。该结论不重新批准整套 delivery，不表示原任务全部验收通过或已经 close。

| 文档说明 | 内容 |
| --- | --- |
| 记录身份 | review/028-fr001-fr002-recheck；报告版本 1；2026-10-16 13:38，Asia/Shanghai |
| 审查者与独立性 | `/root/fresh_suite_review`，原 027 报告作者；未参与本次产品、测试或控制配置的实现；本次没有另开子智能体 |
| 本次实现者 | `/root` |
| 审查协议 | delivery-review；专业契约 1；当前 skill 文件未参与此次修复 |
| 输入依据 | 原 `review/027-independent-fresh-audit.md`；`repairs/FR-001-FR-002/plan.md` 保存的用户授权、修复决定和验证边界 |
| 产品基线 | HEAD `f796c8c251afd53afcf603bbea17ef53432c0eb4` 加下述编排包工作区差异；不能仅用 HEAD 代表修复版本 |
| 写入边界 | 仅新增本报告；未修改产品、测试、历史报告、运行账本或并行根文档；未提交、未 push |

本次审阅版本的 SHA-256：

| 文件（均相对 `delivery/delivery-orchestrate/`） | 内容摘要 |
| --- | --- |
| `scripts/delivery_v2.py` | `97e0e55d0878882bda3989d493867c2914172647b3356790f7149728380c4ce4` |
| `scripts/delivery_recovery.py` | `d6b3c6f6f93e50a1912baf95193db15d52a6faaca2bca04a78a543005abdcdcc` |
| `scripts/delivery_sources.py` | `8cac49f912c8fbdd71e2fbe8a090ea903de16a294c0b997997d5953bfb5b0ad2` |
| `tests/test_delivery_v2.py` | `eb11a50c32f33d79b38268a544b516a849d7a31b8d47d380a90fa3aede2c46a4` |

## 1. 方法与范围

先读取修复计划和实际 `git diff -- delivery/delivery-orchestrate`，再沿两项原问题的真实调用链检查实现；核对新增四条测试的断言、13 条直接相关既有回归的执行记录及同步文档。检查范围包括相关 gate pin、来源链、调查与转接、证据失效、旧恢复语义、当前 run/verdict/close 条件；没有扩展到六包整体审查、外部评测设施或其他工作区改动。

**本次复审没有执行任何测试或模型评测，也没有新增隔离复现。** 读取的既有证据是 `repairs/FR-001-FR-002/check-001/result.json`、`stdout.txt`、`stderr.txt`。其中实际运行 17 条定向回归，退出码 0，stderr 明确 `Ran 17 tests ... OK`；不是空跑或仅有预置结果文件。当前测试体与日志中列出的用例名称、断言目标对应。

运行结果是实施者保存的机械执行证据；本报告的独立工作是源码与要求的复查，没有将自己写成那些测试的执行者。check-001 结果未自带完整源码冻结，因此本报告额外记录了当前被审关键文件摘要；实施者后补的 `repairs/FR-001-FR-002/reviewed-source.json` 所列四个关键文件摘要与上表一致。结论以本次实际检查的差异为范围。

## 2. FR-001 复审：确认解决

原问题为：gate 虽保存实际 skill pin，却未在当前状态计算时检查 pin 是否仍在有效来源链；兼容证据失效后，新规则产生的 gate 仍能放行。

实际修复位于 `delivery_v2.py:276-297`。`gate_state` 现在按 `gate_sources(kind)` 选择相关来源，检查记录中的 pin 属于 `valid_pin_hashes` 后才保留原结果。plan/design 审阅分别检查对应专业包和 orchestrate；mapping/change 检查 orchestrate。相关来源失效会令 gate stale；无关专业包不会使所有 gate 一起失效。`gate()` 使用同一来源选择函数，当前来源检查与历史 gate 有效性不再维护两份不同的角色映射。

`delivery_v2.py:414-430` 的统一执行准入仍先检查这些 gate，因此修复同时作用于 record、run 与 close。没有改写历史 gate，也没有把恢复 P0 包等同于 P1 审阅重新有效。

已有新增回归 `test_delivery_v2.py:837-864` 实际覆盖原反例：P0→P1 兼容更新→P1 plan gate→兼容证据变化→恢复 P0；断言无来源漂移但 plan gate 为 stale、mapping gate 仍 passed，next 显示相同阻塞，三类执行入口拒绝。按当前有效包重新审阅后可 close。check-001 记录该用例通过。

**处置：FR-001（原 P1／阻断）复审确认解决。** 原缺陷与失败语义保留在 027；本记录只说明当前修复版本满足原关闭条件。

## 3. FR-002 复审：确认解决

原问题为：旧运行未回执且 plan/authorization 已变化时，resolve-run 要求先重新配置，而重新配置要求先恢复旧运行；旧命令已撤销时，临时恢复旧来源字节不是合法的通用解法。

本次增加的显式恢复子契约 2 打开了所缺分支，并保留旧契约：

| 原关闭条件或直接保护边界 | 实际实现与复审判断 |
| --- | --- |
| 来源 stale 时能保存真实调查 | `delivery_recovery.py:190-215` 的 `investigate_run` 读取不可变当前配置而不要求其来源文件仍新鲜；同时检查真实未完成 run、实际执行包 pin，保存原配置关联、报告/证据、当前现场清单及产品快照。没有自动执行旧命令。 |
| 调查本身不能重放或收尾 | `safe_to_replan` 与旧 `safe_to_retry` 分开；`investigation_bound`（47-49）要求新配置显式引用调查。未转接前 unknown 仍不能提供运行许可。 |
| 新配置不能洗掉未完成责任 | `validate_recovery_transfers`（51-76）只接受紧邻旧配置下最新、当前有效的调查；新 `configure_payload`（`delivery_v2.py:130-137`）要求每个尚未 settled 的 unknown 都恢复或显式转接。owner、原任务覆盖、command 方法、required/waivable 阈值受保护。 |
| 重新准入与当前验证仍必需 | 旧配置 gate 不会变成新配置 gate；现有必需 plan/mapping/change 等 gate 与执行准入仍生效。新 run 绑定调查并读取新配置当前命令；`valid_run_recoveries`（86-106）核对 owner、转接与有效调查；`recovery_for`（217-237）及原 close 要求替代 run 和 passed verdict。 |
| 调查失效重新阻断 | `investigation_current`（29-44）检查原始报告/证据、调查使用的 orchestrate 来源链，以及现场/产品快照；失效会沿 unknown 恢复状态阻断后续准入。重新调查后仍须明确转接和新的适用 gate，不能仅改 operation ID。 |
| 保留旧语义和历史事实 | 未声明恢复子契约的 resolve-run 仍走 `delivery_recovery.py:164-188` 的原分支；旧 run 不回填为完成。新事件为 `run-investigation`，当前 `delivery_v2.py:36-38` 明确接纳；旧版本的事件白名单没有它，会拒绝新日志，不能忽略新协议继续执行。 |
| 来源修补不成为业务放行 | `delivery_sources.py:140-177` 允许来源评估绑定 stale 的不可变配置，但仍核对 config operation、有效旧 pin、实际包、兼容判断及独立性；普通执行仍经 `assert_ready` 要求当前来源和 gate。 |

检查了 `unknown_runs`、`settled_recovery` 与普通 verification 校验的组合：只有有效替代命令和对应 passed verdict 能形成已处理历史链；之后合法重规划不会要求重放原命令，但调查/判断原始证据及来源链仍需有效。原始 incomplete 事实保留。当前失败、缺 verdict、其他 owner 的成功与 limited 均不能代替这条责任的通过。

已有真实 CLI 定向回归 `test_delivery_v2.py:884-934` 启动命令、终止其控制进程和子进程，实际形成未回执状态；随后更新 plan/authorization 并撤销旧命令，完成调查、显式转接、新准入、新命令、verdict 和 close。该测试断言旧命令计数仍为 1、原运行仍 incomplete。check-001 的 stdout 保留该执行结论，stderr 记录通过。专业报告、独立 actor 与判断由测试夹具提供；这是状态机和真实子进程执行证据，**不是 LLM 真实完成调查或独立审阅的实战证明**。

另两条新增回归（936-991）及已选既有回归对 unresolved/过期调查拒绝、转接后证据失效、method/required/waivable 保护、重新调查后续接、历史链保留和 stale 来源接纳后仍不得执行提供直接证据。本次没有为增加覆盖重跑它们。

**处置：FR-002（原 P2／恢复范围阻断）复审确认解决。** 当前路径不要求恢复已失效授权或重放已撤销命令；原终态门槛未降低。

## 4. 直接影响与后续边界

SKILL、contracts、runtime API、orchestration、maintenance 的同步说明与实际新增分支一致：顶层仍为编排契约 2，恢复子契约需显式启用；五专业接口不变，旧恢复记录不重新解释。源码升级仍需实际来源接纳，不能仅复制新脚本后默认为活动规则。

现场变化使调查过期时，必须依据当前现场重新调查并明确转接；该保守条件不能被误读为一次调查永久覆盖后续修改。脚本能检查绑定及状态关系，不能替调用方认证“进程已停止”“副作用已查清”或用户授权的真实含义。这些限制已在原协议和本次说明中保留，不作为新增缺陷。

本次没有新增发现或扩大原问题。可按用户既有授权完成本次修复的留存与本地提交；不需要因为这份复审增加模型评测或全量回归。原整套任务未验证的能力、实际工作观察缺口及稳定账本状态继续保留；本报告不授权 push，不执行整套 close。
