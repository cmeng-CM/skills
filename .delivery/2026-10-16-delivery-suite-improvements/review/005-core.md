# 编排核心 v2 独立实现审查

**当前存在三个恢复阻断问题 IR-005、IR-006、IR-007，核心暂不通过。** 98 项现有 v1/v2 回归实际通过，不能覆盖本次新增的跨事件恢复反例。问题主要是“失效后重新确认能否恢复”，并非单次失效是否会拦截。

| 身份及范围 | 实际内容 |
| --- | --- |
| 报告、日期、审查者 | review/005-core；2026-10-16；`/root/independent_delivery_review`；v1 |
| 独立性 | 本上下文未设计、编写或修复核心模块、正式测试和 API；只读实际产品与设计，执行隔离引擎反例，写自己的报告 |
| 依据 | 获批 plan.md 的 T-05—T-08、AC-05—AC-08；design.md v1.1 与 design-reviews/001—002；实际 v1 兼容语义 |
| 对象 | delivery.py、delivery_v2.py、delivery_sources.py、delivery_monitor.py、delivery_recovery.py、API v2；真实摘要见 [005-core-manifest.json](005-core-manifest.json) |
| 方法 | 逐分支阅读共享接纳、来源/门禁/影响/恢复与资源；实际运行 v1 63＋v2 35 项回归；在临时 fixture 执行独立多事件恢复反例 |
| 原始反例 | [005-core-probes.json](005-core-probes.json)；没有修改产品或正式测试，没有把手造 run-started 当作真实模型行为 |

## 1. 已有机制检查

| 要求 | 实际实现与当前判断 |
| --- | --- |
| 显式版本与 v1 续接 | init 默认 1，v2 显式 2；CLI 从真实 init payload 分发；v2 请求投影复用 v1，原 Engine 主要语义保留。现有 63 项 v1 通过，包括历史目录、证据、独立性与关闭保护；未知版本/混用拒绝 |
| 所有执行入口准入 | v2 record/close 经 adapting/duplicate 在非重试时调用 assert_ready；run 明确调用；门禁未过、来源过期、范围外变化、未知运行、缺资源拒绝。相同 op 重试返回旧事实，不再次执行命令；这不是重新放行变更后的状态 |
| 来源实际性 | collect_sources 对 orchestrate 核对实际 __file__ 所属包，运行模块加载内容变化须重启；模块混用拒绝；专业声明从实际契约读，未知版本拒绝；真实文件进入可恢复对象。新 pin 和兼容复核不能以手填 skill_revision 替代 |
| 独立性与最新结果 | 历史 source_authors 合并，配置者加入 mapping 作者；gate 同 id 或 context 排除，最新 gate 失败不选旧通过。implementation review 继续排除全部历史实现作者。命令验证须用最新实际 run，后续失败使旧 verdict stale |
| 范围外变化 | 全项目显式 inventory，当前 work/.git 排除，其他排除不得覆盖产品/来源；不跟随软链，FIFO/不可读形成诊断；按完整变化集判断并定向失效；真实变化、判断后再编辑、删除等仍需实际证据。IR-007 阻碍判断证据失效后的恢复 |
| 共享资源与 close 可达 | 工作内合作 claim/release，路径祖先冲突、多读可并行，close 只要求 write 交还；实际正常命令到 close 的测试通过。该协议不约束未登记外部进程。旧 staged 路径内容保护有实际回归 |
| 未知运行 | 先持久 run-started，v2 释放日志锁执行，inspect/重复 op 可观察；释放资源不能解锁未知；须 resolve 与真实 replacement run/verdict，当前配置正常恢复链可 close。但 IR-006 使其在后续合法重配时重新死锁 |
| 修复收敛 | 同目标/根因的连续两轮无新事实/策略失败持久阻断，事实与策略变更可重新诊断；脚本不证明事实自然语言真伪，不自动豁免 |

本表说明实际读取和测试范围，不把未发现新的单步问题升级为整体无缺陷。尤其必须同时证明 pass→fail→新事实→pass，而不是只检查“fail 会阻塞”。

## 2. IR-005：新的兼容复核事件已接纳，但旧失效事件使来源永远漂移

- **状态/影响：** 确认缺陷；阻断更新兼容与恢复要求，未解决。
- **触发：** U1 将 implement 来源从 A 兼容更新至 B，U1 的独立证据随后变化失效；根据当前实际有效的 A pin 对 B 做新的独立复核 U2。
- **预期：** 旧 U1 保持过期事实；完整有效的新 U2 可以接替承担 B 的兼容依据。若必须换配置，应明确拒绝该更新并给出可达恢复入口，不能 API 成功却永远不生效。
- **实际：** source_update 成功写 U2，但 effective_pins 在 U1 处给 name 加 blocked，后面有效 U2 无法清除；valid_pin_hashes 在 U1 处 break，也忽略后续 U2。状态 effective pin 仍 A、actual 为 B，后续 record 拒绝 source drift。反例保存新事件 op、其 B 摘要、仍然有效的 A 摘要和实际拒绝结果。
- **客观关闭条件：** 过期兼容判断后重新完整独立复核，能按真实当前旧 pin 接纳并恢复，历史不改写；过期依据不能被未绑定原链或不完整复核掩盖。有效 pin、可复用历史 pin 与后续记录判定应一致。补覆盖来源恢复链及再次失效。

## 3. IR-006：已完成的未知运行恢复链在重配置后变成无法解除的未知

- **状态/影响：** 确认缺陷；高影响，阻断合法重规划后的推进与收尾，未解决。
- **触发：** C1 中 run-started 未完成；调查后 resolve=safe_to_retry，随后真正执行 replacement run 并登记 passed verification。C1 unknown 展示已有 resolution 与 replacement。再合法重配置到 C2，完成新的 plan/mapping/change gate。
- **预期：** 旧未知及调查/替代链按其真实原配置解释，保留所有历史；合法重配本身不能抹掉已完成恢复。真正未解除的旧未知仍必须阻塞，旧依据失效仍须重新核对。
- **实际：** configure C2 成功，但 unknown_runs(C2) 扫所有历史 starts，而 resolutions 只取 C2；C1 原 interrupted 被重新显示 resolution=null/replacement=null。C2 record 被旧 unknown 拒绝；resolve 又拒绝它属于旧 admission，当前没有返回旧配置的入口，后续 configure 也会因未知再拒绝。
- **证据：** 原状态 op-1 的 interrupted 有 op-12 resolution、op-14 replacement；新 op-19 配置下二者变 null，实际两个拒绝错误已保存。这是隔离实际引擎多事件执行，不是纯文本推断。
- **客观关闭条件：** 已完成旧恢复链跨合法重配仍可解释并继续，真实未恢复/失败/证据过期链不能借此绕过；旧事件与原 scope 继续可追溯。恢复、再重配、关闭应至少形成一个可达正例和过期阻断反例。

## 4. IR-007：新的范围外变化判断已接纳，但旧过期判断永久屏蔽它

- **状态/影响：** 确认缺陷；阻断 B6 重新判断与恢复，未解决。
- **触发：** I1 对 notes 的范围外变化判断 unrelated；I1 专属证据失效；从当前 status 取得完整变化集，用新的报告和原始证据提交 I2。
- **预期：** 原 I1 保持失效；完整新 I2 能接替对当前变化集的判断，允许保留有依据的无关证据。相关变化仍定向失效，不允许新判断忽略未覆盖变化。
- **实际：** I2 成功 append，references_current=true，但 impact_state 在 I1 处 break，I2 永远不参与 baseline 和 context 计算。状态仍列同一 notes 为 unassessed，record 继续拒绝。
- **证据：** op-13→过期→op-14 的完整反例和实际外部路径保留于 probes；I2 覆盖当时 current changes 全部路径，不是遗漏或旧 change_set hash。
- **客观关闭条件：** 有效的新完整判断能恢复；部分覆盖、旧 hash、再次改动和过期依据仍阻断；历史定向失效不能因后续 unrelated 被意外抹掉，追加 context 与真实依赖仍生效。

## 5. 只读派生视图的缓存副作用

source_drift 调用 collect_pin，后者通过 blob 将读到的实际源内容写入 runtime/objects；因此 status/next/brief/source 可能增加对象文件，即使不写 journal。没有看到它修改产品或制造新的通过事件，故本次不把该缓存行为作为交付阻断。建议 API 如实说明“诊断不改状态日志，但可能补不可变对象缓存”，或将仅摘要比较与正式采集分开，二者都可满足同源派生视图原则；不要宣称文件系统完全只读。

## 6. 结论与复核条件

当前规格符合性与恢复可靠性因 IR-005—IR-007 不能通过；正常路径和单次失效保护的实际回归仍然有效，不能据此忽略本次反例。修复者应保留这些多事件失败事实，用新版本定向证明可恢复性，并检查新逻辑不会放宽旧未知、过期来源或影响判断门槛。

后续需要分别完成核心定向复核、harness IR-004 复核、真实五项独立调用与完整组合评测，再形成全局实现审查；本报告不能替代这些活动。
