# 恢复归属与多次中断定向复审

**IR-005—IR-009 已完成独立定向复核；新发现 IR-010 可以复活已失效的旧结果并错误 close，当前核心仍不通过。** 本报告没有将 114 项测试通过或模型评测尚未完成的状态写成整体质量通过。

| 身份及证据 | 实际内容 |
| --- | --- |
| 审查者、日期、独立性 | `/root/independent_delivery_review`；2026-10-16；非核心、恢复规则、正式测试或修复作者；未改产品 |
| 依据 | 原 review/005-core、007-core-recheck、原失败 probes；implementation/007-runtime-recovery-set；计划 B6/B10、证据复用与恢复保证 |
| 本次范围 | repair-002 的 recovery_operations 集合、原 owner/config 绑定、record_current、显式 reuse 与跨配置交叉影响 |
| 真实摘要及回归日志 | [008-unit-manifest.json](008-unit-manifest.json)、[008-unit-log.txt](008-unit-log.txt)；执行前后五模块 SHA-256 相同，114 项通过（63 v1＋51 v2） |
| 原 IR-008/IR-009 独立序列 | [008-owner-set-recheck.json](008-owner-set-recheck.json) |
| 新 IR-010 原始事实 | [008-reused-impact-probe.json](008-reused-impact-probe.json)；完整只读保全见 [008-ir010-forensics/context.json](008-ir010-forensics/context.json) 与同目录 journal.json、五模块源码 |
| 测试范围限制 | 真实引擎/CLI 子进程和故障状态，不是模型专业能力评测；正式 V-06 与全局最终审查另行进行 |

## 1. IR-005—IR-009 关闭与反绕过

IR-005/IR-007 的可达 pin 与 baseline 链保持前轮修复，没有改回永久 blocked/break；原完整重判可恢复、失效祖先后的增量不能跨缺口、历史 invalidated_operations 不被后续无关判断删除的回归实际通过。IR-006 的原跨配置独立序列前轮已能 close，本次归档原配置证明和当前配置再调查保留，相关回归实际通过。

IR-008 原独立多验收组序列重新执行：A1未知→调查→真实 A1 run 与 verdict→真实 A2 run 与 verdict→close，实际 closed；A2 的 recovery_operations 为空，原未知的 replacement 仍指向 A1。原错误 owner 抢回执不再出现。邻近反例实际测试覆盖：A2 单独成功不能解决尚未重跑的 A1，A1 后续真实失败不会被 A2 成功掩盖，交叉 owner 的恢复集合直接校验不通过。达到 IR-008 客观关闭条件。

IR-009 原独立再次中断序列重新执行：X1→R1→X2再次中断→R2→真实 Y run 与 verdict，Y 的恢复集合实际包含 R1/R2；两条旧未知均保留原 operation，并都关联 Y 形成 settled，close 实际 closed。邻近测试实际覆盖：根调查过期使整个 verdict 失效、不同 owner 的调查集合分开、合法重配和未变结果显式重接纳；另有真实 CLI 连续三次中断后第四次成功的回归，本次确实执行通过。达到 IR-009 关闭条件，没有把早期操作改写为成功。

valid_run_recoveries 共享于验证接纳、record_current 与归档判定，核对完整集合中的 owner、解除所属配置和实际证据。单数旧字段按单元素集合解释，不改历史。这个结构改进解决了原回执归属与多祖先丢失，但以下跨配置复用路径仍绕过新的定向失效。

## 2. IR-010：再次重接纳从原配置回读，复活当前已失效结果

- **状态、严重度、阻断性：** 确认缺陷；高影响；阻断核心规格和质量通过，未解决。这次是错误放行和 close，不只是保守死锁。
- **触发顺序：** C1 完成 T1/R1/A1，全部 passed；C2 显式 reuse 这三条未变记录；C2 新增 shared.cfg，独立影响判断为 related 到 T1，实际失效 T1 及下游 R1/A1；没有修复、重新审查或新验收，C3 再次声明 reuse 同三个原 op。
- **预期：** 重接纳必须以当前 admission 的最新有效 rebound 结果为起点。已按真实相关变化失效的记录不能通过回到更早来源状态而复活；新配置的映射/change gate 不代替实现、实现审查和验收的重新证明。
- **实际：** C2 三项实际 stale，impact.invalidated_operations 为原三个 op。C3 configure 成功，gate 后同三个 op 又全部 passed，close 实际写入 closed。没有新增任何专业结果或产品修复；原 shared.cfg 的新增 context 也没有进入这些旧快照。
- **根因证据：** 复用入口继承 v1 configure 的回溯：从原始 record 事件取得原配置 C1，用其 record_current 校验，而不是对当前 C2 的 latest rebound 与失效集合校验。v2 为修复旧 pin provenance 保留回溯是必要的，但不能让“规则来源仍可追溯”变成“当前证据仍有效”。
- **完整事实：** 初次 probe 保存 C2=op-13、相关 impact 失效 op-5/op-8/op-11、C3=op-18 后同 op passed、实际 close。再次独立复现额外保存失败版本五模块原文、完整 23 事件 journal、C2 rebound/impact/extra_context 与 C3/close；context 明确未复制全部不可变对象库，不宣称该单份目录可独立恢复整个 fixture。
- **影响：** B6 的定向失效和有效证据复用保证被重配置绕过；大任务多阶段调整时可能把需要重新证明的实现/审查/验收当成当前通过。新 source-update 的 affected_targets 也应检查同类边界，避免只有 impact 修补而另一条失效路径继续复活。
- **客观关闭条件：** 同一序列 C3 必须拒绝复用失效三项，或保留其 stale 直到新的有效专业结果；不能通过改操作 ID、换配置或旧 pin provenance 绕过。合法来源兼容、任务/产物/报告未变的显式复用仍可用；计划正文在既有授权内细化不应无条件逼迫全部重做。新增当前有效 rebound 检查须区分来源 freshness 与专业证据失效，保持 v1 原行为及历史记录不改写。

## 3. 当前独立结论与后续

本次已解决的 IR-005—IR-009 保持技术关闭，不因新发现而抹掉已有进展；IR-010 是另一个明确问题。当前核心规格符合性和质量结论为**不通过**，不能开始将其作为正式完整组合的可信 close 依据。

作者修复 IR-010 后需要按原跨配置失效序列及合法复用正例定向复核，并检查 source-update 失效的等价路径。本报告没有修改候选源码、v1 引擎、验收要求或历史通过/失败记录；后续真实 agent 组合仍须绑定修复后的实际版本。
