#!/usr/bin/env python3
"""Read visible text from a public conversation share page.

The script avoids installing browser engines. By default it only does static
HTML text extraction. Browser launch is opt-in to avoid intrusive system crash
dialogs in constrained desktop environments.
"""

from __future__ import annotations

import argparse
import ast
import html
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MIN_USEFUL_TEXT_CHARS = 200
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg", "canvas"}:
            self._skip_depth += 1
        if tag.lower() in {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg", "canvas"} and self._skip_depth:
            self._skip_depth -= 1
        if tag.lower() in {"p", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self.parts.append(data)

    def text(self) -> str:
        return normalize_text(" ".join(self.parts))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read visible text from a public conversation share URL."
    )
    parser.add_argument("url", help="Public share URL to read")
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        help="Navigation or request timeout in milliseconds",
    )
    parser.add_argument(
        "--settle-ms",
        type=int,
        default=5000,
        help="Virtual time budget for client-rendered content",
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=MIN_USEFUL_TEXT_CHARS,
        help="Minimum extracted text length considered useful",
    )
    parser.add_argument(
        "--no-static",
        action="store_true",
        help="Skip static HTTP extraction and go straight to browser rendering",
    )
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="Only run static HTML/embedded-data extraction; never launch browsers.",
    )
    parser.add_argument(
        "--allow-system-browser",
        action="store_true",
        help=(
            "Allow discovery and launch of system Chromium-family browsers. "
            "CONVERSATION_SUMMARY_BROWSER is still honored without this flag."
        ),
    )
    parser.add_argument(
        "--allow-playwright",
        action="store_true",
        help="Allow launching already-installed Playwright managed browsers.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit a compact, summary-friendly view when structured share data is available.",
    )
    parser.add_argument(
        "--assistant-chars",
        type=int,
        default=900,
        help="Maximum assistant characters per round in compact mode.",
    )
    parser.add_argument(
        "--user-chars",
        type=int,
        default=300,
        help="Maximum user characters per round in compact mode.",
    )
    return parser.parse_args()


def normalize_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r"\n\s+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def is_useful(text: str, min_chars: int) -> bool:
    if len(text) < min_chars:
        return False
    lowered = text.lower()
    shell_markers = (
        "enable javascript",
        "please enable javascript",
        "browser not supported",
        "403 forbidden",
        "access denied",
    )
    return not any(marker in lowered for marker in shell_markers)


def fetch_static_text(url: str, timeout_ms: int) -> tuple[str, str | None]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout_ms / 1000) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return "", f"static fetch failed: {exc}"

    parser = VisibleTextParser()
    parser.feed(body)
    return combine_texts([parser.text(), extract_embedded_text(body)]), None


def fetch_known_share_api_text(
    url: str,
    timeout_ms: int,
    compact: bool = False,
    user_chars: int = 300,
    assistant_chars: int = 900,
) -> tuple[str, str | None]:
    parsed = urlparse(url)
    if parsed.netloc.endswith("qianwen.com"):
        match = re.search(r"/share/chat/([^/?#]+)", parsed.path)
        if match:
            return fetch_qianwen_share_text(
                url,
                match.group(1),
                timeout_ms,
                compact=compact,
                user_chars=user_chars,
                assistant_chars=assistant_chars,
            )

    return "", "no known static share API matched"


def fetch_qianwen_share_text(
    page_url: str,
    share_id: str,
    timeout_ms: int,
    compact: bool = False,
    user_chars: int = 300,
    assistant_chars: int = 900,
) -> tuple[str, str | None]:
    payload = json.dumps({"share_id": share_id}).encode("utf-8")
    request = Request(
        "https://chat2-api.qianwen.com/api/v1/share/info",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Origin": "https://www.qianwen.com",
            "Referer": page_url,
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout_ms / 1000) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return "", f"qianwen share/info fetch failed: {exc}"

    try:
        payload_data = json.loads(body)
    except json.JSONDecodeError as exc:
        return "", f"qianwen share/info returned invalid JSON: {exc}"

    if payload_data.get("code") != 0:
        return "", f"qianwen share/info returned code={payload_data.get('code')} msg={payload_data.get('msg')}"

    data = payload_data.get("data") or {}
    session = data.get("session") or {}
    records = session.get("record_list") or []
    if compact:
        return format_qianwen_compact(data, records, user_chars, assistant_chars), None

    parts: list[str] = []
    title = data.get("title") or session.get("title")
    if title:
        parts.append(f"# {title}")

    for index, record in enumerate(records, 1):
        user_text = combine_texts(
            [
                message.get("content") or message.get("meta_data", {}).get("ori_query") or ""
                for message in record.get("request_messages", [])
                if isinstance(message, dict)
            ]
        )
        assistant_text = combine_texts(
            [
                extract_message_text(message)
                for message in record.get("response_messages", [])
                if isinstance(message, dict)
            ]
        )
        if user_text:
            parts.append(f"## Round {index} User\n{user_text}")
        if assistant_text:
            parts.append(f"## Round {index} Assistant\n{assistant_text}")

    return combine_texts(parts), None


def format_qianwen_compact(
    data: dict,
    records: list[dict],
    user_chars: int,
    assistant_chars: int,
) -> str:
    session = data.get("session") or {}
    title = data.get("title") or session.get("title") or "Qianwen Share Conversation"
    parts = [
        f"# {title}",
        "",
        "## Conversation Coverage",
        f"- Total rounds: {len(records)}",
        "- This compact view intentionally lists every user turn first, so broad multi-topic conversations are not summarized from the tail only.",
        "",
        "## User Turn Index",
    ]

    round_items: list[tuple[int, str, str]] = []
    for index, record in enumerate(records, 1):
        user_text = clean_extracted_text(
            combine_texts(
                [
                    message.get("content") or message.get("meta_data", {}).get("ori_query") or ""
                    for message in record.get("request_messages", [])
                    if isinstance(message, dict)
                ]
            )
        )
        assistant_text = clean_extracted_text(
            combine_texts(
                [
                    extract_message_text(message)
                    for message in record.get("response_messages", [])
                    if isinstance(message, dict)
                ]
            )
        )
        round_items.append((index, user_text, assistant_text))
        if user_text:
            parts.append(f"{index}. {truncate_text(user_text, user_chars)}")

    parts.extend(["", "## Round Details"])
    for index, user_text, assistant_text in round_items:
        parts.append(f"### Round {index}")
        if user_text:
            parts.append(f"User: {truncate_text(user_text, user_chars)}")
        if assistant_text:
            parts.append(f"Assistant: {truncate_text(assistant_text, assistant_chars)}")

    return "\n".join(parts)


def clean_extracted_text(value: str) -> str:
    value = re.sub(r"\[\[source_group_[^\]]+\]\]", "", value)
    value = re.sub(r"\[\(video_note_list_[^)]+\)\]", "", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return normalize_text(value)


def truncate_text(value: str, limit: int) -> str:
    value = normalize_text(value)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def extract_message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        values = extract_text_from_json_value(content)
        return combine_texts(values) or text_from_maybe_markup(content)

    meta_data = message.get("meta_data")
    if isinstance(meta_data, dict):
        values = []
        for key in ("content", "text", "answer"):
            value = meta_data.get(key)
            if isinstance(value, str):
                values.append(value)
        return combine_texts(values)

    return ""


def combine_texts(values: list[str]) -> str:
    parts: list[str] = []
    for value in values:
        normalized = normalize_text(value)
        if not normalized:
            continue

        duplicate = False
        for index, existing in enumerate(parts):
            if normalized == existing or normalized in existing:
                duplicate = True
                break
            if existing in normalized:
                parts[index] = normalized
                duplicate = True
                break
        if duplicate:
            continue

        parts.append(normalized)
    return "\n\n".join(parts)


def extract_embedded_text(document: str) -> str:
    candidates: list[str] = []
    decoded_document = html.unescape(document)

    for match in re.finditer(r"<script\b[^>]*>(.*?)</script>", decoded_document, re.I | re.S):
        candidates.extend(extract_text_from_js(match.group(1)))

    candidates.extend(extract_text_from_json_scripts(decoded_document))
    return combine_texts(candidates)


def extract_text_from_json_scripts(document: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(
        r"<script\b[^>]+type=[\"']application/json[\"'][^>]*>(.*?)</script>",
        document,
        re.I | re.S,
    ):
        raw = html.unescape(match.group(1)).strip()
        values.extend(extract_text_from_json_value(raw))
    return values


def extract_text_from_js(script: str) -> list[str]:
    values: list[str] = []

    for quoted in re.findall(r'"(?:\\.|[^"\\]){80,}"', script):
        values.extend(extract_text_from_json_value(quoted))

    for quoted in re.findall(r"'(?:\\.|[^'\\]){80,}'", script):
        values.extend(extract_text_from_json_value(quoted))

    return values


def extract_text_from_json_value(raw: str, depth: int = 0) -> list[str]:
    if depth > 4:
        return []

    values: list[str] = []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = decode_quoted_js_string(raw)

    if isinstance(parsed, str):
        text = text_from_maybe_markup(parsed)
        if looks_contentful(text):
            values.append(text)

        stripped = parsed.strip()
        if stripped.startswith(("{", "[")):
            values.extend(extract_text_from_json_value(stripped, depth + 1))
    elif isinstance(parsed, dict):
        for value in parsed.values():
            values.extend(extract_text_from_json_value(json.dumps(value, ensure_ascii=False), depth + 1))
    elif isinstance(parsed, list):
        for value in parsed:
            values.extend(extract_text_from_json_value(json.dumps(value, ensure_ascii=False), depth + 1))

    return values


def decode_quoted_js_string(raw: str) -> str:
    raw = raw.strip()
    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, str):
            return parsed
    except (SyntaxError, ValueError):
        pass
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        raw = raw[1:-1]
    return raw


def text_from_maybe_markup(value: str) -> str:
    if "<" in value and ">" in value:
        parser = VisibleTextParser()
        parser.feed(value)
        parsed = parser.text()
        if parsed:
            return parsed
    return normalize_text(value)


def looks_contentful(value: str) -> bool:
    if len(value) < 80:
        return False
    if value.startswith(("http://", "https://", "//")):
        return False
    if re.search(r"\b(function|const|var|return|document|window)\b", value) and len(
        re.findall(r"[\u4e00-\u9fff]", value)
    ) < 40:
        return False

    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", value))
    newline_count = value.count("\n")
    punctuation_count = len(re.findall(r"[，。！？；：、,.!?;:]", value))
    url_count = value.count("http://") + value.count("https://") + value.count("//")

    if url_count > 3 and cjk_count < 40:
        return False
    return cjk_count >= 20 or (newline_count >= 2 and cjk_count >= 5) or (
        punctuation_count >= 8 and cjk_count >= 10
    )


def executable(path: str | Path | None) -> str | None:
    if not path:
        return None
    candidate = Path(path).expanduser()
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def browser_candidates(allow_discovery: bool) -> list[str]:
    candidates: list[str] = []

    env_value = os.environ.get("CONVERSATION_SUMMARY_BROWSER")
    if env_value:
        candidates.append(env_value)

    if not allow_discovery:
        return unique_executables(candidates)

    commands = [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
        "microsoft-edge-stable",
        "msedge",
        "brave-browser",
        "brave",
        "chrome",
    ]
    for command in commands:
        found = shutil.which(command)
        if found:
            candidates.append(found)

    system = platform.system().lower()
    if system == "darwin":
        candidates.extend(
            [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
                "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            ]
        )
    elif system == "windows":
        prefixes = [
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("LocalAppData"),
        ]
        relative_paths = [
            r"Google\Chrome\Application\chrome.exe",
            r"Microsoft\Edge\Application\msedge.exe",
            r"Chromium\Application\chrome.exe",
            r"BraveSoftware\Brave-Browser\Application\brave.exe",
        ]
        for prefix in prefixes:
            if not prefix:
                continue
            for relative_path in relative_paths:
                candidates.append(str(Path(prefix) / relative_path))

    return unique_executables(candidates)


def unique_executables(candidates: list[str]) -> list[str]:
    seen: set[str] = set()
    valid: list[str] = []
    for candidate in candidates:
        resolved = executable(candidate)
        if resolved and resolved not in seen:
            valid.append(resolved)
            seen.add(resolved)
    return valid


def run_browser_dump(
    browser: str,
    url: str,
    timeout_ms: int,
    settle_ms: int,
    no_sandbox: bool = False,
) -> tuple[str, str | None]:
    with tempfile.TemporaryDirectory(prefix="conversation-summary-browser-") as profile:
        errors: list[str] = []
        for headless_arg in ("--headless=new", "--headless"):
            base_args = [
                browser,
                headless_arg,
                "--dump-dom",
                f"--user-data-dir={profile}",
                f"--virtual-time-budget={settle_ms}",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-extensions",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-networking",
                "--disable-sync",
                "--window-size=1440,1200",
            ]
            if no_sandbox:
                base_args.append("--no-sandbox")
            command = base_args + [url]

            try:
                proc = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=timeout_ms / 1000,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                errors.append(f"{headless_arg}: launch failed: {exc}")
                continue

            if proc.returncode == 0:
                parser = VisibleTextParser()
                parser.feed(proc.stdout)
                return parser.text(), None

            stderr = normalize_text(proc.stderr)
            stdout = normalize_text(proc.stdout)
            detail = stderr or stdout or "no stderr/stdout"
            errors.append(f"{headless_arg}: returned {proc.returncode}: {detail[:500]}")

    return "", f"{browser}: " + " | ".join(errors)


def render_with_system_browser(
    url: str,
    timeout_ms: int,
    settle_ms: int,
    min_chars: int,
    allow_discovery: bool,
) -> tuple[str, list[str]]:
    errors: list[str] = []
    browsers = browser_candidates(allow_discovery)
    if not browsers:
        if allow_discovery:
            return "", ["no system Chromium-family browser found"]
        return "", [
            "system browser launch skipped; set CONVERSATION_SUMMARY_BROWSER or pass --allow-system-browser"
        ]

    for browser in browsers:
        text, error = run_browser_dump(browser, url, timeout_ms, settle_ms)
        if is_useful(text, min_chars):
            return text, errors
        if error:
            errors.append(error)
            if "sandbox" in error.lower() and platform.system().lower() != "windows":
                retry_text, retry_error = run_browser_dump(
                    browser, url, timeout_ms, settle_ms, no_sandbox=True
                )
                if is_useful(retry_text, min_chars):
                    return retry_text, errors
                if retry_error:
                    errors.append(retry_error)
        elif text:
            errors.append(f"{browser}: rendered text was too short ({len(text)} chars)")

    return "", errors


def render_with_playwright(url: str, timeout_ms: int, settle_ms: int) -> tuple[str, str | None]:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "", "Playwright Python package is not installed"

    with sync_playwright() as p:
        launch_errors: list[str] = []
        for browser_type in (p.chromium, p.firefox, p.webkit):
            try:
                browser = browser_type.launch(headless=True)
                break
            except PlaywrightError as exc:
                launch_errors.append(f"{browser_type.name}: {exc}")
        else:
            return "", "Playwright is installed, but no managed browser could launch: " + " | ".join(
                launch_errors
            )

        try:
            page = browser.new_page(
                viewport={"width": 1440, "height": 1200},
                user_agent=USER_AGENT,
            )
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 10000))
            except PlaywrightError:
                pass
            page.wait_for_timeout(settle_ms)
            text = page.locator("body").inner_text(timeout=5000).strip()
        finally:
            browser.close()

    return normalize_text(text), None


def fail(errors: list[str]) -> int:
    print(
        "Unable to read useful text from the URL without an available browser engine.",
        file=sys.stderr,
    )
    print(
        "This does not prove the link requires login or cookies. "
        "It means the current environment could not statically read or render it.",
        file=sys.stderr,
    )
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    print(
        "If a Chromium-family browser is installed, set CONVERSATION_SUMMARY_BROWSER to its executable path. "
        "For automatic browser discovery pass --allow-system-browser. "
        "Otherwise paste the page text or allow installing a browser engine.",
        file=sys.stderr,
    )
    return 2


def fail_static_only(errors: list[str]) -> int:
    print(
        "Static extraction did not find enough useful text. No browser fallback was attempted.",
        file=sys.stderr,
    )
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    print(
        "Do not infer that the link requires login. If this page is known to expose data in HTML, "
        "inspect the full response, not only the first bytes or _SSR_DATA.",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    args = parse_args()
    errors: list[str] = []

    if not args.no_static:
        text, error = fetch_static_text(args.url, args.timeout_ms)
        if is_useful(text, args.min_chars):
            print(text)
            return 0
        if error:
            errors.append(error)
        elif text:
            errors.append(f"static fetch text was too short ({len(text)} chars)")
        else:
            errors.append("static fetch produced no visible text")

        text, error = fetch_known_share_api_text(
            args.url,
            args.timeout_ms,
            compact=args.compact,
            user_chars=args.user_chars,
            assistant_chars=args.assistant_chars,
        )
        if is_useful(text, args.min_chars):
            print(text)
            return 0
        if error:
            errors.append(error)
        elif text:
            errors.append(f"known share API text was too short ({len(text)} chars)")

    if args.static_only:
        return fail_static_only(errors)

    text, browser_errors = render_with_system_browser(
        args.url,
        args.timeout_ms,
        args.settle_ms,
        args.min_chars,
        args.allow_system_browser,
    )
    if is_useful(text, args.min_chars):
        print(text)
        return 0
    errors.extend(browser_errors)

    if args.allow_playwright:
        text, error = render_with_playwright(args.url, args.timeout_ms, args.settle_ms)
        if is_useful(text, args.min_chars):
            print(text)
            return 0
        if error:
            errors.append(error)
        elif text:
            errors.append(f"Playwright rendered text was too short ({len(text)} chars)")
    else:
        errors.append("Playwright launch skipped; pass --allow-playwright to opt in")

    return fail(errors)


if __name__ == "__main__":
    raise SystemExit(main())
