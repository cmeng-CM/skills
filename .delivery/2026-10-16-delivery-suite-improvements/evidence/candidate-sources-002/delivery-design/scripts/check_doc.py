#!/usr/bin/env python3
"""Read-only checks for a documented Markdown subset; no semantic approval."""

import argparse
import html
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote


STANDARD = Path(__file__).resolve().parent.parent / "references/document-standard.md"
CHAPTER = re.compile(r"^\*\*(\d+)\.\s+(.+?)——(必选|可选)\*\*$")
HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
DECISION = re.compile(r"(?<![\w/\-])D-\d{2,}(?![\w\-])", re.ASCII)
LINK = re.compile(r"!?\[([^\]\n]*)\]\(\s*(<[^>\n]*>|[^\s()]+)(?:\s+[\"'][^\n]*?[\"'])?\s*\)")
REF_DEF = re.compile(r"^ {0,3}\[([^\]]+)\]:\s*(<[^>]*>|\S+)(?:\s+.*)?$")
LINK_TOKEN = re.compile(
    r"!?\[(?P<label>[^\[\]\n]*)\]"
    r"(?:\(\s*(?P<target><[^>\n]*>|[^\s()]+)(?:\s+[\"'][^\n]*?[\"'])?\s*\)"
    r"|\[(?P<reference>[^\[\]\n]*)\])?"
)
CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.*?)(?<!`)\1(?!`)")
ANCHOR = re.compile(r"<(?:a|h[1-6])\b[^>]*?\b(?:id|name)=[\"']([^\"']+)[\"'][^>]*>", re.I)
PLACEHOLDER = re.compile(r"\b(?:TODO|TBD)\b|\{\{[^{}\n]+\}\}|待填写|待补充")


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    line: int
    message: str


def plain(text):
    """Only presentation markup, not Markdown structure."""
    text = re.sub(r"<[^>]*>", "", text)
    return html.unescape(text.replace("*", "").replace("_", "").replace("`", "")).strip()


def chapter_title(text):
    text = plain(text)
    return re.sub(r"^(?:\d+(?:[.．、)）]|\s)|[一二三四五六七八九十]+[、.．])\s*", "", text).strip()


def load_chapters(path=STANDARD):
    chapters = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        match = CHAPTER.fullmatch(line.strip())
        if match:
            chapters.append((match[2], match[3] == "必选"))
    titles = [name for name, _ in chapters]
    if not chapters or not any(required for _, required in chapters) or len(titles) != len(set(titles)):
        raise ValueError("规范没有可唯一解析的章节声明；未执行章节校验")
    return chapters


def hide_comments(line, in_comment):
    """Mask prose comments without consuming literal comments inside inline code."""
    chars = list(line)
    position = 0
    code = {match.start(): match.end() for match in CODE_SPAN.finditer(line)}
    while position < len(line):
        if not in_comment and position in code:
            position = code[position]
            continue
        if in_comment or line.startswith("<!--", position):
            end = line.find("-->", position + (0 if in_comment else 4))
            stop = len(line) if end < 0 else end + 3
            chars[position:stop] = " " * (stop - position)
            in_comment = end < 0
            position = stop
        else:
            position += 1
    return "".join(chars), in_comment


def views(text):
    """Keep line positions, plus separate structure and substantive-content views."""
    lines = text.splitlines()
    structure, content, skipped = [], [], []
    fence = None
    in_comment = False
    frontmatter = bool(lines and lines[0].strip() == "---")
    for index, line in enumerate(lines):
        if frontmatter:
            if index and line.strip() in {"---", "..."}:
                frontmatter = False
            structure.append("")
            content.append("")
            continue
        if fence:
            close = re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(fence[1]) + r",}\s*", line)
            structure.append("")
            content.append("" if close else line)
            if close:
                fence = None
            continue
        if not in_comment and (line.startswith(("    ", "\t")) or re.match(r"^ {0,3}>", line)):
            structure.append("")
            content.append(line)
            if re.match(r"^ {0,3}>", line):
                skipped.append((index, line))
            continue
        line, in_comment = hide_comments(line, in_comment)
        opening = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if opening:
            fence = (opening[1][0], len(opening[1]))
            structure.append("")
            content.append("")
        else:
            structure.append(line)
            content.append(line)
    return structure, content, skipped


def escaped(text, index):
    start = index
    while start and text[start - 1] == "\\":
        start -= 1
    return (index - start) % 2 == 1


def cells(line):
    line = line.strip()
    pipes = [i for i, char in enumerate(line) if char == "|" and not escaped(line, i)]
    if not pipes:
        return []
    parts = [line[a + 1:b].strip() for a, b in zip([-1] + pipes, pipes + [len(line)])]
    if pipes[0] == 0:
        parts.pop(0)
    if pipes[-1] == len(line) - 1:
        parts.pop()
    return parts


def strip_code_spans(line):
    return CODE_SPAN.sub(lambda m: " " * len(m[0]), line)


def slug(title):
    title = LINK.sub(lambda m: m[1], title)
    literals = []

    def protect(match):
        literals.append(match[2])
        return f"\x00{len(literals) - 1}\x00"

    title = CODE_SPAN.sub(protect, title)
    title = re.sub(r"(?<![\w\\])(_{1,3})(?=\S)(.+?)(?<=\S)\1(?!\w)", r"\2", title)
    title = re.sub(r"<[^>]*>", "", html.unescape(title)).replace("*", "")
    title = re.sub(r"\x00(\d+)\x00", lambda m: literals[int(m[1])], title)
    title = "".join(c for c in title.lower() if c.isalnum() or c in "_-" or c.isspace())
    return re.sub(r"\s", "-", title.strip())


def reference_key(label):
    return " ".join(label.casefold().split())


def links(line, reference_targets):
    """Resolve the supported link forms, preserving spans for local ID checks."""
    prose = strip_code_spans(line)
    tokens, unknown = [], []
    residue = list(prose)
    for match in LINK_TOKEN.finditer(prose):
        start, end = match.span()
        bracket = match.start("label") - 1
        if escaped(prose, bracket):
            residue[start:end] = " " * (end - start)
            continue
        label = line[match.start("label"):match.end("label")]
        target = match["target"]
        if target is None:
            ref = match["reference"]
            target = reference_targets.get(reference_key(ref or label))
            if target is None and ref is None:
                if prose[end:end + 1] not in {"(", "["}:
                    continue  # An undefined shortcut is ordinary bracketed text.
            if target is None:
                unknown.append(label)
        else:
            target = target.strip("<>")
        tokens.append((start, end, label, target))
        residue[start:end] = " " * (end - start)
    return tokens, unknown, "".join(residue)


def check_document(text, profile="feature-change", standard=STANDARD):
    if profile not in {"feature-change", "generic"}:
        raise ValueError("未知 profile")
    findings = []

    def add(level, code, line, message):
        findings.append(Finding(level, code, line, message))

    structure, content, skipped = views(text)
    headings = []
    anchors = {""}
    uncertain_anchors = set()
    uncertain_headings = set()
    heading_markers = set()
    definitions = defaultdict(list)
    uncertain_decisions = set()
    reference_targets = {}
    previous_quoted = ""
    previous_quote_line = -2
    for i, line in skipped:
        if i != previous_quote_line + 1:
            add("WARNING", "unchecked-blockquote", i + 1, "引用块及其嵌套示例未解析，不参与标题、决策和锚点检查")
        uncertain_decisions.update(DECISION.findall(line))
        quoted = re.sub(r"^(?: {0,3}>[ \t]?)+", "", line)
        heading = HEADING.fullmatch(quoted)
        if heading:
            uncertain_anchors.add(slug(re.sub(r"\s*\{#[^}\s]+\}\s*$", "", heading[2])))
        if i == previous_quote_line + 1 and re.fullmatch(r" {0,3}(?:=+|-+)\s*", quoted):
            uncertain_anchors.add(slug(previous_quoted))
        uncertain_anchors.update(ANCHOR.findall(quoted))
        uncertain_anchors.update(re.findall(r"\{#([^}\s]+)\}", quoted))
        previous_quoted, previous_quote_line = quoted, i
    for i, line in enumerate(structure):
        match = HEADING.fullmatch(line)
        if match:
            level, title = len(match[1]), match[2]
            clean_title = re.sub(r"\s*\{#[^}\s]+\}\s*$", "", title)
            headings.append((i, level, clean_title))
            if clean_title != title:
                uncertain_headings.add(i)
                uncertain_anchors.add(slug(clean_title))
            base = slug(title)
            anchor, suffix = base, 0
            while anchor in anchors:
                suffix += 1
                anchor = f"{base}-{suffix}"
            if i not in uncertain_headings:
                anchors.add(anchor)
            first = DECISION.match(plain(title))
            if first:
                definitions[first[0]].append(i + 1)
        for anchor in ANCHOR.findall(strip_code_spans(line)):
            anchors.add(anchor)
        uncertain_anchors.update(re.findall(r"\{#([^}\s]+)\}", strip_code_spans(line)))
        uncertain_anchors.update(re.findall(r"<[^>]+\bid=[\"']([^\"']+)[\"'][^>]*>", strip_code_spans(line)))
        if i and re.fullmatch(r" {0,3}(?:=+|-+)\s*", line) and structure[i - 1].strip() and not HEADING.fullmatch(structure[i - 1]) and not cells(structure[i - 1]):
            uncertain_anchors.add(slug(structure[i - 1]))
            headings.append((i - 1, 1 if line.lstrip().startswith("=") else 2, structure[i - 1].strip()))
            uncertain_headings.add(i - 1)
            heading_markers.add(i)
            uncertain_decisions.update(DECISION.findall(structure[i - 1]))
            add("WARNING", "unchecked-heading", i, "Setext 标题不在 ATX 检查范围内，需核对标题及锚点")
        reference = REF_DEF.fullmatch(line)
        if reference:
            reference_targets.setdefault(reference_key(reference[1]), reference[2].strip("<>"))

    headings.sort()

    if profile == "feature-change":
        required = [name for name, needed in load_chapters(standard) if needed]
        found = defaultdict(list)
        uncertain = set()
        for i, level, title in headings:
            if level == 2:
                if i in uncertain_headings:
                    uncertain.add(chapter_title(title))
                else:
                    found[chapter_title(title)].append(i + 1)
        for name in required:
            if name in uncertain:
                add("WARNING", "unchecked-chapter", 1, f"章节使用未完整解析的标题语法，存在性及重复性需人工核对：{name}")
            elif not found[name]:
                add("ERROR", "missing-chapter", 1, f"缺少必选二级章节：{name}")
            for line in found[name][1:]:
                add("ERROR", "duplicate-chapter", line, f"重复必选章节：{name}")

    if not any(line.strip() for line in content):
        add("ERROR", "empty-document", 1, "文档没有可检查的正文")
    heading_lines = {i for i, _, _ in headings} | heading_markers
    for number, (i, level, title) in enumerate(headings):
        end = next((j for j, next_level, _ in headings[number + 1:] if next_level <= level), len(content))
        body = [content[j].strip() for j in range(i + 1, end) if j not in heading_lines]
        if level >= 2 and i not in uncertain_headings and not any(body):
            add("ERROR", "empty-section", i + 1, f"章节为空：{title}")

    # Definitions are only in explicitly identified columns of real pipe tables.
    for i in range(len(structure) - 1):
        header, separator = cells(structure[i]), cells(structure[i + 1])
        if not header or len(header) != len(separator) or not all(re.fullmatch(r":?-{3,}:?", s) for s in separator):
            continue
        indexes = [n for n, value in enumerate(header) if plain(value).casefold() in {"编号", "决策编号", "编号与决定", "id"}]
        for j in range(i + 2, len(structure)):
            row = cells(structure[j])
            if not row:
                break
            if len(row) != len(header):
                add("WARNING", "unparsed-table-row", j + 1, "表格列数不同，未推断该行的决策定义")
                uncertain_decisions.update(DECISION.findall(structure[j]))
                continue
            for col in indexes:
                match = DECISION.match(plain(row[col]))
                if match:
                    definitions[match[0]].append(j + 1)
    for decision, locations in definitions.items():
        for line in locations[1:]:
            add("ERROR", "duplicate-decision", line, f"重复定义 {decision}；首次在 L{locations[0]}")

    for i, line in enumerate(structure):
        if not line or REF_DEF.fullmatch(line):
            continue
        # Code spans are allowed for decision identifiers, but not active links.
        prose = strip_code_spans(line)
        tokens, unknown, residue = links(line, reference_targets)
        if unknown or re.search(r"\]\(|\]\[", residue):
            add("WARNING", "unchecked-link", i + 1, "存在未解析的链接或缺失的引用定义，需人工核对")
        for _, _, _, target in tokens:
            if target is None:
                continue
            if target.startswith("#"):
                anchor = unquote(target[1:])
                if anchor not in anchors:
                    if anchor in uncertain_anchors:
                        add("WARNING", "unchecked-anchor", i + 1, f"锚点使用扩展或未解析语法，未验证：{target}")
                    else:
                        add("ERROR", "missing-anchor", i + 1, f"文内锚点不存在：{target}")
        if re.search(r"<[^>]+>", re.sub(ANCHOR, "", prose)) or re.search(r"\{#[^}]+\}", prose):
            add("WARNING", "unchecked-markup", i + 1, "HTML 或扩展标记未完整解析，需核对渲染与锚点")
        # Cross-document linked IDs are not local references, nor are link targets.
        local = line
        for start, end, label, target in reversed(tokens):
            replacement = label if target is not None and (not target or target.startswith("#")) else ""
            local = local[:start] + replacement + local[end:]
        local = re.sub(r"<[^>]*>", "", local)
        for label in unknown:
            for decision in set(DECISION.findall(label)):
                add("WARNING", "unchecked-decision", i + 1, f"决策 {decision} 的链接目标未解析，需核对引用范围")
        for decision in set(DECISION.findall(local)):
            if decision not in definitions:
                if decision in uncertain_decisions:
                    add("WARNING", "unchecked-decision", i + 1, f"决策 {decision} 出现在未解析内容中，需核对定义")
                else:
                    add("ERROR", "undefined-decision", i + 1, f"本地决策 {decision} 没有定义；外部决定请用文档链接")
        if PLACEHOLDER.search(line):
            add("WARNING", "placeholder", i + 1, "发现疑似模板占位，核实是否仍需补写；不改变设计状态")
    return sorted(findings, key=lambda f: (f.line, f.code, f.message))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path, help="待检查的 UTF-8 Markdown 文档")
    parser.add_argument("--profile", choices=("feature-change", "generic"), default="feature-change")
    args = parser.parse_args(argv)
    try:
        findings = check_document(args.document.read_text(encoding="utf-8"), args.profile)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"无法检查：{error}", file=sys.stderr)
        return 2
    for item in findings:
        print(f"{item.level} L{item.line} [{item.code}] {item.message}")
    errors = sum(item.level == "ERROR" for item in findings)
    warnings = sum(item.level == "WARNING" for item in findings)
    print(f"机械检查：{errors} 个错误，{warnings} 个警告；profile={args.profile}")
    print("范围：支持的标题、空节、D-NN 定义与引用、文内锚点及占位提示；外部链接和复杂 Markdown 未验证。")
    print("结果不代表设计可行、共识完整、用户批准或验收通过。输入文件未修改。")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
