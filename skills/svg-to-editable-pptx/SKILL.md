---
name: svg-to-editable-pptx
description: 将单个或多个 SVG 高保真插入或替换到现有 PowerPoint（.pptx）指定页，并转换为可编辑的原生文字、形状、路径、线条和箭头，同时保护模板、母版、背景、LOGO 与非目标页面。用户要求“SVG 转 PPT/PPTX”“把 SVG 写入 PPT”“转换后可编辑”“替换某页架构图”“保留 PPT 模板”时使用；也用于转换前检查 SVG 是否适合原生图形转换。
---

# SVG to Editable PPTX

使用 `scripts/svg_to_editable_pptx.py` 完成确定性转换。不要临时重写转换器，也不要把 SVG 作为普通图片插入后声称可编辑。

## 核心约束

- 一次命令处理一张 SVG；处理多张时按页顺序重复执行，不依赖项目配置文件。
- 只接受 PPT-safe SVG。遇到不支持的元素必须停止，不自动栅格化。
- 默认保留占位符和母版元素；只有用户明确要求替换整页内容时才使用 `replace-slide`。
- 使用最小补丁模式，只改变目标 `ppt/slides/slideN.xml`；报告出现其他 changed parts 时视为失败。
- 转换后的每个元素必须保持为独立 PowerPoint 原生对象。

## 执行流程

### 1. 检查输入

确认 SVG、PPTX 和目标页。先用 `officecli view <pptx> outline`、`officecli get <pptx> '/slide[N]' --depth 1` 和截图检查模板及目标页。

目标页或应删除内容存在歧义时先询问用户，不自行猜测。

### 2. 预检 SVG

```bash
python3 scripts/svg_to_editable_pptx.py \
  --svg "/abs/diagram.svg" \
  --preflight-only
```

退出码 `0` 才能转换。警告需要结合 `references/ppt-safe-svg.md` 判断；阴影滤镜警告可以继续，但必须做视觉检查。错误不得绕过。

### 3. 选择写入模式

| 模式 | 使用条件 | 行为 |
| --- | --- | --- |
| `append` | 空白页或保留已有内容 | 不删除现有对象，追加 SVG 图形 |
| `replace-tagged` | 更新本 Skill 之前写入的图 | 只删除相同 `--prefix` 的对象 |
| `replace-slide` | 明确替换目标页的普通内容 | 删除非占位符页内对象；必须传 `--expected-text` 或显式 `--force` |

优先使用 `replace-tagged`；首次替换已有图时使用 `replace-slide --expected-text`。不要用 `--force` 规避尚未确认的页面内容。

### 4. 转换

写入新文件：

```bash
python3 scripts/svg_to_editable_pptx.py \
  --pptx "/abs/input.pptx" \
  --svg "/abs/diagram.svg" \
  --slide 3 \
  --mode replace-slide \
  --expected-text "部署架构" \
  --output "/abs/output.pptx" \
  --y 0.58 \
  --max-width 11.70 \
  --max-height 6.22
```

直接更新原文件时使用 `--in-place`。脚本会先创建带时间戳的备份：

```bash
python3 scripts/svg_to_editable_pptx.py \
  --pptx "/abs/deck.pptx" \
  --svg "/abs/diagram.svg" \
  --slide 3 \
  --mode replace-tagged \
  --prefix svg2pptx \
  --in-place
```

`--x` 省略时自动水平居中。先根据模板截图确定 `--y`、`--max-width` 和 `--max-height`，不要让图覆盖页眉、LOGO 或页脚。

处理多张 SVG 时逐次以上一次输出作为下一次输入。不要为一次性任务创建 YAML。

### 5. 验收

必须完成以下检查：

```bash
OFFICECLI_NO_AUTO_RESIDENT=1 officecli validate "/abs/output.pptx"
OFFICECLI_NO_AUTO_RESIDENT=1 officecli view "/abs/output.pptx" issues
OFFICECLI_NO_AUTO_RESIDENT=1 officecli view "/abs/output.pptx" screenshot --page 3 -o /tmp/slide-3.png
OFFICECLI_NO_AUTO_RESIDENT=1 officecli view "/abs/output.pptx" screenshot --grid 3 -o /tmp/deck-grid.png
```

验收标准：

- JSON 报告的 `package.changed_parts` 只能包含目标 slide XML。
- `view issues` 为 0；若模板原本存在 schema 警告，只接受与转换前相同的警告集合。
- 目标页无裁切、溢出、错误圆角、错位箭头、字体替换或文字遮挡。
- 全页缩略图确认非目标页、模板背景、LOGO 和页脚未变化。
- 有 filter/opacity 警告时，对对应对象逐项目视确认。

转换或验收失败时保留原文件和备份，报告具体失败项，不交付半成品。

## 环境

需要 Python 3、`python-pptx>=1.0` 和 `officecli`。在 Codex 桌面环境中优先调用 workspace dependency Python；普通 `python3` 缺少 `pptx` 模块时，不要改脚本，改用已配置的依赖运行时。

SVG 支持范围、限制和绘制建议见 `references/ppt-safe-svg.md`。
