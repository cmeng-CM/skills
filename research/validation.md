# Research 整合版验证记录

日期：2026-10-16。适用范围：本次 research 四份正文／参考文件、10 个案例定义，以及下述 3 次实际研究执行。

**三次实际执行已通过独立语义审查；机械核对另行检查文件与版本绑定。** 这不表示 10 个案例全部执行，也不表示归档迁移和安装切换已经完成。

## 验证版本

| 文件 | SHA256 |
|---|---|
| `SKILL.md` | `ceacc5439a125e246fef3b2642dad42c681850e175add6c7f5b1f997982e3506` |
| `references/search-routing.md` | `532c4a4990b7309fb2e7b3d72d0aa00e8ede31d409d251fac26f6a10d29a6e7e` |
| `references/sites.md` | `45d73bc0128310ef232d7ca464836f82ffd9ea1bc5898914a1feb826569a198b` |
| `references/local-context.md` | `7876628b6df342e6fc537b4541f5a587ce50ab46eacec65ce5760f8f82552590` |

四文件摘要表示评估时的包版本，不表示每组都读取了全部参考。实际读取范围由各组原始 metadata 分别记录：公开资料组读取正文和检索参考；两个本地组读取正文。

## 实际执行与独立审查

执行者只接收实际请求、skill 与必要原材料，没有向其提供 expected。原始过程记录均声明未读取案例预期或其他评审答案；独立审查核对了实际答复与来源。各组并没有完整、独立监控的全部工具转录，因此全面的未读／未做声明仍部分依赖执行者过程记录。

执行者与独立审查者均继承父代理模型；环境未提供可核验的精确模型 ID，不推断具体型号。角色独立不代表跨模型独立。

| 实际运行 | 关联案例定义 | 观察与证据范围 |
|---|---|---|
| `behavior-live` | `independent-live` 的近似请求变体 | 实际研究外部工具无回复时的结果不确定性、解决路线与条件；读取公开原始资料，补查版本差异和具体边界。Exa 搜索调用真实失败，改用可用网页工具；关键工具原始返回保存在 `retrieval-log.json`。未读取个人资料或运行研究对象实验。 |
| `behavior-scoped` | `single-file` | 仅以指定合成转载文章判断普遍去重和成本主张，区分恢复耗时与成本；明确未核验原报告。没有借用限定文件之外的样本、方法或接口信息。 |
| `behavior-conflict` | `source-framework`、`evidence-conflict`、`channel-failure` 的组合请求 | 阅读目录及五份合成材料，解释受理、重发和业务效果的关系；比较 v1/v2，追踪两篇转载到同一测量，核对样本、指标与外推限制。“联网不可用”来自请求给定条件，没有真实网络故障注入或联网尝试。 |

因此是 **3 次执行关联 5 类案例定义**，不是 5 次独立实验，也不是逐字执行全部模板。公开资料组的真实 Exa 配置失败，与本地组合组的给定网络限制是不同证据。

独立审查者 `/root/plan_review` 未编写四份产品规则、合成材料或三个研究答复，也未担任行为执行者。其 `behavior-review.md` 对三次运行作出 **pass** 判决，记录 Critical 0 / Important 0 / Minor 0；判决仅限实际输入和已有证据，没有要求修改正文。

## 证据与机械核对

仓库本地工作流目录 `.workflow/research-unification/reports/` 保存：

- `behavior-live/`、`behavior-scoped/`、`behavior-conflict/` 中的真实请求、答复、执行观察及 metadata；公开资料组另有 `retrieval-log.json`。
- `behavior-review.md`：独立语义核对、案例关联及覆盖限制。
- `behavior-manifest.json`：实际路径、产物与材料摘要、评估包版本、模型可见性、独立审查及本验证摘要的绑定信息。

合成材料位于 `.workflow/research-unification/fixtures/`。工作流证据保留在本地，不作为 skill 源码包或版本库内永久附件；仅取得本文件不能替代读取原始证据。

已执行的机械检查：

- `quick_validate.py research` 退出 0，输出 `Skill is valid!`。
- description 为 135 字符；四段式与 5 处相对参考可达；10 个案例 ID 唯一且 JSON 可解析。
- `python3 -B .workflow/research-unification/verify_delivery.py --pre-migration` 核对上述结构、产品无 `scripts/`、案例定义、实际报告与材料摘要、当前四文件版本、审查者 pass 声明及本摘要绑定。退出 0；归档、活动引用迁移和安装三项明确跳过。

检查器不从答复关键词推导语义通过。它验证的是文件和声明绑定，不独立证明工具调用真实性、模型身份、角色独立性或覆盖充分性；语义判决来自独立审查。结构校验和审查 pass 也不替代真实安装或用户验收。

## 尚未验证与限制

- 尚未独立执行 `handoff`、`bounded-enumeration`、`ambiguous-topic`、`collection-notice`、`experiment-boundary`。三组都体现未自动实验的边界，但没有完整执行该专门模板；新版选题上游交接尚待迁移后另行检查。
- 三次主题集中在重试与重复执行，没有旧 skill 对照、重复采样或统计推断，不能据此宣称普遍质量提升。
- 两组使用合成资料，不对应真实产品效果；公开资料组也未做用户系统实验，不能保证实际业务正确性或收益。
- 未逐站重验站点表、全平台登录与凭证、真实笔记保存、安装切换或全部客户端刷新。完整交付模式及安装证据在迁移阶段另记。
