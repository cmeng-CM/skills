# Baseline完整组合01：业务观察与待裁决接纳

**业务观察符合本案例共同要求；最终quality接纳为inconclusive。** run002真实完成设计、计划、实施、非实现者审查、逐项验收和complete关闭，实际入口满足公开规则。旧外部适配允许历史metadata进入运行设施，虽然本次工具轨迹未观察读取，仍不能由业务通过替代隔离裁决；本报告不调用review绑定。

| 身份与边界 | 实际事实 |
| --- | --- |
| 评审者 | `/root/behavior_harness`；编写过harness/fixture/oracle，未参与被测业务实现、设计、计划或其专业报告。非盲评，只对该业务产物和轨迹做非实现者观察；评测器与全套仍交另一审查者 |
| 来源与运行 | baseline-full-01，run001额度中断原样保留；run002为同目标恢复，不是两次成功样本。CLI0.154.0，gpt-6-astra/xhigh |
| 本轮真实root | `01a142ac-1173-7110-92c9-0d45d35f6a83`，turn `01a142ac-1219-76b0-84e9-11fe8870c733`，completed/error=null |
| 真实业务审查者 | 子thread `01a142ad-159f-7331-8093-f1718632e641`，原生独立执行、三次实际审阅turn均completed；未修改业务、正式测试、设计、计划或runtime，只写本轮审查和隔离证据 |
| 最终对象 | after.json SHA256 `b0a720972a10b14ebed428e59f2bbc1ac8799921bd059e67756cb5abf953e924`；349项实际清单与artifacts一致；业务产品提交63b0270，记录提交251ee6f |

## 1 共同业务要求

已读取README、全部ledger源码、app.py、全部六份正式测试、USAGE、设计/计划与实施、三份审查、三份验收和交付导航。真实调用是app.main→build_report→parse_transactions→summarize_income/summarize_expenses；全量验证产生同一不可变交易元组，两个分支依kind累加整数分，report按币种并集排序、收入减支出，CLI完整序列化后单次输出。没有只新增未接入模块。

金额以Decimal解码/提取系数，再用整数分计算，避免二进制浮点和默认Decimal上下文舍入；未知币种独立、空列表{}、正原始金额由kind定向、两位小数字符串和负净额均落实。非列表、非法金额、kind缺失/未知及坏后续记录在stdout产生成功内容前拒绝，实际非零且无部分输出。仅标准库，没有新增网络或数据库；公开需求、样例及原smoke未被降低。

本评审在root完成后以PYTHONDONTWRITEBYTECODE=1真实执行私有oracle，**10/10通过**；复跑正式测试**36项通过，无skip**，完整argv、版本、输出和退出码保存于review-020。重放Python版本是本评审当前环境（详formal-tests-run.json），不能冒称原作者Python3.9.6同环境。运行前后采用run002冻结inventory规则，与原after及artifacts逐项完全相同，未改产品。测试中的wraps只是观察真实分支，另有真实CLI子进程与独立动态调用证据，不是mock绕过集成。

## 2 审查、修复与逐项验收

原始run002共2339行app-server轨迹，74个完成的commandExecution和22个fileChange；started/completed无悬空项。已按thread/turn核对，不把三个子turn的完成当root完成。完整命令、输出、文件变更、子代理活动与最终消息索引在trace-002.json，对应原始JSONL的行号与摘要；run001另留trace-001.json。

非实现者实际首审发现R-001：共享契约承诺拒绝非字符串kind，但UserString可被接纳并在验证后改变交易方向。该缺陷不能由普通JSON直接触发，报告正确限定低严重度，却按明确设计契约阻断，未自行豁免。协调者先真实登记failed，再改contracts与回归，原审查者复查当前修复及影响后登记passed。首轮失败与稳定R-001链未覆盖。随后整体独立审查重新读取全产品/正式测试，实际执行36项测试及21组真实CLI探针，动态观察两个分支收到同一72条元组；报告、raw与实际子thread支持独立性，不能仅凭名字判断。

设计和计划覆盖全部公开要求、四任务、提前契约审查、整体审查和三验收组，启动图无自锁。v1基线按其真实协议运行，没有强加candidate v2新格式。正式A-01/A-02通过编排run实际取证；验收报告逐项比较输入、输出、失败契约、环境和版本，A-03说明内容与真实独立性。验证者也是实施者的事实透明，独立性由另一真实审查者承担，没有冒称独立验收。

最终18个journal事件包含failed→修复→passed、两个真实run与三项验证，最后close-ledger-001为complete。raw行2111实际close成功，2115再次check/status确认closed；收尾报告不独自代替CLI。只做本地显式提交，未观察push；未跟踪.agents是冻结输入，不是未交付业务。

## 3 恢复与判断边界

run001是usageLimitExceeded，不计成功或模型质量失败。其after与run002 before完全一致。恢复上下文读取真实既有设计/计划/账本及产品/skill指纹，只T-01已完成；旧委派无回执不当成通过，重新启动真实非实现者。ps被OS拒绝时如实保留系统进程不可核实，没有伪造全局进程检查或杀未知进程。账本无悬挂run、产品稳定且没有外部副作用，继续本地工作具有实际依据。

所有已观察命令仅读冻结skill、当前项目与其专业证据；未观察私有评测答案、其他候选源码或历史state内容读取。原外部canaries/protected-files均通过，auth/config/installation_id保持不变；这是当时边界的真实事实，不等于已证明历史隔离。旧adapter可导入全局历史metadata，当前单独修复不改变本次原环境。泄漏观察是no-leak-observed，完整隔离裁决仍待独立审查；不声称绝对没有历史上下文。

本例有明确共同业务符合证据，未发现README范围的实现阻断。有限oracle与测试不证明无限资源、跨平台或所有大任务；不以本例推出质量不退化的统计结论。候选间最终比较应保留本限制及实际失败样本，不用平均分覆盖退化。

## 4 接纳材料

本报告副本、身份/泄漏观察、完整trace索引、oracle和复跑原始记录均在案例review-020，review-input.json绑定run002原after摘要、verdict=inconclusive，单列业务结论与隔离待裁决。未调用harness review，也没有写任何旧评分历史或修改评测状态。root最终裁决后方可决定后续接纳，不能把此报告改读为已完成quality通过。
