---
name: md-to-docx
description: 把 Markdown 文件转换为格式规范的 Word 文档（.docx）。用户说"转成 Word"、"转 docx"、"转成文档"、"转换这个 md"、"导出 Word"时触发。使用统一的 word.docx 样式模板确保格式一致。凡是涉及 .md 文件转 .docx 的需求，无论文件来自上传还是本地路径，都应使用本 skill。
---

# md-to-docx

把 Markdown 转换为格式规范的 Word 文档。使用 **预处理+转换（管道） → 后处理** 管线，以 `word.docx` 为样式模板。无中间文件残留。

---

## 工具依赖

| 工具 | 用途 | 是否必须 |
|------|------|----------|
| `pandoc` | 核心转换引擎 | 必须 |
| `python3` + `python-docx` | 模板样式注入 + 预处理 + 后处理 | 必须 |
| `node` + `npx` | Mermaid 图表渲染 (mmdc) | 可选（有 mermaid 图表时需要） |

环境检查：
```bash
pandoc --version
python3 -c "import docx; print('python-docx ok')"
```

`python-docx` 未安装时：
```bash
pip install python-docx --break-system-packages
```

---

## 执行步骤

### Step 0：预处理 + 转换（管道直连，无中间文件）

```bash
python3 scripts/pre_process.py <input.md> --mermaid 2> /tmp/md2docx.log \
  | pandoc -o <output.docx> \
      --reference-doc=word.docx \
      --from markdown-yaml_metadata_block-simple_tables-multiline_tables \
      --toc --toc-depth=3 --metadata toc-title=目录

# 清理 mermaid 临时图片（已嵌入 docx）
TMPDIR=$(grep 'Mermaid tmp:' /tmp/md2docx.log | sed 's/.*tmp: //' | sed 's/ (.*//')
rm -rf "$TMPDIR"
```

如果文档不含 mermaid 图表，去掉 `--mermaid`：
```bash
python3 scripts/pre_process.py <input.md> \
  | pandoc -o <output.docx> --reference-doc=word.docx \
      --from markdown-yaml_metadata_block-simple_tables-multiline_tables \
      --toc --toc-depth=3 --metadata toc-title=目录
```

预处理修复项目：列表前加空行、移除 `---` 分隔线、Mermaid 渲染为 PNG。

**路径约定：**
- 输出 `.docx` 与输入 `.md` 同级目录，同名换扩展名
- 例：`/path/to/prd.md` → `/path/to/prd.docx`

### Step 1：确保模板已注入样式（一次性）

```bash
python3 scripts/inject_styles.py
```

注入样式：Block Text、Compact、Source Code、Verbatim Char、Hyperlink、TOC Heading。

### Step 2：后处理

```bash
python3 scripts/post_process.py <output.docx>
```

后处理项目：
- **TOC 位置**：将目录从文档开头移到 H1 标题之后；设置 `updateFields` 使 Word 打开时自动填入页码
- **表格**：添加单元格边框、表头行加粗 + 灰底
- **图片**：宽度超过页面内容宽度 90% 时等比缩小（含 mermaid 生成的图片）
- **超链接**：确保 Hyperlink 字符样式存在（蓝色下划线）

### Step 3：验证结果

```bash
echo "exit: $?" && ls -lh <output.docx>
```

---

## 样式映射

| Word 样式 | MD 元素 | 效果 |
|-----------|---------|------|
| Heading 1–8 | `#` ~ `########` | 继承 word.docx 标题格式（Arial + 黑体） |
| Normal | 正文 | 12pt，两端对齐 |
| Block Text | `> 引用` | 斜体灰字，左蓝色边框，浅蓝底 |
| Source Code | ` ``` ` 代码块 | Courier New 9.5pt，灰底 + 边框，语法高亮 |
| Verbatim Char | `` ` `` 行内代码 | Courier New 10pt，红色，浅粉底 |
| Compact | 紧凑列表 | 紧凑行距 |
| Hyperlink | `[链接]()` | 蓝色下划线 |

---

## 已知陷阱（必读，遗漏必出问题）

### 陷阱 1：有序列表合并到上文段落 ⚠️ 最高频
**现象**：`1.` `2.` 列表项全部挤在一段，显示为连续文字。  
**原因**：中文写作习惯在列表前不加空行，pandoc/CommonMark 要求列表前必须空行。  
**解决**：Step 0 的 `pre_process.py` 自动修复，在列表前插入空行。

### 陷阱 2：`---` 分隔线使上文变成标题
**现象**：`---` 前一段文字变成 Heading 2 样式。  
**原因**：`-yaml_metadata_block` 禁用 YAML 解析后，pandoc 将 `---` 解释为 setext 标题下划线。  
**解决**：Step 0 的 `pre_process.py` 自动移除独立 `---` 行。

### 陷阱 3：章节标题变成表格
**现象**：文档中用 `---` 作章节分隔线，转换后多个章节标题和内容被合并进一个表格。  
**原因**：pandoc 的 `multiline_tables` 扩展把**两个 `---` 之间的所有内容**解析为表格。  
**解决**：命令必须带 `-multiline_tables`，已包含在标准命令中。

### 陷阱 4：YAML 解析报错导致文件无法生成
**现象**：`YAML parse exception at line X`，输出文件不存在。  
**原因**：文件中的 `>` 被 pandoc 识别为 YAML block scalar 标记。  
**解决**：命令必须带 `-yaml_metadata_block`，已包含在标准命令中。

### 陷阱 5：普通段落被解析为表格
**现象**：段落后紧跟 `---` 时，段落内容变成表格表头。  
**原因**：`simple_tables` 扩展把"段落 + `---`"解析为表格。  
**解决**：命令必须带 `-simple_tables`，已包含在标准命令中。

### 陷阱 6：reference doc 样式不生效
**现象**：代码块无背景、引用块无边框、行内代码无颜色。  
**原因**：`word.docx` 缺少 pandoc 需要的样式名（Block Text、Source Code 等）。  
**解决**：执行 Step 1 的 `python3 scripts/inject_styles.py`。

---

## 不适用场景

| 场景 | 原因 | 替代方案 |
|------|------|----------|
| 需要精细控制 docx 布局 | 多栏、复杂页眉页脚、精确排版 | python-docx 直接编辑 |
| 转换后需要大量编辑 docx | 本 skill 仅负责转换+格式美化 | 先转换，再用 OfficeCLI skill |
