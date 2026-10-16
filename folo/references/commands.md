# Folo CLI 实测细节

只放**厂商原文没有、或写得不够**的部分。命令全量清单见 `SKILL.md` 内嵌的厂商原文（Command Reference 一节），这里不重复。

## 环境与凭据（本机实测）

| 项 | 值 |
|---|---|
| 安装方式 | 全局 `folocli@0.0.5`，命令名 `folo` |
| 二进制位置 | `~/.nvm/versions/node/v25.8.2/bin/folo`（随 nvm 当前 node 版本，换版本会消失） |
| 凭据文件 | `~/.folo/config.json`，明文 JSON，字段 `token` / `apiUrl`，权限 644 |
| token 优先级 | `--token` 参数 > `$FOLO_TOKEN` 环境变量 > 配置文件 |
| 浏览器登录机制 | 本地起 `127.0.0.1` 随机端口回调（`/callback`），打开 `app.folo.is/login?cli_callback=...`；默认等 180 秒（`--timeout` 可调）；浏览器打不开时终端会打印 URL 手动打开 |
| 请求凭据头 | 同时带 `Authorization: Bearer` 与 `better-auth.session_token` cookie |
| API 环境映射 | 生产 `api.folo.is` / `app.folo.is`；包内还含 dev / staging / local 端点 |

## `--view` 合法取值（实测，来自包内 `viewHelp`）

```
articles(0) | social(1) | pictures(2) | videos(3) | audio(4) | notifications(5)
```

名字或数字都接受，其他值报 `Invalid view`。这个参数在厂商原文里出现十几次，但没写过合法值。

## 时间线返回结构（实测）

厂商原文只说了返回 `entries` / `nextCursor` / `hasNext`，没写结构。实际每条是「来源 + 条目」的**包裹结构**：

```jsonc
{
  "ok": true,
  "data": {
    "entries": [
      {
        "read": false,              // 是否已读
        "view": 0,                  // 视图数字
        "aiScore": null,
        "from": ["feed"],           // 来源类型数组
        "entries": {                // ★ 条目对象（单个对象，不是 map）
          "id": "1326587252758786048",   //   → 这就是 entry get / read / mark-read 要的 entryId
          "title": "...", "url": "...", "description": "...",
          "guid": "...", "author": null, "publishedAt": "..."
        },
        "feeds": {                  // ★ 单个 feed 对象
          "type": "feed", "id": "41443203209057309",
          "url": "rsshub://caixin/latest", "title": "...", "siteUrl": "..."
        },
        "subscriptions": { /* ... */ },
        "settings": {}
      }
    ],
    "nextCursor": "2026-10-10T08:36:05.057Z",
    "hasNext": true
  },
  "error": null
}
```

**最容易踩的坑**：entryId 在 `.entries[i].entries.id`，feedId 在 `.entries[i].feeds.id`；照厂商字面把 `[i]` 当条目，所有 id 都会取空。

## 其它实测返回形状

| 命令 | 返回 |
|---|---|
| `unread count` | `data.count`（本机实测 3600） |
| `entry get <id>` | `data.{feeds, entries, settings}`——`data.entries` 同样是那个条目对象 |
| `entry read <id>` | `data.content`，readability 处理后的 HTML 片段（实测某篇 1352 字符）；**不改已读状态** |
| `timeline` 包裹层 | `read` / `view` / `aiScore` / `from` / `entries` / `feeds` / `subscriptions` / `settings` |

## 错误恢复补充

厂商原文的几条之外，本机确认过的：

| code | 处理 |
|---|---|
| `UNAUTHORIZED` | 让用户跑 `folo login`（浏览器授权，agent 代不了）或设 `FOLO_TOKEN`；**不要反复重试** |
| `BROWSER_OPEN_FAILED` | 浏览器没自动打开，终端里那串 URL 手动打开即可 |
| `NETWORK_ERROR` | 本地回调服务器起不来（端口/权限），重试或改用 `--token` |

## 写操作与源可用性实测（2026-10-12，真跑过）

**写操作必须回读校验。** `subscription update <id> --category ""`（传空值，例如脚本解析出错）会把分类**清空**成「未分类」，命令仍返回 `ok: true`——错误的值静默写进去，只有回读才发现。正确流程：

```bash
folo subscription update <feedId> --target feed --category "80深度"
folo subscription list | # 回读该 feedId 的 category 字段确认
```

**源可用性的正确判法**（踩过的坑）：

| 信号 | 能不能用来判断"这个源在 Folo 里收得到内容" |
|---|---|
| `feed analytics` 的 `updatesPerWeek=0` | ✗ 只表示近 7 天没新条目入库。实测阮一峰显示 0/周，订阅后立刻拉到内容 |
| `feed analytics` 的 `latestEntryPublishedAt=null` | ✗ 不可靠。实测宝玉的博客该字段为 null，但 `timeline --feed` 有 3 条内容 |
| `feed get` | ✗ 实测返回 `{}`，没有状态信息 |
| ** `timeline --feed <feedId>` 回读** | ✓ 唯一可靠的判法：有条目=可用 |

**新订阅会触发抓取**：订阅一个 analytics 显示 0 更新的源，仍能立刻拉到它已发布的历史条目（6/6 实测成功）。所以"重新订阅"可以当作修复一个在 Folo 里不产出的源的候选手段。

**三个坏掉的/受限的命令**：

| 命令 | 实测结果 |
|---|---|
| `opml export [--output <file>]` | **坏**。带 `--output` 报 `UNKNOWN_ERROR: The "data" argument must be of type string...`，不带则返回 `data: {}`。备份要自己按 OPML 2.0 生成（分类用嵌套 outline，`type="rss"` + `xmlUrl`/`htmlUrl`），实测生成的 53 条 OPML 结构合法 |
| `feed refresh <feedId>` | 需管理员：普通账号返回 `code 2000 Only admins can refresh feeds` |
| `search discover` 返回的 feed 对象 | 含 `errorMessage`/`errorAt` 字段，可用于识别上游报错的源（如 `wechat2rss` 类路由 `[GET] ... failed`） |

**其它实测**：`subscription add --category <中文名>` 与 `subscription update --category <中文名>` 都能正确写入中文分类名（新增 6 个源 6/6 正确落位）；`subscription list` 返回的每个订阅带 `hideFromTimeline` 字段，但 CLI 没有设置它的选项（客户端侧能力，未实测）。

## CLI 能查到哪些源（2026-10-12 实测）

| 命令 | 状态 | 实测结果 |
|---|---|---|
| `search discover <kw>` | ✓ 可用 | 搜 Folo 源索引，返回 `feed{id,url,title,errorMessage,errorAt}` + `subscriptionCount` + `updatesPerWeek` + `analytics` + `entries`，一次 37~50 条。**找候选源的主力** |
| `search discover <kw> --type lists` | ✓ 可用 | 返回 `list{id,feedIds[],title,fee,...}` + `subscriptionCount`，50 条。**List = 打包一批源**，`subscription add --list <listId>` 一条命令订一批；`fee > 0` 是收费列表（free 角色能否订未实测） |
| `search trending [--range 1d\|3d\|7d\|30d] [--view] [--language eng\|cmn] [--category]` | ✓ 可用 | 返回 `data.feeds[]`，每项含 feed 对象 + `score7d` 热度分 |
| `search rsshub <keyword> [--lang]` | ✗ **坏的** | 帮助文本写 "Search RSSHub routes by category keyword"，实测对 `github`/`twitter`/`bilibili`/`zhihu`/`weibo`/`播客`/`YouTube`（中英文全试）一律返回空 `data: {}`。**RSSHub 路由目录不能通过 CLI 浏览** |
| `list ls` | ✓ 可用 | 返回自己的 list（本机为空数组） |
| `list get <listId>` | ✓ 可用 | 能看任意 list 的内容，含 `feedIds` 数组（实测一个 4 源免费 list） |

**结论：加源不依赖发现能力。** 只要给出 URL 或 `rsshub://` 路由就能 `subscription add`（且会触发抓取，见上）。本机现有订阅里已经含 19 种 `rsshub://` 路由族（twitter / telegram / youtube / xiaoyuzhou / bilibili / gov / caixin / v2ex / sspai / github / zaobao / jike / latepost / readhub / bjp / nasa / 1x / baoyu / deeplearning）+ 微信公众号第三方抓取 URL + 原生 RSS/Atom。所以 X、YouTube、B 站、播客、公众号、Telegram 这些类型 CLI 都能承载——限制只在"发现"一步（靠 `search discover` 或外部查 RSSHub 文档拿路由）。

## 真正的过滤是 `hideFromTimeline`（2026-10-12 实测）

Folo 的「过滤」不由 Spotlight 承担（Spotlight 只做关键词高亮）。起作用的是**订阅级开关** `hideFromTimeline`：

| 行为 | 证据 |
|---|---|
| 该源条目**不进时间线** | `entry/store.ts`：新条目入库时若 `subscription.hideFromTimeline` 为真，不加入 `entryIdByView` 的任何桶 |
| 时间线的**未读口径不含它** | `unread/getters.ts` 的 `getUnreadScopeIds` 传 `excludeHidden: true`；注释原文："Hidden subscriptions are left out of the timeline by the server as well." |
| 服务端账号级 `unread count` **不变** | 实测隐藏前后都是 3.7k 量级（只随时间增长），隐藏只改时间线口径 |
| 源不丢 | 订阅、历史都在；单独打开该 feed 仍能看到它的条目 |
| App 里的入口 | 订阅/列表的编辑表单（源码 `FeedForm.tsx` / `ListForm.tsx` 含该字段）：设置 → 订阅源 → 编辑 |

**CLI 不支持这个 flag**（`subscription update` 只有 `--category/--title/--view/--private/--public`，包里搜不到 `hideFromTimeline`）。但 SDK 类型支持：

```ts
// @follow-app/client-sdk → SubscriptionUpdateRequest
{ view?, category?, isPrivate?, hideFromTimeline?: boolean | null, title?, feedId?, listId? }
```

用 node 直调 SDK 批量设置（`<缓存目录>` 用 `ls ~/.npm/_npx` 找，SDK 随 folocli 装在缓存里）：

```js
import { readFileSync } from 'node:fs'
const cfg = JSON.parse(readFileSync(process.env.HOME + '/.folo/config.json', 'utf8'))
const { FollowClient } = await import(
  process.env.HOME + '/.npm/_npx/<缓存目录>/node_modules/@follow-app/client-sdk/dist/index.mjs'
)
const client = new FollowClient({ baseURL: 'https://api.folo.is' })
client.setAuthToken(cfg.token)
client.setHeaders({ Cookie: `__Secure-better-auth.session_token=${cfg.token}; better-auth.session_token=${cfg.token}` })
await client.api.subscriptions.update({ feedId: '<feedId>', hideFromTimeline: true })
// → { code: 0, lastSyncId: ... }
```

**必须回读**：写入后 `folo subscription list` 确认该源 `hideFromTimeline` 变 `true`。这条写入路径官方 CLI 没有暴露，`code: 0` 不等于业务生效。实测批量 10/10 成功。



