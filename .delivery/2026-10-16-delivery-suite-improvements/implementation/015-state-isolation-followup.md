# IR-014 相邻结构与跨 fixture 隔离修补

结论：作者修补及无模型正向验证完成，**等待非作者复核，不由作者宣布环境审查通过**。旧 024 启动、旧环境报告和全部反例保留；本次新证据为 `evidence/behavior/startup-history-isolation-diagnostic-025`。未发送模型 turn、未绑定旧质量成绩、未修改五专业包或被测业务、未提交/push。

作者：`/root/contract_runtime`。根据 root 明确续补授权处理独立 `review/023-environment-checks.json` 与 `023-other-fixture-state-probe.json` 的原例；最低规则及准确边界与独立审阅者同步。本作者不承担自己适配修补的独立审查。

## 具体缺口与最小修补

| 独立发现 | 旧机制缺口 | 本次实际修补与验证 |
| --- | --- | --- |
| `threads(other TEXT)` 的 COUNT 为 0 也通过 | 同名对象未证明是 CLI 线程表 | 验证 sqlite_master 是真实普通 table，拒 view/virtual；最低 9 个本机必需元数据列及 TEXT/INTEGER；id 必须为单一主键。未知/错型/缺 key 均拒绝 |
| 有历史表但空 view 名叫 threads 也通过 | 空视图可伪装零历史 | 独立原 SQL 在回归中拒绝；不是补一句“表应正确”而继续 COUNT |
| SQL/读取/COUNT 返回错误 | 可能缺少专用失败记录 | 错库/读错/SQL 错误与未知返回形状保存 `startup-state-audit.json` 的 passed=false、错误类型和原因；拒绝 turn/start。COUNT 仅接受单字段、非负的真正 int，拒 bool、字符串、浮点、负数、缺字段及多字段 |
| 当前 fixture 封旧库，其他已知 fixture 原 361 行库仍可读 | 只保护自己旧树，未覆盖其他候选与历史 | 精确 temp 父目录 + 固定 `delivery-eval-work-*` 前缀，动态禁读全部兄弟 fixture 整体，当前 workspace 唯一例外；不只封 state，也封其他候选 README/代码 |
| 后来创建的目录绕过“扫描已有者” | 静态目录集合不完整 | SBPL regex 不以存在性为前提；profile 生成后真实创建新兄弟 fixture，README/state 仍被拒绝；仅删除这次自建 canary，不删旧数据 |
| 非标准诊断 fixture 的旧污染库 | 不受标准目录名前缀覆盖 | 从本目标 `evidence/behavior/*/evaluation.json` 和 `*/result.json` 的 evaluator-owned 顶层 workspace 元数据生成已知旧 state 清单；留源路径/摘要，禁读实际旧 state。没有递归读取业务 artifacts 中同名 JSON，也不读历史正文 |

最低 9 列：id、rollout_path、created_at、updated_at、source、model_provider、cwd、title、first_user_message。对本机 0.154.0 的实际普通表，PRAGMA 记录 40 列；最低列检查通过，额外兼容列不必逐列相等。这是特定受控 CLI 的最低 schema 接纳，未知变种保持拒绝，不复制重型数据库版本引擎。

仍保留 014 中的全部实际保证：全局历史入口拒绝；每 run 新子目录且不可复用或用 symlink；自己旧 state 读写拒绝，仅当前子目录及公共父目录必要 stat 例外，父目录 listing 拒绝；auth/config 原读方式、installation_id 精确 O_RDWR、HOME/CODEX_HOME 原值保持。外部 profile 仍不是整机或网络封闭容器。

## 实际改动及边界

只修改 `external_seatbelt.py`、对应单测和 evaluation README；本轮未再碰 runner。已告知 behavior_harness 保留上一轮 runner 的 audit 字段和可读说明关联。

新增路径规则只覆盖精确 temp 父目录的 harness 标准命名前缀，以及本目标已经明确记录的非标准旧 state；没有禁读整个 `/tmp`、用户主目录或所有机器文件。路径取实际 resolve，并记录/验证 `/private/var` 与 `/var`（适用时 `/private/tmp` 与 `/tmp`）alias。当前 fixture 若本身符合标准前缀，通过 require-not-subpath 唯一例外，真实读写仍能工作。处理的是具体评测隔离，没有新增运行状态机或改专业包契约。

## 最终真实无模型 025

`startup-history-isolation-diagnostic-025` 的 driver 使用正常安装包原生 codex 0.154.0、相同正常配置与认证、单层实际 OS profile；工作区这次使用标准 `delivery-eval-work-*` 前缀以真实测试当前例外。

实测 **181 项 canary 全符合预期**：当前写/读及别名读正常、全局历史 32 入口拒绝、自己旧 4 文件读写拒绝、旧父目录 listing 拒绝；跨 fixture 的 66 个实际目标分别以两种路径 alias 拒绝 open-read，共 132 项。目标包含原 `candidate-full-01` 已确认 361 行的旧 state 库，也包含其他 fixture 的业务 README。没有通过读取历史正文取得证明，失败 open 没有返回内容。新建兄弟 canary 明确发生在 profile 生成后，清单有其路径，原旧库及业务未被删除或改写。

`prior-state-paths.json` 留存 8 条已知非标准 workspace 元数据记录及摘要；相应 state 禁读。最终结果的旧 4 个自建 seed 文件 SHA 保持一致，受保护 auth/config/installation_id 内容、mode、mtime、size 不变。旧运行和早先失败没有被清理。

真实 RPC 只有 initialize、initialized、thread/start、mcpServerStatus/list；无 turn/start。CLI 正常退出 0，新 state 普通 threads 表最低 schema 与 id 主键通过，COUNT(*) 为 0。`real-cli-thread-schema.json` 留下真实 PRAGMA 元数据（40 列），不包含历史行。`startup-state-audit.json` 同时留存实际库位置、已验证列、普通表和零行结论。

025 的 `external_seatbelt.snapshot.py` 与实际源码逐字节一致，SHA-256：`665550103ceb4450db1b137e17235b9eac03c0470bde15b7bc75e7200cc3ba40`。profile、完整 requests/appserver JSONL、stderr、实际逐项 isolation.json、known path 清单、result.json 均留存；没有新 LLM 能力成绩。

## 单测及未跑范围

最终 **34 项适配单测通过，5.236 秒**，输出 `025/final-unit-tests.txt`；此前 31/33 项阶段输出也保留。新回归含独立原 empty-view/unknown-table、错列类型/主键、COUNT 异常、真实损坏 SQLite 的专用错误留据与不发 turn，动态兄弟前缀/当前例外、元数据收集不信任 artifacts、既有 canary 失败阻断。fake RPC 只验证设施门禁，不能算模型表现。

未重跑全仓库套件，未测试新模型/完整组合。root 将重新冻结源码 003 并安排非作者定向环境检查；在独立通过前不启动新模型。旧 standalone review/verify 的业务评价另存 `review/024-...`、`025-...`，overall 仍为 inconclusive，未被本次设施正例追溯改成隔离通过。
