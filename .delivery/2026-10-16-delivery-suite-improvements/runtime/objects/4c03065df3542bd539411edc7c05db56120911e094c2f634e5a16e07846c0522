# IR-010 定向复审与核心独立结论

**IR-010 已解决；当前冻结运行时核心在已声明的审查与反例范围内，规格符合性和实现质量均通过独立审查。** 这项结论仅覆盖运行时、其 API 和确定性恢复/证据机制；不代表五项真实模型调用、完整组合、大任务质量比较或最终全部交付通过。

| 身份、来源及证据 | 实际内容 |
| --- | --- |
| 审查者、日期、独立性 | `/root/independent_delivery_review`；2026-10-16；未设计、实现或修复核心及正式测试；没有修改产品 |
| 原问题 | review/008-core-owner-set-recheck.md 的 IR-010；原错误 closed 事实和完整旧源码/日志保全不变 |
| 本轮来源 | `evidence/runtime/frozen-repair-003/delivery/` 固定包；本次执行从固定包实际导入，不从活动包运行再谎报另一 pin |
| 与交付源码关系 | 十个运行时、测试、契约/API 文件逐字节核对活动工作树一致，结果见 [009-reuse-recheck-probes.json](009-reuse-recheck-probes.json)；其他作者可能仍改评测设施，不把固定包中的旧 harness 自动算最终版本 |
| 当前核心摘要与日志 | [009-unit-manifest.json](009-unit-manifest.json)、[009-unit-log.txt](009-unit-log.txt)；固定五模块前后摘要一致 |
| 实际整组结果 | v1 63＋v2 55＝**118 项通过**；24.665 秒；真实 CLI/子进程回归与可控日志故障反例，不是模型行为 |
| 当前门槛 | IR-005—IR-009 原关闭结论与反绕过回归保留；本轮关闭最后已知核心发现 IR-010；V-06 及全局交付仍待真实证据 |

## 1. 原三配置反例复核

与原失败一致：C1 三项实际 passed→C2 显式复用原结果→C2 shared.cfg 相关 impact 导致三项 stale→C3 试图复用同三个原 op。当前 API 明确拒绝 `cannot reuse stale latest rebound result from current admission`，原 C2 配置保持不变，没有新增 configure 或错误 close。

另外独立把中间失效源换成 compatible source-update 的 affected_targets=[implementation:T1]；其通过兼容性本身不能抹掉受影响结果，三项实际 stale，同一 C3 复用也拒绝，配置保持不变。修复作用于当前有效 rebound，覆盖两条定向失效来源，不是只匹配 impact 反例。

实际阅读 configure_payload：每个 reuse 先定位紧邻 old_config 的 latest rebound，校验操作身份和 `record_current(ignore_config=True)`，而原专业 pin 仍按真实 provenance 解释。原来源可追溯与当前证据可复用不再混为一件事。v1 原方法未改，本次新增要求只在 v2 接纳边界执行。

## 2. 合法复用与上下文继承

独立运行以下正负例，具体状态见 probes：

| 场景 | 实际结果 |
| --- | --- |
| related impact 后新形成有效实施/审查/验收，再显式 reuse | 允许；验收当前 passed |
| C2 新判断的 shared.cfg 进入 C3 | target_scope 实际包含 shared.cfg 与 src；继承没有丢失 |
| 之后再次编辑 shared.cfg | implementation 实际 stale，不能继续依赖旧结果 |
| 仅合法细化计划说明，产品/报告/任务语义未变 | 明确 reuse 后可 close，未因旧来源文字变化强迫全部重做 |
| 将已继承 shared.cfg 伪称生成物加入 exclude | 实际拒绝 exclusion overlaps，不能隐藏相关输入 |

API v2 已如实说明紧邻配置 rebound 校验、合法 source refinement 的 ignore_config 边界、原 pin/恢复链追溯、继承 context 与稳定 owner 限制。上下文保守继承进入 target_scope 与 exclude 检查，共用实际派生状态，没有新增独立权威状态表。

## 3. 原恢复修复的相关回归

本次独立实际运行完整 118 项，而非引用作者的通过结果。日志覆盖：完整 source/impact 重判可恢复、失效祖先后增量不得跨缺口、历史失效不复活；已恢复未知按原配置解释、真证据过期后当前配置可重查；多 owner 不串回执、多次中断携带完整调查集合、根调查证据过期整体阻断；真实 CLI 连续三次中断后合法完成；原 pin 与已恢复链的明确重接纳；最新真实失败不能被旧成功或其他 owner 成功掩盖；资源交还后正常 close；原 v1 兼容回归。

这些结果连同先前独立原反例，支持 IR-005—IR-010 技术关闭。不是因为测试数量达到 118 才判断通过，而是原触发、预期性质、实际失败和相邻反绕过分别得到证据。

## 4. 当前独立结论和剩余工作

运行时核心的规格符合性：在已审范围内满足；实现质量：未发现未解决阻断，原恢复/复用缺陷经实际修复复核。机械事件、版本、身份冲突、引用和快照不证明自然语言判断真实或遗漏为零，调用方仍须完成实际专业独立审阅和映射核查；资源协议仍只是本工作内合作约束，命令执行也不是沙箱。

本报告不接纳或改写本目标控制账本。后续需把当前核心与最终评测设施、六包入口共同冻结，对真实五项独立活动、完整组合、恢复及同环境比较的实际产物和轨迹作独立评审，最后才形成全局实现与交付结论。若核心再改，按真实差异重新评估本报告适用性，不沿用旧摘要提前关闭任务。
