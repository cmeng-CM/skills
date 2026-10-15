# delivery-verify 负向行为记录

结论：隔离检查同时存在一项不符合和一项未验证。命令退出 0 没有转化成验收通过；未知项不能通过带限制交付豁免。

## 依据与对象

验证者 independent_audit，2026-10-15；按已加载 delivery-verify 契约 1 的规范执行。规则快照见 ../live-example/docs/delivery/2026-10-15-label-prefix/evidence/independent-verify-001/。本次对象是 probe_zero_failure_unknown.py 创建的隔离 API 夹具，不是用户真实业务产品。夹具明确 A1 的 stdout 应为 READY，A2 需要真实人的操作记录；实际仅生成并执行 print("BROKEN")，没有真实人工操作。

所有夹具 actor 和 authorization 字段为合成测试输入；不将它们当用户授权、独立审查完成或真实人工验收。实际验证活动只对观察到的命令结果与状态门禁负责。

## 方法与执行

执行 `python3 -B docs/delivery/2026-10-15-delivery-suite/evidence/independent-runtime/probe_zero_failure_unknown.py`。探针通过真实引擎 run 启动 Python，读取原始 stdout 对象，再读取状态；随后分别录入不符合与未知的语义判断，尝试以 limited 豁免未知以检查拒绝路径。

完整输入操作由 probe_zero_failure_unknown.py 保留，实际输出见 zero-failure-unknown.json。引擎自己不把退出码 0 变为通过：执行后 A1 仍 pending，逐项判断后 A1 failed、A2 unknown 同时存在。门禁探针合成批准仅用于确认 unknown 被拒绝，不是申请本任务例外交付。

## 逐项判断

| 项目 | 预期与实际 | 结果 | 证据与后续 |
| --- | --- | --- | --- |
| A1 业务输出 | 预期 READY；真实 stdout 为 BROKEN，退出 0 | 不符合 | zero-failure-unknown.json 的 exit_code/stdout 与 state；若为真实产品应反馈实施，不能只改测试预期 |
| A2 人工操作 | 需要实际人的操作与观察；本次没有发生 | 未验证 | 缺少具体人员、动作和观察，不编造；只能等待所需条件 |
| 编排保留差异 | 要求失败与未知不混淆 | 符合本次机制检查 | 状态同时保留 failed/unknown；V-F1 未被清除 |
| 未知不可豁免 | limited 不能吞掉缺少证据 | 符合本次机制检查 | 实际拒绝：only currently evidenced failed criteria can be excepted; not unknown/stale/pending |

## 限制与交接

本次是审查者编写的确定性隔离探针加实际语义判断，不是盲测，也不证明任意模型都能识别退出 0 的错误业务输出。夹具不修改正式 runtime 或正式测试，不修改业务要求。A1 的失败和 A2 的未验证保留；探针成功验证了这些门禁，不把夹具业务描述成验收通过。没有真实 limited close 成功，也没有用户接受缺陷的事实。
