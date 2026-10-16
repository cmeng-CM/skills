# 评测适配器边界更新独立审查

**当前适配器仍因 IR-013 不通过：损坏或缺字段的 MCP inventory 可以被当成空目录，在模型 turn 前放行。** 其他本次变化未发现新的确定阻断；真实已运行案例是否受影响必须检查它自己的完整目录与轨迹，不能由这个解析反例推断所有案例失效。

| 身份、版本与证据 | 实际内容 |
| --- | --- |
| 审查者、日期、独立性 | `/root/independent_delivery_review`；2026-10-16；非评测器、边界策略、案例或修复作者，未改产品 |
| 范围 | 最新 external_seatbelt.py、evaluate_suite.py、评测 README、两组回归；installation_id 精确例外/保护、六 canary、feature/MCP 入口、精确 runtime 目录排除、CLI 摘要 |
| 当前源码及回归 | [011-harness-manifest.json](011-harness-manifest.json) 保存五文件实际摘要和前后相同的检查；两个原始日志以 011-test_ 开头留在本目录 |
| 实际执行结果 | external 15 项、evaluate 24 项通过；本地受控 JSON-RPC 及进程 mock，不是模型能力或完整组合通过 |
| 独立反例 | [011-mcp-shape-probe.json](011-mcp-shape-probe.json)；损坏目录实际触发模型 turn 并被适配器判 executed；无真实模型调用 |
| 其他原始输入 | 读取 startup-installation-id-diagnostic-012/result/profile/request/stdout 的启动与保护事实，以及 environment-review-smoke 的残留 MCP 拒绝事实；不把这些环境证据算正式专业质量 |

## 1. 安装标识与真实写边界

当前 profile 不给整个用户目录、arg0、全局 SQLite 或 auth/config 写例外。只有 fixture 子树、/dev/null，以及实际初始化所需的既有 installation_id 精确路径可写打开。运行器在创建 profile 前要求该标识为预先存在的普通非软链文件、有效 UUID、mode 0644，不创建或修复它。

这是一项明确例外，不能把它描述为“所有工作区外文件完全不可写”。运行前后记录 installation_id/auth/config 的内容摘要和 mode/mtime/size；异常变化使状态 invalid-protection，不计有效质量证据。脚本不输出 UUID 或认证原文，也不自动用旧内容覆盖发生变化的文件。代码与可读说明当前对这些限制一致。

独立读取环境 012 的实际结果：六项 probe 的私有读与外写被拒、内写可用、标识 O_RDWR 可用、auth/config 的 O_RDWR 被拒；原生 CLI 0.154.0 initialize 成功且退出 0，model_turn_started=false，三个保护文件前后摘要/元数据相同。它证明这一环境启动与边界配置可工作，不能外推模型已完成实现、审阅或组合。

## 2. Feature/MCP、原生多 agent 与实际入口

显式禁用当前支持的 apps/plugins/remote_plugin/memories/shell_snapshot，保留正常原生 multi_agent；读取用户 MCP server 名后逐项 enabled=false，不使用未知试验开关、不覆盖 HOME/CODEX_HOME。turn 前仍查询真实 MCP inventory，暴露工具、资源、模板或未结束分页时拒绝。保留这一实际检查是必要的；原 smoke 检出自动注入能力并拒绝的事实没有被修改成成功。

当前未知客户端 RPC 继续拒绝，不给交互批准或任意 client tool 权限。已修 IR-004 的 thread/turn 双重绑定和早到通知缓冲保持；其他线程完成不等于本线程完成，commentary-only 不算最终结果。feature 开关和既有 MCP 名关闭不能代替实际能力目录，IR-013 正发生在这一目录的结构判断边界。

## 3. 产品清单、原始证据与输出

四个顶层 .evaluation-state/.evaluation-log/.evaluation-tmp/.evaluation-output 先于 before 清单创建，明确为评测派生设施；所有候选得到同一公开说明。仅这些精确顶层路径被产品快照和 artifact 副本排除；嵌套业务目录同名仍采集，实际回归验证了这一点。候选不能把业务代码/需求/专业报告藏进这些路径来规避验证，后续独立轨迹检查仍需确认实际用途。

正式模型输出、request、原始 appserver/events JSONL、stderr 和最终答复仍在 run 目录单独留存；review 用同一排除规则绑定当前实际产品清单，防止运行时数据库持续变化产生无关失效。CLI run 只输出 id/status/reason/seconds/output，函数 API 与文件保留完整记录，避免将巨大工具目录重复倾倒到对话而丢失上下文。

## 4. IR-013：缺必需目录结构被默认空值掩盖

- **状态、严重度、阻断性：** 已确认协议/边界判断缺陷；中高影响；阻断当前适配器审查通过，未解决。
- **触发：** mcpServerStatus/list 响应 result 缺 data，或 data 中的条目缺工具/资源/模板目录等必需字段。
- **预期：** 依据本机实际导出 schema，ListMcpServerStatusResponse 必需 data 数组；McpServerStatus 条目必需 name/authStatus/tools/resources/resourceTemplates，且类型可判。缺失/损坏必须在 turn/start 前拒绝，不能把“无法确定目录”解释成“目录为空”。
- **实际：** execute 用 inventory.get('data', []) 及 server.get(...) 的默认空值；独立实际驱动当前函数，result={} 和 result={data:[{}]} 均发送 turn/start，并最终返回 executed。证据中保存真实发送过 turn 的判定和源摘要 `b73c1f98f3ff7afa5de06e428fcb3ead850e579f95f3021036978191f41bc48b`。
- **影响：** CLI 协议损坏/不兼容时，实际无外部工具的前提没有成立就启动模型；违反损坏结果不能放行的要求。它不证明当前真实案例发生了损坏，也不证明私有答案已泄露。
- **客观关闭条件：** 解析前按实际 schema 验证必要结构/类型，未知目录保持拒绝；缺 data、非数组、缺 entry 必需字段、错误目录类型、非法 cursor 等反例均不得 turn/start。合法完整空目录可正常运行；完整非空能力继续拒绝；正确原始目录与失败记录留存。可做最小必要结构检查，不要求引入通用 JSON Schema 平台。

## 5. 结论与后续

installation_id 例外、前后保护、精确派生目录、真实配置/feature 描述和摘要输出在本次范围内符合已确认边界；IR-013 仍使适配器整体规格与质量结论不能通过。修复后按原两条反例及完整合法/非法结构定向复核，不需因此重跑所有已有真实模型案例。

对正在运行或已结束的正式案例，应分别检查其实际 MCP inventory 是否完整且无外部能力、保护文件是否不变、实际 profile/原始轨迹是否符合约定，以及业务与专业产物本身；完整有效的旧实例仍可保留为其实际版本证据。正式案例质量结论和完整组合比较另行独立评审，不在本报告预填。
