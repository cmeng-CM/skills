# 运行时修复记录：失效后完整复核与跨配置恢复

| 信息 | 内容 |
| --- | --- |
| 记录、日期与作者 | 006；2026-10-16；`/root/contract_runtime`，上下文相同 |
| 范围 | 独立审查 IR-005、IR-006、IR-007；只修改运行时判断链、相关回归和 v2 API 说明 |
| 输入 | [独立反例原始结果](../review/005-core-probes.json)，主协调者明确要求修复；已批准 plan/design 的恢复、来源与证据规则 |
| 前次交接 | [004-runtime.md](004-runtime.md) 与作者清单保持不动；初始自检不等于独立审查通过 |
| 当前源码身份 | [repair-001-manifest.json](../evidence/runtime/repair-001-manifest.json)；工作树未提交，由主协调者统一处理 |
| 专业记录规则 | 继续参考 delivery-implement 契约 1，前次报告所留存的报告规则副本；此修复未改变五项独立能力输入输出 |

独立反例发现三处真实恢复缺陷：API 可以保存新判断，但派生状态仍永久卡在早期过期判断；跨配置又会把已经完整解除的历史运行重新算成无解除入口的未知。此次修复使“过期→完整新判断→恢复”有可验证的接线，并保留依赖缺口和历史失效。以下为作者修复与自检，不自行关闭独立发现。

## 1 原问题与实际修复

| 原稳定 ID | 失败原因 | 实际修改 | 防止反向放宽 |
| --- | --- | --- | --- |
| IR-005 来源复核永久受阻 | effective_pins 遇到 stale 判断后把该 skill 永久 blocked；新有效完整 U2 虽 append 成功却无法成为有效 pin | pin_lineage 把每个判断作为旧 pin→新 pin 的边；只接纳从原配置有效 pin 可达且证据当前的边；新的完整重判从当前有效旧 pin 出发可以恢复 | 只依赖失效 U1 新 pin 的增量 U2 不能跨缺口；valid_pin_hashes 复用同一可达关系，避免状态和记录有效性两套计算 |
| IR-007 影响重判永久受阻 | impact_state 遇到旧 stale I1 即 break，所有后来合法 I2 被忽略 | 新 impact 保存 baseline_hash，状态只接纳链接当前有效 baseline 的判断；旧格式事件通过完整变更差异摘要匹配来保守解释；有效完整重判可推进 baseline | 仅覆盖旧 I1 后增量的后代不能隐藏 I1 未评估变化；全部历史 invalidated_operations 继续生效，已判相关 context 在本配置保守保留，不因无关重判复活旧结果 |
| IR-006 重配制造历史未知 | unknown_runs 扫描所有历史 start，却只查当前配置 resolution；旧已完成链变成 resolution=null；resolve 又拒绝跨配置 | 以解除事件所属配置解释调查→替代真实 run→passed verdict；归档链核对原报告/证据、稳定回执和来源 pin 关系；合法重配置及后续产品/计划变化不倒推旧副作用未知 | 未真正完成恢复链不能重配；原调查或 verdict 证据过期仍阻塞，并可在当前配置重新调查和产生新替代链；保持未知运行验收 owner 与任务覆盖，避免恢复入口被孤立 |

原 run-started 永远保留 incomplete/unknown；“归档链已settled”只说明它已经有真实替代证明，不修改旧事实。当前交付仍需自己配置下的实施、独立审查和验收，不能拿旧 C1 的 verdict 直接通过 C2。

## 2 验证与原始证据

运行 `python3 -B -m unittest discover -s delivery/delivery-orchestrate/tests -p 'test_delivery*.py' -v`，共 **105 项通过**：原 v1 63 项与 v2 42 项。完整输出：[unittest-repair-001.txt](../evidence/runtime/unittest-repair-001.txt)。初始 98 项输出和失败反例保持原样。

新增七项针对性回归：

1. IR005：旧兼容证据过期后，新的完整独立复核生效并可 record。
2. IR005：依赖失效祖先的增量复核仍受阻；完整第三次复核可恢复。
3. IR007：旧影响证据过期后，完整新判断清掉未评估差异；旧失效记录不复活，原相关 context 保留。
4. IR007：只覆盖后续增量的旧后代不能越过失效祖先；状态显示全部未评估变化，新完整重判可恢复。
5. IR006：调查、真实替代 run、passed verdict 后，合法重配置且计划正文细化仍可重新实施/审查/运行/验收/close。
6. IR006：归档调查证据真的过期会阻塞；当前配置可重新调查并完成新的运行与 verdict，不死锁。
7. IR006：真正未解除的未知运行不能通过重配置消失。

check_suite 包检查通过，git diff --check 通过。它们只证明结构/链接和格式，不能证明独立复核结论正确或真实 agent 组合质量。

## 3 交接与剩余验证

源码再次冻结供非作者按原 ID 定向复核；修复仅发生在 delivery_v2.py、delivery_sources.py、delivery_monitor.py、delivery_recovery.py、test_delivery_v2.py 和 runtime-api-v2.md。没有改写历史账本、初始作者清单、前次报告或审查反例，也没有提交/push。

主协调者需用当前修复清单重新绑定候选测试版本；旧候选的真实行为记录可保留为旧版本结果，不能当作当前修复版完整验收。独立审阅者自行确认原问题关闭及邻近影响，作者不以新增用例替代审阅。
