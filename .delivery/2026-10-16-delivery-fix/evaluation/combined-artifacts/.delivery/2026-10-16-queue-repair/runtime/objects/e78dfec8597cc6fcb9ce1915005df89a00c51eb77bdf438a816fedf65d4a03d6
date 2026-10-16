#!/usr/bin/env python3
"""Bounded packaging checks; not a semantic or behavioral skill evaluation."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

NAMES = tuple('delivery-' + suffix for suffix in
              ('design', 'plan', 'implement', 'review', 'verify', 'orchestrate'))
OPTIONAL = ('delivery-fix',)


def check(root, require_fix=False):
    errors = []
    counts = {'skills': 0, 'markdown': 0, 'json': 0, 'local_links': 0}
    selected = NAMES + tuple(name for name in OPTIONAL if require_fix or (root / name).exists())
    for name in selected:
        folder = root / name
        entry = folder / 'SKILL.md'
        if not entry.is_file():
            errors.append(f'{name}: missing SKILL.md')
            continue
        counts['skills'] += 1
        body = entry.read_text(encoding='utf-8')
        front = re.match(r'\A---\n(.*?)\n---(?:\n|$)', body, re.S)
        metadata = dict(re.findall(r'^(name|description):\s*(.+)$',
                                  front.group(1) if front else '', re.M))
        if metadata.get('name') != name:
            errors.append(f'{name}: frontmatter name mismatch')
        if not 1 <= len(metadata.get('description', '')) <= 249:
            errors.append(f'{name}: description must contain 1..249 characters')
        for heading in ('Working Protocol', 'Exit Criteria', 'Exit Protocol'):
            if f'## {heading}' not in body:
                errors.append(f'{name}: missing {heading}')
        policy = folder / 'agents/openai.yaml'
        if not policy.is_file() or not re.search(
                r'(?m)^policy:\s*\n[ \t]+allow_implicit_invocation:\s*false\s*$',
                policy.read_text(encoding='utf-8')):
            errors.append(f'{name}: explicit invocation policy missing')
        for path in sorted(folder.rglob('*')):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if path.suffix == '.json':
                counts['json'] += 1
                try:
                    json.loads(path.read_text(encoding='utf-8'))
                except (ValueError, UnicodeError) as exc:
                    errors.append(f'{relative}: invalid JSON: {exc}')
            if path.suffix != '.md':
                continue
            counts['markdown'] += 1
            # Check ordinary inline Markdown links outside fenced examples.
            content = re.sub(r'(?ms)^```[^\n]*\n.*?^```\s*$', '',
                             path.read_text(encoding='utf-8'))
            for target in re.findall(r'(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)', content):
                target = target.strip().split(' "', 1)[0].strip('<>')
                if urlsplit(target).scheme or target.startswith('#'):
                    continue
                target = unquote(target.split('#', 1)[0])
                if not target:
                    continue
                counts['local_links'] += 1
                resolved = (path.parent / target).resolve()
                if not resolved.is_relative_to(folder.resolve()):
                    errors.append(f'{relative}: link leaves self-contained skill: {target}')
                elif not resolved.exists():
                    errors.append(f'{relative}: broken local link: {target}')
    return {'ok': not errors, 'counts': counts, 'errors': errors,
            'scope': 'Packaging, basic metadata, explicit-entry policy, JSON syntax and ordinary local Markdown links only; no semantic quality or behavioral guarantee.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skills-root', required=True, type=Path)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--require-fix', action='store_true', help='Require the optional fix package in this candidate suite')
    args = parser.parse_args()
    result = check(args.skills_root.resolve(), args.require_fix)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else
          '\n'.join([f"suite packaging: {'PASS' if result['ok'] else 'FAIL'}",
                     str(result['counts']), result['scope']] + result['errors']))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
