#!/usr/bin/env python3
"""
Pre-process markdown for pandoc → docx conversion.

Fixes three common issues in Chinese technical markdown:
  1. Adds blank lines before ordered/unordered lists
     (pandoc requires blank line before list, else merges into paragraph)
  2. Removes standalone --- section separators
     (with -yaml_metadata_block, pandoc treats --- as setext heading underline)
  3. Renders ```mermaid code blocks to PNG images via mmdc
     (pandoc can't render mermaid natively)

Usage:
    # Basic pre-processing (lists + --- removal)
    python3 scripts/pre_process.py input.md -o clean.md

    # With mermaid rendering
    python3 scripts/pre_process.py input.md -o clean.md --mermaid

    # Pipe to pandoc directly
    python3 scripts/pre_process.py input.md | pandoc -o output.docx --reference-doc=word.docx
"""

import os
import sys
import re
import shutil
import subprocess
import argparse
import uuid
import tempfile


# ── Check mmdc availability ────────────────────────────────────────

def mmdc_available():
    """Check if mmdc (mermaid-cli) can be invoked via npx."""
    try:
        result = subprocess.run(
            ['npx', '--yes', '@mermaid-js/mermaid-cli', '--version'],
            capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0
    except Exception:
        return False


# ── Fix 1: Blank lines before lists ─────────────────────────────────

def fix_list_blank_lines(text):
    """Insert blank lines before ordered/unordered lists.

    Pandoc (CommonMark) requires a blank line between a paragraph
    and a subsequent list. Chinese technical writing often omits
    this blank line, causing pandoc to merge the list into the
    preceding paragraph.
    """
    lines = text.split('\n')
    result = []
    in_code_block = False
    prev_is_blank = True  # start of file: virtual blank
    prev_is_list = False

    # Pattern: line that starts a list item
    # Ordered: "1. ", "1) ", " 1. " etc (digits, optional indent, dot/paren, space)
    # Unordered: "- ", "* " (optional indent, dash/star, space)
    list_pattern = re.compile(r'^(\s*)(\d+[.)]\s+|\-\s+|\*\s+)(.*)')

    for i, line in enumerate(lines):
        stripped = line.strip()
        is_hr = stripped == '---'

        # Track code block boundaries (don't modify inside)
        if stripped.startswith('```'):
            in_code_block = not in_code_block
            result.append(line)
            prev_is_blank = False
            prev_is_list = False
            continue

        if in_code_block:
            result.append(line)
            prev_is_blank = (stripped == '')
            prev_is_list = False
            continue

        m = list_pattern.match(line)
        is_list_item = m is not None and not is_hr

        # Insert blank line before list if needed
        if is_list_item and not prev_is_blank and not prev_is_list:
            result.append('')
            prev_is_blank = True

        result.append(line)
        prev_is_blank = (stripped == '')
        prev_is_list = is_list_item

    return '\n'.join(result)


# ── Fix 2: Remove --- separators ───────────────────────────────────

def remove_hr_separators(text):
    """Remove standalone --- lines.

    With -yaml_metadata_block, pandoc treats --- as a setext heading
    underline, converting the preceding text into an H2 heading.
    In Chinese markdown, --- is used purely as a visual section
    separator and should not appear in the Word output.
    """
    lines = text.split('\n')
    result = []
    in_code_block = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        if stripped.startswith('```'):
            in_code_block = not in_code_block
            result.append(line)
            continue

        if in_code_block:
            result.append(line)
            continue

        # Remove standalone --- (just dashes, possibly with trailing whitespace)
        if stripped == '---' or re.match(r'^\-{3,}\s*$', stripped):
            # Don't add an empty line that would create unintended spacing
            # If previous line already added, skip duplicate
            continue

        result.append(line)

    return '\n'.join(result)


# ── Fix 3: Mermaid → PNG via mmdc ──────────────────────────────────

def extract_mermaid_blocks(text):
    """Extract ```mermaid code blocks with their positions."""
    blocks = []
    lines = text.split('\n')
    in_mermaid = False
    start_idx = None
    mermaid_lines = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r'^`{3,}mermaid\s*$', stripped):
            in_mermaid = True
            start_idx = i
            mermaid_lines = []
            continue
        if in_mermaid and re.match(r'^`{3,}$', stripped):
            blocks.append({
                'start': start_idx,
                'end': i + 1,  # exclusive
                'code': '\n'.join(mermaid_lines).strip()
            })
            in_mermaid = False
            continue
        if in_mermaid:
            mermaid_lines.append(line)

    return blocks, lines


def render_mermaid_diagram(mermaid_code, output_path, width=1600, scale=2):
    """Render a mermaid diagram to PNG using mmdc (via npx).

    Returns True on success, False on failure.
    """
    # Write mermaid code to temp file (mmdc needs a file for complex diagrams)
    tmp_mmd = output_path + '.mmd'
    try:
        with open(tmp_mmd, 'w', encoding='utf-8') as f:
            f.write(mermaid_code)

        result = subprocess.run(
            [
                'npx', '--yes', '@mermaid-js/mermaid-cli',
                '-i', tmp_mmd,
                '-o', output_path,
                '-w', str(width),
                '-s', str(scale),
                '-b', 'white',
                '-q',  # quiet
            ],
            capture_output=True, text=True, timeout=30
        )
        success = result.returncode == 0 and os.path.exists(output_path)

        # Cleanup temp .mmd file
        os.unlink(tmp_mmd)

        return success
    except Exception:
        # Clean up on failure
        if os.path.exists(tmp_mmd):
            os.unlink(tmp_mmd)
        if os.path.exists(output_path):
            os.unlink(output_path)
        return False


def render_mermaid_blocks(text, image_dir=None):
    """Render all ```mermaid blocks to PNG images.

    If image_dir is None, mermaid blocks are left as-is (code blocks).
    Returns (modified_text, image_count, failures).
    """
    blocks, lines = extract_mermaid_blocks(text)
    if not blocks:
        return text, 0, 0

    if image_dir is None:
        return text, 0, 0

    os.makedirs(image_dir, exist_ok=True)

    rendered = 0
    failed = 0

    # Process blocks in reverse order so line indices stay valid
    for block in reversed(blocks):
        code = block['code']
        if not code.strip():
            # Empty mermaid block — leave as-is
            continue

        img_name = f"mermaid_{uuid.uuid4().hex[:8]}.png"
        img_path = os.path.join(image_dir, img_name)

        if render_mermaid_diagram(code, img_path):
            # Replace ```mermaid ... ``` with image reference (absolute path)
            # Using absolute path so pandoc finds images regardless of cwd
            img_line = f'![]({img_path})'

            # Replace lines from start to end-1 with the image reference
            lines[block['start']:block['end']] = [img_line, '']
            rendered += 1
        else:
            # Render failed — leave code block as-is
            failed += 1

    return '\n'.join(lines), rendered, failed


# ── Main ────────────────────────────────────────────────────────────

def pre_process(text, mermaid=False, image_dir=None, fix_lists=True,
                remove_hr=True):
    """Apply all pre-processing steps to markdown text."""
    if fix_lists:
        text = fix_list_blank_lines(text)

    if remove_hr:
        text = remove_hr_separators(text)

    if mermaid:
        text, rendered, failed = render_mermaid_blocks(text, image_dir)
    else:
        rendered, failed = 0, 0

    return text, rendered, failed


def main():
    parser = argparse.ArgumentParser(
        description='Pre-process markdown for pandoc → docx conversion')
    parser.add_argument('input', nargs='?', help='Input markdown file '
                        '(reads stdin if omitted or "-")')
    parser.add_argument('-o', '--output', help='Output file (writes to '
                        'stdout if omitted)')
    parser.add_argument('--mermaid', action='store_true',
                        help='Render ```mermaid blocks to PNG images')
    parser.add_argument('--mermaid-dir', default=None,
                        help='Directory for mermaid images (default: '
                        '<output_dir>/mermaid_images/)')
    parser.add_argument('--no-lists', action='store_true',
                        help='Skip list blank-line fix')
    parser.add_argument('--no-hr', action='store_true',
                        help='Skip --- separator removal')

    args = parser.parse_args()

    # Read input
    if args.input and args.input != '-':
        with open(args.input, 'r', encoding='utf-8') as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    # Determine image directory
    image_dir = None
    mermaid_tmp_dir = None  # track for cleanup
    if args.mermaid:
        if args.mermaid_dir:
            image_dir = args.mermaid_dir
        else:
            # Use temp directory — images are embedded in docx, files
            # don't need to persist. Cleaned up in the workflow.
            mermaid_tmp_dir = tempfile.mkdtemp(prefix='md2docx_mermaid_')
            image_dir = mermaid_tmp_dir

    # Check mmdc availability
    if args.mermaid and not mmdc_available():
        print('WARNING: mmdc (mermaid-cli) not available via npx.\n'
              '  Install: npm install -g @mermaid-js/mermaid-cli\n'
              '  Or run: npx @mermaid-js/mermaid-cli --version\n'
              '  Mermaid blocks will be left as code blocks.',
              file=sys.stderr)
        args.mermaid = False

    # Process
    text, rendered, failed = pre_process(
        text,
        mermaid=args.mermaid,
        image_dir=image_dir,
        fix_lists=not args.no_lists,
        remove_hr=not args.no_hr,
    )

    # Write output
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f'Pre-processed → {args.output}', file=sys.stderr)
    else:
        sys.stdout.write(text)

    # Report
    if args.mermaid:
        print(f'Mermaid: {rendered} rendered, {failed} failed',
              file=sys.stderr)
        if mermaid_tmp_dir:
            print(f'Mermaid tmp: {mermaid_tmp_dir} (clean up after pandoc)',
                  file=sys.stderr)


if __name__ == '__main__':
    main()
