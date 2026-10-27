# MinerU 补充信息

安装环境、性能数据、产物结构、长文档用法与路由依据。执行细节变化时以 `mineru-kit parse --help` 实际输出为准。

## 安装与环境（2026-10-27 实装）

- 版本 v4.0.12（uv tool，Python 3.12）。安装：`uv tool install --python 3.12 "mineru>=4.0,<5"`。命令与参数以 4.x 为准，5.0 可能不兼容
- 命令在 `~/.local/bin`：`mineru`（文档库/服务）、`mineru-kit`（无状态转换）、`mineru-webui`（Gradio 网页）
- 模型在 `~/.mineru/models/`（standard 档 = 小模型套件 + MinerU2.5-Pro 1.2B GGUF）。补装或换机重装：`mineru-kit models download --tier standard --source modelscope`
- 模型源优先 modelscope（国内快）；默认本地解析，`--remote` 才走云端

## 性能（M 系 32GB 实测，standard 档）

| 场景 | 耗时 |
|---|---|
| 冷启动（含模型加载） | 约 50 秒 |
| 稳态文本 PDF | 1.5–3 秒/页 |
| 稳态图片 OCR | 约 3 秒/页 |

## zip 产物结构

```
markdown.md                # 主产物
middle_json.json           # 版面坐标级中间结果
structured_content.json    # 结构化内容
model_output.json          # 模型原始输出
images/                    # 抽取图片与表格截图（page_N_table_M.jpg，可人工核对数字）
```

## 长文档与批量

- `mineru server start` 常驻服务避免每次冷启动；`mineru parse` 默认只读 PDF 前 10 页，其余用返回的 locator 续读
- `mineru scan <目录>` 入文档库、`mineru search <词>` 全文检索，适合长期反复使用同一批文档
- `mineru-kit webui` 起本地网页，人工偶尔转文件用

## 路由依据（何时 MinerU、何时视觉模型）

- 基准：MinerU2.5（1.2B 专用模型）OmniDocBench 均分约 90.7，略超 Gemini 2.5 Pro（约 90.0），明显超 GPT-4o（80+）；出处 arXiv:2509.22186。同类专用小模型（dots.ocr）编辑距离约为 GPT-4o 一半。专用小模型在文档解析上稳定强于通用视觉大模型
- 通用视觉模型弱项：数字/内容幻觉、长文档上下文退化、表格行列与合并单元格错乱
- 本机 A/B（2026-10-27，简单中文表格 PNG）：视觉模型与 MinerU 输出逐字一致——简单场景精度不构成区分项，速度与省事才是
- 结论：单页简单 → 视觉模型；多页/批量/数字要准/要落盘 → MinerU；数字关键场景最优组合 = MinerU 识别落盘 + 视觉模型对照核对
