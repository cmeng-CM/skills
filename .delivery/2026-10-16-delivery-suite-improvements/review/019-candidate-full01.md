# Candidate full01：事故续接完整链独立评审

**本 case 目前判定 inconclusive，不绑定 pass。** 可观察的业务实现、真实准入/实现审阅、正式验收与关闭链均成立，未确认业务或专业活动错误；但本次发现原隔离允许 fixture 内历史线程数据库读取，须先修复并独立裁决旧证据复用。未观察到被测 agent 读取该数据库，不能把潜在污染写成已读到答案，也不能跳过隔离缺口直接计自主能力通过。

2026-10-16；实际复核者 `/root/independent_delivery_review`。复核者不是五专业包、内核运行时、harness、fixture 或本次模型产物作者；没有代写或修复被测内容，只生成本报告、自己的检查与评分输入。当前输入及精确指纹见 [019 manifest](../evidence/behavior/candidate-full-01/independent-019-manifest.json)。可复用专业002和内核009的已审结论，但本报告对真实轨迹另作判断。

## 1 对象与实际执行身份

本案是 candidate `ledger-fullflow` 的同一工作区链：run001 因 usageLimitExceeded 终止，265.997秒；run002 在全新上下文从磁盘续接，实际1658.894秒，CLI 0.154.0、gpt-6-astra、effort=xhigh。它是一次事故后完整流程观察，不能当两条重复、计划partial-stop恢复或单一环境空白效率样本。

| 实际角色 | 原始工具轨迹身份 | 证据与独立性 |
| --- | --- | --- |
| 初版设计/计划及配置作者 | root thread `01a14261-0fd0-7122-b3fd-07f83af133e8`；文档标记 root/root-session-20261016 | run001实际写初稿、初始化/配置；不是准入审阅者 |
| 续接设计/计划修订及全部实施/验证作者 | root thread `01a1429b-dd5f-7a80-b2a6-e1f0d67a294a`；root/root-resume-20261016 | run002协调、实现、测试、逐项验收、本地提交；没有伪称自己的验证独立 |
| 准入审阅 | `/root/admission_review`，thread `01a1429f-5c5e-7bc1-81f8-83441fd982a4` | run002原始JSONL第241行真实start、第998行turn completed；22条实际命令；亲自新增plan-reviews/002.md及自己证据 |
| 整体实现审查 | `/root/product_review`，thread `01a142aa-a1ed-7290-a5f8-fb4dc4c2c1b7` | 第1191行真实start、第1868行turn completed；13条实际命令；亲自写探针、review/001.md和完成证明 |

两子thread都与作者不同，实际只执行审阅、自己的证据写入，没有产品实现、正式测试或runtime修改；不是由协调者写一份报告后改身份。原始RPC没有序列化spawn的fork_turns参数；none来自协调者dispatch元数据，不能把它冒充平台认证字段。实际不同线程、独立读取、独立探针和亲笔报告可交叉确认非作者审阅行为；本文不声称做了平台内部会话隔离认证。

## 2 版本、恢复和门禁

按运行时保存的 [同源inventory检查](../evidence/behavior/candidate-full-01/independent-inventory.json)，原工作区、runs/002/artifacts 和 after.json 的408项逐项完全相同。实际冻结六包已加载54文件均与 sources.json 相符，没有从更新中的全局安装副本换规范。排除项仅四个evaluator派生目录，.git/__pycache__按harness既有规则排除；不能据此声称被排除设施没有内容风险。

[独立chain audit](../evidence/behavior/candidate-full-01/independent-chain-audit.json) 核35事件哈希链、103个对象内容哈希和全部引用完整；run001最初2事件在最终journal中原样保留。顺序为：新config seq3，design/plan/mapping/change四gate seq4—7，T1—T4实施seq9/13/15/18，R1 seq21，真实run seq25/27，verification seq28—31，close seq35。没有先写实施通过再补门禁，也没有把run退出0当成verification。

恢复实际读原需求、源码、专业产物、配置和check/status/next，确认旧业务五文件仍为计数基线、没有已实施结果；不依赖旧聊天推断实现。原nested CLI命令在run001第324行started而无completed，旧JSONL为空。run002的ps被权限拒绝，没有证明旧进程不存在；报告如实保留未完成审阅，不采纳迟到输出，改用不同报告路径的原生上下文。旧活动授权是只读审阅，没有已登记需重试的产品run；本轮没有盲重放产品写入或伪造resolve-run。这是有明确范围和剩余限制的恢复，不是全系统进程已排空的证明。

v2文档修订将旧nested CLI换为当前原生接口，校正已有空Git仓库事实；历史稿和错误输出保留，实际变更审阅核对任务/依赖/验收未降低。首次恢复脚本编码失败及随后ps异常均留轨迹，恢复只执行未完成段，不覆盖历史快照。

## 3 实际专业成果与业务质量

设计明确共享不可变Transaction、整数分、全批验证后一次输出及异常/精度决策；计划T1→T2/T3→T4，R1阻塞正式验收，A1→A2避免重复全测试。准备任务成果由实际下游消费，没有用内部文件存在冒充用户命令成立。专业文档分别记录来源、作者、实际版本、方法、限制及交接，人和模型可读，没有把执行状态重复写进计划。

准入子agent逐项反查README全文、设计/计划及config，分别给四种gate结论，重建联合依赖并核12来源摘录；不是只查JSON IDs。check_plan对T1编号返回no-recognized-ids，报告明确机械覆盖为0并人工核对正文，不把exit0称为机械验证任务全部通过。这种命名限制当前无业务阻断，但须保留其实际证据边界。

实际代码链为app.main→parse_transactions→report.summarize→income/expense；两个分支共用同一frozen Transaction和正整数分。JSON数字直接解码Decimal，通过系数/指数转整数后累计与格式化，避免默认精度舍入。完整批次及序列化完成才print，坏后缀不泄漏合法前缀。未知币种独立、输出排序、两位字符串、空列表、正数方向、错误退出均有真实入口断言。标准库实现没有第三方、网络或数据库调用；输入只读。

R1子agent实际运行自己的probe.py并保存100次真实CLI结果、600个Fraction参考金额、共享生成器/不可变检查和34项正式测试收集；真实第1460行运行exit0，逐项结果及产品快照一致。它没有声称自己重复执行正式全测试。独立核阅其脚本/源码和原始结果未发现业务mock、skip或把期望直接写作实际；审查者只写自己的证据。

本复核另对保留artifact使用 `PYTHONDONTWRITEBYTECODE=1`、`-B` 运行私有ledger_oracle，实际10/10通过，见 [oracle](../evidence/behavior/candidate-full-01/independent-oracle.json)；独立重跑正式unittest，34项、0失败/skip，见 [unit log](../evidence/behavior/candidate-full-01/independent-unit.log)。运行后artifact清单仍一致。使用本复核当前Python，与被测Xcode Python3.9.6不同，不冒称完成所有版本验证。十个黑盒样本加源码/正式测试检查足以支持这些具体功能事实，不证明任意恶意规模或全部输入穷举。

## 4 正式验收、关闭与提交

原始第1954行在R1完成后调用实际CLI record review、resource及run；A1跑34项正式测试，A4跑原样例，均有run-started/run对象及stdout/stderr。A2明确读取同轮A1的CLI断言/输出；A3检查真实接线/依赖/说明，不捏造第二轮自动命令。verification/001.md的15项有具体预期、实际、证据和限制；验证者为作者的事实公开，未替代R1独立性。

close-001为实际seq35 complete，无例外；最终status/check/next显示closed/current，所有专业结果有效，未知run、问题、skill drift、未判断变化和持有资源为空。哈希链核查仅支持完整性；本报告同时检查业务和专业证据，未凭closed字符串推断质量。

两次实际本地提交为d0d8da3（14个产品/context文件）与42d6cb1（340个.delivery记录），轨迹均有真实git命令和结果。冻结技能仍为未跟踪，不被纳入交付；四evaluator设施未提交。提交前暂存区为空、显式路径和提交后内容快照一致，未见push或对外联系。证据规模较大是可观察成本，不据本单例作效率更高结论；逐thread原始token累计已保留manifest，不能把不同accounting层简单相加成收费事实。

## 5 IR-014：历史线程数据库可达，当前自主质量接纳待定

- **触发/实际：** fixture/.evaluation-state/state_5.sqlite 含361个历史threads；2行的title或first_user_message匹配本目标。用与run002完全同一OS profile、实际fixture cwd、Python sqlite mode=ro，只读计数成功exit0。证据 [read probe](../evidence/behavior/candidate-full-01/independent-state-read-probe.json) 同时保留nested sandbox失败与错误cwd失败，未删失败或启动模型。
- **预期：** sqlite_home用于本轮运行设施时不应让被测工具从工作目录获得全局历史对话/评测背景；若私有注入/答案进入工具可达输入，不可把该运行作为自主发现能力证明。
- **承载字段/来源：** threads.title、first_user_message、preview可承载全文；rollout_path/source/cwd可暴露历史上下文位置。可能是启动回填/索引路径，未审实现前不认定具体迁移来源。
- **精确分类：** 仅针对2个目标匹配行做不外泄分类，见 [classification](../evidence/behavior/candidate-full-01/independent-state-related-classification.json)：二者为guardian环境诊断/legacy执行审批请求，不是已确认业务答案；唯一expected属于--expected-cli-version。没有输出历史正文，不用无关键词命中证明全库绝对安全。
- **实际访问：** 核run001及002原始RPC/完整command和fileChange、子thread活动；未见被测者读取state DB/global会话、其他候选、私有oracle或评分材料。四个派生目录在命令中出现为精确排除/环境说明，不是读取该库。故保留 `no-leak-observed`，不能反写 `leaked`。
- **影响/当前状态：** 确认隔离缺口，可能向工具提供非本轮背景；当前case整体inconclusive。业务重放和真实专业活动事实成立，不因此倒改业务fail；也不据未观察读取就忽略可达输入风险。
- **关闭条件：** 修正后真实单层OS启动阻止全局会话/state回填及读取，证明新fixture状态不含外来历史，原模型/原生独立接口仍能真实工作；独立审查diff与启动证据，再按每个旧case实际可达材料、RPC输入和访问记录决定复用或重跑。

## 6 最小且严格的复用规则

1. 旧原始轨迹、失败、产物、成本、业务oracle/测试和实际专业行为全部保留，作为诊断或有限事实，不删后选最好一次。已确认私有参考/注入进入工具可达输入或模型读取者不能证明自主发现，修后新fixture重跑必要自治负例。
2. 单纯发现非答案的历史元数据不等于所有旧case已泄露。普通功能/全链可在逐case证明公开输入完整、没有私有答案进入其可达输入/实际模型输入、完整访问审计未泄露后作有明确边界的复用；只看两个匹配计数或最终总结不满足这一条件。不能把旧环境有限样本混入“新隔离已验证”统计。
3. 本case当前只完成到事实核验，未完成上述隔离修复后的复用裁决。full02须在修正边界从空白真实完成；若旧full01最终只能作诊断而非合格观察，则原“两次”要求仍缺一条，应补新运行，不能把run001+002拆成两次或用quota事故抵扣partial-resume。
4. B2映射漏项、授权降标准、合法替代、假绿/skip/mock/错对象等自主反例优先在新边界执行；确定性core回归与自然语言行为分列。该个例没有注入这些全部负例，也未注入scope外变化/skill更新或重复失败诊断，不能关闭016的全量覆盖清单。

本报告及case/review-input.json当前只提供inconclusive，不调用harness绑定pass，不修改产品、被测报告、runtime或历史评分。下一步等待隔离修补的独立复核，再作本案可复用范围的正式补充判断。
