#!/usr/bin/env python3
"""Sync Folo collection entries into Obsidian clippings.

The script only creates new files under <vault>/11-Clippings. It never edits,
moves or deletes existing files. Default mode is a dry run; pass --write to
create files.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "spm",
    "from",
    "scene",
    "poc_token",
    "wxfrom",
    "wx_lazy",
    "ref",
}
ILLEGAL_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
DEFAULT_CATEGORY = "11-Clippings"


def quote(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def normalize_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS and not key.lower().startswith("utm_")
    ]
    query.sort()
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))


def normalize_title(title: str) -> str:
    return re.sub(r"[\s\W_]+", "", (title or "").lower(), flags=re.UNICODE)


def sanitize_filename(title: str, fallback: str) -> str:
    name = ILLEGAL_FILENAME.sub("-", title or "")
    name = re.sub(r"\s+", " ", name).strip(" .-")
    if not name:
        name = f"clipping-{fallback}"
    return name[:80].rstrip(" .-") or f"clipping-{fallback}"


def load_existing_sources(clippings_dir: Path) -> set[str]:
    sources: set[str] = set()
    if not clippings_dir.exists():
        return sources
    for path in clippings_dir.glob("*.md"):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not text.startswith("---"):
            continue
        end = text.find("\n---", 3)
        if end == -1:
            continue
        frontmatter = text[3:end]
        match = re.search(r"^source:\s*(.+?)\s*$", frontmatter, re.MULTILINE)
        if not match:
            continue
        raw = match.group(1).strip()
        if raw.startswith('"') and raw.endswith('"'):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = raw[1:-1]
        elif raw.startswith("'") and raw.endswith("'"):
            raw = raw[1:-1]
        normalized = normalize_url(str(raw))
        if normalized:
            sources.add(normalized)
    return sources


def load_existing_titles(clippings_dir: Path) -> set[str]:
    titles: set[str] = set()
    if not clippings_dir.exists():
        return titles
    for path in clippings_dir.glob("*.md"):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not text.startswith("---"):
            continue
        end = text.find("\n---", 3)
        if end == -1:
            continue
        frontmatter = text[3:end]
        match = re.search(r"^title:\s*(.+?)\s*$", frontmatter, re.MULTILINE)
        if not match:
            continue
        raw = match.group(1).strip()
        if raw.startswith('"') and raw.endswith('"'):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = raw[1:-1]
        elif raw.startswith("'") and raw.endswith("'"):
            raw = raw[1:-1]
        normalized = normalize_title(str(raw))
        if normalized:
            titles.add(normalized)
    return titles


def clean_html(raw_html: str) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return raw_html
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe", "object", "embed"]):
        tag.decompose()
    for tag in soup.find_all(["div", "span"]):
        tag.unwrap()
    for tag in soup.find_all(["p"]):
        if not tag.get_text(strip=True) and not tag.find(["img", "br", "hr"]):
            tag.decompose()
    allowed = {"href", "src", "alt", "title"}
    for tag in soup.find_all(True):
        original = dict(tag.attrs)
        attrs = {key: value for key, value in original.items() if key in allowed}
        if tag.name == "img" and "src" not in attrs and original.get("data-src"):
            attrs["src"] = original["data-src"]
        tag.attrs = attrs
    return str(soup)


def postprocess_markdown(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_to_markdown(raw_html: str, pandoc_bin: str) -> str:
    cleaned = clean_html(raw_html)
    if shutil.which(pandoc_bin):
        result = subprocess.run(
            [pandoc_bin, "-f", "html", "-t", "gfm", "--wrap=none"],
            input=cleaned,
            text=True,
            capture_output=True,
            timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            return postprocess_markdown(result.stdout)
    try:
        from markdownify import markdownify
    except ImportError:
        return postprocess_markdown(re.sub(r"<[^>]+>", "", cleaned))
    return postprocess_markdown(markdownify(cleaned, heading_style="ATX"))


def render_frontmatter(entry: dict, source: str, pending: bool) -> str:
    title = entry.get("title") or "Untitled"
    author = entry.get("author")
    authors = [author] if isinstance(author, str) and author else []
    lines = [
        "---",
        f"title: {quote(title)}",
        f"source: {quote(source)}",
    ]
    if authors:
        lines.append("author:")
        lines.extend(f"  - {quote(item)}" for item in authors)
    else:
        lines.append("author: []")
    lines.extend(
        [
            f"published: {quote(entry.get('publishedAt') or '')}",
            f"created: {quote(date.today().isoformat())}",
            'description: ""',
            "tags:",
            '  - "clippings"',
        ]
    )
    if pending:
        lines.append('  - "待整理"')
    lines.append("---")
    return "\n".join(lines)


def unique_path(clippings_dir: Path, title: str, entry_id: str, planned: set[str]) -> Path:
    base = sanitize_filename(title, entry_id or "unknown")
    candidate = clippings_dir / f"{base}.md"
    if not candidate.exists() and candidate.name not in planned:
        planned.add(candidate.name)
        return candidate
    suffix = entry_id or date.today().strftime("%Y%m%d")
    candidate = clippings_dir / f"{base} - {suffix}.md"
    index = 2
    while candidate.exists() or candidate.name in planned:
        candidate = clippings_dir / f"{base} - {suffix}-{index}.md"
        index += 1
    planned.add(candidate.name)
    return candidate


def build_plan(
    entries: list[dict],
    existing: set[str],
    existing_titles: set[str],
    content_fetcher,
    clippings_dir: Path,
    pending: bool,
    pandoc_bin: str,
) -> list[dict]:
    plan: list[dict] = []
    seen = set(existing)
    seen_titles = set(existing_titles)
    planned_names: set[str] = set()
    for wrapper in entries:
        entry = wrapper.get("entries") or {}
        entry_id = str(entry.get("id") or "")
        title = entry.get("title") or ""
        source = entry.get("url") or ""
        normalized = normalize_url(source)
        normalized_title = normalize_title(title)
        if (normalized and normalized in seen) or (
            normalized_title and normalized_title in seen_titles
        ):
            plan.append({"status": "duplicate", "title": title, "source": source})
            continue
        if normalized:
            seen.add(normalized)
        if normalized_title:
            seen_titles.add(normalized_title)
        try:
            raw_html = content_fetcher(entry_id) or ""
        except Exception as exc:  # noqa: BLE001 - report per-entry failure
            plan.append(
                {"status": "failed", "title": title, "source": source, "error": str(exc)}
            )
            continue
        link_only = False
        if not raw_html.strip():
            description = entry.get("description") or ""
            if not description.strip():
                plan.append({"status": "no_content", "title": title, "source": source})
                continue
            raw_html = f"<p>{html_lib.escape(description)}</p>"
            link_only = True
        markdown = html_to_markdown(raw_html, pandoc_bin)
        if not markdown.strip():
            plan.append({"status": "no_content", "title": title, "source": source})
            continue
        if link_only:
            markdown = f"> 原文：[{title or source}]({source})\n\n{markdown}"
        path = unique_path(clippings_dir, title, entry_id, planned_names)
        plan.append(
            {
                "status": "add",
                "title": title,
                "source": source,
                "path": path,
                "frontmatter": render_frontmatter(entry, source, pending),
                "markdown": markdown,
                "link_only": link_only,
            }
        )
    return plan


def run_json(command: list[str], timeout: int = 90) -> dict:
    result = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n{result.stderr.strip()}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON from {' '.join(command)}: {exc}") from exc
    if not payload.get("ok"):
        raise RuntimeError(str(payload.get("error") or payload))
    return payload


def resolve_folo(binary: str) -> list[str]:
    if shutil.which(binary):
        return [binary]
    if shutil.which("npx"):
        return ["npx", "--yes", "folocli@0.0.5"]
    raise RuntimeError(
        "folo CLI not found. Install folocli or run with --folo-bin pointing to it."
    )


def collection_entries(folo_command: list[str], limit: int) -> list[dict]:
    collected: list[dict] = []
    cursor = None
    while len(collected) < limit:
        page_size = min(50, limit - len(collected))
        command = [*folo_command, "collection", "list", "--limit", str(page_size)]
        if cursor:
            command.extend(["--cursor", cursor])
        payload = run_json(command)
        data = payload.get("data") or {}
        if isinstance(data, list):
            page = data
            has_next = False
            next_cursor = None
        else:
            page = data.get("entries") or []
            has_next = bool(data.get("hasNext"))
            next_cursor = data.get("nextCursor")
        if not page:
            break
        collected.extend(page)
        if not has_next or not next_cursor:
            break
        cursor = next_cursor
    return collected[:limit]


def entry_content(folo_command: list[str], entry_id: str) -> str:
    try:
        payload = run_json([*folo_command, "entry", "read", entry_id])
        content = (payload.get("data") or {}).get("content") or ""
        if content.strip():
            return content
    except Exception:  # noqa: BLE001 - fall back to entry get
        pass
    try:
        payload = run_json([*folo_command, "entry", "get", entry_id])
        entries = (payload.get("data") or {}).get("entries") or {}
        return entries.get("content") or ""
    except Exception:  # noqa: BLE001 - report as no content
        return ""


def write_clipping(path: Path, frontmatter: str, markdown: str) -> None:
    content = f"{frontmatter}\n\n{markdown.strip()}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(content)
        temp_name = handle.name
    os.replace(temp_name, path)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync Folo collection entries into Obsidian 11-Clippings."
    )
    parser.add_argument(
        "--vault-root",
        default=os.environ.get("OBSIDIAN_VAULT", ""),
        help="Obsidian vault root (or set OBSIDIAN_VAULT).",
    )
    parser.add_argument("--limit", type=int, default=50, help="Maximum collection entries.")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Actually create files. Without this flag the script only prints a plan.",
    )
    parser.add_argument(
        "--no-pending",
        action="store_true",
        help="Do not add the pending-review tag 待整理.",
    )
    parser.add_argument("--folo-bin", default="folo", help="Folo CLI binary name.")
    parser.add_argument("--pandoc-bin", default="pandoc", help="Pandoc binary name.")
    parser.add_argument(
        "--from-json",
        help="Fixture JSON with {entries, contents}; skips live Folo calls.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if not args.vault_root:
        print("error: --vault-root or OBSIDIAN_VAULT is required", file=sys.stderr)
        return 2
    vault_root = Path(args.vault_root).expanduser().resolve()
    clippings_dir = vault_root / DEFAULT_CATEGORY
    if not clippings_dir.is_dir():
        print(f"error: {clippings_dir} does not exist", file=sys.stderr)
        return 2

    existing = load_existing_sources(clippings_dir)
    existing_titles = load_existing_titles(clippings_dir)
    if args.from_json:
        fixture = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        entries = fixture.get("entries") or []
        contents = fixture.get("contents") or {}

        def fetch(entry_id: str) -> str:
            return contents.get(entry_id) or ""

    else:
        try:
            folo_command = resolve_folo(args.folo_bin)
            entries = collection_entries(folo_command, args.limit)
        except Exception as exc:  # noqa: BLE001 - top-level CLI failure
            print(f"error: {exc}", file=sys.stderr)
            return 1

        def fetch(entry_id: str) -> str:
            return entry_content(folo_command, entry_id)

    plan = build_plan(
        entries,
        existing,
        existing_titles,
        fetch,
        clippings_dir,
        pending=not args.no_pending,
        pandoc_bin=args.pandoc_bin,
    )

    counts = {"add": 0, "duplicate": 0, "no_content": 0, "failed": 0}
    for item in plan:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
        if item["status"] == "add":
            print(f"ADD   {item['title'] or '(untitled)'} -> {item['path']}")
        elif item["status"] == "duplicate":
            print(f"SKIP  duplicate: {item['title'] or item['source']}")
        elif item["status"] == "no_content":
            print(f"SKIP  no content: {item['title'] or item['source']}")
        else:
            print(f"FAIL  {item['title'] or item['source']}: {item.get('error', '')}")

    print(
        "Summary: "
        f"{counts.get('add', 0)} add, {counts.get('duplicate', 0)} duplicate, "
        f"{counts.get('no_content', 0)} no content, {counts.get('failed', 0)} failed"
    )
    if not args.write:
        print("Dry run: no files written. Re-run with --write to create them.")
        return 0 if counts.get("failed", 0) == 0 else 1

    for item in plan:
        if item["status"] != "add":
            continue
        write_clipping(item["path"], item["frontmatter"], item["markdown"])
        print(f"WROTE {item['path']}")
    return 0 if counts.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
