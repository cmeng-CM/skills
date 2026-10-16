# IR-013 定向复审与评测器逻辑结论

**IR-013 已解决；当前评测适配器在已审逻辑与边界范围内通过独立审查。** 原旧版失败报告与反例保留。正在执行或已结束的真实模型案例，其专业质量、独立审阅、消费者结果和完整隔离轨迹仍需分别审查，不由此提前通过。

| 身份、版本与证据 | 实际内容 |
| --- | --- |
| 审查者、日期、独立性 | `/root/independent_delivery_review`；2026-10-16；非 adapter、校验器、正式测试或案例作者；未改产品 |
| 原发现 | review/011-harness-boundary.md 的 IR-013；原 probe 的 executed 误放行事实保持不变 |
| 本次 adapter | external_seatbelt.py SHA-256 `f8cf882162ada74dbfbeaf382e3e20133ccc8b9c384f2304a06ea91e447b9f92` |
| 实际来源与日志 | [012-recheck-manifest.json](012-recheck-manifest.json)、[012-external-unit.log](012-external-unit.log)：四个相关源码/说明/测试文件前后摘要相同 |
| 独立原反例及真实前置目录检查 | [012-shape-recheck-and-inventory.json](012-shape-recheck-and-inventory.json)；独立读取实际 wire response，不引用作者的审计通过代替检查 |
| 实际回归 | external 18 项通过；fake 本地 RPC server、边界构造与可控异常，不算模型质量或真实完整流程 |

## 1. 原反例和新判断

原两个输入 response={} 和 response={data:[{}]} 现在都返回 execution-failed，真实 requests 中均没有 turn/start。对照正例：完整 data=[]、完整 disabled-server 的空 tools/resources/resourceTemplates 都允许正常执行。没有把“所有 inventory 全拒绝”伪装成修复。

实际读取 validate_mcp_inventory 并对照本机导出的 0.154 schema：必需 data 数组；每个条目必需 object、name/authStatus 字符串、tools 对象、resources/resourceTemplates 数组；authStatus 使用实际五个枚举值，不能给未知值默认放行；nextCursor 仅 null/string，任何非 null（包括空串）都不能证明分页完整。完整非空能力仍拒绝。

结构有效与能力为空分别判定。新测试真实驱动本地 RPC 对端，覆盖缺字段、错误类型、未知枚举、非法 cursor，没有模型 turn 发生；旧的真实跨线程身份绑定、空 final、损坏 JSONL、进程异常和超时规则保持。达到 IR-013 客观关闭条件。

## 2. 已有真实运行的目录前提

独立从八份实际 appserver.jsonl 的 id=5 响应读取原目录，并核对 requests 是否已开始模型回合：

- environment-review-smoke/001：目录结构完整但能力非空，实际没有 turn/start，原拒绝事实正确保留。
- environment-review-smoke/002，以及 baseline/candidate/legacy 的 full-01、resume-01 各 run001：七份目录结构完整、nextCursor=null；均只含已 disabled 的 node_repl 元数据、空 tools/resources/resourceTemplates；开始模型回合符合这项前提。

这只是初始 MCP 前置条件检查，不是对全工具轨迹、私有答案未泄露或模型专业质量的结论。部分 wire 文件仍在增长，本报告保存了当时实际 id=5 内容，不将增长中的文件整体 hash 当成最终案例版本。因为这些具体前提本身有效，IR-013 不构成自动推翻它们的理由；无需仅为这项修复盲重跑模型。

## 3. 当前范围结论

结合 004、006、011 及本次实际复核，已知 adapter/判据发现 IR-002/IR-003/IR-004/IR-013 均完成技术关闭；本次没有发现未解决的确定阻断。准确的 config/feature/写入例外、保护文件检查、原始证据、精确派生目录排除和结果绑定保持已声明边界。

网络未隔离、全机读未封闭、全局 skill 描述可能存在、精确 installation_id 写打开例外和原生 multi_agent 保留等限制仍须如实报告。执行完成只表明本次协议根 turn 完成；专业产物、要求覆盖、真实消费者、独立作者和证据充分性由后续真实案例独立评审给出，不能将本报告直接记为 V-06 或全部交付通过。
