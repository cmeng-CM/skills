---
name: mineru
description: 把图片、扫描 PDF、拍照材料识别为结构化 Markdown 的本地识别层，表格还原为 Markdown 表格；转 Word/Excel 先经本 skill 识别再转交 officecli 等排版。用户要识别图片/照片、扫描件转文字或表格、图片转 Word/Excel 时使用。单页简单内容或看图问答用视觉模型直读；带文本层的 PDF 走文本提取，均不走本 skill。
---

# MinerU 文档识别

本地 MinerU CLI 把图片与无文本层 PDF 识别为结构化 Markdown（表格、公式、版面）。本 skill 只做识别层：识别结果落盘后，Word/Excel 由 officecli、docx/xlsx skill 或 pandoc 完成。

## Working Protocol

### 1. 路由判断（先于执行）

| 输入与诉求 | 走向 |
|---|---|
| 图片 / 无文本层 PDF，要转档或落盘 | 本 skill |
| 单页且内容简单，只需口头回答或轻度整理 | 视觉模型直读，不启动本 skill |
| PDF 有文本层（能选中文字、pdftotext 能提取） | 文本提取（pdf skill / pdftotext），不走 MinerU——重 OCR 更慢且可能引入错字 |
| 要把内容语义重写成报告 | 视觉模型处理；本 skill 只做原样转写 |
| 批量、多页、表格数字要逐字准 | 本 skill 的优势场景 |

不确定 PDF 是否有文本层时，先 `pdftotext <文件> -` 试提取；空或乱码再走 MinerU。

### 2. 执行识别

```bash
mineru-kit parse <输入文件或目录> -o <输出路径> --tier standard
```

- `--tier` 默认 standard；只要文字大意可降 flash；确认纯扫描件加 `--ocr-mode ocr`；追求精度用 advanced（更慢）
- 大 PDF 用 `--pages 1-10,25` 选页；目录批量时 `-o` 必须是目录
- 需要表格截图或中间 JSON 时加 `--format zip`（产物结构见 references/tips.md）
- 输出目录默认 `~/workspace/temp/yyyyMMdd`（当天日期），用户另有指定时从其指定
- 命令找不到时检查 `~/.local/bin` 是否在 PATH；未安装时按 references/tips.md 的安装节处理

### 3. 转交下游（识别完成即转交，本 skill 不排版）

- 要 Excel：把 md 中的表格交给 xlsx skill 或 officecli 生成 xlsx
- 要 Word：全文 md 交给 docx skill / officecli；需套模板时走 pandoc reference-doc
- 数字关键场景（报表、价格、实验数据）：转交时提示抽查——用 zip 里的表格截图或视觉模型对照 md 核对

### 4. 边界与失败处理

- CLI 不直出 docx/xlsx，输出只有 markdown / middle_json / zip；不要尝试找 docx 输出参数
- 无线框表格不还原为表格（按行输出文字）；需要表格结构时告知用户此限制，可改由视觉模型尝试并提醒核对
- 首次调用冷启动约 50 秒（模型加载）；连续批量前可 `mineru server start` 常驻
- 永远不加 `--remote`（材料不出本机），除非用户明确要求云端解析
- 识别错误只报告不静默修正；无法判断是否扫描件时按默认 auto 先跑

## Exit Criteria

- [ ] 产物 md 已落盘，输出路径已告知用户
- [ ] 含表格的输入已核对表格结构完整（行列、表头无错位）
- [ ] 发生转交时，明确说出转交对象与下一步
- [ ] 让位场景（视觉模型 / 文本提取）已说明原因

## Exit Protocol

交付时报告：产物路径、内容概览（页数、表格数）、识别疑点。需要 Word/Excel 时给出转交建议，不直接展开排版，除非用户要求继续。失败时报告命令、报错与已排除的原因，不按完成交付。
