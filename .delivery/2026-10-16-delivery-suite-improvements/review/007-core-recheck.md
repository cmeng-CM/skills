# 核心恢复链定向复审与相邻发现

**IR-005、IR-006、IR-007 的原多事件反例已解决；当前核心仍因新发现 IR-008、IR-009 不能整体通过。** IR-008 作者修复已进入本次回归版本，但原独立反例尚待定向重跑；IR-009 已复现的再次中断死锁不能被现有通过数量覆盖。

| 身份及版本 | 实际内容 |
| --- | --- |
| 审查者、日期、独立性 | `/root/independent_delivery_review`；2026-10-16；未参与运行时设计、实现或修复，只读产品和正式测试、运行隔离反例、保存自己的记录 |
| 依据 | 原 review/005-core.md；implementation/006-runtime-repair.md；已批准 design v1.1 和计划的未知运行/来源/影响恢复要求 |
| 原独立序列和新反例 | [007-core-recheck-probes.json](007-core-recheck-probes.json)；保留原 005 失败记录，未覆盖历史事实 |
| 整组回归实际版本 | [007-unit-manifest.json](007-unit-manifest.json) 保存五模块执行前后 SHA-256，二者一致；[007-unit-log.txt](007-unit-log.txt) 保存原始完整输出 |
| 实际机械结果 | `python3 -B -m unittest discover -s delivery/delivery-orchestrate/tests -p 'test_delivery*.py' -v`；**108 项通过**，包括此期间作者新增的 IR-008 三项，而非只引用先前 105 的作者结果 |
| 结论限制 | 隔离实际引擎/子进程与控制日志故障状态，不是实际模型组合；V-06 未完成，不得据此整体质量通过 |

## 1. 原三项客观关闭条件

| 原发现 | 本次实际独立复核 | 处置 |
| --- | --- | --- |
| IR-005 兼容复核不可恢复 | 同原序列：U1有效→U1独立证据变化→从当前有效旧 pin 对实际新来源做 U2 完整复核。U2 生效摘要等于 effective pin，drift为空，implementation 可接纳 | 原问题复审确认解决 |
| IR-007 影响判断不可恢复 | 同原序列：I1有效→I1专属证据变化→按完整当前 change_set 新建 I2。I2后 unassessed为空，implementation 可接纳 | 原问题复审确认解决 |
| IR-006 旧已恢复运行跨重配死锁 | 同原序列：C1未知→真实调查→真实替代命令及 passed verdict→C2合法重配和独立 gates→新实施/审查/命令/验收→close。旧未知仍有原 resolution/replacement/settled，C2可正常 closed | 原问题复审确认解决；新相邻多 owner/多次中断分别见下，不用原 ID 掩盖 |

实际阅读 pin_lineage：有效旧 pin 到新 pin 的证据边必须从配置原 pin 可达；依赖失效祖先的增量不能跨缺口，新完整复核可恢复。valid_pin_hashes 与 effective_pins 共用该关系，避免双重有效性计算。

实际阅读 impact baseline_hash 链：新判断必须链接当前有效 baseline；无字段的旧事件按完整差异摘要保守解释；仅旧 I1 之后的增量不能越过 I1 失效缺口。历史 invalidated_operations 保持，已经加入的相关 context 在本配置保守保留。正式新增反例检查这些条件，整组实际通过。

实际阅读旧恢复归档与再调查：历史链按原配置解释，保留真实报告/证据和 source pin 关系；合法后续产品/计划变化不会倒推旧副作用为新未知。真正调查或 verdict 证据过期仍阻塞，允许当前配置重新调查，未完成恢复则不允许重配跳过。这些单次中断条件已通过原序列和相邻回归。

## 2. IR-008：另一个验收组抢走未知运行的替代回执

- **性质与状态：** 已确认多验收组恢复缺陷；原独立反例失败。作者已修复并新增三项回归，独立原反例定向复查尚待执行；不提前关闭。
- **触发：** T1 被 A1/A2 两个 command 验收覆盖。A1 未知后调查 R1，实际 A1 replacement run Y1 和 passed verdict 完成；随后正常 A2 run Y2 和 passed verdict。
- **预期：** A1 的未知只由 A1 的对应替代回执与 verdict 证明。A2 可受共享副作用就绪条件限制，但不能成为 A1 replacement。两组均真正完成后可关闭。
- **原实际：** recovery_for 因共享 T1 把 A2 也标为 R1 的 recovery_operation；unknown_runs 无 owner 过滤，选 Y2 替代 Y1。状态 A1/A2 都 passed、unknown settled=true，却 replacement=Y2，close 又要求 A1 verdict 指向 Y2，形成错误阻塞。
- **证据：** probes.cross_acceptance_recovery 保存 Y1=op-14、Y2=op-20、原实际拒绝。该反例使用真实两条子进程命令，不是对源码字符串的检查。
- **客观关闭条件：** 新版同一原序列可 close；其他 owner 的通过不能替代未完成的 A1，A1 后续真实失败不能被 A2 的成功掩盖；历史回执不改写。作者已新增对应三项，不能只据它们通过就替代本次独立复现。

## 3. IR-009：替代运行再次中断后，最早未知永远没有替代

- **性质与状态：** 已确认缺陷，未解决；阻断多次中断恢复与最终 close。
- **触发：** A1 首次未知 X1→调查 R1→替代动作 X2 再次中断（持久 run-started，recovery_operation=R1）→调查 X2 得 R2→实际成功运行 Y 并登记 passed verdict。
- **预期：** 所有原未知、调查、再次中断和成功回执保持历史。完整有效的恢复链必须有可达关闭条件；不能只在最近一次 interruption 上有效，忘记 X1。
- **实际：** 当前 recovery_for 最终只返回最后一个 resolution 字符串，Y 只绑定 R2。X2 settled=true、replacement=Y；X1始终 replacement=null，close 要求新替代回执而永久拒绝。更换普通 run 操作 ID也继续只选择最后 R2，不会修复更早缺口。
- **证据：** probes.twice_interrupted_recovery 保存 R1=op-12、R2=op-13、Y=op-15，A1 passed，但首次 unknown replacement=null 和实际 close 拒绝。两个中断 reservation 按现有故障 fixture 注入为真实合法日志状态，Y 是实际成功子进程；没有假称真的杀死两次模型进程。
- **客观关闭条件：** 有可验证的传递恢复链或完整绑定集合，使同 owner 多次未知在所有必要调查和最终真实回执有效时可关闭；缺任何必要调查、其证据过期、后续实际失败仍阻塞；不同 owner 不能混用。新状态不能把历史未知改写为旧操作成功。

## 4. 当前核心独立结论

截至本报告的原独立复查，来源、影响重判与单次未知跨配置恢复已经满足原三项关闭条件；正式图、来源绑定、共享资源和 v1 兼容等原审查未发现新增直接放行捷径。但多验收组和替代运行再次中断是同一恢复机制的实际相邻路径，IR-008/IR-009 未全部独立关闭前，核心规格符合性与恢复质量仍为**不通过**。

后续修复再次冻结后，按两项客观条件定向复核即可；不要求无依据重跑全部模型评测，也不能用更多测试数量替代问题关闭。真正完整组合和最终全局实现结论由后续真实证据另行给出。
