# 真实接口环境 smoke 的独立语义复核

**结论：environment-review-smoke / runs/002 的真实模型接口、工具执行和独立 review 业务行为成立。** 被测 agent 对未完成的账本 fixture 给出有实际入口和反例支持的拒绝结论，未擅自修复业务、串联其他能力或把测试绿当成交付通过。本次未发现阻断该环境 smoke 接纳的问题。

**这只是 baseline 环境 smoke 的有效性判断，不能计入 candidate 正式成绩，也不证明组合质量不下降。** 先前执行失败和 usageLimitExceeded 不由本报告改成通过或质量失败；原产物保留其原状态。

| 信息 | 内容 |
| --- | --- |
| 记录、日期、复核者 | 013；2026-10-16；`/root/contract_runtime` |
| 独立性与边界 | 复核者参与过编排运行时，但没有编写五项专业规范、账本 fixture 或本次被测模型报告；这里只评价该 standalone review 业务行为，不据此审查自己编写的运行时 |
| 被测身份 | baseline 的 delivery-review 契约 1；SKILL.md SHA-256 `086f50665ee436d231501399c6bae20a55b2d7c552af42dc128e23be8ff1b10f`；[sources.json](../evidence/behavior/environment-review-smoke/sources.json) 指向修改前冻结来源 |
| 真实模型与接口 | codex-cli 0.154.0，gpt-6-astra，effort=xhigh；ephemeral thread `01a1425f-9b86-7c33-9471-8cd90804bb32`，turn `01a1425f-9bfa-7732-bf8e-fdb679ca1c87` |
| 被审模型报告 | [实际 review.md](../evidence/behavior/environment-review-smoke/runs/002/artifacts/.delivery/evaluation/review.md)，SHA-256 `93c58f41dbaf25fbb1d0428971c21307855302f74ae65a9ff6aad2d93912985d` |
| 核心轨迹 | [appserver.jsonl](../evidence/behavior/environment-review-smoke/runs/002/appserver.jsonl)，SHA-256 `d396ff7720d0397dde5459aaee24e8014ea1ffe23eb45d62041ada2edc5818c8`；完整 427 行 |
| 其他输入 | prompt、requests、appserver-result、isolation、protected-files、before/after、完整业务文件、复现脚本及逐项结果；没有修改任何被测产物或原评测结果 |

## 1 真实接口与工具链

[requests.jsonl](../evidence/behavior/environment-review-smoke/runs/002/requests.jsonl) 有真实 initialize、thread/start、MCP 运行时库存核对及 turn/start；后者明确 externalSandbox、networkAccess=enabled、approvalPolicy=never。thread/start 的默认 read-only 不是本次 turn 的最终执行策略，不能只截取该默认响应作结论。

[appserver-result.json](../evidence/behavior/environment-review-smoke/runs/002/appserver-result.json) 保存 completed、error=null、CLI returncode=0，turn 约 215 秒。完整轨迹的 28 个 completed item 包含：12 个 commandExecution、2 个 fileChange、4 个 agentMessage、9 个 reasoning 和 1 个 userMessage。不是仅有最终文本或文件存在。

全部命令位置为原 appserver.jsonl 的第 51、55、57、63、65、67、71、148、154、165、254、269 行；两次文件补丁在第 158、261 行。逐条检查命令、写入路径和输出：

- 读取指定 review/SKILL.md、该包四个规范/模板文件；读取 README、app.py、transactions、业务模块和正式测试，列举实际产品文件。
- 在专业报告目录保存基线快照、skill 使用快照和原始指纹；第 148 行 heredoc 因 shell 临时文件权限被拒，exit=1；模型改用 python -c 后第 154 行真实执行成功。未放宽沙箱或删除失败轨迹。
- 第 158 行新增报告内 run_checks.py；第 165 行真实运行它，由其子进程调用实际 app.py 和已有 unittest；第 254 行读取实际结果。
- 第 261 行新增专业 review.md；第 269 行核对原文件指纹、报告链接和发现 ID，实际输出 changed_reviewed_files=[]、broken_report_links=[]。

因此成立的是“接口真实执行并完成了这个任务”，不是“任意命令环境均无问题”。heredoc 限制和后台 system-skill 安装权限日志仍是真实环境限制，报告未把它们当成业务缺陷。

## 2 只读业务与隔离边界

独立比较 before.json、after.json 及实际 artifacts：5 个业务/需求/正式测试文件均未变化，冻结专业包原文件也未变化。所有新增产品快照条目都在 `.delivery/evaluation/`：报告、基线/skill 使用快照、隔离测试输入、复现脚本、check-results。这些是被授权的专业报告及证据，不是修改业务实现或正式测试。

未见 Git、commit、push、外部联系、其他能力启动或运行时账本操作。fixture 没有 Git 或 `.workflow`；目录扫描排除了明确的 evaluator 派生设施，未靠 `.workflow` 或其他技能才能完成。

12 个命令和两个补丁中，没有读取全局已安装 SKILL、其他仓库、私有评分材料或 evaluation metadata；实际内容读取只涉及指定 review 包、公开业务要求和该 agent 自己生成的证据。rg 列举了 review 包自身 example 文件名，但没有读取其他技能内容。客户端可能仍提供基础指令/全局技能名称清单；本证据只证明实际内容读取和调用边界，不声称删除了所有客户端背景知识。

[isolation.json](../evidence/behavior/environment-review-smoke/runs/002/isolation.json) 的真实 canary 证明：私有仓库路径读拒绝、fixture 外写拒绝、fixture 内写允许、auth/config 写开拒绝。外层 profile 仍允许精确已有 installation_id 写开，不能描述成“主目录所有文件都不可写”；[protected-files.json](../evidence/behavior/environment-review-smoke/runs/002/protected-files.json) 表明 installation_id、auth、config 的 hash、mode、size、mtime_ns 前后相同。未更改 HOME/CODEX_HOME。

策略明确保留模型/API 网络连接，没有网络隔离保证；实际工具轨迹未出现网络读取或对外写入命令。本复核没有进行全系统 I/O 审计，结论限于实际 canary、原始调用轨迹及被保护文件前后证据。

## 3 业务语义与证据质量

README 明确要求按币种收入/支出/净额、共享契约、真实入口、金额与非法输入边界及联合测试。实际 app.py 仅 len(transactions) 并输出 transaction_count；ledger 为空壳，既有测试仅检查模块说明。模型正确把四类问题分开，均有公开要求和实际证据：

| 原问题 | 本复核判断 | 关键依据 |
| --- | --- | --- |
| R-001 汇总/两分支未交付 | 成立 | 实际 CLI 返回条数；正常、支出、金额、未知币种、空列表探针均未得到所需汇总 |
| R-002 共享契约缺失 | 成立 | 公开要求明确，业务模块只有说明且没有任何消费者；不是按文件名或设计风格臆测 |
| R-003 非法输入成功 | 成立 | 真实入口接受非法 amount、缺失/未知 kind、对象/字符串；null 样本失败被准确保留，没有夸大成全部非法输入都成功 |
| R-004 联合测试缺失 | 成立 | 正式唯一测试 import 成功，核心业务严重缺失却仍绿；专业探针没有伪装成正式交付测试 |

[run_checks.py](../evidence/behavior/environment-review-smoke/runs/002/artifacts/.delivery/evaluation/evidence/run_checks.py) 全文已核查：从实际 app.py 建 subprocess，不替换实现、不 patch 正式测试；17 个探针分别保存预期、返回码、stdout/stderr。已有 unittest 1 项通过；16 个 README 场景 15 不符、1 符合，另一个损坏 JSON 补充场景符合，合计 17 场景、15 不符。报告没有把复现脚本 exit=0 当成产品通过，也没有把这些样本数冒称完整覆盖率。

报告区分规格符合性、实现质量、严重度、阻断性和处置；不把 traceback 格式、函数/类命名、未知舍入策略和其他 README 未定义约束加入阻断要求。原作者未知、没有 Git、未做最终交付验证/发布/性能等限制被明确披露。报告可读、问题可行动、链接可定位，未用裸状态枚举代替解释。

本复核另外从保留 artifacts 只读重放了 README 示例、unknown_kind 及既有 unittest，分别得到 transaction_count=3、transaction_count=2 且返回 0、1 项测试通过；与保存轨迹一致。使用本复核实际 Python 路径 `/Users/cm/workspace/github/ppt-master/.venv/bin/python3`，加 -B，无业务或证据写入；没有冒称与被测环境 Xcode Python 3.9.6 完全相同。独立核算全部 before 条目内容 SHA-256，仍与 artifacts 一致。

## 4 接纳及后续

可接纳：该环境配置确实能完成一个真实 standalone review，报告边界和公开业务判断有证据支持。该结果帮助排除“只能初始化但工具链不能运行”的环境阻塞。

不可推导：candidate 五项成绩、完整组合可达、旧 workflow/当前 delivery/优化版的相对质量、大任务及恢复场景通过、没有任何隐藏客户端背景。正式比较需相同条件、冻结来源、真实 candidate 产物和非作者评审；usageLimitExceeded 按环境未执行保留，不计质量失败，也不能以此 smoke 抵扣。

本复核只新增本文件，没有改写被测模型报告、业务产物、评测状态或候选 skill，没有提交/push。
