# Research 整合版验证记录

日期：2026-10-16。适用范围：本次 research 四份正文／参考文件、10 个案例定义，T2 的 3 次及 T3 追加的 1 次实际研究执行，以及归档与安装的文件系统检查。

**四次实际执行已分别通过独立语义审查，归档与安装切换已完成机械核对。** 这不表示 10 个案例全部执行，也不证明客户端自动发现或运行中的会话已经重载。

## 验证版本

| 文件 | SHA256 |
|---|---|
| `SKILL.md` | `ceacc5439a125e246fef3b2642dad42c681850e175add6c7f5b1f997982e3506` |
| `references/search-routing.md` | `532c4a4990b7309fb2e7b3d72d0aa00e8ede31d409d251fac26f6a10d29a6e7e` |
| `references/sites.md` | `45d73bc0128310ef232d7ca464836f82ffd9ea1bc5898914a1feb826569a198b` |
| `references/local-context.md` | `7876628b6df342e6fc537b4541f5a587ce50ab46eacec65ce5760f8f82552590` |

四文件摘要表示评估时的包版本，不表示每组都读取了全部参考。实际读取范围由各组原始 metadata 分别记录：公开资料组读取正文和检索参考；两个 T2 本地组读取正文；T3 交接组读取选题与研究两份正文。

交接使用的 `research-topic-selection/SKILL.md` SHA256 为 `f02064a850d5f840a94f502c619b2ad1dcd45addaff88b51b794b4c5c2d9ef2b`，另在 manifest 的 `upstream_files` 绑定；不将上游文件混入 research 四文件快照。

## 实际执行与独立审查

执行者只接收实际请求、skill 与必要原材料，没有向其提供 expected。原始过程记录均声明未读取案例预期或其他评审答案；独立审查核对了实际答复与来源。各组并没有完整、独立监控的全部工具转录，因此全面的未读／未做声明仍部分依赖执行者过程记录。

执行者与独立审查者均继承父代理模型；环境未提供可核验的精确模型 ID，不推断具体型号。角色独立不代表跨模型独立。

| 实际运行 | 关联案例定义 | 观察与证据范围 |
|---|---|---|
| `behavior-live` | `independent-live` 的近似请求变体 | 实际研究外部工具无回复时的结果不确定性、解决路线与条件；读取公开原始资料，补查版本差异和具体边界。Exa 搜索调用真实失败，改用可用网页工具；关键工具原始返回保存在 `retrieval-log.json`。未读取个人资料或运行研究对象实验。 |
| `behavior-scoped` | `single-file` | 仅以指定合成转载文章判断普遍去重和成本主张，区分恢复耗时与成本；明确未核验原报告。没有借用限定文件之外的样本、方法或接口信息。 |
| `behavior-conflict` | `source-framework`、`evidence-conflict`、`channel-failure` 的组合请求 | 阅读目录及五份合成材料，解释受理、重发和业务效果的关系；比较 v1/v2，追踪两篇转载到同一测量，核对样本、指标与外推限制。“联网不可用”来自请求给定条件，没有真实网络故障注入或联网尝试。 |
| `behavior-handoff` | `handoff` 的具体请求变体 | 从明确指定的选题源码入口接续 research，复用五项交接信息，在指定合成材料内研究；没有重新选题。请求明确反馈已记录并禁止再次记录或保存成果，本次不验证反馈写入。实际八份读取日志保存在 `retrieval-log.txt`。 |

T2 的 3 次执行关联 5 类定义；T3 追加 1 次交接执行后，合计 **4 次执行关联 6 类案例定义**。组合覆盖不拆算成独立实验，也不是逐字执行全部模板。公开资料组的真实 Exa 配置失败，与本地组合组的给定网络限制是不同证据。

独立审查者 `/root/plan_review` 未编写四份产品规则、合成材料或上述研究答复，也未担任行为执行者。其 `behavior-review.md` 保留 T2 三次运行的 **pass** 判决，并追加 T3 第四次运行的 **pass**；`handoff-review.md` 记录上游改动及交接证据。两阶段均记录 Critical 0 / Important 0 / Minor 0，判决仅限实际输入与已有证据，没有要求修改 research 核心正文。

## 证据与机械核对

仓库本地工作流目录 `.workflow/research-unification/reports/` 保存：

- `behavior-live/`、`behavior-scoped/`、`behavior-conflict/`、`behavior-handoff/` 中的真实请求、答复、执行观察及 metadata；公开资料组另有 `retrieval-log.json`，交接组另有 `retrieval-log.txt`。
- `behavior-review.md` 与 `handoff-review.md`：独立语义核对、案例关联及覆盖限制。
- `behavior-manifest.json`：实际路径、产物与材料摘要、评估包版本、模型可见性、独立审查及本验证摘要的绑定信息。

合成材料位于 `.workflow/research-unification/fixtures/`。工作流证据保留在本地，不作为 skill 源码包或版本库内永久附件；仅取得本文件不能替代读取原始证据。

已执行的机械检查：

- `quick_validate.py research`、`quick_validate.py research-topic-selection`、`quick_validate.py folo` 均退出 0，输出 `Skill is valid!`。
- description 为 135 字符；四段式与 5 处相对参考可达；10 个案例 ID 唯一且 JSON 可解析。
- T2 的 `python3 -B .workflow/research-unification/verify_delivery.py --pre-migration` 退出 0，当时明确跳过归档、活动引用与安装三项。
- T3 的 `python3 -B .workflow/research-unification/verify_delivery.py` 完整模式退出 0，核对结构、产品无 `scripts/`、案例定义、四次运行及实际产物摘要、研究与上游版本、审查声明、本摘要绑定，以及归档、活动引用与安装链接。原始结果另存本地 `reports/T3-full-verification.json`。

检查器不从答复关键词推导语义通过。它验证的是文件和声明绑定，不独立证明工具调用真实性、模型身份、角色独立性或覆盖充分性；语义判决来自独立审查。机械检查和审查 pass 不等于用户验收。

## 安装与归档

安装前确认 `~/.claude/skills/research`、`~/.agents/skills/research` 均不存在，四个旧入口均为指向本仓库预期旧包的软链接。使用现有 `install-skill.sh research` 新装并先验证两个目标，再使用现有卸载脚本移除两个客户端中的旧入口；各命令退出 0。两个 research 链接均指向本仓库 `research/`。

旧包迁到 `Archive/research-unification-2026-10-16/` 下对应原目录；基线七文件 SHA256 全部一致，历史正文、案例和验证记录未改写。其中六个原跟踪文件随归档进入版本库，原已忽略的 `.DS_Store` 保留在本地归档而不强制入库。选题与 folo 的指定活动引用已迁移，其他历史文档保持原语义。

交接行为证明的是明确源码入口接续；安装检查证明的是磁盘链接及目标。二者均不能扩写为客户端自动发现、自动触发或运行中的会话已刷新。上游独立消费检索参考与缺包降级只有文本和路径审查，尚无对应模型行为实测。

## 尚未验证与限制

- 尚未独立执行 `bounded-enumeration`、`ambiguous-topic`、`collection-notice`、`experiment-boundary` 四类模板。各组体现了未自动实验的边界，但不代表完整执行该专门模板。
- 四次主题集中在重试与重复执行，没有旧 skill 对照、重复采样或统计推断，不能据此宣称普遍质量提升。
- 三组使用合成资料，不对应真实产品效果；公开资料组也未做用户系统实验，不能保证实际业务正确性或收益。
- 未逐站重验站点表、全平台登录与凭证、真实反馈或研究成果保存、全部客户端刷新。整体终审、workflow verify/close 由本地工作流另行记录，本摘要不替代其证据。

---

# 2026-10-29 交付形式与上下文改动验证

适用范围：本次对 `SKILL.md`（description、定位句、第 1 步上下文规则、Exit Protocol、Exit Criteria）与 `test-prompts.json`（新增 4 条案例）的改动。`references/` 三份参考未改动。上一节 2026-10-16 的记录与 SHA 表保持原样，不表示本次版本。

## 改动版本

| 文件 | SHA256 |
|---|---|
| `SKILL.md` | `3199f4cc50d0f456754fcac9fa265573d5160ceae2503a613ca4d3bd3bb4b032` |
| `test-prompts.json` | `c48cc00fdb9ad4a2c846f93f4113bb2b4e9261f56c9ab3492317860e50e2e4e1` |

## 机械检查（实际运行）

- `quick_validate.py research`（取自 codex 样例包，以 `python3 -I` 运行）输出 `Skill is valid!`，退出 0。
- description 长度 148 字符；`SKILL.md` 中 4 处相对参考链接可达；`research-topic-selection/SKILL.md` 指向 research 的 3 处引用（检索路由、站点登记表、SKILL.md）均可达。
- `test-prompts.json` 可解析，14 个案例 id 唯一；`git diff --check` 无输出。

## 行为执行（Claude Code 2.1.312，`claude -p`，每次 1 次）

执行目录为临时工作区；原始请求、工具调用序列、最终答复与退出状态在本次验证后已按要求清理，未长期保留，因此本节记录只是摘要，不能替代原始证据。模型标识由执行环境提供，未单独核验。

| 案例 | 结果 | 观察 |
|---|---|---|
| `context-anchored` | 通过 | 主动加载 research；26 次工具调用均围绕 A/B 与“下游不保证幂等”展开；交付含结论、依据、思路（A/B 对照表 + 分层推荐）、成立条件；未重新询问已知背景 |
| `trigger-diaoyan` | 通过 | “调研一下”触发 research；交付四部分齐全；只读取检索参考，未读 Vault 或个人资料；结尾提出一个影响档位的澄清问题 |
| `fact-check-brief` | 部分通过 | 篇幅短、思路从简，符合预期；但**未加载 research**，答复来自模型已有知识并无出处，仅声明“未能联网核实”。说明“查证一下”这类短请求的触发不稳定 |
| `single-file` | 通过 | 只读指定文章，不读其他文件或外链；明确样本、统计口径与转载无法核实的限制；未扩写方案 |
| `not-trigger-locate` | 通过（该次执行因配额 403 中断） | 只做了代码检索，未加载 research；中断发生在检索之后，不影响“未误触发”的判断 |

两次涉及联网的执行（`context-anchored`、`trigger-diaoyan`）中，WebFetch 对所有目标域返回域名校验失败，Bash 的 `curl` 未获批；两次答复都声明了摘要是唯一证据并降低证据等级。首次批量执行时 3 次因代理配额 403 中断，配额恢复后重跑 2 次；`not-trigger-locate` 未重跑。环境中 WebSearch 曾出现 `unrecognized_model` 报错，与实际技能行为无关。

## 尚未验证

- 每个案例只执行 1 次，不能证明稳定性；未做旧版本对照或重复采样。
- `fact-check-brief` 暴露的触发不稳定，未做进一步定位（是模型判断“简单事实无需研究”，还是 skill 发现机制），也未针对它调整描述。
- 只覆盖 Claude Code；未验证 Codex 等客户端的触发与输出。
- 未验证保存路径、Vault 写入、个人资料读取的改动后行为（本次未改动相关规则）。

清理：临时工作区与原始执行记录均已删除；本文件只保留结论与限制。
