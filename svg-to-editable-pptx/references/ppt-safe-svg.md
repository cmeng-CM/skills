# PPT-safe SVG Profile

本规范限定可稳定映射为 PowerPoint 原生对象的 SVG 子集。输入不符合规范时，先修改 SVG，不要降级为整图图片。

## 支持

### 元素

- `svg`、`g`
- `rect`，包括 `rx` / `ry` 圆角
- `circle`、`ellipse`
- `line`
- `path`
- `polygon`、`polyline`
- `text`、`tspan`
- `defs` 中的 `linearGradient`、`marker`、`style`

### Path 命令

- 绝对或相对：`M/m`、`L/l`、`H/h`、`V/v`
- 二次和三次曲线：`Q/q`、`C/c`
- 闭合：`Z/z`

曲线会采样为 PowerPoint 自由形状节点。对架构图图标足够，但不适合要求像素级曲线控制的复杂插画。

### 样式

- CSS 标签选择器和单类选择器，例如 `text {}`、`.card {}`
- 行内 `style` 与常用 presentation attributes
- 实色填充、线性渐变
- `stroke`、`stroke-width`、`stroke-dasharray`
- `marker-start`、`marker-end`，映射为 PowerPoint 三角箭头
- `text-anchor`、`font-size`、`font-weight`、`font-style`
- `fill-opacity` 和简单 `opacity`，可能存在轻微差异

## 不支持并终止

- `image`、`use`、`foreignObject`
- `textPath`
- `clipPath`、`mask`、`pattern`
- `symbol`
- 任意 `transform`
- Path 的 `A/S/T` 等未列出的命令
- 嵌入字体、外部 CSS、脚本和动画

这些特性无法稳定映射为独立 PowerPoint 对象。预检发现后必须修改源 SVG。

## 可继续但必须视觉检查

- `filter` 和 `feDropShadow`：当前忽略，不影响对象可编辑性，但阴影可能减少。
- 非 100% `opacity`：转换结果可能与浏览器混合效果略有差异。
- 字体：PowerPoint 使用命令行指定字体；目标机器没有字体时会发生替换。
- 多个 `tspan`：按多行文字处理，不保留每个 tspan 的独立字体或位置变化。
- 渐变角度：稳定支持水平和垂直线性渐变，复杂角度会近似。

## SVG 绘制建议

- 使用明确的 `width`、`height` 和 `viewBox`。
- 复杂图标优先使用简单闭合 path，不使用 mask 或 clipPath。
- 用独立 `text` 元素表达每个标签；多行标签用 `tspan`。
- 用 `marker-end` 表达箭头，不手工叠加三角形。
- 将背景、容器、连线、文字按期望的 PowerPoint 图层顺序书写。
- 为需要后续识别的元素设置稳定 `id`。
- 圆角使用 `rx` / `ry`；转换器会按 SVG 半径校正 PowerPoint 默认圆角。
- 避免依赖浏览器特有字体测量；长文本预留 10% 以上宽度。

## 模板适配

- 先渲染 PPT 模板，测量页眉、LOGO、页脚之外的内容区域。
- `--max-width` 和 `--max-height` 表示 SVG 的等比适配框，不会拉伸。
- `--x` 省略时水平居中；`--y` 必须根据模板显式选择。
- 对于 16:9 模板，常见内容框可从 `y=0.5~0.8in` 开始，到页脚上方结束，但不得直接套用固定数值。
