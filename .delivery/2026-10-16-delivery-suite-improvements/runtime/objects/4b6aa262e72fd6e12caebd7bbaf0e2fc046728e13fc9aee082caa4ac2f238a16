# 运行时修复记录：恢复的验收归属与完整调查集合

| 信息 | 内容 |
| --- | --- |
| 记录、作者、日期 | 007；`/root/contract_runtime`；2026-10-16 |
| 输入与授权 | 独立复核 IR-008、IR-009；[007-core-recheck-probes.json](../review/007-core-recheck-probes.json)；主协调者明确要求修复，仍属原设计的未知运行与恢复保证 |
| 前次材料 | [004 初始交接](004-runtime.md)、[006 前轮修复](006-runtime-repair.md)、相应原始失败证据与清单保持原样 |
| 当前交接版本 | [repair-002-manifest.json](../evidence/runtime/repair-002-manifest.json) 逐文件摘要；未提交，由主协调者统一处理 |
| 专业记录方法 | 继续使用前次留存的 delivery-implement 契约 1 模板与记录规则；无专业契约升级 |

独立复核证明，原实现把“相关任务均需核查副作用”错误扩大成“相关验收都可取得同一恢复身份”；它还只能保存最后一条解除，连续中断时会丢失早期祖先的替代路径。此次明确分离门禁相关性和恢复身份，并让实际替代运行携带同一验收的完整调查集合。作者已实际验证恢复可达及拒绝错误放行，等待非作者原问题定向复核。

## 1 原问题与实际修复

| 原 ID | 原失败行为 | 当前机制与边界 |
| --- | --- | --- |
| IR-008 | A1 的未知运行与 A2 共享 T1，A2 正常成功运行也被挂上 A1 的恢复身份；unknown_runs 选择最新 A2 当 A1 替代，close 失败 | recovery_for 仍检查所有相关未知副作用，但仅原 acceptance owner 获取恢复绑定；unknown_runs 选择替代时同时核对原 owner 和解除所属配置；settled_recovery、verification 和 record 有效性再次检查 owner，不允许外组成功冒充原组 |
| IR-009 | X1 中断→R1→X2 再中断→R2→最终 Y 只保存 R2，X1 永久没有替代回执 | 新 run payload 保存 recovery_operations 数组，包含该 owner 所有当前有效调查；单数 recovery_operation 保留末项供早期记录兼容；未知状态按成员关系寻找真实替代 run，每个根调查、原 owner 和配置均检查，不能只验证最后 R2 |

同一函数 valid_run_recoveries 用于正式验证接纳、record_current 和归档 settled 判定；它不是三套各自忽略祖先的逻辑。旧只有单数恢复字段的实际记录按单元素集合解释，不改写原事件。

其他组可以在完成相关副作用调查后执行，但不占用原组的替代回执。同一组后续真实失败仍使先前 verdict 过期，不能用另组成功或较早本组成功收尾。根调查证据变化会使整条完整集合失效，收尾和未经核查的新运行继续拒绝。

为保持跨配置一致性，显式 reuse 的报告按 readmitted_from 找到原专业 pin；恢复回执按其实际原配置验证历史调查集合，而新配置仍核对当前产品/报告/来源。这样既不把原规则冒充当前规则，也不因明示重接纳制造无法关闭的假未知。

## 2 实际验证

运行 `python3 -B -m unittest discover -s delivery/delivery-orchestrate/tests -p 'test_delivery*.py' -v`，**114 项通过**：原 v1 63 项、新 v2 51 项。原始输出：[unittest-repair-002.txt](../evidence/runtime/unittest-repair-002.txt)。包检查与差异格式检查通过。

本轮增加九项针对性用例：

1. A1/A2 同任务：A1 恢复成功、A2 正常运行，两项通过且正常 close；A2 没有 A1 恢复身份。
2. 仅 A2 成功不能替代尚未重跑的 A1；直接 settled 计算也拒绝错误 owner。
3. A1 后续真实失败，即使 A2 通过仍不能用旧 A1 成功收尾。
4. 同 owner 连续两次中断，最终 run 绑定两个调查；正常通过且合法重配置后仍可完成。
5. 多次恢复后最早根调查证据过期，整个 verdict 过期且所有相关 settled 失效，close 拒绝。
6. 两个 owner 都有未知运行：先核查两组副作用，各自 run 只绑定自己的调查集合，最后正常 close；把 A1 的绑定放入 A2 运行被校验拒绝。
7. **真实 CLI 连续三次中断**：每轮实际子进程启动并保存 PID，测试终止协调 CLI 和实际子进程组，明确交还资源后逐轮调查；第四次真实命令成功，绑定全部三个调查，新 verdict 后 close。三个旧 run 仍 incomplete，不补造完成事件。
8. 两次中断完整恢复后，显式重接纳未变的产品/报告/结果，原配置恢复链仍有效，可 close。
9. 兼容 skill 更新后显式重接纳未变报告，保留实际旧报告 pin 来源，可 close。

测试中的中断和进程组清理发生在自动清理的隔离项目，没有在本目标账本留未知运行或资源。真实 CLI 多次中断是脚本行为证据，不等同真实 agent 专业组合评测。

## 3 交接

运行时源码再次冻结。修改仅限 delivery_recovery.py、delivery_v2.py、test_delivery_v2.py 与 runtime-api-v2.md；修复清单同时列出当前全部作者源码供核对。未改写原审查证据、旧事件、初始交接或前轮清单；没有提交/push。

请非作者按 IR-008/IR-009 及前轮 IR-005/006/007 定向复核，核查新绑定集合没有跨 owner 或丢失祖先证据。真实候选组合需绑定当前 repair-002 版本；旧版本的运行证据保留其原适用范围。作者不自行声明独立发现已关闭。
