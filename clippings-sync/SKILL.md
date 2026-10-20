---
name: clippings-sync
description: 把 Folo 收藏同步到 Obsidian 剪藏：读取 Collection、按来源去重、把正文转为 Markdown、写入 11-Clippings 的标准 frontmatter，并列出首轮整理清单。不用于一般 Folo 阅读/订阅操作，也不替代主题综合与项目写入。
---

# Folo 收藏同步到 Obsidian 剪藏

把 Folo Collection 中的文章搬进 Vault 的 `11-Clippings/`，只创建新的原始剪藏，不做主题综合、不改已有笔记。同步完成后给出需要补 `description`、标签和去向的清单。

## Working Protocol

### 1. 前置检查

- `folo` CLI 已登录；缺失时脚本会尝试 `npx --yes folocli@0.0.5`，再失败就报告，不猜凭据。
- `pandoc` 可用；缺失时脚本回退到 Python `markdownify`，两者都没有会报错。
- 确认 Vault 根目录包含 `11-Clippings/`。本机为 `/Users/cm/workspace/obsidian/obsidian-repository`，其他环境通过 `--vault-root` 或 `OBSIDIAN_VAULT` 传入。
- Folo 的收藏/Collection 是唯一输入队列。只收藏确定要留下的文章；不要把整个时间线都收藏。

Folo CLI 的返回结构、`entry read` 与 `entry get` 的差异、分页和错误码，以 `folo` skill 的 `references/commands.md` 为准；本 skill 只固化同步所需的最小调用。

### 2. 先跑 dry-run

```bash
python3 scripts/folo_to_clippings.py \
  --vault-root /Users/cm/workspace/obsidian/obsidian-repository \
  --limit 50
```

输出只有四类：

- `ADD`：会新建的剪藏；
- `SKIP duplicate`：`source` 归一化后已存在于 `11-Clippings`；
- `SKIP no content`：没有正文也没有可用描述，需手动 Web Clipper；
- `FAIL`：单条读取或转换失败，附原因。

**先审这份清单**：确认 `ADD` 都是要留的；重复项不应再建；`SKIP no content` 是否值得手动补。默认不写文件。

### 3. 确认后写入

```bash
python3 scripts/folo_to_clippings.py \
  --vault-root /Users/cm/workspace/obsidian/obsidian-repository \
  --limit 50 --write
```

脚本的写入边界：

- 只新建 `11-Clippings/<标题>.md`；
- 不修改、不移动、不删除任何已有文件；
- 不改 Folo 的已读状态，不移除 Collection；
- 文件名冲突时追加 entry id，不覆盖；
- `source` 去重会忽略 `utm_*`、`spm`、`from`、`scene`、`poc_token` 等跟踪参数。

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

不想进入整理队列时加 `--no-pending`，不写 `待整理`。

### 4. 同步后的首轮整理

对每个新增剪藏：

1. 检查标题、来源、正文；公众号图片/公式损坏时回到原文重新 Web Clipper。
2. 补 `description`：一句中文，≤30 字，写“这篇讲什么”，不复制摘要。
3. 补 1–3 个主题标签；准备做主题综合的保留 `待整理`。
4. 选一个去向：
   - 项目相关 → 在 `20-Projects/<项目>/` 对应文档加链接和一句影响；
   - 通用 AI/Agent 知识 → 链到 `31-AI-Agent/<子主题>/` 已有主题页的“来源”，并在“证据”写一句补充/反驳；
   - 工具/服务 → 在 `12-资源目录/<分类>.md` 加一行；
   - 暂时不用 → 去掉 `待整理`，留在 Clippings。
5. 没有对应主题页时先不新建；同一主题累计 3 篇来源或出现真实项目决策后再建。
6. 主题页稳定、跨项目可复用时，再通过 `knowledge-register` 登记知识地图；项目专属内容不登记。

任何对已有笔记、项目文档、主题页、周报或记忆的写入，仍使用对应的 `obsidian-write`、`work-closeout`、`memory-write`，不交给本脚本。

### 5. 失败处理

| 情况 | 处理 |
|---|---|
| `entry read` 为空（常见于公众号） | 脚本自动回退 `entry get` 的 `entries.content`；仍为空则 `SKIP no content`，手动 Web Clipper |
| 视频、播客、图片集没有正文 | 有描述时生成 link-only 剪藏，正文以原文链接开头；没有描述则跳过 |
| 同名文件已存在 | 追加 entry id；不覆盖 |
| 同一 URL 已剪藏 | `SKIP duplicate`，不重复创建 |
| Folo 未登录 / CLI 不存在 | 停止并报告；不要反复重试，不要猜 token |
| Pandoc 转换失败 | 回退 `markdownify`；仍失败则 `FAIL`，保留 Folo 原文链接供手动处理 |

## Exit Criteria

- [ ] 已实际运行 dry-run，并说明 `ADD` / `SKIP duplicate` / `SKIP no content` / `FAIL` 的数量。
- [ ] 写入时只新增了 `11-Clippings` 下的文件；已有文件内容和数量未变。
- [ ] 每个新增文件都有合法 frontmatter：`title`、`source`、`created`、`description`、`tags`。
- [ ] 重复来源没有生成第二份剪藏；文件名冲突没有覆盖。
- [ ] 失败项已报告，没有把“跳过/失败”说成“同步完成”。
- [ ] 已给出需要补 `description`、标签和去向的清单，没有声称主题整理已经完成。

## Exit Protocol

汇报格式：

```text
同步结果：
- Vault：<路径>
- 新增：N 个（列出文件）
- 跳过：N 个重复，N 个无正文
- 失败：N 个（原因）
- 下一步：为新增剪藏补 description / 标签 / 去向；待整理项进入每周 1–3 篇的主题综合
```

未写入时明确说“仅 dry-run，未创建文件”。不把脚本成功当成内容已整理完成。
