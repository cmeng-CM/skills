# 历史线程元数据隔离修补

结论：已修补 external-seatbelt 的历史回填与旧 fixture 可读入口；最终真实无模型启动通过，28 项适配单测通过。未启动新 LLM，未重新接纳旧行为成绩，待非作者审查修补和旧证据复用范围。

## 身份、来源与实际根因

作者：`/root/contract_runtime`。授权来源：协调者明确要求修补独立评审发现的历史元数据回填；本作者不再承担该适配修补的独立审查。原发现留存在 `evidence/behavior/candidate-full-01/independent-state-metadata-audit.json`，只报告 361 条及聚合 marker 计数，没有导出标题或消息。旧评测、旧 after、数据库和失败轨迹均未删除或改写。

实际阅读本机官方 Codex checkout，HEAD `61a44880a85d2fd0d8770908dea5733495e571c8`，无 `.codegraph`。`codex-rs/rollout/src/state_db.rs::try_init_with_roots_inner` 将 sqlite 配置用于目标 StateRuntime，却把原 codex_home 传给 `wait_for_backfill_gate`；`metadata.rs:218` 起扫描原 home 下的 sessions/archived_sessions，提取元数据并 upsert 至目标新库。`sqlite_home`、ephemeral thread、关闭 memories 因此不足以切断历史来源。相关确切片段、文件摘要及提交标识保存为最终探测目录的 `official-source-evidence.json`。

其他被禁读的 history/session_index/memory/全局 SQLite/global-state 是现存可被工具直接访问的持久历史入口；没有把它们都声称为此次自动 backfill 的来源。`session_index` 与全局 SQLite 的路径另由源码确认；global-state 名称来自本机目录元数据核查，没有读取其内容。

## 修改范围与执行保证

| 文件 | 实际修改与理由 |
| --- | --- |
| `delivery/delivery-orchestrate/scripts/external_seatbelt.py` | 增加 OS 历史读拒绝、已有目标真实 canary、旧 fixture state 读写拒绝、每 run 新 state、真实空库门禁和无模型启动路径；最终 439 行，未引入通用引擎 |
| `delivery/delivery-orchestrate/tests/test_external_seatbelt.py` | 真 SQLite + 本地 fake RPC 的确定性边界回归，包含可读历史立即拒绝、非零/缺表库不发 turn、旧状态隔离、alias、不能重用 state、新启动不发模型请求；fake 只用于维护测试 |
| `delivery/delivery-orchestrate/tests/evaluation/README.md` | 说明真实回填根因、OS 范围、必要父目录 metadata 例外、旧结果审计与不外推限制 |
| `scripts/evaluate_suite.py` 两处关联 | 固定 six-canary 文案改为 base+历史及旧 state；运行记录 allowlist 增加 startup_state_audit。随后已通知 root 与 behavior_harness，其余 runner 归该作者维护 |

原用户 home 的 sessions、archived_sessions、memories、memories_v2、sqlite、log、dictation-history、thread-writer-locks 禁读；全局所有 `*.sqlite` 及版本/sidecar、history/transcription-history/session_index、global-state 正文/备份/临时文件用真实 SBPL regex 拦截，现有符号链接真实目标一并拒绝。没有扩大 home 写权限，没有 HOME/CODEX_HOME 覆盖，没有删除历史或复制认证；auth/config 原读取方式及 installation_id 原精确 O_RDWR 例外不变。

每次 run 目录为 fixture `.evaluation-state/run-<run-id>/`，必须全新，不接纳已有目录或 state 目录符号链接。对 fixture 整个旧 state 树单独禁止该子进程读写，仅当前新子目录例外。SQLite 初始化需 stat 公共父目录，因此只给该单一目录 metadata，目录列表仍拒绝；这不开放任一旧库内容、WAL/SHM 或前次 run 子库。旧库不通过删除而“净化”。

初始化及 ephemeral thread/start、MCP 验证后，任何 turn/start 之前，父评测器以只读 SQLite 查询实际新 state 库：恰好一个、有效 threads 表、COUNT(*) 必须为 0。错误/缺库/非零均不发送模型 turn；非零证据保留 startup-state-audit.json。`startup_only=True` 经相同 profile/RPC/门禁后返回 initialized，不发 turn/start、不成为模型成绩。正常运行没有按“只声明已隔离”放行的旁路。

## 真实验证与原失败保留

全部探测在 `evidence/behavior/startup-history-isolation-diagnostic-019` 至 `024`，未挑最好记录删除失败：

| 探测 | 实际结果与后续 |
| --- | --- |
| 019 | 工具外层已有 sandbox，sandbox_apply 被拒；未证明新 profile，未启动 CLI/模型。后续在允许单层 profile 的已批准执行边界运行 |
| 020 | 基本边界成立，真实历史 canary 检出 SBPL regex 字面量双转义使全局文件仍可 open；门禁阻止模型。修正 #regex 字面量编码 |
| 021 | 32 个现存全局历史入口读拒绝，真实 CLI initialize/thread-start/MCP 正常、新库 0 行，保护文件不变；未发 turn。此时尚未纳入旧 fixture 全树保护，不能当最终恢复证据 |
| 022 | 加入旧树后，4 个旧文件读写拒绝且 hash 不变，但父目录 metadata 也被拒导致真实 SQLite 初始化失败；没有模型。仅修为父目录 stat 例外，保留列表禁令 |
| 023 | 全局及旧 fixture 保护、真实新库零历史通过；单测当轮 1 项因结构断言未适配嵌套 require-all 失败，原输出保留；随后断言加入父目录列表禁令并保留原安全条件 |
| 024 最终 | **47 项真实 canary 全符合预期**：基础 6、全局历史读 32、旧 fixture 文件读写 8、旧父目录 listing 拒绝 1；真实 CLI 正常退出 0，新库 threads=0，旧 4 文件 hash 不变，auth/config/installation_id 内容及元数据不变；**无 turn/start** |

最终 024 保存 driver、实际 profile、完整 requests/appserver JSONL、stderr、isolation.json、startup-state-audit.json、result.json、适配源码快照及单测输出。requests 只有 initialize、initialized、thread/start、mcpServerStatus/list。CLI 为正常安装包原生 codex 0.154.0；没有模型 turn、嵌套 CLI、重签、注入或危险无沙箱模式。实际 profile 使用原认证和配置、同样禁用 apps/plugins/remote_plugin/memories/shell_snapshot/MCP 的既定配置。

最终适配源码 SHA-256：`5b5dd7902114e028a3d4cd2c560231693d33f04c9b7fc5a671f17830efe2f3c4`；024 的 `external_seatbelt.snapshot.py` 与实际源码逐字节一致。最终 28 项适配单测全部通过（5.208 秒），此前开发中的路径归一化断言及结构断言失败未冒称通过。新增测试验证原始历史可读/可写会拒绝 gate，而非仅检查声明字段。

## 边界、剩余工作和交接

本次只证明本机 0.154.0 当前 profile、正常初始化、实际历史入口与空库门禁；没有新 LLM、模型工具执行或组合质量成绩。未重跑全部套件；runner 关联由 behavior_harness 接管后应独立检查，最终统一套件由协调者安排。固定配置或 CLI 版本变化导致缺库、schema/权限不匹配应保持失败，不静默放宽。

旧专业案例和组合结果必须由非作者重新审计污染范围及完整轨迹，区分业务事实可见性与旧环境隔离缺口；本次无模型成功不得回填旧 run。未看到模型读旧库也不能自动接纳旧严格隔离成绩。本作者未重绑定旧 pass、未自行重测模型、未改产品或运行时账本、未提交或 push。现在可冻结这些源文件交非作者检查。
