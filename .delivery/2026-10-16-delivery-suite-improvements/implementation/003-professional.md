# T-04：五项专业 skill 内容完善

| 文档说明 | 内容 |
| --- | --- |
| 活动、作者、日期 | T-04 及 T-10 的五包专业案例定义；`/root/professional_skills`；2026-10-16；记录 v1 |
| 实施依据 | 用户批准本目标 [plan.md](../plan.md) 完整实施；[design.md](../design.md) v1.1 与[独立设计复核](../design-reviews/002.md)；root 明确放行五包编辑 |
| 专业规则 | delivery-implement 契约 1；本次依据迁移时未修改版本工作，来源可恢复于 `evidence/baseline/sources/delivery-implement/`；不是用自改后的规则倒推本次授权 |
| 产品基线 | `15aabb99b2666d213ea83dcaa7b16855b4f128b5` 加基线保存的未提交来源；迁移后专业文件逐个与基线一致；本次实际内容摘要见 [product-manifest.json](../evidence/professional/product-manifest.json) |
| 改动归属 | 独占五个专业包；没有编排包脚本、根导航、安装脚本或安装软链写入权限；没有提交或 push |
| 当前程度 | 专业方法、骨架、示例和维护用案例已形成；静态和检查器回归通过；实际 agent 行为与组合验证待主协调安排 |

五项能力仍然输出可读 Markdown 并维持专业契约 1。本次补齐设计/计划真实独立审阅的身份判断、阶段成果的实际消费者、共享资源和中断交接、问题客观关闭，以及 skip/mock/错对象的证据边界。没有把编排 v2 字段变成专业输入，也没有要求其他 skill、Git 或 `.workflow` 才能独立工作。

## 1. 依据与边界

对应 B1/B3/B7/B8/B9、AC-04，并为 AC-08/10/11 的专业验证提供规则与案例。编排决定何时需要审阅、如何绑定版本和能否推进；专业包各自规定怎样设计、规划、实施、审查和验证。实际设计审阅和计划审阅分别归 design/plan，implementation review 只检查实际交付物。

本次前置设计检查由本人作为非作者完成，随后本人实施专业文案。本人不是本次专业变更的独立审查者；后续须由未参与这些改动的 reviewer 检查。所有原专业脚本、自动选择策略、原 `task-workflow`/`design-tech-doc`/`plan-implementation` 保留。

## 2. 实际改动与产物

| 能力 | 实际变化与使用理由 | 主要落点 |
| --- | --- | --- |
| design | 从完整目标反查机制；区分作者自检、实际独立设计审阅与用户批准，记录身份与版本 | SKILL、references/review、专业行为案例 |
| plan | 修正“没有发现也不能声称独立评审”的笼统表述；专业审阅与正文→机器配置映射分开；阶段交付说明实际消费者，明确共享资源交接 | SKILL、plan-standard/review、plan-template、example-plan、案例 |
| implement | 工作树/index/测试库/生成目录写入交接；中断记录未回执动作和未知副作用，恢复先核查；独立调用无需专用 JSON | SKILL、work-rules/implementation-standard、模板和实施示例、案例 |
| review | 用实际消费者检验测试能否发现回归；按原性质与客观证据关闭问题，允许等价替代修复；重复失败不能成为放宽标准理由 | SKILL、work-rules/review-standard、模板和复审示例、案例 |
| verify | 识别空跑、全部 skip、全 mock 与错运行版本；区分替身子范围、真实结果、已知不符合和证据不足 | SKILL、work-rules/verification-standard、模板和验证示例、案例 |

基于迁移时摘要，共有 27 个专业文件发生有意变化，完整清单及当前摘要见 product-manifest；未新增专业脚本。既有规则和字段足以表达本次改进，重复判断自动化归编排维护，避免五包各造一套状态或脚本。

行为案例新增 11 个：design 2、plan 2、implement 2、review 2、verify 3；总数分别为 16、13、8、8、9。保留既有 request/prompt、expected/expectations/prohibited 等接口；运行器需明确规范化。案例中的预期和 fixture 构造说明只交评测者，不交被测 agent。**案例定义已写入，不表示 54 个案例已经真实运行。**

## 3. 实际自检及其限度

| 检查 | 实际命令/结果 | 原始证据与限制 |
| --- | --- | --- |
| 六包结构与链接 | `python3 -B delivery/delivery-orchestrate/scripts/check_suite.py --skills-root delivery`；退出 0，6包、42 Markdown、22 JSON、49本地链接 | [packaging.json](../evidence/professional/packaging.json)；只检查基本包装，不证明语义或行为 |
| 设计检查器回归 | `python3 -B -m unittest discover -s delivery/delivery-design/tests -p 'test_*.py' -v`；44/44通过 | [design-unit.json](../evidence/professional/design-unit.json)；检查器行为，不是设计质量评分 |
| 计划检查器回归 | 同上 tests 目录换为 delivery-plan；14/14通过 | [plan-unit.json](../evidence/professional/plan-unit.json)；不证明计划覆盖或图文一致 |
| 计划示例机械检查 | `python3 -B delivery/delivery-plan/scripts/check_plan.py delivery/delivery-plan/references/example-plan.md --json`；退出 0，ok=true | [plan-example.json](../evidence/professional/plan-example.json)；5条警告：P-01标题不被识别、四卡未声明可识别细化状态；无显式依赖表，未检查完整联合循环。示例采用语义完整的旧写法，不为消除警告改造全文 |
| 安装入口读取 | 逐个 lstat/readlink 并检查目标 SKILL.md；12/12有效 | [installed-links.json](../evidence/professional/installed-links.json)；本人只读，没有更新链接 |
| 原保护清单 | 439条中437条当前字节相同；README/CLAUDE 各有经本计划允许的 delivery 导航增补，已读 diff | product-manifest 保存实际差异；这两项由主协调修改，本人没有写入。旧专业体系及历史记录未发现变化 |
| 语义自检 | 对照 B1/B3/B7/B8/B9、已通过设计和模板/示例，检查职责、独立性与证据结论 | 作者自检；后续非作者审查尚待安排 |

未运行新的真实专业 agent 案例或完整组合；未把静态案例存在、54个定义或58个单元通过说成行为评测通过。五包真实独立调用、替代修复、消费者遗漏、skip/mock/错对象及新编排完整组合，由后续 V-06 的隔离运行取得证据。

## 4. 偏差、决定与遗留

- 五个专业契约保持 1：此次仅澄清已有质量方法和反例，没有新增必需输入、改变输出状态含义或调用权限；新编排强制门禁属于编排契约 2。
- 不统一重写五包现有行为案例接口：减少无关扰动；harness 规范化责任已反馈主协调。新案例沿用所在包格式，保留历史用例。
- 没有为模板/示例补专门测试：既有检查器回归和包内路径检查足以证明本次机械部分；新增质量要求需真实行为验证，不用文本包含测试冒充。
- 重大新需求或用户需重新决定的事项未发现。当前限制是尚无本次专业规则的独立审查和真实行为结果，不可提前宣布交付完成。

## 5. 交接结论

五包专业修改已形成可审版本，包内引用自足，迁移后安装入口有效。主协调可读取 product-manifest 绑定本版本，开始非作者审查和隔离真实行为评测；若后续改包，需刷新版本绑定并定向补验。未创建提交、未 push，工作区中仍有主协调与其他实施者的并行改动，本人未暂存或清理任何文件。
