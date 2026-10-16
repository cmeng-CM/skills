# 真实评测运行器与判据独立实现审查

**当前不能关闭 V-05：外部 app-server 适配器存在 IR-004，可能把其他线程的完成当成本次任务完成。** 原发现 IR-002（排序 oracle 误通过）和 IR-003（报告误述实际配置策略）已在本次定向检查中解决。现有证据支持操作系统边界探针成功，不等于真实完整组合已经运行或质量通过。

| 身份与版本 | 实际内容 |
| --- | --- |
| 报告、日期、审查者 | review/004-harness；2026-10-16；`/root/independent_delivery_review`；v1 |
| 独立性 | 未参与 harness、seatbelt 适配、oracle、正式案例/测试及产品修复；只读取并写本报告、原始检查结果和隔离探针 |
| 作者集合 | root 及本目标 harness 实施者；实际主体规则以作者实施记录和源码范围为依据，不以审查者换 skill 声称独立 |
| 依据 | plan.md T-09/T-10、AC-09/AC-10/AC-11、V-05；evaluation-spec.md；公开 fixture README 的完整功能/失败规则；delivery-review 契约 1 |
| 对象及摘要 | [004-harness-checks.json](004-harness-checks.json) 保存 evaluate_suite.py、external_seatbelt.py、oracle 和相关测试的实际 SHA-256 与重跑日志；专业包初审不在此重复提升为整体通过 |
| 当前限制 | core v2 仍在完善，未审为通过；没有在本活动启动实际模型；真实执行及全局审查另行进行 |

## 1. 实际方法与结果

读取 run/prepare/review 的公开输入白名单、源码副本、失败与超时分支、完整轨迹、产物复制、实际版本绑定和独立评审接纳；读取显式 external-seatbelt 的 OS profile、三种 canary、协议探测和 JSON-RPC 生命周期。检查了 oracle 的真实消费者选择与失败断言，未只依赖测试数量。

实际运行 exec harness 回归 22 项通过，以及修复后 oracle 回归 8 项通过，原始 stdout/stderr 见 checks 文件。前者使用 mock 进程，只证明运行器分支；后者真正执行临时 CLI 消费者，但不调用模型、不证明模型自主发现缺陷。另独立写了两个临时 probe：排序误通过和异线程完成误绑定，输出分别保留为 [004-oracle-order-probe.json](004-oracle-order-probe.json)、[004-thread-binding-probe.json](004-thread-binding-probe.json)。没有把探针写成正式产品测试或业务代码。

## 2. 已检查的质量边界

| 边界 | 实际检查与判断 |
| --- | --- |
| 公开输入与私有答案 | prepare 不复制技能维护 tests，公开案例按白名单构造；fixture 构造注释和预期不作为 prompt。副本逐文件摘要可查。正式执行仍需审计真实提示、工具轨迹及实际禁读 roots |
| 单项隔离 | standalone 仅允许一个专业包，fixture 不含 Git/.workflow；该结构不等于 agent 已遵守边界，需在真实报告/轨迹核实 |
| 真实接口 | 生产脚本只调用真实 CLI；exec 与显式 external-seatbelt 两策略分开，不静默退回。schema 由本机实际 CLI 导出，不凭猜测使用 externalSandbox |
| 系统访问边界 | profile 默认允许读取，但禁止所选私有/源码目录读取；写入仅 fixture、/dev/null 和明确 state/log SQLite 名称。不是全机读取封闭、网络隔离或恶意管理员安全边界；报告必须保留该限制 |
| 原始 OS 证据 | 读取 external-boundary-probe/isolation.json 与 profile/protocol 原文件：private read 被拒、fixture 外 write 被拒、fixture 内 write 成功；三项 passed。该过程没有模型，不能据此宣布 app-server 实际工具或组合任务成功 |
| MCP 与配置 | 实际用户 config 的 server 名逐项 `enabled=false`，拒绝未知名称引用；turn 前核对实际 MCP inventory 无工具/资源/模板及分页。model/effort 显式沿用真实配置，不覆盖 HOME/CODEX_HOME；app-server 仍加载真实其他配置，报告不应误说全部用户配置忽略 |
| 失败和超时 | exec 保留原始输出、部分文件、timeout/interrupted，未自动重试；外部适配有 deadline、interrupt 和进程组关闭。核心解析错误/不同线程仍须由针对适配器的实际控制流反例验证，不由 exec 的 mock 覆盖替代 |
| 产物与独立评审 | executed 只表示执行结束，必须另行 review；review 绑定最新成功 run、当前清单和真实证据摘要，来源变化拒绝旧评价；同声明作者拒绝，泄露或未审计不得 pass。身份字段不能证明真实独立性，实际作者/上下文仍需本次独立检查 |

## 3. IR-002：排序要求被 oracle 漏检——已解决

原触发：公开 README 要求输出顶层币种键排序；旧 oracle 将 stdout 解析成 dict 后只做内容相等。独立探针把参考正确实现的 sorted(out.items()) 换成 reversed(list(out.items()))，实际 USD→CNY，旧 oracle 仍 pass。旧 oracle SHA-256 `53b4e0dc144bf93ae2fe0c5010dee0c617c858939088c48022d152e2fc817fdb`，错误结果保留在原 probe。

修复后 oracle 增加实际键顺序判断与逆序输入案例，正式回归增加逆序输出、只保留输入插入顺序的拒绝反例；仍接受排序正确的两种代码组织。本次实际重跑 8 项通过，新 oracle SHA-256 `0b13e7eba6dafe139a64c1e9e3fecb1a0c839c67980fb4c997f9642803d7b24b`。达到检出币种未排序、保留合法替代组织的客观关闭条件。这个 oracle 仍是有限案例集合，不能单独代替完整需求的语义评审。

## 4. IR-003：人读报告误述 app-server 配置——已解决

原 report Limits 固定声称使用 --ignore-user-config；external-seatbelt 的 app-server 不支持/没有使用该 flag，实际保留用户 config 并禁用配置 MCP。这不是 OS 边界失效，但会让读者误判评测条件。

现 markdown 已明确 exec 使用该 flag、app-server 不使用；实际配置 hash、显式 model/effort、逐 MCP disable 和外层单沙箱策略有可读说明；未把网络或全机读边界宣称为隔离。当前 evaluate_suite.py SHA-256 `e3197bfbad0040338b90e26ec7156c5c5f8f2439aa68dff431e602c060a3895e`。本次修复保持两种策略区别，没有静默 fallback，达到原关闭条件。

## 5. IR-004：异线程通知可结束本次根任务——未解决，阻断 V-05

- **类型、严重度：** 已确认适配器绑定缺陷，影响执行事实准确性；阻断当前适配器被作为正式组合运行的完成证据。
- **触发：** app-server 连接中出现非本次 thread/turn 的 item/completed 或 turn/completed 通知。这里不声称当前本机 CLI 一定会推送子线程，缺陷是适配器接受此输入时没有按协议身份判别。
- **预期：** 本次 thread/start 与 turn/start 返回的线程/回合身份是事实绑定；其他线程通知原样留存，不能成为根任务 final、usage 或 terminal。根回合没有完成时不能 executed。
- **实际与证据：** `external_seatbelt.execute.consume()` 对所有通知直接写 final_messages/token_usage/terminal。独立用隔离 JSON-RPC counterpart 实际驱动该函数：创建 root-thread/root-turn，只发 child-thread/child-turn final+completed，根回合一直没有完成；函数返回 status=executed、turn.id=child-turn、last-message='Child finished only'。原始通知和源摘要 `bc4d45deacb2d47b4e04b5fae6e78fc103841296e44b2faa4907d91a701c5deb` 见 thread-binding probe。
- **影响：** 真实根任务的文件与步骤可能尚未形成，运行器却记录完整执行并复制中间状态；之后的独立语义评审仍应拒绝，但不能用它掩盖执行事实错误。多 agent 评审/组合尤其需要正确的线程归属。
- **客观关闭条件：** 同一反例在根回合没有有效完成时保持失败/未知或等待超时，只有本次线程和回合的正确通知允许 executed；错误、超时、空结果、同线程不同回合等均不能成为完成；原始其他通知保留。用定向控制流回归验证正常完成、异线程通知、错误及超时，不限定如何拆函数或保存状态。

## 6. 后续与结论范围

规格符合性目前因 IR-004 不满足运行事实绑定要求；除该缺陷外，输入分离、有限来源、状态/证据分开及实际交付对象 oracle 的机制方向符合已确认计划。系统探针成功与 schema 支持证明环境具备尝试正式运行的部分条件，不能填入真实组合的成功结果。

IR-004 修复后应保留原反例，定向复核修复版本和相关通知错误分支。正式运行前还须检查实际 adapter 的执行轨迹；正式评测结束后，再由非实现者逐项检查交付、独立作者身份、完整公开需求、私有材料未泄露、恢复和证据绑定。不得把本报告、mock 数量或 oracle 自检直接记为 AC-11 通过。
