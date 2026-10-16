# 垂直站点登记表

通用搜索引擎对**垂直聚合站**的收录总是慢半拍、也不全。这张表记录"某类资源该去哪个专门的站、怎么查"。

**用法**：判完资源类型后，先扫一遍本表看有没有对口的站。有 → 按登记的路线走；没有 → 走通用检索，并在交付时说明"没有专用站，用的是通用检索"。

**先看状态栏**：`已实测` 的可以照抄；`未实测` 的先用小代价跑一次验证再依赖它（这条路是本机还是那个站点变了都可能导致它失效）。

---

## 收录规程（加新站照这个来）

新站不断出现，这张表是要长期长的。加一条要满足：

1. **有专属覆盖**——它是某类资源的专门索引，且通用搜索覆盖不好。判据：**在这上面搜，能搜到通用搜索搜不到的**。（skills.sh 就是靠这条进来的：它搜出了 GitHub 代码搜索漏掉的 `mazrean/agent-skills/writing-technical-design`。）
2. **实测过再写进来**。没跑通就不写，或写进来但状态标 `未实测`。**禁止凭"这个站应该有搜索"填一条路线**——本表最贵的教训就是猜出来的路线全是错的。
3. **一次性的站不加**。为一次查询去翻的页面，留在当次结果里就行，不要进表。
4. **必须写「保底」**。站会改版、会挂、会反爬。每条都要写清拿不到时退到哪。

每条固定五栏，**不要漏栏**：

```markdown
### <站点名>
- **状态**：已实测（<日期>） / 未实测
- **覆盖**：<什么资源类型> —— 用于和用户意图匹配的关键词
- **检索**：<具体命令或 URL 模板，可直接复制执行>
- **穷举**：<怎么拿它的全量条目；没有就写「不适用」>
- **保底**：<这个站拿不到时退到哪>
- **坑**：<已知的坑；没有就写「无」>
```

---

## 已收录

### skills.sh（Agent Skills 目录）
- **状态**：已实测（2026-09-27）
- **覆盖**：agent skill / Claude Code skill / 提示词包 —— 关键词：skill、技能、agent skill、有没有人写过 X 的 skill
- **检索**：`tavily_search` 限定站内
  ```
  query: "<要做的功能>"         include_domains: ["skills.sh"]
  max_results: 8                search_depth: advanced
  ```
  一次调用就能拿到多个 skill 的摘要 **加 SKILL.md 正文片段**（实测 1.8 秒返回 7 条，正文可见）。
- **穷举**：站点首页有排行榜（All Time / Trending 24h / Hot）与分类页 `Packs / Topics / Official / Audits`；单仓库的 skill 列表在 `https://www.skills.sh/<owner>/<repo>`。整页 `curl` 下来即可读（服务端渲染，实测 tag 剥离后排行榜文本完整）。
- **保底**：`gh search code --filename SKILL.md "<关键词>"` —— 查 GitHub 上的 SKILL.md 原文。两条路线**互补而非替代**：skills.sh 覆盖已收录的、按安装量排序；gh 覆盖没被收录进目录的。
- **坑**：站内那个搜索框可能是客户端渲染，**不要去点它**，用搜索引擎的站内限定更可靠。URL 形态是 `<owner>/<repo>/<skill>`，检索结果里有 `Installs` 与 `Security Audits` 字段可用于筛质量。

### GitHub（代码 / 仓库 / skill 文件）
- **状态**：已实测（2026-09-27）
- **覆盖**：代码、仓库、issue、以及仓库内任何文件的原文 —— 关键词：项目、仓库、源码、实现、有没有人做过
- **检索**：`gh search code --filename <文件名> "<关键词>"`。**按文件层搜是关键**——它绕开仓库名与描述的措辞差异，只要文件名匹配就命中。`gh search repos "<词>" --sort stars` 用于找合集类仓库。
- **穷举**：`gh api "repos/<o>/<r>/git/trees/<branch>?recursive=1" --jq '.tree[]|select(.type=="blob")|.path'` —— 列仓库全部文件。**路径不要猜**，先列树。
- **取正文**：`gh api repos/<o>/<r>/contents/<path> --jq '.content' | base64 -d`，或 `curl -sL https://raw.githubusercontent.com/<o>/<r>/<branch>/<path>`。
- **保底**：`last30days`（它内置 GitHub 源，凭证已配）+ `tavily_search` 补网页文档。
- **坑**：**网页搜索引擎对代码的索引质量很差**，找代码不要用网页搜索。分支名会变（`main`/`master`），抓不到就 `gh api repos/<o>/<r> --jq '.default_branch'` 问一下。

### designdocs.dev（公开设计文档合集）
- **状态**：已实测（2026-09-27）
- **覆盖**：各公司公开的设计文档 / RFC / KEP 库 —— 关键词：设计文档、RFC、技术方案、某某公司怎么写
- **检索**：`tavily_search` 自然命中；也可直接打 `https://www.designdocs.dev/library`。
- **穷举**：`tavily_map`，`max_depth:1  max_breadth:30  limit:40` —— 实测 0.72 秒返回 30 条，里面是各项目的仓库地址（含 `rust-lang/rfcs`、`kubernetes/enhancements`、`TritonDataCenter/rfd` 等）。**这条是本表的样板案例**：它是个目录站，任务形态是穷举，不是检索。
- **保底**：`awesome-agent-skills` / `awesome-claude-skills` 这类 awesome list（用 `gh search repos "awesome ..."` 找），或 `gh search code --filename checklist.md`。
- **坑**：**别停在"我知道有这个站"**。看到目录站要立刻切到穷举动作，否则等于没查。

### X / Twitter（推文搜索）
- **状态**：已实测（2026-10-12）
- **覆盖**：X/Twitter 上的帖子、讨论、当事人一手发言 —— 关键词：推特、推文、X 上、某某说了什么、社区反应
- **检索**：`opencli twitter search "<query>" --limit 20 -f json`（实测 5.2 秒返回；字段：id / author / text / created_at / likes / views / url / media_urls。query 支持 x.com 原生操作符原样透传：`from:`、`since:YYYY-MM-DD`、`lang:en`、`"精确短语"`、OR；`--product live` 切 Latest 标签，`--top-by-engagement N` 按互动重排）
- **穷举**：不适用（无公开全量目录）；要更多加大 `--limit`（内部自动翻页）
- **保底**：① 苟活 Nitter 实例的搜索 RSS：`curl -s "https://nitter.kareem.one/search/rss?f=tweets&q=<query>"`（备胎 `nitter.meowing.monster`；两个实测各返回 19 条，但随时会死）；② 需要"最近 30 天 + 互动量"视角时走 `last30days <话题>`（其 X 源已配 bird 后端）
- **坑**：
  - **登录态**走 Chrome 扩展桥接（daemon `127.0.0.1:19825`）。Chrome 未开/扩展未连 → exit 69；x.com 登出 → exit 77，跑 `opencli twitter login` 补。次要后端 `twitter` CLI 已配好同一对 cookie（凭据 `~/.config/twitter-cli/credentials.env`），**但其 `search` 端点目前上游 404**（X 改 GraphQL，版本已是最新 0.8.5）；`twitter feed` / `twitter user-posts` 可用。
  - **默认读 Top 标签**，会混入几年前的爆款推文（实测 "OpenAI" 的 Top 里出现 2022 年内容）；要近期内容加 `--product live` 或 `since:`。
  - **last30days 的 X（bird 后端）**依赖 `~/.config/last30days/.env` 里的 `AUTH_TOKEN`/`CT0`（2026-10-12 经 opencli 桥接提取写入）；登出/改密后 cookie 失效，重跑桥接提取刷新即可。
  - Nitter 苟活实例：X 自 2026-08 起法律清剿（xcancel、nitter.net、sotwe、twstalker 已关停或 403），仅存实例带 bot 检查与限流——**不要当主路线**。

### r.jina.ai（任意网页转 Markdown 的兜底）
- **状态**：未实测
- **覆盖**：任何没有专用抓取路线的网页 —— 关键词：通用兜底
- **检索**：不适用（它是取正文的，不是检索的）
- **穷举**：不适用
- **取正文**：`curl -s "https://r.jina.ai/<完整URL>"`
- **保底**：`tavily_extract`
- **坑**：本机**没有** `jina` 这个可执行文件，agent-reach 文档里出现它时指的是这个 URL 服务，用 curl 打。

---

## 待收录（有线索但还没实测，用之前先验）

| 站/源 | 覆盖 | 为什么值得收 | 待验什么 |
|---|---|---|---|
| Hacker News（Algolia API） | 技术讨论、风向 | 讨论质量高且可全文搜 | `https://hn.algolia.com/api/v1/search?query=` 是否可用、限流如何 |
| arXiv | 论文 | 本机 `arxiv-pp-cli` 已装好（2026-10-12），last30days 内置源当天实测返回过结果（5 条） | 直连路线 `arxiv-pp-cli query --search-query "<q>" --agent` 当日实测被 arXiv 限流（429/超时）——换个时段复验一次干净通过即可转正 |
| awesome list 家族 | 各类资源的清单 | `gh search repos "awesome <主题>"` 能找一批 | 收录哪些、还是只用通用检索即可 |

---

## 维护提示

- **一次会话里不要重复探测同一个站**。实测结果记进「状态」栏的日期，下次直接用。
- 某条路线失效时，**就地改「状态」为「未实测」并写清失效现象**，不要删——知道"这条曾经能用、现在不行"比留个空位有用。
- 表变长以后按**资源类型**而不是字母序排，因为用的人是按意图来找的。
