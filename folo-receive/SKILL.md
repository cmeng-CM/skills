---
name: folo-receive
description: 从 Folo 时间线生成每日阅读摘要：只拉 T1/T2 源，按关键词、排除词、已收藏/已看过去重和启发式分数排序，输出 10-Inbox 下的 folo-digest Markdown。用于决定今天看什么；不创建剪藏，不改变 Folo 已读状态。
---

# Folo 每日接收层

把 Folo 从“所有订阅的无限时间线”变成“今天值得看的 5–13 条决策清单”。

核心不是再订阅更多，而是：

- 只从 **T1/T2 源**拉取，T3 池子和 99归档不进入接收流；
- 先做确定性过滤：时间窗、关键词、排除词、已收藏/已看过去重、单源上限；
- 再用 **启发式分数**排序，输出每日摘要；
- 摘要只是决策清单，值得留的再进 Folo Collection，由 `folo-collection-pull` 拉成剪藏。

## Working Protocol

### 1. 配置

复制示例配置并编辑：

```bash
mkdir -p ~/.config/folo-receive
cp config.example.json ~/.config/folo-receive/config.json
```

关键字段：

```json
{
  "vault_root": "/Users/cm/workspace/obsidian/obsidian-repository",
  "output_dir": "10-Inbox",
  "state_file": "~/.local/state/folo-receive/state.json",
  "window_hours": 72,
  "per_feed_limit": 20,
  "now_max": 3,
  "daily_max": 10,
  "min_score": 3,
  "max_per_feed": 2,
  "tiers": {
    "T1": ["Anthropic Engineering", "Claude Code changelog", "vLLM Blog"],
    "T2": ["OpenAI News", "机器之心", "晚点 - 最新报道"]
  },
  "priority_keywords": ["agent", "context", "RAG", "vLLM", "知识库"],
  "include_keywords": ["LLM", "大模型", "RAG", "inference", "benchmark"],
  "exclude_keywords": ["招聘", "课程", "促销", "股价"]
}
```

- `tiers` 用源标题、URL 或 feed id 精确匹配；支持 `*` 通配。未列出的源默认 T3，不进入摘要。
- T1 建议 10–15 个，T2 建议 20–25 个；不要把所有源都放进 T2。
- `window_hours` 默认 72 小时：低产 T1 源（Anthropic Engineering、vLLM 等）不会因为 24 小时没更新就消失。
- `max_per_feed` 防止一个高产源淹没摘要。

### 2. 先 dry-run

```bash
python3 scripts/folo_receive.py \
  --config ~/.config/folo-receive/config.json \
  --date 2026-10-20
```

只打印摘要，不写文件、不更新状态。检查：

- `现在看` 是否是 T1 或 priority 命中；
- `今日候选` 的 T2 是否值得；
- `统计` 里的 `T3 未进入`、`排除词命中`、`低于阈值`、`单源上限` 是否符合预期。

如果摘要为空，先检查 `tiers` 标题是否和 Folo 订阅标题完全一致，再检查 `window_hours`。

### 3. 写入每日摘要

```bash
python3 scripts/folo_receive.py \
  --config ~/.config/folo-receive/config.json \
  --date 2026-10-20 --write
```

输出：

```text
<vault>/10-Inbox/folo-digest-2026-10-20.md
```

同时更新：

```text
~/.local/state/folo-receive/state.json
```

状态记录已展示/已跳过的 entry id，重复运行时不会把同一条再次放进摘要；需要重新评估时加 `--include-seen`。

### 4. 在哪里读

打开 `10-Inbox/folo-digest-YYYY-MM-DD.md`：

- `## 现在看`：T1 或 priority 命中，最多 `now_max` 条；
- `## 今日候选`：T2 分数达到 `min_score` 的，最多 `daily_max` 条；
- 每条都有标题、来源、T1/T2、分数、为什么命中、原文链接；
- 勾选框只用于你自己标记“看过”；
- 觉得值得留的条目，**加入 Folo Collection**；不要直接复制到剪藏目录。

随后由 `folo-collection-pull` 把 Collection 拉到 `11-Clippings`，并在 `folo-collection-ledger.json` 记录 `unprocessed`。这样“接收”和“留存”是两条清晰链路：

```text
Folo timeline → folo-receive 摘要 → 你决定 → Folo Collection
→ folo-collection-pull → 11-Clippings + 账本 → 处理 → mark-processed
```

### 5. 调度

先手动跑 1–2 周，确认摘要质量后再定时。macOS 可以用 launchd，Linux 可以用 cron；示例：

```cron
0 8 * * * cd /Users/cm/workspace/github/skills && \
  /usr/bin/python3 folo-receive/scripts/folo_receive.py \
  --config /Users/cm/.config/folo-receive/config.json --write
```

定时任务只生成摘要，不发通知；如果需要“现在看”提醒，再单独加 macOS 通知或 Telegram，不默认推送。

### 6. 调参

- 每天记录：top 5 里你打开/剪藏了几条；
- 每周抽 20 条被过滤（T3/低于阈值/排除词）的，检查有没有重要遗漏；
- 连续 4 周没有贡献有用条目的源，降级或退订；
- 高产但低价值的源，降到 T3 或加 `exclude_keywords`；
- 如果 T2 噪声仍然大，再考虑加 LLM 评分；当前版本不需要 LLM。

## Exit Criteria

- [ ] dry-run 或 `--write` 实际执行，并报告 `时间线 / 显示 / T1 / T2 / T3 / 已收藏 / 排除 / 低于阈值`。
- [ ] `--write` 时摘要写入 `10-Inbox/folo-digest-YYYY-MM-DD.md`，没有写 `11-Clippings`。
- [ ] 摘要每条都有标题、来源、tier、分数、理由和原文链接。
- [ ] 重复运行同一日期不会重复展示已看过的 entry（除非 `--include-seen`）。
- [ ] T3 和 99归档没有进入摘要；已收藏/已拉取条目被跳过。
- [ ] 没有改变 Folo 已读状态，没有创建剪藏。
- [ ] 已说明下一步：值得留的条目加入 Folo Collection，再由 `folo-collection-pull` 拉取。

## Exit Protocol

```text
接收结果：
- 摘要：10-Inbox/folo-digest-YYYY-MM-DD.md
- 时间线：N；显示：N（现在 N / 候选 N）
- T1：N；T2：N；T3 未进入：N
- 已收藏跳过：N；排除词：N；低于阈值：N；单源上限：N
- 状态：~/.local/state/folo-receive/state.json
- 下一步：在 Obsidian 打开摘要；值得留的加入 Folo Collection
```

只跑了 dry-run 时明确说“未写文件、未更新状态”。不要把摘要说成“已经读完”或“已经剪藏”。
