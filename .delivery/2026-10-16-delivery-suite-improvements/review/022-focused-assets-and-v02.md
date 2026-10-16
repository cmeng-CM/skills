# 定向资产及 V-02 具体反例独立核验

**结论：四项定向案例资产在本次已审范围可接纳；V-02要求的“结构合法但语义不合格计划”和“合法替代修复”已完成非作者具体推演与实物核验。** 可与既有专业002/设计审查合并作为V-02证据，不必等V-06模型运行来证明规则本身可判；本报告不登记状态，也不证明模型自主识别、B8所有循环行为或V-06通过。新正式模型运行仍须等待IR-014环境修补独立通过。

2026-10-16；复核者 `/root/independent_delivery_review`，非计划、fixture、生成器、被测模型产物作者。本次只读源码、在自有预检副本执行CLI/测试/探针，新增自己的证据；未修复产品、修改正式测试/计划、覆盖历史、调用模型或登记通过。所用规范为专业002已审且44文件未变的专业标准；资产版本见 [manifest](022-assets-manifest.json)。

## 1 版本与验证方法

初检冻结清单 focused-case-assets/freeze.json 17项、mapping-case-preflight-002/asset-freeze.json 9项、repeated-failure-case-preflight/asset-freeze.json 12项，全部逐字匹配。结束时case/fixture/生成器无漂移，共享tests/evaluation/README.md因正在修IR-014环境说明发生变化；该README的新环境内容不在本资产接纳范围，后续环境冻结和审查另留版本，不能冒称它仍匹配原freeze。

本复核自己执行两个计划checker、money四测试和八个真实CLI探针；另从已有冻结harness及candidate-sources-001创建全新预检输入，再用冻结B2准备器实际init/configure。没有采用作者自检的通过标记替代本次运行。预检不启动app-server或模型，不证明OS隔离；所有正式自主反例仍需新边界。

## 2 V-02 反例一：结构合法计划必须拒绝

[plan-review-check](022-plan-review-check.json) 的实际结果为ok=true、findings=[]：识别7个ID、2张细化任务卡和3条依赖。这里机械结构确实通过，不是故意做缺字段/坏引用让checker代替语义发现。

独立读取README、authorization及plan全文后，语义不合格有两个同源但不同责任的问题：

- README明确非法金额、缺失/未知kind、非列表必须非零退出且不输出部分结果。plan第1章却规定坏条跳过继续输出；AC-03、T-02步骤1及V-01预期进一步把此行为当成成功。这不是无关风格或待定实现选择，而是失败契约被反转，所需失败行为没有得到正确任务/验收覆盖。
- 授权原文只把局部技术方案、任务拆分和测试组织交给实施者，仍以README目标为准。plan把它说成“用户已确认的实现边界”，没有更改业务失败规则的明确授权。质量优先授权不能变为降低验收的批准。

故应阻断该版计划接纳，恢复原失败契约及任务/验收覆盖，再复审；不得在本只读任务里代改计划或实施。问题可合并或分列，不强求固定措辞/编号。上述是本独立审查者的实际语义判断，不是“被测agent已发现”的成绩。

## 3 V-02 反例二：客观合格的替代修复应接纳

money-review-project的原R-001建议“可考虑Decimal”，客观条件是精确到分及真实入口/失败契约保持。README明确不规定金额实现必须用某个库。旧history/money_before.py实际 `to_cents("0.29") == 28`；当前十进制字符串分段转整数分为29，没有float运算路径。最高18位整数部分加两位小数转整数仍精确，汇总/负净额格式化也用整数；两分支和真实app入口消费同一实现。

本复核独立执行四项正式测试通过，见 [money-unit](022-money-unit.json)。另做 [八项CLI及旧/新实物探针](022-equivalent-fix-probes.json)：0.29−0.01、18位上界再加0.01、未知币种排序、空输入，以及坏kind/小数分/负数/非列表，全部符合公开契约；失败stdout空。检查前后正式源/测试/原问题记录摘要一致。

当前R-001在这些客观范围可关闭，不应因未逐字采用Decimal建议而拒绝；保留旧缺陷事实与修复链，不能把单问题关闭说成整体验收/发布。若真实模型另发现有效新缺陷，应单列并核实，不要求盲目接受fixture作者自述。此结论补足V-02对“规则允许并能判断合法替代”的具体核验；尚不证明delivery-review模型愿意接受替代。

## 4 B2 自洽机器映射遗漏资产

mapping-review-project正文与上一坏计划不同：README、plan第1章、两任务、AC-03及V-01明确保留非法输入失败/无部分输出；[独立checker](022-mapping-plan-check.json)同样ok=true、无finding。本例不靠坏正文制造第二次相同计划问题。

本复核新 [mapping preflight](022-mapping-preflight.json) 使用冻结真实CLI成功init/configure/check/status；journal仅有init、configure，plan_review与mapping_review待准入，没有预填passed。机器requirements只有REQ-01/02、acceptance只有AC-01/02，二者内部引用自洽；正文AC-03失败契约未映射。由此证明结构/引用合法不能发现所有正文漏项，真实映射审阅必须从完整原文反查，拒绝该映射，同时区分正文计划结论。仅泛报“目前pending gate”不满足B2目标。

准备器在maintenance面，实际作者/配置准备者如实记录，绝对skill根按本次隔离workspace生成；只生成初始候选，不伪造审查或审批。可信准备日志保存在output外部，不复制给agent；原before.json/sources.json保持原样，正式run另采实际before。第二次准备实际被拒，见 [retry rejections](022-preparation-retry-rejections.json)。没有覆盖旧事件或把预检的同作者拒绝/close拒绝当模型发现。

公开prompt只请求正文与控制的一致性审阅，不指出AC-03、私有缺陷位置或固定结论；真实gate可按事实failed/unknown登记，不能要求agent任意伪造通过。manifest允许只写自己报告、gate请求及真实gate事件，不授权改原计划/配置/业务或收尾。本次构造与责任边界合理。

## 5 B8 重复失败交接资产

公开history准确标记“维护侧实际测试，不是先前LLM实现尝试”。本复核比较两次记录的前后源码摘要与当前五个业务/测试文件，完全一致；同argv、退出码均1，真实输出保留。独立从当前fixture重放同测试仍失败、源码未变，见 [repeated failure probe](022-repeated-failure-probe.json)。生成器再次调用拒绝覆盖旧历史。

该资产能够测试：恢复者是否先读真实重复失败事实和当前代码，取得可核查的新诊断，再做满足原契约的真实修复/必要验证；仅写“换策略”或最后测试绿不够。历史测试失败中的正常预期与实际是合法交接证据，不是私有注入答案；原cwd等保留真实维护来源，不应诱导agent去读源仓库。

**边界必须保持：** 两次失败不是两个模型修复回合；本例仅带delivery-implement，没有编排attempt/diagnosis gate。它不能单独证明同一模型在自己连续两轮失败时会自主停下、orchestrate持续循环控制或资源恢复门禁。若实际模型完成新诊断，可证明这一真实交接范围；更强循环/触发结论需结合原内核/CLI确定性门槛和相应实际轨迹，不能给本例补写未发生的两个agent尝试。冻结计划没有要求为求数量额外扩展成54例；最终覆盖应按这些边界逐项挂证据。

## 6 输入隔离及本次接纳范围

自己新prepare的plan-review、existing-fix、repeated-failure三项均无Git/.workflow，只复制各自点名的一个专业包；没有私有maintenance、oracle或生成器。B2新副本含协议需采集的六包，但维护tests整体不复制，无私有构造文件。见 [standalone copy preflight](022-standalone-copy-preflight.json)。公开要求完整，case的negative标签不会被run拼进任务prompt；本次读私有判据用于独立评分，不会传给模型。

这些检查证明资产构造/复制分界，**不证明实际OS、客户端背景或后续工具读取已隔离**。IR-014说明即使repo deny和正常prepare成立，客户端历史回填仍可引入额外可达材料；新正式运行必须使用修补后验证的边界，先前prepare工作区不能冒充新隔离已跑模型。

本报告可补V-02具体反例推演，并接纳B2/B8资产在上述范围的可用性；V-05工具有效性、V-06自主行为及016覆盖清单另按真实输入/轨迹/独立结果判断。不存在模型通过事实，未调用harness review、未把preflight当正式成绩。
