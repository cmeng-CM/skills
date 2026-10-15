# 运行时追加独立审查

结论：首轮 F-01 已在实际源码修复并独立复现通过；另发现 F-03，需要处理后才能完成整体审查。审查者仍为 independent_audit，未修改产品或正式测试。

## 依据与范围

延续 001-initial-independent.md 的需求与独立性，直接读取 delivery-orchestrate/scripts/delivery.py，对 issues/configure/record/close 的交互执行隔离探针。实际源码快照及指纹另存在 evidence/independent-runtime/delivery-followup.py 与 manifest-followup.json。此报告仅覆盖运行时修复与配置重组，不替代最终整体审查。

## F-01 复审

同版本同证据下，失败问题经复审解决，再写一份相同通过结论，F1 仍为 resolved，审查仍 passed。原独立探针未修改即通过，证据为 resolution-after-fix.json。实现将仍有效的历史解决记录纳入判断；新增测试另覆盖产品变化时历史解决失效。独立运行当时 54 项单测均通过；这不等于六技能整体质量已通过。

## F-03 配置重组可产生无法处置的历史阻断问题

严重度 P2；阻断当前交付；状态：已报告，待修复。规格要求计划拆并和变更保留稳定映射、原问题与处理路径，历史不能丢失，也不能使合法重组后永远无法收尾。

复现顺序：

1. 初始配置 T1 / R1 / AC1；实施通过，R1 提出阻断 F1。
2. 显式 configure 调整为 T2 / R2 / AC2，当前引擎接纳此配置。
3. 新 T2、R2、AC2 均录入当前通过证据。
4. close 仍因旧 F1 报 unresolved blocking issue。
5. R2 尝试为 F1 记录有证据处置，报 resolution must be by original finding capability and target；R1 不在当前配置，无法录入。

完整探针与原输出见 evidence/independent-runtime/probe_replan_issue.py、replan-before-fix.json。探针只检查状态机制，不把测试里的虚构 scope 确认当作实际用户授权。

建议：明确保存原问题并支持有依据的责任转接；若首版不支持，则在 configure 原子接纳前拒绝会遗留无法处置问题的变更，并提供可执行的先处置/保留原责任目标路径。不能通过自动删除历史 F1 或把其标为已解决修复本问题。

## 限制与后续

F-02 显式入口适配待最后核对。独立探针不代表模型全场景表现；其他三能力实际行为、组合闭环与安装尚待最终审查。修复由实现者完成，本审查者保留原失败并复查具体影响。
