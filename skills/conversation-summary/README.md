# conversation-summary

`conversation-summary` 用于把当前对话或公开分享对话整理成一份简短、可迁移的中文上下文交接卡，方便在新对话、其他模型、IDE 插件或 CLI 工具中继续推进。

## 适用场景

- 总结当前可见对话，生成上下文交接卡。
- 读取公开分享链接，并基于真实对话内容生成交接卡。
- 更新已有交接卡，合并新确认的信息，删除过时内容。
- 将上下文迁移到其他 AI 工具、模型或新会话。

常见触发说法：

```text
总结当前对话
生成上下文交接卡
更新这份交接卡
总结这个分享链接的对话内容：https://...
```

## 输出格式

默认输出中文 Markdown，并固定使用以下七个章节：

```markdown
# 上下文交接卡

## 1. 当前任务

## 2. 当前目标

## 3. 已确定结论

## 4. 当前基准稿

## 5. 待解决问题

## 6. 下一步建议

## 7. 后续对话使用方式
```

交接卡只保留高信号信息：任务背景、约束、已确认结论、当前可复用内容、待解决问题和下一步动作。不会复述完整聊天记录。

## 分享链接读取策略

当用户提供公开分享链接时，skill 会优先尝试不安装浏览器引擎的读取方式：

1. HTTP、静态抓取或 `web_fetch` 类工具。
2. bundled 脚本 `scripts/render_share_text.py` 的静态模式。
3. 已知公开分享 API，例如 `qianwen.com/share/chat/...` 的 `share/info` 接口。
4. HTML、SSR 数据、路由数据、嵌入 JSON、长文本字段抽取。

只有静态读取失败，并且确实需要执行 JavaScript 渲染时，才考虑浏览器路径。浏览器路径默认不自动启用，也不会自动安装 Playwright 浏览器引擎。

已重点验证的链接类型：

- `doubao.com/thread/...`
- `qianwen.com/share/chat/...`

## 脚本用法

脚本路径：

```bash
scripts/render_share_text.py
```

普通静态读取：

```bash
python3 scripts/render_share_text.py "https://www.doubao.com/thread/..." --static-only
```

千问长对话或多主题对话推荐使用 compact 模式：

```bash
python3 scripts/render_share_text.py "https://www.qianwen.com/share/chat/..." --static-only --compact
```

`--compact` 会先输出完整 `User Turn Index`，再输出每轮用户问题和回答摘录，避免长对话总结时只覆盖最后几轮。

常用参数：

- `--static-only`：只做静态读取，不启动本机浏览器，不启动 Playwright。
- `--compact`：结构化压缩输出，适合长对话、多主题对话。
- `--timeout-ms 15000`：设置请求或渲染超时时间。
- `--user-chars 300`：compact 模式下每轮用户消息最大字符数。
- `--assistant-chars 900`：compact 模式下每轮助手回复最大字符数。
- `--allow-system-browser`：允许自动发现并启动本机 Chromium 系浏览器。
- `--allow-playwright`：允许启动已经安装好的 Playwright 托管浏览器。

## 浏览器与环境说明

默认策略是不污染用户电脑环境：

- 不自动执行 `playwright install`。
- 不自动下载 Chromium、Firefox、WebKit 等浏览器引擎。
- 不默认启动系统浏览器。
- 静态读取成功后，不再尝试浏览器渲染。

如果必须使用本机浏览器，推荐显式指定浏览器路径：

```bash
CONVERSATION_SUMMARY_BROWSER="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
python3 scripts/render_share_text.py "https://..." --allow-system-browser
```

系统差异：

- macOS：可使用 Chrome、Edge、Chromium、Brave；默认不会自动启动，避免系统崩溃弹窗。
- Windows：可使用 Chrome、Edge、Chromium、Brave 的 `.exe` 路径。
- Linux 或信创系统：优先使用已安装的 Chromium 系浏览器路径；如果没有可用浏览器引擎，无法可靠读取必须执行 JavaScript 后才显示内容的页面。

## 长对话总结要求

对长对话或多主题对话，必须先看 `User Turn Index` 或轮次标题，归纳主要主题簇，再生成交接卡。

不要只总结最后几轮。比如同一条分享里同时包含 Obsidian、Folo 二开、同步工具、代理客户端、V2EX、翻译工具等主题时，交接卡应在 `当前任务` 和 `已确定结论` 中按主题覆盖，而不是只保留最后的翻译模块。

## 常见问题

### 静态抓取只拿到很少内容，是否说明链接需要登录？

不一定。很多分享页首屏 HTML 只有空容器，正文可能在嵌入 JSON、后半段脚本或公开 API 中。不能只凭 `curl | head`、`head -c` 或 `_SSR_DATA` 为空就判断需要登录。

### 无痕浏览器能打开，但工具读取失败怎么办？

先运行 bundled 脚本：

```bash
python3 scripts/render_share_text.py "https://..." --static-only
```

如果是千问长对话：

```bash
python3 scripts/render_share_text.py "https://..." --static-only --compact
```

只有脚本也失败后，才考虑系统浏览器或让用户粘贴页面可见内容。

### 会不会安装浏览器引擎或污染用户环境？

默认不会。脚本不会自动安装 Playwright 浏览器，也不会默认启动系统浏览器。系统浏览器路径和 Playwright 都是显式 opt-in。

### 什么时候需要用户手动粘贴内容？

当静态抓取、bundled 脚本、已知公开 API、系统浏览器和已安装 Playwright 都不可用或都失败时，才请用户粘贴对话正文或页面可见内容。此时不要臆测链接内容。

## 文件结构

```text
conversation-summary/
├── SKILL.md
├── README.md
├── agents/
│   └── openai.yaml
└── scripts/
    └── render_share_text.py
```

