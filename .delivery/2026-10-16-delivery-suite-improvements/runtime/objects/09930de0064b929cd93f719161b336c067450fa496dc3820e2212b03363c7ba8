# 契约与接入实施记录

记录 C-009；2026-10-16；报告版本 1。范围 T-02，依据 plan.md v1.1、design.md v1.1 和 authorization.md。作者为 `/root/contract_runtime`（API/契约实现）与 `/root`（设计及集成说明）；由协调者整理。生成规范为 delivery-implement 契约 1，实际专业来源提交 `197b989`；本目标仍由基线 v1 引擎控制。

编排接入升级为显式契约 2，五专业契约维持 1。新规范把正文审阅、机器映射、真实授权、影响判断和恢复事实分开，保留旧契约续接。规范与实际引擎已接受独立检查；真实模型组合质量仍待评测。

## 依据与范围

本次落实 AC-02、AC-03 的接入定义，供 T-04—T-08 实施使用。设计审阅见 design-reviews/002.md，计划与映射复核见 plan-reviews/004-mapping-recheck.md。没有修改原 task-workflow、design-tech-doc、plan-implementation。

## 实际产物

`delivery/delivery-orchestrate/references/contracts.md` 定义各能力承接内容、语义演进、实际来源和接纳边界；`runtime-api-v2.md` 定义准入、来源、影响、资源和恢复命令。`runtime-api.md` 保留 v1 并明确版本导航。源码分派由 delivery.py 接入 v2 模块，省略版本仍保持既有 v1 行为。

## 检查与证据

review/009-core-reuse-recheck.md 独立复测核心与 118 项回归，关闭 IR-005—IR-010；review/010-integration.md 复核版本导航和专业边界，关闭 API 路由歧义 IR-012。这些结论没有替代实际模型行为验证。最初失败和修复记录仍保存在 review/005、007、008 及 implementation/004、006、007、008。

## 决定与遗留

没有原地升级历史 v1 账本；需要 v2 保证时显式建立关联目标。源码实际 pin 包含未提交内容，不仅依靠 HEAD。来源更新与证据过期均需重新判断；已失效记录不能通过回溯早期配置重新复活。以上属于批准设计内的质量要求，没有降低验收。

## 交接

契约和 API 已形成，可供专业能力接入与运行时实施使用。最终统一机械检查、真实组合及整体独立审查尚未结束，不能据此关闭 AC-11。核心已本地提交 `ac24bc3`，没有 push。
