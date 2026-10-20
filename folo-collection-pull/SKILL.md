---
name: folo-collection-pull
description: 把 Folo Collection 中尚未处理过的条目拉取到 Obsidian 11-Clippings：状态账本记录已拉取 entry id，剪藏目录再按来源和标题兜底去重，重复运行不会重复生成文件。只新建原始剪藏，不做主题综合或项目写入。
---

# Folo Collection 拉取到 Obsidian 剪藏

把 Folo Collection 中的**新条目**拉进 Vault 的 `11-Clippings/`。收藏是长期不变的队列，所以本 skill 的核心不是“每次都拉全部”，而是**只拉没拉过的**：

1. 本地状态账本记录已拉取/已 baseline 的 entry id；
2. 再扫描 `11-Clippings/`，按 `source` 和“标题 + 域名”兜底去重；
3. 已拉过的条目在取正文之前就跳过，重复运行不会重复进剪藏。

## Working Protocol

### 1. 前置检查

- `folo` CLI 已登录；缺失时脚本会尝试 `npx --yes folocli@0.0.5`，再失败就报告，不猜凭据。
- `pandoc` 可用；缺失时回退 Python `markdownify`。
- Vault 根目录包含 `11-Clippings/`。本机为 `/Users/cm/workspace/obsidian/obsidian-repository`，其他环境用 `--vault-root` 或 `OBSIDIAN_VAULT`。
- Folo Collection 是唯一输入队列；只收藏确定要留下的文章。
- 默认状态账本：`~/.local/state/folo-collection-pull/state.json`，可用 `--state-file` 改。

Folo CLI 的返回结构、`entry read` / `entry get` 差异和分页，以 `folo` skill 的 `references/commands.md` 为准；本 skill 只固化拉取所需的最小调用。

### 2. 首次使用：先给当前收藏建 baseline

如果当前 Collection 里已经有内容、但现在不想拉取，先运行一次 baseline：

```bash
python3 scripts/folo_collection_pull.py \
  --vault-root /Users/cm/workspace/obsidian/obsidian-repository \
  --baseline
```

baseline 只读取 `collection list` 的元数据，不调用 `entry read` / `entry get`，不创建剪藏文件；它把当前 entry id 标记为 `baseline`。之后正常拉取时，这些条目会被跳过。

如果以后想补拉某条 baseline 条目，用 `--include-pulled` 覆盖账本；剪藏目录扫描仍会防止重复文件。

### 3. 日常：先 dry-run

```bash
python3 scripts/folo_collection_pull.py \
  --vault-root /Users/cm/workspace/obsidian/obsidian-repository \
  --limit 50
```

输出四类：

- `ADD`：本次会新建的剪藏；
- `SKIP duplicate`：entry id 已在账本，或 `source` / “标题 + 域名”已存在于 `11-Clippings`；
- `SKIP no content`：没有正文也没有可用描述，需手动 Web Clipper；
- `FAIL`：单条读取或转换失败，附原因。

默认不写文件，也不更新账本。

### 4. 确认后写入

```bash
python3 scripts/folo_collection_pull.py \
  --vault-root /Users/cm/workspace/obsidian/obsidian-repository \
  --limit 50 --write
```

写入边界：

- 只新建 `11-Clippings/<标题>.md`；
- 不修改、不移动、不删除已有文件；
- 不改 Folo 已读状态，不移除 Collection；
- 文件名冲突追加 entry id，不覆盖；
- 每成功写入一条，立即把 entry id 记入状态账本；下一次运行直接跳过。

新建文件使用现有剪藏字段，不新增 frontmatter 字段：

```yaml
title: "..."
source: "..."
author:
  - "..."
published: "..."
created: "YYYY-MM-DD"
description: ""
tags:
  - "clippings"
  - "待整理"
```

不想进入整理队列时加 `--no-pending`。

### 5. 幂等规则

**第一层：状态账本。** 以 entry id 为准，记录 `status: pulled|baseline`、来源、标题、剪藏相对路径。它比文件更稳定：剪藏被移动、改名或删除后，同一 entry 仍不会被重复拉取。

**第二层：剪藏目录扫描。** 每个已有剪藏解析 `source` 和 `title`：
- `source` 去掉 `utm_*`、`spm`、`from`、`scene`、`poc_token` 等跟踪参数后比较；
- 微信短链 `https://mp.weixin.qq.com/s/xxx` 和长链 `?__biz=...` 无法按 URL 对齐时，用“标题 + 域名”兜底去重。

**覆盖方式：**
- `--include-pulled`：忽略账本，重新检查 baseline/pulled 条目；剪藏目录扫描仍生效。
- 不要为了重新拉取而删除账本；账本损坏时脚本会停止，避免误判为“全都没拉过”。
- 如果确认要重建账本，先备份并明确知道会重新扫描收藏；不要静默删除。

### 6. 拉取后的首轮整理

对每个新增剪藏：

1. 检查标题、来源、正文；公众号图片/公式损坏时回到原文重新 Web Clipper。
2. 补 `description`：一句中文，≤30 字。
3. 补 1–3 个主题标签；准备做主题综合的保留 `待整理`。
4. 选一个去向：
   - 项目相关 → `20-Projects/<项目>/` 对应文档加链接和一句影响；
   - 通用 AI/Agent 知识 → 链到 `31-AI-Agent/<子主题>/` 已有主题页的“来源”，写一句补充/反驳；
   - 工具/服务 → `12-资源目录/<分类>.md` 加一行；
   - 暂时不用 → 去掉 `待整理`。
5. 没有主题页时先不新建；同一主题累计 3 篇来源或出现真实项目决策后再建。
6. 主题页稳定、跨项目可复用时，再用 `knowledge-register` 登记知识地图。

任何对已有笔记、项目文档、主题页、周报或记忆的写入，仍使用 `obsidian-write`、`work-closeout`、`memory-write`，不交给本脚本。

### 7. 失败处理

| 情况 | 处理 |
|---|---|
| 状态账本损坏 | 停止并报告；不要删除账本或强行拉取，先修复/备份 |
| `entry read` 为空（公众号常见） | 自动回退 `entry get` 的 `entries.content`；仍为空则 `SKIP no content` |
| 视频、播客、图片集没有正文 | 有描述时生成 link-only 剪藏；没有描述则跳过 |
| 同名文件已存在 | 追加 entry id；不覆盖 |
| 同一来源已剪藏 | `SKIP duplicate`，不重复创建 |
| Folo 未登录 / CLI 不存在 | 停止并报告；不反复重试，不猜 token |
| Pandoc 转换失败 | 回退 `markdownify`；仍失败则 `FAIL` |

## Exit Criteria

- [ ] 首次使用已说明当前 Collection 是 baseline 跳过还是实际拉取；baseline 没有读取正文、没有写剪藏。
- [ ] dry-run 已说明 `ADD` / `SKIP duplicate` / `SKIP no content` / `FAIL` 数量。
- [ ] `--write` 只新增了 `11-Clippings` 下的文件；已有文件内容和数量未变。
- [ ] 每个新增文件都有合法 frontmatter：`title`、`source`、`created`、`description`、`tags`。
- [ ] 连续执行两次 `--write`，第二次为 `0 add`；没有重复来源或重复标题文件。
- [ ] 状态账本已写入，且下一次运行在取正文前跳过已拉取 entry。
- [ ] 失败项已报告，没有把“跳过/失败”说成“拉取完成”。

## Exit Protocol

汇报格式：

```text
拉取结果：
- Vault：<路径>
- 状态账本：<路径>（新增 N 条 pulled / baseline）
- 新增：N 个（列出文件）
- 跳过：N 个已拉取，N 个无正文
- 失败：N 个（原因）
- 幂等核对：第二次运行 0 add（或未执行）
- 下一步：为新增剪藏补 description / 标签 / 去向
```

未写入时明确说“仅 dry-run，未创建文件”。不要声称“收藏已同步完”，只报告本次新增和跳过。
