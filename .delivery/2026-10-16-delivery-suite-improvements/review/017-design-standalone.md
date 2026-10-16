# 017 · candidate design 单项真实行为独立评审

结论：**pass**。技术方案覆盖公开需求，具体机制可据以实施，恢复和检查证据诚实，活动保持独立设计边界。无阻断性发现。该结论只接纳本小型项目的这一条两段恢复链，不证明整套编排、大任务能力、设计已获用户批准或功能验收通过。

## 对象、身份与版本

本评审者为 `/root/contract_runtime`，未参与五项专业 skill 内容、该案例文档或案例业务代码的创作；此前参与编排运行时实现不构成本案例专业产物的作者。检查对象为真实 prompt、两段完整 app-server 工具轨迹、冻结技能来源、README、业务基线、专业正文及索引、前后清单和隔离记录。未把模型自述或机械检查直接当作语义通过。

两段均使用 codex-cli 0.154.0、gpt-6-astra、xhigh、真实 app-server/externalSandbox；run001 的 CLI 退出 0 不等于模型完成，原 turn.failed / usageLimitExceeded 与空 final 保留。run002 是新 thread，读取磁盘原稿后续检，不是另一个独立成功样本，也不因换上下文构成独立审阅。run001 after 与 run002 before 清单逐项相等；两段所有 started 工具项均有 completed 回执，没有不明在途工具被冒称完成。

泄漏判断为 **no-leak-observed**：工作区实际只装指定一个专业包，没有 Git 或 `.workflow`；完整执行项限于本地事实核查、指纹、指定文档检查及本案例专业文件补丁（设计案例另只读运行既有入口和冒烟测试以核实现状），未见外部仓库、其他技能内容、私有答案或评测元数据读取，无提交、push、网络命令、对外联系或子 agent。局部文件名检索不是读取其他技能。MCP/相关功能按实际配置禁用；两段六项隔离探针通过，installation_id 的精确 write-open 例外及 auth/config 的前后 hash、mode、mtime 均保持一致。网络策略为 enabled，不能把“未观察到网络调用”写成网络被隔离，也不能声称所有系统目录或全局目录在物理上不可读。两段实际加载配置的摘要不同是跨运行环境事实，各自受保护文件未变，不能归因为模型改了配置。

使用当前 harness 原有 `inventory(workspace, latest.product_snapshot_excludes)` 核对实际工作区，结果与 run002 原 after.json 完全一致；沿用既有 `.git`、`__pycache__` 排除及四个明确派生设施目录，没有扩大 excludes 或清理缓存来伪造一致。全冻结包文件均与 sources.json 的 loaded_snapshot 一致。仅运行 `python3 -B` 只读文档检查器作独立机械复核，未改候选 skill、业务、原记录或 evaluation 状态；最终接纳由协调者运行 harness 绑定。


| 版本对象 | 实际值 |
| --- | --- |
| run001 作者 thread | `01a14263-924d-7d23-b304-c90e105c7485` |
| run002 作者 thread | `01a142b1-2b44-72b0-9a62-16234ccf8faa` |
| frozen delivery-design / 契约 | SKILL SHA `9b55dfb526eb7146671e6dbeed9ba6aee2051f6152d7b7a95287a3cfafb651d6`；契约 1 |
| 原稿 v1.0 SHA | `0190f6c1cdf19c7ef99eb69d2512fb3743a1986ad58e7bff5ff9f5867164fea9` |
| 最终方案 v1.1 SHA | `d3727e561d33ddbe189b04a5417eeb57edca50ac29684afd06c36ea363c82729` |
| 本次绑定 run002 after.json SHA | `8721c9d777d9abc120e6d67270f83d600e391c5d95b22796717297b1ea9f91d7` |

## 实际行为与恢复链

run001 实际完成 11 个命令、1 次补丁（新建 design.md 与 index.md），之后额度中断。第 82 行 heredoc 被权限阻止，后续第 89 行换 python -c 成功读取同一事实，没有绕开目录权限。第 179/181 行实际入口输出仍为 transaction_count=3、原导入 smoke 1/1 通过。初稿把机械检查留作未完成，没有伪造检查成功。

run002 完成 19 个命令、1 次补丁，只修改这两份专业文档。轨迹第 58、70、74 行读取原稿、源码及样例；第 145 行核对原 11 项来源；第 153、155 行重新实测现状和既有 smoke；第 157、175 行机械检查均 0 错误/0 警告；第 163 行补全 v1.1 及索引；第 173 行再次核对来源和链接。业务、README、样例、测试、冻结包在两段前后均未变。原 1.0 内容仍由 run001 artifacts 留存，正文有准确替代关系。

## 语义评审

- README 的币种隔离、未知币种、空列表、排序、三字段两位字符串、正数 amount、kind 方向、精确到分、所有指定失败及无部分输出，均映射到 G1—G7 和 A01—A17，附明确输入、方法及预期。既有计数行为与目标输出明确区分。
- 共享规范化先全量校验、不可变且可重复消费的交易序列、两个实际业务分支、报告合并币种并集、真实 main 调用链均有确切接口和错误责任；不把分支单测当作接线证据。
- 数字直接 Decimal 解码、精确系数/指数转分、整数累计与格式化避免 float 及默认 Decimal 上下文舍入；缺侧补零、支出正额、负净额与负零规则一致。全量处理并序列化之后输出，覆盖合法前缀后出现坏记录的反例；stdout 设备断开与输入原子性分开说明，没有夸大事务保证。
- 对金额尾零/科学计数、币种空白、字符串金额等局部边界，显式标成模型在本案质量优先授权内的选择；并非伪造用户逐条批准。没有改变公开范围、舍入或引入依赖。容量未设硬承诺，潜在长金额/大文件资源成本已披露。
- 六个必选及适用可选主题完整，图表与正文一致；第 4.4 节组合推演有具体失败和隔离机制。机制/验收口径属于设计内容，没有变成实现任务分配或启动计划。

独立机械复核再次返回 0 错误/0 警告，只支持结构结论。业务新功能尚未实现，A01—A16 仍待单独授权和实际验收；run002 作者明确自检≠独立审阅、交付≠批准。本报告没有替其补造批准。

## 证据入口与剩余界限

主要原始证据位于本案例 `runs/001/`、`runs/002/` 的 prompt.txt、appserver.jsonl、appserver-result.json、before/after.json、protected-files.json、isolation.json，以及两段 artifacts/.delivery/evaluation/design.md 和 index.md；sources.json 固定技能来源。最终方案的 11 项来源指纹本评审逐项复算一致。原始 trace SHA：run001 `d1b70d9a42c263ed4a4f78299139ab63d35a4dc9410c90e4fa2ff64a2a7eeac9`；run002 `88d36ae6bb738bb4c16fd5e881c6cb1b11f11f8921930868dc8c13a396d9a232`。

没有发现需修正文档才能接纳的缺陷；本样本不能外推生产容量或多任务组合质量。报告及 case 内副本、review-input.json 为本评审新增文件，未提交或写入模型工作区。
