# 024 · 旧 candidate review 单项实际行为评价

**overall verdict：inconclusive（旧环境 IR-014 隔离不足）；专业业务子结论：pass。** 模型正确识别未交付实现、未被绿色 smoke 误导，并保持只审不改边界。产品不符合要求是应报告的事实，不能反过来将这次专业发现判成 skill 质量失败。

## 对象、版本和边界

评审者：`/root/contract_runtime`。未参与五专业包内容、该被测业务或本案例模型专业报告的创作；近期参与了评测环境修补，因此本报告**不审、不批准本作者的环境修补**。范围只涵盖旧案例的实际专业行为、证据与限制。

旧运行采用 codex-cli 0.154.0 / gpt-6-astra / xhigh 的真实 app-server，run001 为 executed；完整 trace 中所有 started 项均有 completed 回执。已逐项读取全部命令、补丁、专业正文、探针实现和结果；只有指定专业包，实际没有 Git/.workflow。所有新增文件均位于 `.delivery/evaluation/`；README、入口、ledger、正式 tests 和样例前后内容不变，整个冻结专业包与 sources.json 一致。按 harness 既有 inventory（含缓存排除）核对当前工作区，与原 after.json 完全相同；这一产物一致性不证明环境隔离充分。

**IR-014 限制：** 此 run 的旧 profile 没有历史状态读拒绝，未具备后来新增的真实 table/schema/空库门禁。独立调查已证实相同旧环境可把全局历史线程元数据回填到 fixture 新库。下述“未观察到泄漏”仅是对实际工具轨迹的描述：未见读取历史库/评测设施内容、外部仓库、其他技能或私有答案，未见网络命令、委派、提交/push、安装或串联其他阶段；不能据此声称不可访问、绝对隔离或排除环境潜在影响。真实 MCP/稳定外部能力禁用和六项旧 canary、auth/config/installation_id 前后保护成立，仅支持当时实际测试边界。网络为 enabled，不作网络隔离声明。

本报告保留 **overall verdict: inconclusive**，不生成可接纳 pass、不执行 harness review、不改 evaluation 状态、不写回被测文档。业务子结论可以 pass，但不能自动计入严格隔离的新版能力成绩。后续由非作者审计旧结果复用范围，并在通过独立审查的新环境重跑关键自治案例；新环境证明不得回填旧 run。


| 对象 | 记录 |
| --- | --- |
| 案例 | `evidence/behavior/candidate-review-standalone-01/runs/001` |
| 实际模型作者 thread / turn | `01a142b7-9d85-77b1-8f0f-e2ea63ba000a` / `01a142b7-9de4-7f03-abc6-c118a4da7dd2` |
| 实际 skill / 契约 | delivery-review；1；SKILL SHA `ff7ae29d213da40a9301fe133969021309dad3d6a6eb5f7b725345f4b3782e50` |
| 专业报告 SHA | `5493a9ad4ab99c0f65e145754bad49ba36459a13fc06ea3381100cbefd0a6c54` |
| 原 after.json SHA | `08b40b7cff9289ddc5af537b7f803cbfd1a1ce2b0fde5235e52aeb2a07e7eb25` |
| 原完整 trace SHA | `a7523fef4fc0305469b5c01c8f8a5fd81672d205a431e98ed69267cc9a8e2099` |

## 全部实际链路

实际 11 个 commandExecution、2 次 fileChange；没有其他执行工具类型或不明在途项。trace 第 63、68、69 行仅加载 review 及必要规则/模板和 README；第 77、79、83 行读完整业务和测试；第 85 行核环境/设施；第 163 行保存五个产品文件及五个已读 skill 文件快照；第 169 行新增证据探针；第 176 行真实运行探针及原 smoke；第 269 行只新增审查报告；第 277 行比对原件、快照、目录集合和链接。未修代码、正式测试或需求，没有创建计划、执行账本或调用别的专业能力。

专业报告保存于 `runs/001/artifacts/.delivery/evaluation/review.md`。原始 `probe-results.json` 自报与逐条复算一致：26 个真实 app 子进程，2 个符合有限拒绝条件、24 个不符；已有 unittest 真执行 1 项并通过，无 skip。探针 wrapper 自身退出 0 只表示证据采集完整，不是产品通过，模型结论正确区分。

## 专业判断的证据与质量

R-001（高，阻断，未解决）：样例及正向场景只得 transaction_count，`__main__→main→json.load→len→print` 没有交易解析、共享契约、双分支或收入/支出/净额；完整 ledger 仅说明字符串。静态缺失与真实入口相互印证，合理合并同根因的格式、币种、空列表失败，没有按模块名或特定架构强行要求实现方式。

R-002（高，阻断，未解决）：P09—P22/P25/P26 共 16 类坏输入成功退出，合法前缀之后坏记录也被计数成功；null 和数字因 len 异常退出只覆盖相应有限拒绝结果。报告没有把“计数输出”编造成“部分金额汇总泄漏”，也没捏造 float 舍入 bug；仅退出码违约已足以阻断。规则未明确的超分精度政策、错误文案等未被额外制造成缺陷。

R-003（中，阻断，未解决）：正式测试只有导入和 docstring 断言，即使所有业务未交付也绿色；README 明确要求联合测试，因此这是验收交付遗漏而非风格偏好。模型自己的 26 个探针仍标为审查证据，没有冒充已补齐项目正式测试。

报告按规范分别给规格符合性和实现质量结论，稳定 ID、触发/预期/实际/位置、影响、严重度、阻断性与状态分开，并给等价修复可接受的客观关闭条件。修复方向交由调用方决定，未代写补丁、批准风险或自动启动 implement。已有 README 的“修改后说明”条件未在未知历史下被捏造成缺陷。当前作者身份未知如实保留；本次模型未参与被审产品实现，未通过切换 skill 声称独立。

## 接纳界限与后续

专业活动满足本案例审查目标；没有发现影响上述业务子结论的实质误判。它只覆盖首次审查一个简单缺失实现项目，不覆盖修复复审链、复杂并发、大任务或新隔离环境。原始完整证据在 case 的 prompt、sources、trace、before/after、protected-files，以及报告引用的 baseline-manifest、原文快照、probes.py、probe-results、existing-tests.log、integrity-check 中。

**此次不绑定成绩。** 不以旧工具轨迹中的 no-leak-observed 宣称旧 OS 边界充分；overall 保留 inconclusive，后续条件见共同限制。
