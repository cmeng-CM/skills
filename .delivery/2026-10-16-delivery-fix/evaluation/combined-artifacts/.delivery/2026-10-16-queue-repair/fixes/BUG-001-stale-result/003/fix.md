# BUG-001：过期持有者覆盖已重新租用任务的结果 — 第 003 轮

| 文档说明 | 内容 |
| --- | --- |
| bug、轮次与任务范围 | BUG-001-stale-result；003；2026-10-16-queue-repair 的 T1/Q1；承接正式交接后的授权修复与作者自检 |
| 报告作者、时间与版本 | /root/fix_combined_resume；context=native-agent:/root/fix_combined_resume；2026-10-16T15:10:13.273446+08:00；报告版本 1，本轮正式交接后固定 |
| 实施作者及成果归属 | 本 actor 修改 queue_store.py、新增 tests/test_queue_owner.py，编写 003 报告和证据；前序 /root（context=delivery-fix-combined-control）做初次检查与 001；/root/fix_combined_diagnose（context=native-agent:/root/fix_combined_diagnose）仅做 002 诊断、探针与交接；原始产品及既有测试作者未知，保留身份缺口 |
| skill 与契约 | 仅本项目 delivery-fix；契约 1；SKILL.md SHA-256 7daff8e141e9646c1ea314dd9d61af7eb1b2083b2b5a503d9d17de93b7ce49d2；本轮所读 skill 和自身引用的实际快照在 evidence/before/.agents/skills/delivery-fix/，指纹在 baseline.json |
| 输入与授权 | README、plan.md Q1/T1、authorization.md，以及本轮协调者委派，见 evidence/delegation-scope.md；允许本地修复 queue_store.py、增加必要回归与本轮记录；保留公共 API、README、既有测试、R1 和非豁免 A1；不提交、不 push、不读写 runtime 或其他 skill |
| 实际产品版本 | 无 Git 仓库（本轮 git status --short 退出 128）；产品与测试由 SHA-256 及修复前后可恢复快照绑定。queue_store.py：5dafb66963d6fa0d9b45fb8a917012df4c1ba824e0f668b46d030e2cb402fc98 → 638deb0d2074ff34c1738a48b50c1e69204681d350450ce3b5cf3477d95abea1；新增测试 SHA-256 832e2085885771b538923d92cf6734df0d2c52112bcf915505ef27be0df51339 |
| 前次关联 | [001 初次失败](../001/fix.md)、[002 诊断交接](../002/fix.md)；同一问题、同一 T1/Q1；不覆盖两轮报告、证据或失败历史 |

**根因由现有代码和前轮受控复现支持；本轮已实施 owner 校验修复，作者自检 7 项全部通过，待独立 R1/A1。** 本轮先核对了 002 列出的全部输入与 skill 指纹，均与当前一致，再继承其诊断；新增回归在修复前也实际暴露了重领旧 owner 和有效租期错误 owner 两条缺陷路径。修复没有改变接口、要求或验收标准，本报告不授予独立审查、正式验证或整体通过。

## 1. 问题与边界

README 要求 pending 可领取、到期可重领、只有当前 owner 可完成；旧 owner 返回 False 且不能改内存或磁盘；成功结果经新实例保留；重复 enqueue 不能覆盖 leased/done。现有 complete 忽略 owner，故旧 A 在任务重领给 B 后仍能写 stale 并把任务标为 done，阻止 B 写入 fresh，错误值还会持久保留。

本轮按协调者已明确给出的修复授权接续，不复用前轮“仅诊断”的动作限制。只改产品 queue_store.py 与新增必要测试，报告和证据只写 003；README、既有测试、计划和历史保持原值。独立 R1、强制 A1 仍由协调者安排。本轮没有读取或修改编排 runtime，也没有操作其他 skill。

## 2. 现场与复现

本轮环境为 macOS-27.0.1-arm64-arm-64bit、Python 3.9.6；项目绝对路径、Python 完整版本、Git 回执和前轮指纹逐项核对在 [baseline.json](evidence/baseline.json)。起点 queue_store.py、既有测试、README、计划、授权及所用 skill/引用与 002 完全匹配，因此 [002 的受控状态证据](../002/evidence/probe.stdout.json) 适用于当前起点。002 已确认无未回执命令、无其启动的后台进程，不需要重放未知动作；本轮没有重跑无新信息的原始诊断。

本轮先新增正式回归，再在未改 queue_store.py 的版本上运行 `python3 -B -m unittest discover -s tests -p test_queue_owner.py -v`：4 项中 2 项通过、2 项失败，退出 1。失败分别是重领后的旧 A 和有效 lease 中 unrelated-worker 都返回 True；见 [原始输出](evidence/new-regression-before.stderr.txt) 与 [执行回执](evidence/new-regression-before.result.json)。本次失败断言停在错误返回值，内存/磁盘污染的修复前完整观察继承 002，不把未执行到的断言声称为本轮已观察。

测试均采用显式时钟和 TemporaryDirectory，无睡眠、外部服务或真实队列数据。

## 3. 诊断过程

| 判断及区分目的 | 本轮核对与证据 | 结论及范围 |
| --- | --- | --- |
| complete 未校验当前 owner 是写入缺口 | 当前起点源码 complete 的 owner 参数未使用；代码与 002 指纹一致；新增两条回归修复前都实际失败 | 继承并加强 002 的因果依据；缺陷不限于到期重领 |
| 是 lease 太短或边界判断错误 | 002 对 lease=10 与 1000000 均重现；当前 claim 代码相同；既有 active/boundary 测试修复后仍通过 | 无新信息支持重做同一时长实验；加长 lease 不是根因修复 |
| 是持久化读回错误或 enqueue 覆盖 | 002 在 complete 后已观察到内存污染；正常 owner 持久化及重复 enqueue 路径工作；本轮相关新旧测试通过 | 对已观察的顺序单实例触发链排除这些替代路径；不据此声称写盘故障或并发原子性已测 |
| 拒绝分支是否影响正确 owner 或状态保护 | 修复后原故障、有效 lease 错误 owner、pending/done 拒绝、重复 enqueue 和新实例读回均实际通过 | 支持此修复切断已证实的非法写入链，同时保留当前 API 行为 |

002 的失败和探针保留原处。没有猜测性产品补丁、临时日志、环境变更或需要撤销的实验性改动。

## 4. 根因与修复选择

因果链保持为：claim 将当前 owner 更新为 B → stale A 调 complete → 原实现只看 leased，放行 A → update 把内存改为 done/stale → _save 把错误状态落盘 → B 被 done 拒绝，重启仍读到 stale。前轮代码、显式时钟复现、内存/磁盘和新实例观察共同支持该链；本轮确认相同产品基线并取得新回归的修复前后结果。

正式修复在任何 job.update 和 _save 之前联合检查 `state != "leased" or job["owner"] != owner`，命中即返回 False。这样在当前顺序调用链上，旧 owner 和无关 owner 都不能触及内存或持久化；当前 owner 仍走原成功路径。方法名称、参数和返回协议均未变，claim、enqueue、保存格式与时钟语义均未改。这是针对已证实缺口的根因修复，并非延长 lease 等缓解。

多 Queue 实例并发、线程/进程竞争、同一 owner 字符串重获 lease 的代际区分、写盘失败和崩溃恢复仍未覆盖；当前公开 API 没有独立 lease token，本轮没有自行扩大或重新定义这些语义。

## 5. 实际修改

| 成果 | 行为及作用点 | 实际作者与处置 |
| --- | --- | --- |
| queue_store.py 的 Queue.complete | 拒绝条件增加当前 owner 比较，在状态更新和 _save 之前执行；非 leased 拒绝保持 | /root/fix_combined_resume；正式修复，保留；[完整差异](evidence/product.diff) 与 [后快照](evidence/after/queue_store.py) |
| tests/test_queue_owner.py | 4 个测试：重领旧 owner 拒绝且全内存/磁盘不变、当前 owner 完成后新实例保留；有效 lease 中无关 owner 拒绝；pending/done 重复 complete 拒绝；leased/done 重复 enqueue 不覆盖 | 同 actor；正式新增相关回归，已执行；[后快照](evidence/after/tests/test_queue_owner.py) |
| 003/fix.md 与 evidence | 本轮身份、授权、前后快照、精确差异、失败与成功回执、保护项指纹 | 同 actor；保留本轮交接材料 |
| 001/002 与原始产品/测试 | 仅继承先前检查和诊断，不归为本轮新成果；原始产品作者仍未知 | /root、/root/fix_combined_diagnose 的范围按文首继承；两轮全部文件结束指纹与起点相符 |

没有修改 README、tests/test_queue.py、计划、授权或 skill；没有提交/push，项目仍未被初始化为 Git 仓库。索引维护不在本 actor 写入范围，交回协调者追加 003 导航，不在索引重复记通过状态。

## 6. 自检与回归

| 检查 | 实际结果与证据 | 覆盖和限制 |
| --- | --- | --- |
| 新回归对修复前产品 | 4 项，2 失败/2 通过，退出 1；[stderr](evidence/new-regression-before.stderr.txt)、[回执](evidence/new-regression-before.result.json) | 证明新用例确实识别旧 owner/无关 owner 缺口；继承前轮完整污染观察 |
| 项目规定命令 `python3 -B -m unittest discover -s tests -v` | 7 项全部通过，退出 0；[stderr](evidence/selfcheck.stderr.txt)、[回执](evidence/selfcheck.result.json) | 既有 3 项全部原样保留，新增 4 项实际运行；覆盖显式 lease 到期、拒绝不变、正确完成持久化、重复 enqueue 保护；仅作者自检，不是独立 A1 |
| 输入和历史保护检查 | README、既有测试、计划、授权、skill 及引用与起点相同，001/002 全部文件相同；[结束指纹](evidence/handoff-identity-check.json) | 核对明确列明对象，不声明扫描全部系统或排除其他 actor 的任意并发动作 |

新增测试没有以文件存在冒充已执行；规定命令的通过没有授予 R1/A1 或整体验收。通过后没有因缺乏新问题而反复运行同一套测试。

## 7. 续接与正式交接

本轮正式交接：已形成针对 owner 缺口的修复及相关回归，作者自检符合；下一步由协调者按原计划安排独立 R1 审查和非豁免 A1 验证，并核对全部实际参与者和原始作者未知这一身份缺口。本轮不能自行关闭 T1、授予独立性或宣称整体交付通过。后续活动先核对 [结束指纹](evidence/handoff-identity-check.json) 与实物，若版本漂移，由协调者判断证据适用性。

资源仍由协调者持有和分配，待协调者交还；本 actor 未操作引擎，未读取、写入或释放 runtime/资源。全部本轮 subprocess 已回执，无本轮启动的后台进程、未结束命令或持有的数据句柄。TemporaryDirectory 已随测试清理；已知持久副作用只有 queue_store.py、正式新测试及 003 的报告/证据。未做全系统扫描，不假称排除了其他 actor 或全树未知变化。无实验性产品改动待撤销，无待重放命令，无提交/push。

本轮报告版本 1 与证据正式交接后保留；后续新增同 bug 轮次继续沿用固定目录，不覆盖 001/002/003。
