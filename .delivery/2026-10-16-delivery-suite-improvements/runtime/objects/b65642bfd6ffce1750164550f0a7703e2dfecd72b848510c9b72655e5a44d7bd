# Harness 历史隔离、产物采集与评审历史独立复核

**最终结论：IR-014及其两个已报相邻反例已关闭；当前未发现仍阻断本次实体实现接纳的问题。** 最终external为 `665550103ceb4450db1b137e17235b9eac03c0470bde15b7bc75e7200cc3ba40`。runner采集与评审历史修补可接纳。以下第1—4节保留先前阶段事实，第5节给出最终定向关闭依据；不把修补证明回填旧模型成绩。按用户最新收敛要求，没有再跑全套测试、新模型或新增案例。

2026-10-16；实际复核者 `/root/independent_delivery_review`。非被审external、runner、测试或case作者；只写本报告和自己的隔离证据，未修改产品、旧run、业务工作区或控制状态。

## 1 第一冻结版本与真实证明

external_seatbelt.py SHA-256 `5b5dd7902114e028a3d4cd2c560231693d33f04c9b7fc5a671f17830efe2f3c4`；独立重跑28适配回归通过，源摘要前后相同，见023-external-unit.log和023-environment-checks.json。

独立核对024源码快照与上述实物相同、profile与isolation摘要相同，47项canary符合已定义预期。真实RPC仅initialize、initialized、thread/start、mcpServerStatus/list，无turn/start；实际新库threads=0。证据见023-original-024-evidence-audit.json。旧同fixture四文件/侧文件保留且被拒读写，新run独占子目录和现有全局历史入口拒读改善真实成立；不能因后续反例把这些事实改为未发生。

## 2 尚未关闭的两个相邻反例

| 触发与预期 | 实际与证据 | 影响及关闭条件 |
| --- | --- | --- |
| 未知schema不得假装“真实空历史库”；同名view/无关表不等于CLI线程元数据表 | inspect_state_database仅COUNT(*)。创建threads(other TEXT)即passed；另库中private_history有1行但threads为空view，同样passed。缺库、损坏、缺表确实抛错；真实非零返回passed=false。全部独立反例在023-environment-checks.json | 不能声称unknown shape fail-closed。应核当前受支持CLI的最低实际threads表形状/类型并核计数返回；异常/不认识的结构须留拒绝事实，保持正常真实启动正例 |
| 新fixture也不得读取已经确认污染的另一评测fixture旧状态 | 在024原profile与实际cwd，用只读SQL仅计数candidate-full01旧state5，真实exit0、361行。见023-other-fixture-state-probe.json，无模型或历史正文输出 | 当前只封自身旧state，已知入口可从旁边fixture再达。最小对受控临时根的其他评测fixture及明确已知旧状态入口拒读，当前workspace/新state作精确例外；加跨fixture及alias真实canary。无需封闭整机或改HOME |

root已认定两项属于IR-014同一闭环并交作者。这里没有据“361行”宣称包含本案私有答案；已确认事实为历史元数据可达，而非模型已读泄露。旧成绩仍按019的inconclusive及逐案复用规则处理。

## 3 Runner 两项冻结修补

冻结evaluate_suite.py为 `c08ff7f8fbd7fa889d06835a936fe1b15c60d0c1a3633902c2ecd15eae8c2a73`，test_evaluate_suite.py为 `be68d0f8fe2daf69a9cc0447a54a22bc7881cf7abcd0b237efa471e67dff1d95`。独立29项回归通过、前后源码摘要一致，见023-harness-checks.json与023-harness-unit.log。这些是设施回归，不计模型能力。

产物采集与prepare分开：prepare仍拒来源软链；collector用不follow的fwalk与目录fd相对stat/readlink/open(O_NOFOLLOW)，复制普通文件并记录链接原字符串，不解析或重建内部/外部/循环/失效链接。四运行目录与原Git/cache规则保持，原始after仍有实际链接身份。独立真实文件系统探针验证.workflow普通证据存活、循环/悬空/外链不导致丢弃或复制外部内容、artifact不含可逃逸软链、source清单未变，见023-live-collector-probe.json。正式case评审应将artifact普通文件与artifact-symlinks.json一起对照after，不能要求物理副本重新建立外链，也不能忽略原链接记录。

review在全部身份/版本/证据验证后用排他创建append history-NNN，保留被接纳的真实value、evidence_versions、run_id、after摘要、时间与case/evaluation身份。current两个镜像仍表示最新；新run清current但不删history；拒绝输入不生成已接纳历史。实际回归覆盖同run pass→inconclusive、拒绝输入不改旧历史、新run使current失效而历史字节不变。该最小修补符合原T-09原始证据留存，不需要新评分状态机。旧未自动保存的记录不能伪造回填；root此前手工抢救属于独立历史事实。

本阶段runner两项未发现新的阻断。旧artifact采集失败保留原状态，不能用collector单测回填为旧run executed；未来真实run需新采集回执。后续environment源码/runner若再变，按实际diff补审，不以本阶段29项覆盖未知新改动。

## 4 待最终复核

等待两个环境反例修补冻结，独立重跑原例及同profile真实拒绝/新空库证明，随后向root给是否可启动新真实模型的明确门禁结论。环境门禁通过仅允许进入真实行为评测，不代表新模型完成或旧成绩自动恢复。正式完整病例/自治反例以及控制006仍待后续相应证据。


## 5 最终定向复核：关闭已知缺口并收敛

本次仅重现第2节已报两类原反例，没有扩展威胁面或重复整套检查。

- 原 `threads(other TEXT)` 现在以元数据schema不兼容拒绝；原有历史表但空threads view现在以非真实表拒绝。最终实现检查普通threads表、9项最低列/类型、id单主键以及COUNT单一非负整数；读取/SQL/结构错误和非零结果保存failed startup audit，任何turn/start之前拒绝。原反例重现见 [023-ir014-final-recheck.json](023-ir014-final-recheck.json)。
- 使用025保存的**同一实际profile、同一cwd、同一旧candidate-full01路径**重放原只读计数：过去可读361行，现在exit1、`sqlite3.DatabaseError: authorization denied`且stdout空。见 [023-cross-fixture-final-recheck.json](023-cross-fixture-final-recheck.json)。初始结果解析只认Operation-not-permitted拼写而误标false，证据保留该解析事实；依据真实SQLite权限拒绝修正解释，没有再运行或改原始输出。

025源码快照与最终实物逐字节相同、profile摘要一致；独立核对181项真实canary记录与实际RPC，只有initialize/initialized/thread/start/MCP目录核对，无turn/start。新库为普通表、最低9列及idPK/0行；现有40列不被错误要求逐列完全相等。全局/当前旧state/侧文件/其他fixture（含原full01）双alias拒绝、profile生成后新兄弟fixture拒绝、当前workspace正常读写由原025真实证据支持。8项非规范前缀状态路径从可信output的workspace元数据取得，不读取历史正文；旧文件和auth/config/installation_id保护未变。

最终34项适配回归由作者及最后唯一统一247项检查留存通过，本次不重复执行；其适用源码与冻结003一致。上述两个原例由本非作者亲自定向复核，不仅采信作者测试数。

因此IR-014当前已知实现缺口已关闭。该结论限于已审本机CLI0.154/profile/目录及启动门禁，不是网络或全机器封闭保证；没有新模型工具链/组合执行成绩。旧环境case保持原隔离限制和inconclusive，不自动接纳为新环境自主能力。

用户最新要求停止反复测试、转真实工作验证，故本报告此前“环境通过后启动新模型”等调度建议不再执行；不是因重复次数未完成而继续扩建设。尚无真实工作证据的能力由最终026/verification收敛记录单列，不擅自修改强门禁或关闭目标。
