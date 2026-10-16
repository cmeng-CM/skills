# 运行时修复记录：重新接纳必须服从上一配置的实际失效

| 信息 | 内容 |
| --- | --- |
| 记录、作者、日期 | 008；`/root/contract_runtime`；2026-10-16 |
| 输入 | 非作者独立发现 IR-010，原反例 [008-reused-impact-probe.json](../review/008-reused-impact-probe.json)；主协调者明确要求修复 |
| 基线及前次交接 | [004](004-runtime.md)、[006](006-runtime-repair.md)、[007](007-runtime-recovery-set.md) 与旧清单、失败证据均保持原样 |
| 当前版本 | [repair-003-manifest.json](../evidence/runtime/repair-003-manifest.json)，运行时作者文件逐项摘要 |
| 专业记录规则 | 参考之前留存的 delivery-implement 契约 1 模板和实际来源；没有改专业输入输出或原 v1 |

IR-010 证明：即使 C2 的 impact 已明确使三项 rebound 结果失效，原 v1 configure 逻辑仍可能回溯 C1 原事件重新验证，从而在 C3 恢复旧通过。此次在 v2 准入边界校验紧邻配置的实际 rebound，保守继承已知上下文；不把来源文字合法细化当成必须全部重做。独立复核仍由非作者作出，本报告仅说明实际修复和自检。

## 1 修改与边界

- EngineV2.configure_payload 对每个 reuse 查紧邻 old_config 的 latest rebound，要求操作身份相同且 record_current(ignore_config=True) 成立；不能只证明更早 C1 原记录仍有效。ignore_config 保留原用途：新计划说明变化时，可明确重接纳产品、报告和要求未变的结果，不一概拒绝所有源文字变化。
- old_config 的 impact_state.extra_context 保守继承入新 payload.inherited_context。target_scope 的同源派生继续绑定它，避免 C3 中未来记录丢失 C2 已知依赖。
- validate_monitor 把继承上下文纳入排除重叠检查，不能给 shared.cfg 加“生成物”排除来隐藏已经判断相关的真实输入。
- 历史 invalidated_operations 不撤销；失效结果必须新实际实施/审查/验证，之后才能按当前有效 rebound 重新接纳。
- 原 v1 核心方法没有修改。原专业 pin、原报告和恢复链的合法显式复用继续按实际来源追溯，不把它们强行改成当前 pin。

本次没有自动迁移已知上下文 owner 的节点身份；保留稳定目标或建立关联新工作，沿用此前发现 owner 和节点血缘迁移边界。没有通过改变字段或修改旧日志来使反例消失。

## 2 验证结果

新增四项回归：

1. 原 C1→显式复用 C2→相关 impact→试图再次复用同原 op 建 C3，拒绝且当前配置仍为 C2，不能 close 冒充完成。
2. 受影响目标产生新实际活动后，可以重新接纳；共享上下文保留，之后 shared.cfg 再变使实施 stale，收尾拒绝。
3. 来源正文仅合法细化说明，当前 rebound 的产品/报告未变，仍可明确复用并 close。
4. 不能通过新监测排除隐藏继承的真实上下文。

v2 55 项单独运行全部通过。首次全 118 项协作工作树运行，有一项正确触发 actual gate skill source drift：其他作者在运行期间更新了同包来源。失败原始输出保留为 [unittest-repair-003.txt](../evidence/runtime/unittest-repair-003.txt)，没有修改门禁或过滤该用例来通过。

随后把六个 skill 复制为固定源码快照，从该实际快照包运行全部 **118 项（v1 63＋v2 55）通过**：[unittest-repair-003-frozen.txt](../evidence/runtime/unittest-repair-003-frozen.txt)。执行包的真实 __file__ 与实际 pin 同包；不是运行另一份代码却声明工作树来源。作者所负责运行时、测试和 API 文件与活动工作树逐字节一致，校验记录见 [source-match.json](../evidence/runtime/frozen-repair-003/source-match.json)，修复清单生成时再次比较一致。

包检查及 git diff --check 通过。最终整体交付仍须主协调者在统一冻结的全部包版本复跑，不能把本作者固定快照中其他作者文件版本当作他们之后修改的证明。

## 3 交接

当前修复仅改 delivery_v2.py、delivery_monitor.py、test_delivery_v2.py、runtime-api-v2.md，运行时源码再次冻结。未改写本目标账本或任何历史审查/交接记录，未提交/push。

请独立审阅者按 IR-010 定向复核原反例和邻近合法复用情形，并结合前次 IR-005—IR-009 复查完整恢复链。作者不自行声明独立发现已关闭。环境启动诊断按协调者要求暂停，没有为启动 CLI 放宽主目录写权限或修改评测设施。
