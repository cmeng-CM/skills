# 实施记录：编排契约 2、范围外影响与恢复

| 文档说明 | 内容 |
| --- | --- |
| 目标、范围与记录 ID | 本目标 T-05—T-08；运行时源码、运行时测试及 API/契约说明；记录 004 |
| 作者、时间、版本 | `/root/contract_runtime`；2026-10-16；报告 1.0，提交独立代码审查的实施交接 |
| 报告规则 | 参考 delivery-implement 契约 1 与当前实施模板；实际专业包树摘要 `4724ae60da205080ec02a6f781c00f936a49065444fcfbe6617ffaf9faa54b77`，可恢复副本见 [report-rule-source](../evidence/runtime/report-rule-source/delivery-implement/SKILL.md) |
| 输入与批准 | [plan.md](../plan.md)，用户已明确批准执行到底、本地提交、不 push；[design.md](../design.md) v1.1、摘要 `53c43d35e4ec3e1c5e44c2f8ea317162038aafe413abff1a8ef46b1bc411d0db`；[独立设计复核](../design-reviews/002.md) 通过后才开始编码 |
| 产品基线 | 修改前来源在 evidence/baseline；当前源码已由主作者迁入 delivery/；本作者未迁移目录或改变本目标 runtime 账本 |
| 当前产品身份 | [作者范围清单及摘要](../evidence/runtime/author-manifest.json) 精确标识交接源码；工作树尚未由本作者提交，清单不代表其他作者的最终整体版本 |
| 关联发现 | 设计 DR-001、DR-002 已设计复核关闭，实施另需独立代码审查，不以设计结论代替实现证据 |

契约 2 已形成可运行的前置准入、变化影响、实际包来源、资源和恢复机制。原契约 1 的核心方法保留，新增契约通过明确工作版本进入，五项专业契约没有被迫升版。作者已实际执行 98 项运行时回归，包括真实命令、跨进程运行中读取和恢复副本执行；独立实现审查与真实 agent 完整组合由非作者继续承担。

## 1 实施依据与边界

覆盖计划 B1/B2/B5/B6/B10，以及 B4/B7/B8 的编排侧职责。专业规范仍归五包，编排器不解析自然语言来代替专业审阅。独立能力无需 runtime、Git 或其他包；本次脚本只在组合准入时使用。

本作者独占修改 delivery.py、四个 v2 职责模块、test_delivery_v2.py、contracts.md、runtime-api.md 和新增 runtime-api-v2.md。没有修改其他作者的 evaluate_suite.py、external_seatbelt.py、validate_suite.py、五包专业规范、SKILL.md 或本目标日志。没有执行提交和 push，由主协调者按整体交付边界提交。

## 2 实际改动与产物

| 成果 | 实际变化与接线 | 产物 | 对应要求 |
| --- | --- | --- | --- |
| 版本分发 | init 可显式选择 2；省略仍 v1；日志容器仍 1；工作按 init 版本路由，混合请求拒绝；v1 核心门禁不改 | delivery.py 的 main；delivery_v2.py 的 EngineV2 | AC-02、AC-07 |
| 前置准入 | configure 是 pending，独立 gate 才放行；大任务/重大重规划强制计划审阅，映射恒需独立；历史作者不能删名；后续失败覆盖早期通过 | EngineV2.configure/configure_payload/gate/assert_ready | AC-05 |
| 授权与覆盖 | 源摘录、稳定需求→任务→验收引用；变更分类与具体授权；确定性验收弱化强制 material，不能伪装局部组织调整 | configure_payload、gate_state | AC-05 |
| 范围外影响 | 全树摘要监测、明确排除、特殊文件不读取；变更集精确判断，相关目标及依赖 op 永久失效，未来记录带新增 context | delivery_monitor.py | AC-06 |
| 实际来源 | 采集完整包普通文件/模式及契约声明；绑定实际入口、模块位置和加载时源码字节；可导出旧包，兼容判断证据失效会使新记录过期 | delivery_sources.py | AC-07 |
| 资源交接 | 写范围、读审查、命令共享资源、返回；路径父子冲突；同稳定身份新恢复 context 可明确交还；close 不要求接管旧作者锁 | MonitorMixin.resource/required_resources/assert_resources | AC-08 |
| Git 暂存保护 | Git 可用时采集初始已暂存条目，后续准入检查这些条目未被替换；非 Git 不依赖 Git；不执行提交 | EngineV2.capture_index/index_entry/assert_ready | AC-01、AC-08 |
| 未知运行恢复 | run-started 持久后释放 journal 锁执行；未知运行相关活动受阻，仅 release 不解除；resolve-run 证据化允许新 op，替代 run+新 verdict 后可收尾 | EngineV2.run；delivery_recovery.py | AC-08 |
| 连续失败诊断 | 相同根因、事实和策略重复失败产生诊断门禁；新事实/策略须记录，不自动豁免或关闭问题 | RecoveryMixin.attempt/diagnosis_state | AC-08 |
| 可读恢复入口 | status/next 原因、brief 全文来源索引、source 导出；Markdown/JSON 同源输出，不维护第二份进度 | EngineV2.inspect；RecoveryMixin.brief；delivery.render_markdown | AC-08、AC-12 |

新增模块均低于 500 行，按准入、监测资源、来源、恢复四类拆分。v2 使用有限适配复用 v1 的图、对象、独立性、问题和验收实现；操作 ID 绑定完整 v2 请求，不能仅绑定投影后的 v1 字段。

额外加强两项可确定行为：有后续运行后旧 verification 过期；不能用较早成功回执绕过后来的失败。源修订不能借重新 configure 静默切换，需先明确兼容 source-update 或新建关联工作。

## 3 测试与自检

| 检查 | 实际结果 | 证据及限制 |
| --- | --- | --- |
| 原运行时回归 | 63/63 通过，原测试文件未修改 | 新 discovery 同时覆盖；证明既定 v1 行为样本，没有把 v2 保证追加到历史 |
| 新 v2 回归 | 35/35 通过 | [完整运行输出](../evidence/runtime/unittest.txt)；共 98 项，退出码 0 |
| 实际命令正向 | 真实 Python argv→退出码→专业 verdict→close | test_full_real_command_delivery_and_close；不是实际 agent 专业产出 |
| 运行中并发 | 真实 CLI 启动长命令，另一进程 2 秒内读状态；同 op 返回 run-started 不重放；测试终止父/子进程并清理 | test_actual_inflight_cli_releases_journal_lock_and_duplicate_does_not_rerun |
| 可恢复包执行 | 从对象恢复字节精确的编排包，在恢复目录真实运行 CLI 完成 close | test_original_package_restored_elsewhere_can_really_close_from_its_cli |
| 核心负例 | 缺 gate 全执行入口拒绝、身份冲突、报告改动、映射缺项、验收弱化、范围外变化、过期判断、FIFO、source 假声明、兼容证据过期、资源冲突、未知运行、重复失败、已有暂存内容 | 具体用例名称和结果见完整输出；正文遗漏、兼容语义等仍需真实独立判断 |
| 包检查 | PASS；6 skill、43 Markdown、22 JSON、57 本地链接（检查当时） | check_suite.py --skills-root delivery；只是打包/基础元数据/链接检查 |
| 差异格式 | git diff --check 通过 | 只证明所查差异没有格式错误 |
| 共享工作区总体测试 | orchestrate 下 test_*.py discovery 134 项通过（检查当时，含其他作者的评测设施测试） | 主协调者仍需在最终冻结版本复跑；本作者不以他人测试数量冒充运行时专属证据 |

实施中曾有一个测试夹具 helper 名为 run，意外覆盖 unittest.TestCase.run；运行器立即失败，改名 execute_run 后重新运行整组。它没有作为通过证据保留，也没有修改产品来迁就测试。其余新增用例在当前交接版本均通过。

设计层原发现的实施证据：DR-001 对应“仅释放仍拒绝”“有证据后新 run+verdict 可收尾”“解除证据变化重新阻塞”三项；DR-002 对应执行包 B 声明 A 拒绝，以及恢复原包真实 CLI 可继续。独立审阅者需要直接核查实现，不能只凭该表关闭实现问题。

## 4 偏差、决定与遗留

| 事项 | 当前决定及依据 | 后续条件 |
| --- | --- | --- |
| v1 未知运行没有新解除命令 | 保持原契约，不给历史加隐含保证；新命令仅用于 v2 | 需要新保证时明确关联新工作与调查依据 |
| 同一 v2 工作内切换 skill | 新配置不能静默采集未接纳的新修订，先 source-update 或新目标；纯字节不变路径迁移可恢复 | 独立检查兼容报告与实际差异 |
| 未知运行时重规划 | 未核查/未有替代运行时拒绝重配置，避免抹掉副作用上下文；来源已变应先恢复原配置来源完成调查 | 非作者检查恢复路径及实际文档是否足够清晰 |
| 假语义声明 | 字段无法认证真实人类、完整需求、实际上下文、影响与兼容正确性；脚本落实明确规则，语义由独立活动负责 | 真实 agent 负例评测必须覆盖漏正文、假成功测试和无效交付对象 |
| 全树监测性能 | 普通文件摘要，不全项目复制内容；对象仍用于正式产品与证据；自动排除当前 work，其他派生输出显式说明 | 真实组合/代表性项目测成本，不能以性能为由漏真实来源 |
| 测试边界 | 98 项是作者回归及实际子进程证据，尚非真实 agent 五能力组合质量结论 | 主协调者安排独立代码审查和完整组合、基线对比 |

当前没有需要用户新增范围授权的设计改变；重要行为选择来自已批准计划和已通过设计。若独立审查或真实组合发现质量问题，修复并复测后更新版本，不能把本次作者交接当整体完成。

## 5 交接结论

T-05—T-08 产品与作者自检已可接入下一阶段。代码暂冻结供非作者检查；已启动测试均有完成回执，作者没有在本目标账本留下未知运行、资源持有或临时后台进程。测试中的中断流程位于自动清理的隔离 fixture。

尚需独立实现审查、真实组合与最终整体交付验证。请按 [作者清单](../evidence/runtime/author-manifest.json) 核对源码版本；如其他作者改变包说明/运行器文件，整个 skill 树摘要也会变化，真实行为运行前应统一冻结并重采集，而不是拿本报告摘要代替整包版本。

### 附录：T-05—T-08 函数级实施细化

1. T-05：main 读取工作版本；EngineV2.configure 严格 schema；configure_payload 采集作者/需求/授权/来源；gate 保存独立结论；duplicate 在新操作执行前调用 assert_ready。复用旧图、问题及验证规则。
2. T-06：validate_monitor 校验排除；inventory 只采可监测摘要；impact_state 比较基线；impact 验证当前变更集合、保存判断和 invalidated_operations；target_scope 追加有效上下文；record_current 落实失效。
3. T-07：collect_pin/collect_sources 校验实际包及契约、保存源对象；executing_root 核对实际加载模块；effective_pins/valid_pin_hashes 追踪有效更新链；source_update/source 执行明确接纳与导出。
4. T-08：resource/required_resources/assert_resources 管交接；run 分开持久预约和真实执行；resolve_run/resolution_current/recovery_for 管未知副作用；attempt/diagnosis_state 记录诊断；state/inspect/brief/render_markdown 生成同源恢复视图。
