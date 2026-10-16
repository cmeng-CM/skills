# BUG-001：过期持有者覆盖已重新租用任务的结果 — 第 002 轮

| 文档说明 | 内容 |
| --- | --- |
| bug、轮次与任务 | BUG-001-stale-result；002；2026-10-16-queue-repair 的 T1/Q1，诊断与正式交接 |
| 报告作者、时间与版本 | /root/fix_combined_diagnose；context=native-agent:/root/fix_combined_diagnose；2026-10-16T15:05:47.541034+08:00；报告版本 1，正式交接后固定 |
| 实施作者及成果归属 | 当前 actor 只编写本轮报告、隔离探针和证据，未改产品；前序 /root（context=delivery-fix-combined-control）只做初次检查及 001 报告；原始 queue_store.py 和正式测试作者未知，保留身份缺口，不可据此认定独立性 |
| skill 与契约 | delivery-fix；契约 1；SKILL.md SHA-256 7daff8e141e9646c1ea314dd9d61af7eb1b2083b2b5a503d9d17de93b7ce49d2；实际使用源码与自身引用完整快照见 evidence/snapshots/.agents/skills/delivery-fix/，其余文件指纹见 evidence/baseline.json |
| 输入与授权 | README、plan.md Q1/T1、authorization.md 和本轮父委派；证据快照及 evidence/delegation-scope.md；仅诊断、必要检查、本轮隔离材料，无修复/提交/push 授权 |
| 实际产品基线 | 无 Git 仓库；queue_store.py SHA-256 5dafb66963d6fa0d9b45fb8a917012df4c1ba824e0f668b46d030e2cb402fc98；源码、测试及输入快照和其他指纹见 evidence/baseline.json；结束时核对均未变化 |
| 前次关联 | ../001/fix.md 与 ../001/evidence/before.stderr.txt；同一 BUG-001/T1，承接失败及作者链，不改前轮记录 |

**结论：根因有直接代码与受控实验支持，尚未实施修复。** `Queue.complete` 只检查 `state == "leased"`，完全未比较参数 owner 与当前 job owner，因此被重新租用后，旧 worker 能把新 owner 的任务改成 done 并持久化过期结果。本轮保留当前失败、完整状态变化及修复建议；没有独立审查、A1 验证或整体通过结论。

## 1. 问题与边界

README 要求：pending 可领取；lease 到期可重领；只有当前 lease owner 可完成；旧 owner 返回 False，不能改内存或磁盘；成功完成经新实例保留；重复 enqueue 不覆盖 leased/done。计划要求保留公共 API、既有测试及 R1/A1，不得降低 README 或验收。

本轮仅诊断这些异常并交接。产品、正式 tests、README、计划和授权均未改。route 与资源由协调者负责，本轮不读写 runtime。较宽项目授权不能覆盖本轮明确限制。

## 2. 现场与复现

Python 版本、平台、绝对项目路径和输入指纹见 [baseline.json](evidence/baseline.json)。`git status --short` 返回 128（非 Git 仓库），因此实际版本用可恢复源码/测试快照与 SHA-256 绑定，不虚构 HEAD 或工作区清洁结论。

既有命令 `python3 -B -m unittest discover -s tests -v` 本轮实际运行：3 项，2 通过，stale completion 失败，退出码 1。原始输出见 [baseline-tests.stderr.txt](evidence/baseline-tests.stderr.txt)，命令与退出码见 [baseline-tests.result.json](evidence/baseline-tests.result.json)。失败在旧 worker completion 应为 False 但返回 True；既有测试在该断言停止，单靠它不能证明后续内存/磁盘影响，所以增加隔离探针。

[diagnostic_probe.py](evidence/diagnostic_probe.py) 直接导入未修改的 Queue；显式时钟，无睡眠、外部服务。数据仅写本轮 `evidence/probe-data/`，原始状态见 [probe.stdout.json](evidence/probe.stdout.json)。重现步骤：enqueue job → A 在 now=0/lease=10 领取 → B 在 now=10 重领 → A 完成 stale。A 返回 True；内存和磁盘均从 leased/B/null 变为 done/B/stale；B 随后完成 fresh 返回 False；新 Queue 仍读到 stale。相同脚本把 lease 改成 1000000，在对应到期边界重领，仍产生相同结果。

## 3. 诊断过程

| 候选原因与区分目的 | 检查与实际观察 | 判断及局限 |
| --- | --- | --- |
| complete 未验证 owner | 当前源码 complete 接收 owner 但不使用；重领后旧 A 和未重领时 unrelated owner 均可完成，见 probe 输出 | 直接支持根因；错误不限于到期重领 |
| lease 到期判断错误 | 既有 active/boundary 测试通过；探针两种 lease 均在明确到期值成功重领给 B，完成前状态/owner 正确 | 在本轮单实例、顺序操作条件下排除 boundary 判定导致此次故障；不宣称所有时钟行为均验证 |
| 纯磁盘写入或重启读取错误 | 在写盘前由 complete 直接变更同一 job；探针内存已是 stale，新实例忠实读回该值；正常 owner 完成也能持久保留 correct | 排除此复现为单纯反序列化/重启丢值；文件写入故障和并发原子性未测 |
| 短 lease 是根因/加长即可修复 | lease=10 和 1000000 都在重领后被旧 owner 覆盖 | 加长只推迟重领条件，不能消除 owner 校验缺口；README 历史尝试不是本轮实施成果 |
| enqueue 覆盖或 pending 任意完成 | leased/done 重复 enqueue 返回 False 且内存/磁盘不变；pending complete 返回 False 且不变 | 在探针条件下排除这些替代路径；仍须修复后保留回归 |

前轮的失败未被清除；本轮未进行任何猜测性产品补丁。探针退出码 0 表示观察脚本完成，**不表示行为符合要求**。

## 4. 根因与修复选择

可核查因果链为：claim 正确将 job 的 owner 替换为 B 且保持 leased → A 的迟到 complete 只看 leased 而忽略当前 owner → update 先改为 done/stale → _save 把错误状态持久化 → B 因 state 已非 leased 被拒绝，重启继续得到错误结果。该链由源码、前后状态与重启观察共同支持。

建议下一轮获得修复授权后，在 `Queue.complete` 任何状态变更与 `_save` 前，联合拒绝非 leased 或 owner 不匹配；保留方法签名和已约定的 lease/claim 语义。这样在本轮已证实的单实例调用链上切断错误 owner 修改内存和磁盘的路径。增加相关正式回归：重领旧 owner 的拒绝与内存/磁盘完整不变、正确新 owner 随后成功和重启保留；未重领时错误 owner 同样拒绝；pending/done 和重复 enqueue 保护继续满足。不要用更长 lease、忽略结果写入、弱化测试或改 API 掩盖原因。

多 Queue 实例同时运行、线程/进程并发、同一个 owner 字符串再次获得 lease 的代际语义、写盘失败/崩溃恢复未被本轮证据覆盖；这些若纳入交付预期须由调用方澄清或安排针对检查，不能宣称上述局部建议已经证明解决所有分布式队列问题。

## 5. 实际修改

| 实际成果 | 作者及作用 | 处置与影响 |
| --- | --- | --- |
| 002/fix.md 与 evidence | /root/fix_combined_diagnose；本轮持久诊断、输入快照、执行输出、授权范围与交接 | 保留作为下一位续接依据 |
| evidence/diagnostic_probe.py | 同一 actor；读取原始 Queue 并检查可区分的行为 | 仅诊断，未纳入正式 tests，未改产品；脚本和输出均保留 |
| evidence/probe-data/*.json | 探针生成的 5 个隔离数据文件 | 故意保留已污染与正常样本；只在本轮 evidence 中，不得当产品数据恢复或重放 |
| 001 初次检查材料 | /root；只检查、未修改产品 | 引用并保留，不认领为本轮成果 |

正式产品修复为零；正式测试新增为零；无 commit/push。源码、正式测试、README、计划、授权、所用 skill 的结束指纹均匹配开始快照，见 [handoff-identity-check.json](evidence/handoff-identity-check.json)。

## 6. 自检与回归

| 检查 | 实际结果与覆盖 | 限制 |
| --- | --- | --- |
| 既有 unittest 命令 | 退出 1，3 测试中 1 失败/2 通过；与 001 原失败同类 | 当前产品未通过；本轮是诊断自检，不是独立 A1 验证 |
| 隔离探针 | 退出 0；两种 lease 下旧 owner 返回 True 并改变内存、磁盘，当前 owner 返回 False；错误 owner 在有效 lease 中也可写；pending 与正常持久化/重复 enqueue 按所观察条件工作 | 证实缺陷及有限排除，不是修复后回归通过或正式验收 |
| 前后身份核对 | baseline 中全部输入文件 SHA-256 一致 | 仅核对列明文件；项目未被建立为 Git 仓库，未作全树未知副作用保证 |

本轮没有正式修复，因此没有“修复后通过”、独立审查或验收结果；R1 和非豁免 A1 原样保留。

## 7. 续接与正式交接

本轮已正式交接，报告 002 及其 evidence 固定保存。**尚未实施修复，T1 不具备以修复通过接纳的条件。** 下一位应先读 001 与本报告，核对实际产品与 baseline 指纹及授权，再在同一 BUG-001 目录开 003 承接；不要覆盖 001/002 或重置已失败历史。建议优先实施第 4 节的 owner 拒绝条件与对应外部行为回归，再运行原命令；实现、自检后仍须由调用方安排独立 R1/A1。

作者链必须继承 /root（初次只检查）、/root/fix_combined_diagnose（仅诊断产物）以及后续实际修复者。原始产品作者未知，不能当作“没有其他作者”通过独立性判断。

本轮所有 subprocess 均已回执，无后台进程、外部服务或持有数据句柄；测试使用 TemporaryDirectory 且已结束，探针仅使用本轮路径并关闭文件。协调者分配的编排资源仍由协调者处理，本轮没有主动释放或读取其状态。没有需要重放的未知命令；不要重放任何未知进程。已知副作用为本轮报告、快照、日志、探针与 5 个保留数据文件；无产品写入。未进行全系统进程/文件扫描，无法排除其他 actor 的并发动作或全树未知变化；恢复时若实际指纹不符，先定位新变化并由调用方判断旧证据适用性，不能直接沿用“已核对”结论。

索引未修改（本轮写权限仅 002），请协调者将具体 `002/fix.md` 加入 bug 目录导航；不得以导航链接替代具体轮次证据或添加通过状态。
