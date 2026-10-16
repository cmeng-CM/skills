# Legacy完整组合01：1800秒内未完成，部分业务观察

**run002在1800秒预算后timeout，完整组合要求未满足，不能计为成功。** 已落盘的实际业务入口通过本评审私有oracle10/10与正式54项测试；这些只证明冻结部分产物功能，不补造root完成、整体终审、A9、verify或close。旧历史metadata隔离还需独立裁决，最终quality仍inconclusive，未调用接纳绑定。

| 身份与版本 | 实际事实 |
| --- | --- |
| 评审者与独立范围 | `/root/behavior_harness`，写过harness/fixture/oracle，没有参与该业务设计/实现/专业报告；非盲业务观察，不是评测器自身独立审查，整套仍交另一审查者 |
| 运行与预算 | legacy-full-01，CLI0.154.0、gpt-6-astra/xhigh；run001额度中断保留，run002实际1800.415秒timeout，不是两次成功样本 |
| root | thread `01a142ac-1a6a-70f3-a9bd-fdbd68bb33ce`，turn `01a142ac-1ad8-7e63-a545-6d918140a8b5`；无completed、无last-message |
| 实现者 | 原生子thread `01a142af-1798-70c3-bbc9-4233db5b001b`，实际写业务、正式测试与T5文档 |
| 独立审阅者 | 原生子thread `01a142ac-cff8-77d3-ad01-48336cc939f6`，计划与各任务只读审阅；不同于上述实现者，没有把昵称当独立证据 |
| 冻结实物 | run002 after SHA256 `a1f3e76ecf92a10a08f8a700987edfb9ade04c8b442288563261eb2c04e8ffe4`，112项；HEAD cd948f1，后续没有替被测者补提交或批准 |

## 1 预算结束时真正完成与未完成的范围

完整5680行原始app-server轨迹显示110个已完成命令、14个fileChange。实际启动了两个原生子代理；11个子turn completed不能驱动root成功。最后仍有一个agentMessage只有started/delta而未completed，最后没有root turn/completed或最终答复；这与adapter timeout、无last-message一致。完整命令/输出/patch/子代理事件/完成turn索引保存在review-021/trace-002.json，并保留原始行号与SHA。

T1–T4共享契约、两个分支、report及实际app入口已形成，并有真实独立任务审查。T5提交了使用说明、实施记录、逐项验收草稿和交付核验脚本，真实报告明确下一步仍需独立T5审查、计划快照、整体终审、A9和workflow verify/close。冻结.delivery实际只有design/implementation/acceptance/verify_delivery.py，没有plan.md与review.md；acceptance.md的A9仍为PENDING。

原始核验脚本在缺产物时实际退出1，报告没有抹掉失败或假填全部PASS。已结束的子实现者说T5 DONE只针对自身文档任务，不能当整体交付完成。root超时前未完成后续收束，因此**此共同full案例在给定预算内未达到硬性完成要求**。这是一项有效的未完成/受限观察；不强迫旧候选全绿，不擅改原skill、预算、提示预期或用户批准。

## 2 已落盘业务的独立部分检查

按root安排，只在run002冻结artifacts重放，未触碰原工作区或与后续root并发测试。PYTHONDONTWRITEBYTECODE=1，真实私有oracle10/10；正式unittest54项全部通过。命令、实际Python版本、cwd、时间、完整stdout/stderr和退出码均保存。采用本run冻结inventory规则，重放前后与原after112项逐项一致；没有修改源码、测试、专业报告或旧证据。该环境是本评审当前Python，不能冒充作者Python3.9.6同环境。

已读取实际业务链、关键CLI/契约测试及验收记录。共享parse_transactions全量验证后返回不可变Transaction；amount通过十进制系数转整数分，两分支分别累加；report先物化可迭代输入，避免生成器被第一分支耗尽，再按币种并集排序并求净额。app读取真实JSON后依次调用共享解析与report，序列化成功才stdout输出。实际CLI覆盖两方向、未知币种、空输入、负净额、数值/字符串金额、精度、排序和失败无部分输出。CLI正式测试不是mock返回值；少数wraps用于观察真实调用，另有真实子进程和生成器检查。没有发现README范围的已确认业务阻断，也不以此免除尚未完成的流程要求。

README补充了使用说明并更新初始Git状态描述，原公开功能与失败规则保留，没有以修改验收凑绿。仅标准库、本地模块；没有新增网络或数据库依赖。

## 3 旧工作流实际有价值的机制与限制

独立计划审查真实发现T5/A9完成条件自锁：T5要求完整核验绿，但计划快照和整体终审只能之后形成。控制器修订启动顺序，把完整门禁移到真实终审归档后；原独立者定向复核确认阻塞解除、最终要求没有弱化。该失败和复审原文均保留，没有为等待用户批准而停住这项已授权局部组织调整。

随后采用真实任务片段、独立实施者、每任务规格/质量审查与本地提交，T1–T4审查来源可追溯。复用同一未实现业务的审查线程不会自动失去独立性；仍须核对实际写入范围。T5把重要局部决定归位设计并明确当前证据/缺口，这些观察对原workflow机制有价值。但其文档/核验/收束组织在本次预算内未完成，不能因机制丰富就假定交付成功，也不能从一个超时样本断言所有旧workflow必然失败。

run001因usageLimitExceeded而失败，另有未配对的commandExecution started；当时曾尝试嵌套Codex独立评审，没有据此取得有效独立通过。run002真实读取恢复材料，改走公开环境指定的原生工具。原run001 after与run002 before相同；没有重建空目标抹掉中断。恢复材料没有把旧嵌套尝试当成功；系统进程查询被拒的限制如实保留。所有原始未知和失败记录仍在，不把它们补写成模型已完成动作。

## 4 泄漏观察与接纳范围

实际工具读取限于冻结task-workflow、当前项目与其.workflow/.delivery材料；未观察私有答案、其他候选或历史state内容读取。原canary/protected-files通过只说明当时所验证边界；旧adapter仍可把全局历史metadata导入评测state，no-leak-observed不等于绝对无历史。该环境问题保留待独立裁决，修复后的新adapter不追溯改变本次环境。

review-input.json以inconclusive绑定run002原after，明确complete_flow_verdict=not-completed-within-budget、partial_business_verdict=pass-within-tested-snapshot。因实际run为timeout，当前harness本就拒绝把它绑定为成功运行的quality review；此JSON只是可追溯观察输入，不能绕过规则使用。没有执行review绑定或改原evaluation，没有创建缺失文档、补批准或追加假close。

完成后的新共同样本应按原授权、同环境和预算另行真实执行。本案例的timeout和部分业务实证独立保存，不选择最好片段覆盖未完成事实。候选自身仍必须真完整，不能以旧候选未完成降低新组合质量要求。
