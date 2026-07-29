#!/usr/bin/env python3
"""
Inject missing pandoc-mapped styles into word.docx.

Pandoc maps these markdown elements to named Word styles:
  > quote       → Block Text
  tight lists   → Compact
  ```code```    → Source Code
  `inline`      → Verbatim Char
  [link](url)   → Hyperlink

If these styles don't exist in the reference doc, pandoc falls back to
Normal / Default Paragraph Font — losing all visual distinction.

This script adds them with formatting that harmonizes with the existing
template. It is idempotent (safe to re-run).

Usage:
    python3 scripts/inject_styles.py [word.docx]
"""

import os
import sys
import shutil

from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.enum.style import WD_STYLE_TYPE


# ── Resolve template path ──────────────────────────────────────────
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(SKILL_DIR, "word.docx")

if len(sys.argv) > 1:
    TEMPLATE = os.path.abspath(sys.argv[1])

if not os.path.exists(TEMPLATE):
    print(f"ERROR: template not found: {TEMPLATE}")
    sys.exit(1)


# ── Helpers ─────────────────────────────────────────────────────────
def set_font(style, name, size, bold=None, italic=None, color=None,
             east_asian=None):
    """Set basic font properties on a style."""
    style.font.name = name
    style.font.size = Pt(size)
    if bold is not None:
        style.font.bold = bold
    if italic is not None:
        style.font.italic = italic
    if color:
        style.font.color.rgb = RGBColor(*color)
    if east_asian:
        _set_ea_font(style.element, name, east_asian)


def _set_ea_font(el, ascii_f, ea_f):
    """Set East-Asian font on a style element."""
    rPr = el.find(qn('w:rPr'))
    if rPr is None:
        rPr = OxmlElement('w:rPr')
        el.append(rPr)
    rf = rPr.find(qn('w:rFonts'))
    if rf is None:
        rf = OxmlElement('w:rFonts')
        rPr.insert(0, rf)
    rf.set(qn('w:ascii'), ascii_f)
    rf.set(qn('w:hAnsi'), ascii_f)
    rf.set(qn('w:eastAsia'), ea_f)
    rf.set(qn('w:cs'), ea_f)


def _get_pPr(el):
    """Get or create paragraph properties element."""
    ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    p = el.find(f'{{{ns}}}pPr')
    if p is None:
        p = OxmlElement('w:pPr')
        el.insert(0, p)
    return p


def _get_rPr(el):
    """Get or create run properties element."""
    ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    r = el.find(f'{{{ns}}}rPr')
    if r is None:
        r = OxmlElement('w:rPr')
        el.insert(0, r)
    return r


def add_shading(parent, fill, elem_type='p'):
    """Add w:shd (shading) to pPr or rPr."""
    s = OxmlElement('w:shd')
    s.set(qn('w:val'), 'clear')
    s.set(qn('w:color'), 'auto')
    s.set(qn('w:fill'), fill)
    parent.append(s)


def add_border(el, sides, color, sz=4, sp=4):
    """Add paragraph border. sides: list of 'top'/'bottom'/'left'/'right'."""
    pp = _get_pPr(el)
    pb = pp.find(qn('w:pBdr'))
    if pb is None:
        pb = OxmlElement('w:pBdr')
        pp.append(pb)
    for side in sides:
        b = OxmlElement(f'w:{side}')
        b.set(qn('w:val'), 'single')
        b.set(qn('w:sz'), str(sz))
        b.set(qn('w:space'), str(sp))
        b.set(qn('w:color'), color)
        pb.append(b)


def add_spacing(style, before=None, after=None, line=None, line_rule=None):
    """Set paragraph spacing — all values in Pt.

    line_rule: None (auto) | 'exact' | 'atLeast' | 'multiple'
    Default uses AT_LEAST to avoid text clipping.
    """
    if before is not None:
        style.paragraph_format.space_before = Pt(before)
    if after is not None:
        style.paragraph_format.space_after = Pt(after)
    if line is not None:
        from docx.enum.text import WD_LINE_SPACING
        rule_map = {
            'exact': WD_LINE_SPACING.EXACTLY,
            'atLeast': WD_LINE_SPACING.AT_LEAST,
            'multiple': WD_LINE_SPACING.MULTIPLE,
        }
        if line_rule and line_rule in rule_map:
            style.paragraph_format.line_spacing = Pt(line)
            style.paragraph_format.line_spacing_rule = rule_map[line_rule]
        else:
            # Default: AT_LEAST — ensures long text doesn't get clipped
            style.paragraph_format.line_spacing = Pt(line)
            style.paragraph_format.line_spacing_rule = WD_LINE_SPACING.AT_LEAST


# ── Color palette (harmonizes with word.docx theme) ─────────────────
C = {
    'body':       (38, 38, 38),     # #262626
    'quote_text': (89, 89, 89),     # #595959
    'quote_border': '4874CB',       # accent1 from theme (hex for XML)
    'quote_bg':   'EDF2FB',         # light accent1
    'code_bg':    'F6F8FA',
    'code_border': 'D0D7DE',
    'code_text':  (31, 35, 40),     # #1F2328
    'inline_text': (199, 37, 78),   # #C7254E
    'inline_bg':  'F9F2F4',
    'link':       (5, 99, 193),     # #0563C1
}


# ── Inject function ─────────────────────────────────────────────────
def inject(doc):
    """Add missing pandoc styles. Returns count of styles added."""
    added = 0

    # --- Block Text (blockquote) ---
    name = 'Block Text'
    if name not in [s.name for s in doc.styles]:
        s = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        s.hidden = False
        s.font.italic = True
        s.font.color.rgb = RGBColor(*C['quote_text'])
        s.font.size = Pt(11)
        s.paragraph_format.left_indent = Cm(0.8)
        s.paragraph_format.right_indent = Cm(0.4)
        add_spacing(s, before=6, after=6, line=18)
        _set_ea_font(s.element, 'Calibri', '等线')
        add_border(s.element, ['left'], C['quote_border'], sz=16, sp=6)
        add_shading(_get_pPr(s.element), C['quote_bg'])
        print(f'  + Block Text (blockquote)')
        added += 1
    else:
        print(f'  ✓ Block Text (already exists)')

    # --- Compact (tight lists) ---
    name = 'Compact'
    if name not in [s.name for s in doc.styles]:
        s = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        s.hidden = False
        s.font.size = Pt(11)
        s.font.color.rgb = RGBColor(*C['body'])
        add_spacing(s, before=0, after=2, line=16)
        _set_ea_font(s.element, 'Calibri', '等线')
        print(f'  + Compact (tight lists)')
        added += 1
    else:
        print(f'  ✓ Compact (already exists)')

    # --- Source Code (fenced code blocks) ---
    name = 'Source Code'
    if name not in [s.name for s in doc.styles]:
        s = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        s.hidden = False
        set_font(s, 'Courier New', 9.5, bold=False, italic=False,
                 color=C['code_text'], east_asian='Courier New')
        add_spacing(s, before=6, after=6, line=15, line_rule='exact')
        add_border(s.element, ['top', 'bottom', 'left', 'right'],
                   C['code_border'], sz=4, sp=5)
        add_shading(_get_pPr(s.element), C['code_bg'])
        print(f'  + Source Code (fenced code blocks)')
        added += 1
    else:
        print(f'  ✓ Source Code (already exists)')

    # --- Verbatim Char (inline code) ---
    name = 'Verbatim Char'
    if name not in [s.name for s in doc.styles]:
        s = doc.styles.add_style(name, WD_STYLE_TYPE.CHARACTER)
        s.hidden = False
        set_font(s, 'Courier New', 10, color=C['inline_text'],
                 east_asian='Courier New')
        add_shading(_get_rPr(s.element), C['inline_bg'])
        print(f'  + Verbatim Char (inline code)')
        added += 1
    else:
        print(f'  ✓ Verbatim Char (already exists)')

    # --- Hyperlink (links) ---
    name = 'Hyperlink'
    if name not in [s.name for s in doc.styles]:
        s = doc.styles.add_style(name, WD_STYLE_TYPE.CHARACTER)
        s.hidden = False
        s.font.color.rgb = RGBColor(*C['link'])
        s.font.underline = True
        print(f'  + Hyperlink (links)')
        added += 1
    else:
        print(f'  ✓ Hyperlink (already exists)')

    # --- TOC Heading (table of contents title, for pandoc --toc) ---
    name = 'TOC Heading'
    if name not in [s.name for s in doc.styles]:
        s = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        s.hidden = False
        s.font.name = 'Calibri'
        s.font.size = Pt(16)
        s.font.bold = True
        s.font.color.rgb = RGBColor(*C['body'])
        s.paragraph_format.space_before = Pt(12)
        s.paragraph_format.space_after = Pt(6)
        _set_ea_font(s.element, 'Calibri', '黑体')
        print(f'  + TOC Heading (table of contents)')
        added += 1
    else:
        print(f'  ✓ TOC Heading (already exists)')

    return added


# ── Main ────────────────────────────────────────────────────────────
def main():
    print(f'Template: {TEMPLATE}')

    # Backup on first run
    backup = TEMPLATE + '.bak'
    if not os.path.exists(backup):
        shutil.copy2(TEMPLATE, backup)
        print(f'Backup: {backup}')
    else:
        print(f'Backup exists: {backup} (skipped)')

    doc = Document(TEMPLATE)
    added = inject(doc)

    if added > 0:
        doc.save(TEMPLATE)
        print(f'\nDone — {added} style(s) added to word.docx')
    else:
        print(f'\nDone — all styles already present, nothing to do')

    # Report current style inventory
    style_names = {s.name for s in doc.styles if s.type is not None}
    expected = {'Block Text', 'Compact', 'Source Code', 'Verbatim Char', 'Hyperlink', 'TOC Heading'}
    present = expected & style_names
    print(f'Style check: {len(present)}/{len(expected)} pandoc styles present')


if __name__ == '__main__':
    main()
