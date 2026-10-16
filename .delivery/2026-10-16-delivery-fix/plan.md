# Delivery Fix 接入决定与实施计划

状态：用户已授权实施。基线：4a47c70a3c37b39e849a7c6759dd0481d6f36f78，开始时工作区干净。

## 已确认约束

新增 delivery-fix，复杂故障诊断、授权修复、自检和留存；独立不依赖 Git、其他 skill 或 .workflow。组合中可选承担 implementation，不替代独立审查、验证或 close。

同 bug 固定 fixes/BUG-ID-topic/，每轮 NNN/fix.md 与 evidence/；index 只导航。重要诊断连续记录，正式交接或被下游使用后冻结，新轮次关联旧记录。区分实验、缓解、根因修复及证据程度，不强制稳定复现。

## 具体接入

顶层编排契约2，专业fix契约1，实施接入子契约1。显式 enable-fix 使用 schema_version=2、contract_version=2、actor、implementation_contract_version=1、reason，写 implementation-protocol 事件。旧v2未知事件拒绝；启用不准入、不解除未知运行、不执行命令。已有配置须先接纳实际编排源码，启用同操作可幂等重试。

configure 可选 implementation_routes，按任务声明 {skill: delivery-fix, bug_id, bug_path} 或 {skill: delivery-implement}，缺省implement。接入字段与fix来源仅启用后可用。选择变化须正常配置和适用gate；不能复用受影响的旧通过。

record 类别仍 implementation；fix 必填 implementation_skill 与非空 implementation_authors（含实际actor）。报告限定 bug_path/NNN/fix.md；回执绑定实际专业pin。历史作者与本轮作者累计，用于审查排除、来源审阅和brief，配置不能清除。未知真人/遗漏作者不能靠脚本认证，由接纳者核实。

## 任务与验收

| 任务 | 成果 | 依赖 | 验收 |
| --- | --- | --- | --- |
| T-01 | 本接入决定、旧引擎快照 | 用户授权 | 新旧解释边界明确 |
| T-02 | 自包含fix九个文件 | T-01 | 内容规范、例子、目录与恢复一致 |
| T-03 | 可选路线、真实来源、完整作者链 | T-01、T-02专业接口 | 不选fix正常，选择后质量门槛保持 |
| T-04 | 文档、包检查和评测入口 | T-02、T-03 | 声明与实际一致 |
| T-05 | 有限机械回归和两次实际agent场景 | T-04 | 原始证据、报告和限制可查 |
| T-06 | 独立审查、交付、安装与本地提交 | T-05 | 无未处置阻断、不push |

## 验证与停止条件

V-01：包、元数据、本地引用、内容语义。V-02：新路由/作者/来源/失效/未通过阻塞/旧CLI拒绝/启用幂等与恢复，加直接相关原回归。V-03：独立修复与组合转交/续接各一次实际agent执行，受控故障明确为演练。V-04：独立源码与实际产物审查。

测试通过后不因再次保险重复全量验证；只对新修改、失败或明确缺口做必要复验。证据缺失保留未验证，不伪造通过。

## 执行和恢复

本计划只定义任务；后续报告记录真实结果、skill与产品版本、环境、失败、未完成命令及下一安全动作。恢复先核对文件和现场，复用有效证据。重要验收改变、历史迁移或明显范围扩大反馈用户；普通实现细节按本方案处理。
