---
name: folo
description: 操作 Folo（RSS 阅读器）的阅读流与订阅时用——拉时间线/未读、取条目正文、搜索并新增订阅源、整理已读与收藏、OPML 导入导出、管理 List。用户说"有什么新文章""哪些没读""帮我订阅这个源""搜一下有没有 X 的 RSS""把未读清一下""这篇存起来"时触发。不适用：读本地文件、上网搜资料（那是 research-router / tavily）、操作非 Folo 的 RSS 数据
---

# Folo CLI

**正文取自厂商官方 `skill.md`**（`https://api.folo.is/skill.md`，302 到 GitHub `RSSNext/Folo` 仓库 `apps/cli/skill.md`，2026-10-10 抓取，CLI 版本 0.0.5），逐字保留、未做改动。下面一段是**本机实测校正与守卫——与厂商正文冲突时以本段为准**；返回结构、`--view` 取值、错误码等细节见 `references/commands.md`。

## 本机实测校正（优先于厂商正文）

1. **版本策略覆盖厂商的 Execution Policy。** 厂商写 `npx --yes folocli@latest`，本机不用 `@latest`——每次执行都拉 npm 最新版，等于把登录 token 交给版本不受控的包。改用：优先已装的 `folo`（本机 `folocli@0.0.5`），缺失时 `npx --yes folocli@0.0.5`。升级时同步改这两处。
2. **破坏性操作必须先跟用户确认**，并在同一段里说清影响面：`entry mark-all-read`（清空未读状态，本机实测 3600 条，不可逆）、`subscription remove`、`list delete`、`opml import`（批量建订阅，先看清文件里有多少条）。厂商正文没有任何确认要求。
3. **`entry read` 不改已读状态**（实测走 `entries.readability`，纯取正文）；改状态的是 `entry mark-read`。别因为怕改状态而不敢用它取正文。
4. **条目 id 的位置**：时间线每条是「来源 + 条目」的包裹结构，entryId 在 `data.entries[i].entries.id`，feedId 在 `.feeds.id`——不是 `[i].id`。厂商正文没写输出结构，照字面取会全部取空。
5. **环境事实**：`folo` 全局装在 nvm 当前 node 版本目录下，`nvm use` 换版本后报 `command not found`，按第 1 条的 npx 兜底，不是 skill 装坏了。凭据在 `~/.folo/config.json`（明文 JSON、权限 644），不要放进任何同步或上传目录；token 优先级 `--token` > `$FOLO_TOKEN` > 配置文件。
6. **写操作一律回读校验**（2026-10-12 实测踩过）：`subscription update <id> --category ""` 会把分类**清空**成「未分类」——传参与解析出错时字段会被写空而不是报错，所以每次写完都要用 `subscription list` 回读同一字段确认。同批实测另三条：`opml export` 在 0.0.5 是坏的（带 `--output` 报 `UNKNOWN_ERROR`，不带则返回空 `data`），备份要自己按 OPML 2.0 生成；`feed refresh` 需管理员权限（普通账号报 `Only admins can refresh feeds`）；`feed analytics` 的 `updatesPerWeek=0` / `latestEntryPublishedAt=null` **不能**用来判断源是否可用（实测有 0/周 的源订阅后正常送达内容），判可用性看「订阅 → `timeline --feed <feedId>` 回读」。
7. **新订阅会触发抓取**：实测订阅一个 analytics 显示 0 更新的源，仍能立刻拉到它的历史条目（6 个新源 6/6 成功），所以"加订阅"本身可以用来修复一个在 Folo 里没内容的源。
8. **要「过滤」用 `hideFromTimeline`，不是 Spotlight。** Spotlight 只是关键词/正则**高亮着色**（源码字段仅 `pattern` / `patternType` / `caseSensitive` / `color`），没有任何隐藏、标读、通知动作。真正的过滤是订阅级的 `hideFromTimeline`：该源条目不进时间线，**时间线的未读口径也不含它**（源码 `unread/getters.ts` 传 `excludeHidden: true`，注释明确"服务端同样把隐藏订阅排除在时间线之外"）。CLI 的 `subscription update` **不暴露**这个 flag，但 SDK 类型 `SubscriptionUpdateRequest` 里有 `hideFromTimeline?: boolean | null`，可直调 SDK 批量设置（脚本见 `references/commands.md`）。注意：服务端的账号级 `unread count` **不变**，隐藏只改时间线口径。
9. **两件未实测的事，不要当事实讲**：`--api-url` 指向自建实例是否可行；免费账号（本机 `role: free`）能否建收费 List。

**以下为厂商原文（逐字保留，未改动）：**

# Folo CLI Skill

## Trigger Conditions

Use this skill when a user asks to:

- Manage RSS subscriptions
- Browse timeline entries
- Read entry details or readability content
- Mark entries as read/unread
- Search feeds/lists or trending sources
- Import/export OPML
- Check unread counts

## Preconditions

1. Node.js and npm are installed so the CLI can be executed with `npx`.
2. Authentication is configured:
   - `npx --yes folocli@latest login` (recommended, opens browser and auto-logins)
   - or `npx --yes folocli@latest login --token <session-token>`
   - or set `FOLO_TOKEN=<token>`

## Execution Policy

- Prefer `npx --yes folocli@latest ...` for all agent runs.
- Do not require `npm install -g folocli`.
- No separate update preflight is needed. Using `folocli@latest` is the update strategy.
- If a user already has a working global `folo` binary, it is acceptable, but `npx --yes folocli@latest` remains the recommended default in docs and automation.

## Output Contract

Default output is JSON with a stable envelope:

```json
{
  "ok": true,
  "data": {},
  "error": null
}
```

Errors return:

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "UNAUTHORIZED",
    "message": "Token is invalid or expired."
  }
}
```

You can switch output mode:

- `--format json` (default)
- `--format table`
- `--format plain`

## Core Workflows

### 1. Timeline Reading

1. Fetch timeline:
   - `npx --yes folocli@latest timeline --limit 10`
2. Get entry detail:
   - `npx --yes folocli@latest entry get <entryId>`
3. Get readability content:
   - `npx --yes folocli@latest entry read <entryId>`

### 2. Subscription Management

1. Discover:
   - `npx --yes folocli@latest search discover <keyword>`
2. Add subscription:
   - `npx --yes folocli@latest subscription add --feed <url>`
   - or `npx --yes folocli@latest subscription add --list <listId>`
3. List subscriptions:
   - `npx --yes folocli@latest subscription list`

### 3. Unread Processing

1. Check unread total:
   - `npx --yes folocli@latest unread count`
2. List unread subscriptions:
   - `npx --yes folocli@latest unread list`
3. Read unread entries:
   - `npx --yes folocli@latest timeline --unread-only --limit 20`
4. Mark read:
   - `npx --yes folocli@latest entry mark-read <entryId>`
   - or batch: `npx --yes folocli@latest entry mark-all-read --view articles`

### 4. Collection Operations

- Add: `npx --yes folocli@latest collection add <entryId>`
- Remove: `npx --yes folocli@latest collection remove <entryId>`
- List: `npx --yes folocli@latest collection list --limit 20`

### 5. OPML Import / Export

- Export:
  - `npx --yes folocli@latest opml export --output backup.opml`
- Import:
  - `npx --yes folocli@latest opml import feeds.opml`

## Pagination Pattern

`npx --yes folocli@latest timeline` returns:

- `entries`
- `nextCursor`
- `hasNext`

Loop until `hasNext` is `false`:

1. `npx --yes folocli@latest timeline --limit 20`
2. Read `nextCursor`
3. `npx --yes folocli@latest timeline --limit 20 --cursor <nextCursor>`
4. Repeat

## Command Reference

- `npx --yes folocli@latest login [--timeout <seconds>] [--token <token>]`
- `npx --yes folocli@latest logout`
- `npx --yes folocli@latest whoami`
- `npx --yes folocli@latest auth login [--timeout <seconds>] [--token <token>]`
- `npx --yes folocli@latest auth logout`
- `npx --yes folocli@latest auth whoami`

- `npx --yes folocli@latest timeline [--view <type>] [--limit <n>] [--unread-only] [--cursor <datetime>]`
- `npx --yes folocli@latest timeline --feed <feedId> [--limit <n>] [--cursor <datetime>]`
- `npx --yes folocli@latest timeline --list <listId> [--limit <n>] [--cursor <datetime>]`
- `npx --yes folocli@latest timeline --category <name> [--view <type>] [--limit <n>]`

- `npx --yes folocli@latest subscription list [--view <type>] [--category <name>]`
- `npx --yes folocli@latest subscription add --feed <url> [--category <name>] [--view <type>] [--private]`
- `npx --yes folocli@latest subscription add --list <listId> [--category <name>] [--view <type>]`
- `npx --yes folocli@latest subscription remove <id> [--target feed|list|url]`
- `npx --yes folocli@latest subscription update <id> [--target feed|list] [--category <name>] [--title <title>] [--view <type>] [--private|--public]`

- `npx --yes folocli@latest entry get <entryId>`
- `npx --yes folocli@latest entry read <entryId>`
- `npx --yes folocli@latest entry mark-read <entryId>`
- `npx --yes folocli@latest entry mark-unread <entryId>`
- `npx --yes folocli@latest entry mark-all-read [--feed <feedId>] [--list <listId>] [--view <type>]`

- `npx --yes folocli@latest feed get <feedId|feedUrl>`
- `npx --yes folocli@latest feed refresh <feedId>`
- `npx --yes folocli@latest feed analytics <feedId>`

- `npx --yes folocli@latest list ls`
- `npx --yes folocli@latest list get <listId>`
- `npx --yes folocli@latest list create --title <title> [--description <desc>] [--view <type>] [--fee <n>]`
- `npx --yes folocli@latest list update <listId> [--title <title>] [--description <desc>] [--view <type>] [--fee <n>]`
- `npx --yes folocli@latest list delete <listId>`
- `npx --yes folocli@latest list add-feed <listId> --feed <feedId>`
- `npx --yes folocli@latest list remove-feed <listId> --feed <feedId>`

- `npx --yes folocli@latest search discover <keyword> [--type feeds|lists]`
- `npx --yes folocli@latest search rsshub <keyword> [--lang <lang>]`
- `npx --yes folocli@latest search trending [--range 1d|3d|7d|30d] [--view <type>] [--limit <n>] [--language eng|cmn] [--category <keyword>]`

- `npx --yes folocli@latest collection list [--limit <n>] [--cursor <datetime>]`
- `npx --yes folocli@latest collection add <entryId> [--view <type>]`
- `npx --yes folocli@latest collection remove <entryId>`

- `npx --yes folocli@latest opml export [--output <file>]`
- `npx --yes folocli@latest opml import <file> [--items <url1,url2,...>]`

- `npx --yes folocli@latest unread count`
- `npx --yes folocli@latest unread list [--view <type>]`

## Error Recovery

- `UNAUTHORIZED`
  - Re-login: `npx --yes folocli@latest login`
  - or `npx --yes folocli@latest login --token <token>`
  - Or set `FOLO_TOKEN`
- `HTTP_4xx` / `HTTP_5xx`
  - Retry with `--verbose` for request details
  - Verify `--api-url` if using non-default endpoint
- `INVALID_ARGUMENT`
  - Run `npx --yes folocli@latest <command> --help` to inspect accepted options
