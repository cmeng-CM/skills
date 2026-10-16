#!/usr/bin/env python3
'''Read-only, bounded checks for ordinary Markdown implementation plans.'''
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sys

ID_PATTERN = r'(?:AC|T|V|P|R|G|D|C|S|E|B)-\d+'
ID_RE = re.compile(r'(?<![A-Za-z0-9_-])' + ID_PATTERN + r'(?![A-Za-z0-9_-])')
ID_FULL = re.compile(ID_PATTERN)
DEFINITION_HEADERS = {'ID', '任务 ID', '任务ID', '验收 ID', '验收ID',
                      '验证组 ID', '验证组ID', '条件 ID', '条件ID', '决策 ID', '决策ID',
                      '来源 ID', '来源ID', '记录 ID', '记录ID'}
RELATION_HEADERS = {'前置对象', '后续对象', '依赖类型', '满足条件'}
RELATION_TYPES = {'产物可接入', '验证前置', '验证通过', '设计确认', '细化就绪', '资源交接'}
REQUIRED_FIELDS = {
    '目标与产物': {'目标与产物', '目标与交付物'},
    '设计依据': {'设计依据', '设计引用'},
    '范围与约束': {'范围与约束', '修改边界'},
    '前置与启动条件': {'前置与启动条件', '启动条件'},
    '必读材料': {'必读材料'},
    '代码位置': {'代码位置', '涉及文件'},
    '验收与验证归属': {'验收与验证归属', '验收归属'},
    '反馈触发条件': {'反馈触发条件', '反馈触发'},
}


@dataclass
class Finding:
    level: str
    code: str
    line: int
    message: str


@dataclass
class Table:
    headers: list[str]
    rows: list[tuple[int, list[str]]]
    line: int
    section: str


def clean(value: str) -> str:
    return value.strip().strip('`* ').strip()


def cells(line: str) -> list[str] | None:
    '''Respect escaped pipes and pipes inside matching inline backticks.'''
    text = line.strip()
    if not text.startswith('|'):
        return None
    parts, buf, i, tick_width = [], [], 0, 0
    while i < len(text):
        ch = text[i]
        if ch == '\\' and i + 1 < len(text):
            buf.extend(text[i:i + 2]); i += 2; continue
        if ch == '`':
            j = i
            while j < len(text) and text[j] == '`':
                j += 1
            width = j - i
            if not tick_width:
                tick_width = width
            elif tick_width == width:
                tick_width = 0
            buf.extend(text[i:j]); i = j; continue
        if ch == '|' and not tick_width:
            parts.append(''.join(buf).strip()); buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append(''.join(buf).strip())
    if parts and parts[0] == '':
        parts.pop(0)
    if parts and parts[-1] == '':
        parts.pop()
    return parts


def visible_lines(text: str) -> list[str]:
    # Retain line numbers while excluding comments and fenced examples/diagrams.
    text = re.sub(r'<!--[\s\S]*?-->', lambda m: '\n' * m[0].count('\n'), text)
    result, fence = [], None
    for line in text.splitlines():
        match = re.match(r'^\s{0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            result.append('')
        elif match:
            fence = match[1]; result.append('')
        else:
            result.append(line)
    return result


def parse(text: str):
    lines = visible_lines(text)
    headings, tables, section = [], [], ''
    i = 0
    while i < len(lines):
        heading = re.match(r'^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$', lines[i])
        if heading:
            section = clean(heading[2])
            headings.append((i + 1, len(heading[1]), section))
        header = cells(lines[i])
        separator = cells(lines[i + 1]) if i + 1 < len(lines) else None
        if header and separator and len(header) == len(separator) and all(re.fullmatch(r':?-{3,}:?', s) for s in separator):
            table = Table([clean(h) for h in header], [], i + 1, section)
            i += 2
            while i < len(lines):
                row = cells(lines[i])
                if row is None:
                    break
                table.rows.append((i + 1, row)); i += 1
            tables.append(table)
            continue
        i += 1
    return lines, headings, tables


def find_cycle(edges: list[tuple[str, str]]) -> list[str]:
    graph: dict[str, list[str]] = {}
    for before, after in edges:
        graph.setdefault(before, []).append(after)
        graph.setdefault(after, [])
    state, stack = {}, []
    def visit(node):
        state[node] = 1; stack.append(node)
        for target in graph[node]:
            if state.get(target) == 1:
                return stack[stack.index(target):] + [target]
            if not state.get(target):
                found = visit(target)
                if found:
                    return found
        stack.pop(); state[node] = 2
        return []
    for node in graph:
        if not state.get(node):
            found = visit(node)
            if found:
                return found
    return []


def check_text(text: str) -> dict:
    lines, headings, tables = parse(text)
    findings: list[Finding] = []
    declared, heading_ids, external, edges = set(), {}, set(), []
    edge_lines = {}
    detail_checked = 0
    dependency_tables = 0
    def add(level, code, line, message):
        findings.append(Finding(level, code, line, message))
    for line, depth, title in headings:
        match = ID_RE.match(title)
        if match:
            key = match[0]
            declared.add(key)
            if key in heading_ids:
                add('error', 'duplicate-heading-id', line, f'{key} 重复标题，首次位于第 {heading_ids[key]} 行')
            else:
                heading_ids[key] = line
    for table in tables:
        for line, row in table.rows:
            if len(row) != len(table.headers):
                add('error', 'table-width', line, f'表格有 {len(row)} 列，表头有 {len(table.headers)} 列')
        if table.headers and table.headers[0] in DEFINITION_HEADERS:
            seen = set()
            for line, row in table.rows:
                key = clean(row[0]) if row else ''
                if not ID_FULL.fullmatch(key):
                    continue
                if key in seen:
                    add('error', 'duplicate-table-id', line, f'{key} 在同一张定义表中重复')
                seen.add(key)
                if table.section == '外部引用':
                    if '来源' not in table.headers or len(row) <= table.headers.index('来源') or not clean(row[table.headers.index('来源')]):
                        add('error', 'external-source-empty', line, f'{key} 外部引用缺少来源')
                    else:
                        external.add(key)
                else:
                    declared.add(key)
        if RELATION_HEADERS.issubset(table.headers):
            dependency_tables += 1
            for line, row in table.rows:
                if len(row) != len(table.headers):
                    continue
                data = dict(zip(table.headers, map(clean, row)))
                before, after = data['前置对象'], data['后续对象']
                if not (ID_FULL.fullmatch(before) and ID_FULL.fullmatch(after)):
                    add('warning', 'dependency-unparsed', line, '依赖对象需为单个 ID；本行未纳入循环检查')
                    continue
                if data['依赖类型'] not in RELATION_TYPES:
                    add('warning', 'dependency-type-unparsed', line, '未识别的依赖类型；本行未纳入循环检查')
                    continue
                if not data['满足条件']:
                    add('error', 'dependency-condition-empty', line, '依赖缺少满足条件')
                edges.append((before, after))
                edge_lines[(before, after)] = line
    unresolved = {}
    for number, line in enumerate(lines, 1):
        # Link labels count as text; link destinations are not ID references.
        line = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', line)
        for match in ID_RE.finditer(line):
            key = match[0]
            if key not in declared and key not in external and key not in unresolved:
                unresolved[key] = number
    for key, line in unresolved.items():
        level = 'error' if key.split('-')[0] in {'T', 'AC', 'V'} else 'warning'
        add(level, 'unresolved-reference', line, f'{key} 没有可识别的本地定义或外部引用声明')
    for index, (line, depth, title) in enumerate(headings):
        match = ID_RE.match(title)
        if not match or not match[0].startswith('T-'):
            continue
        end = next((n for n, d, _ in headings[index + 1:] if d <= depth), len(lines) + 1)
        fields = {}
        for table in tables:
            if line < table.line < end and len(table.headers) == 2:
                table_fields = set()
                for number, row in table.rows:
                    if len(row) == 2:
                        label = clean(row[0])
                        known_fields = set().union(*REQUIRED_FIELDS.values()) | {'细化状态', '实施步骤', '待细化说明'}
                        if label in table_fields and label in known_fields:
                            add('error', 'duplicate-task-field', number, f'{match[0]} 同一任务卡字段重复：{label}')
                        table_fields.add(label)
                        fields[label] = (number, clean(row[1]))
        state = fields.get('细化状态', (line, ''))[1]
        if state == '已细化':
            detail_checked += 1
            for label, aliases in REQUIRED_FIELDS.items():
                present = [fields[k] for k in aliases if k in fields]
                if not present or not any(value for _, value in present):
                    add('error', 'task-field-empty', line, f'{match[0]} 已声明已细化，但缺少非空字段：{label}')
            body = '\n'.join(lines[line:end - 1])
            steps = fields.get('实施步骤', (line, ''))[1]
            if not steps and not re.search(r'^\s*\d+[.)]\s+\S', body, re.M):
                add('error', 'task-steps-empty', line, f'{match[0]} 缺少实施步骤')
        elif state == '待细化':
            if not fields.get('待细化说明', (line, ''))[1]:
                add('error', 'refinement-condition-empty', line, f'{match[0]} 待细化但缺少待细化说明')
        else:
            add('warning', 'task-fields-unchecked', line, f'{match[0]} 未显式声明细化状态，未按完整任务卡核查字段')
    cycle = find_cycle(edges)
    if cycle:
        add('error', 'dependency-cycle', edge_lines[(cycle[0], cycle[1])], '显式依赖表存在循环：' + ' → '.join(cycle))
    if not declared and not external:
        add('warning', 'no-recognized-ids', 1, '未识别到 ID 定义，ID 覆盖检查不完整')
    scope = [
        f'识别本地 ID {len(declared)} 个、外部声明 {len(external)} 个；跨表汇总允许重复引用。',
        f'核对已声明已细化的任务卡 {detail_checked} 张；只检查已支持字段非空，不判断实际可执行性。',
        f'识别依赖表 {dependency_tables} 张、关系 {len(edges)} 条；仅对这些关系检查循环。' if dependency_tables else '未检查联合依赖循环：没有可识别的显式依赖表。',
        '未检查语义覆盖、关键决策确认的真实性、图文一致性、外部材料与实际证据；未展开 ID 区间或自然语言依赖。',
    ]
    return {'ok': not any(f.level == 'error' for f in findings),
            'findings': [asdict(f) for f in findings], 'scope': scope,
            'counts': {'local_ids': len(declared), 'external_ids': len(external),
                       'detailed_tasks': detail_checked, 'dependency_edges': len(edges)}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--json', action='store_true', dest='json_output')
    args = parser.parse_args(argv)
    try:
        report = check_text(args.path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError) as error:
        report = {'ok': False, 'input_error': str(error), 'findings': [], 'scope': []}
        if args.json_output:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f'无法读取计划：{error}', file=sys.stderr)
        return 2
    report['path'] = str(args.path)
    if args.json_output:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print('机械检查：识别范围内未发现错误' if report['ok'] else '机械检查：发现错误')
        for item in report['findings']:
            print(f"{item['level'].upper()} L{item['line']} [{item['code']}] {item['message']}")
        for scope in report['scope']:
            print('范围：' + scope)
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
