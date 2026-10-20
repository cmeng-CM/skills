#!/usr/bin/env python3
"""Build a daily reading digest from the Folo timeline.

The digest is deliberately a decision list, not a clipping store:
- source tiers decide who is allowed into the digest;
- keywords and excludes do the cheap deterministic filtering;
- a small heuristic score ranks the remaining T2 candidates;
- the result is a Markdown file under 10-Inbox (by default).

No Folo read state is changed. No clipping files are created here.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
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
DEFAULT_CONFIG = "~/.config/folo-receive/config.json"
DEFAULT_STATE = "~/.local/state/folo-receive/state.json"
LEDGER_NAME = "folo-collection-ledger.json"
DIGEST_PREFIX = "folo-digest-"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp_name = handle.name
    os.replace(temp_name, path)


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


def title_key(title: str, source: str) -> str:
    normalized = normalize_title(title)
    if not normalized:
        return ""
    host = urlsplit(source or "").netloc.lower()
    return f"{normalized}@{host}"


def frontmatter_value(frontmatter: str, field: str) -> str:
    match = re.search(rf"^{re.escape(field)}:\s*(.+?)\s*$", frontmatter, re.MULTILINE)
    if not match:
        return ""
    raw = match.group(1).strip()
    if raw.startswith('"') and raw.endswith('"'):
        try:
            return str(json.loads(raw))
        except json.JSONDecodeError:
            return raw[1:-1]
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]
    return raw


def load_retained(vault_root: Path) -> dict:
    sources: set[str] = set()
    title_keys: set[str] = set()
    clippings = vault_root / "11-Clippings"
    ledger = clippings / LEDGER_NAME
    if ledger.exists():
        try:
            data = load_json(ledger)
            for record in (data.get("entries") or {}).values():
                normalized = record.get("normalized_source") or normalize_url(
                    record.get("source") or ""
                )
                if normalized:
                    sources.add(normalized)
                key = record.get("title_key") or title_key(
                    record.get("title") or "", record.get("source") or ""
                )
                if key:
                    title_keys.add(key)
        except (OSError, json.JSONDecodeError):
            pass
    if clippings.is_dir():
        for path in clippings.glob("*.md"):
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
            source = frontmatter_value(frontmatter, "source")
            normalized = normalize_url(source)
            if normalized:
                sources.add(normalized)
            key = title_key(frontmatter_value(frontmatter, "title"), source)
            if key:
                title_keys.add(key)
    return {"sources": sources, "title_keys": title_keys}


def feed_matches(rule: str, feed: dict) -> bool:
    fields = [str(feed.get("id") or ""), str(feed.get("url") or ""), str(feed.get("title") or "")]
    rule_lower = rule.lower()
    if "*" in rule:
        return any(fnmatch.fnmatchcase(value.lower(), rule_lower) for value in fields)
    return any(value.lower() == rule_lower for value in fields)


def tier_for(feed: dict, tiers: dict) -> str:
    for tier in ("T1", "T2"):
        if any(feed_matches(str(rule), feed) for rule in (tiers.get(tier) or [])):
            return tier
    return "T3"


def keyword_hit(text: str, keyword: str) -> bool:
    keyword = (keyword or "").strip()
    if not keyword:
        return False
    if re.fullmatch(r"[A-Za-z0-9_ .+-]+", keyword):
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(keyword)}(?![A-Za-z0-9_])"
        return re.search(pattern, text, re.IGNORECASE) is not None
    return keyword.lower() in text.lower()


def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if keyword_hit(text, keyword)]


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def score_entry(entry: dict, tier: str, config: dict, now: datetime) -> dict:
    title = entry.get("title") or ""
    description = entry.get("description") or ""
    text = f"{title}\n{description}"
    excluded = keyword_hits(text, config.get("exclude_keywords") or [])
    if excluded:
        return {"excluded": excluded, "score": 0, "reasons": [], "priority": [], "include": []}
    priority = keyword_hits(text, config.get("priority_keywords") or [])
    include = keyword_hits(text, config.get("include_keywords") or [])
    base = {"T1": 4, "T2": 2}.get(tier, 0)
    score = base + (3 if priority else 0) + min(len(include), 3)
    reasons = []
    if tier == "T1":
        reasons.append("T1 必读")
    elif tier == "T2":
        reasons.append("T2 观察")
    if priority:
        reasons.append("priority: " + ", ".join(priority))
    if include:
        reasons.append("include: " + ", ".join(include[:3]))
    published = parse_time(entry.get("publishedAt"))
    if published and now - published <= timedelta(hours=6):
        score += 1
        reasons.append("6 小时内")
    return {
        "excluded": [],
        "score": score,
        "reasons": reasons,
        "priority": priority,
        "include": include,
        "published": published,
    }


def feed_map(subscriptions: list[dict]) -> dict[str, dict]:
    mapping = {}
    for subscription in subscriptions:
        feed_id = str(subscription.get("feedId") or subscription.get("id") or "")
        if feed_id:
            mapping[feed_id] = subscription
    return mapping


def build_digest(
    entries: list[dict],
    subscriptions: list[dict],
    config: dict,
    retained: dict,
    seen: dict,
    include_seen: bool,
    now: datetime,
) -> tuple[str, dict, list[dict]]:
    feeds = feed_map(subscriptions)
    min_score = int(config.get("min_score", 3))
    max_per_feed = int(config.get("max_per_feed", 2))
    now_max = int(config.get("now_max", 3))
    daily_max = int(config.get("daily_max", 10))
    tiers = config.get("tiers") or {}
    stats = {
        "total": len(entries),
        "archived": 0,
        "t3": 0,
        "retained": 0,
        "seen": 0,
        "excluded": 0,
        "below": 0,
        "duplicate": 0,
        "feed_cap": 0,
        "t1": 0,
        "t2": 0,
        "shown": 0,
    }
    candidates = []
    processed = []
    seen_sources = set()
    seen_title_keys = set()
    per_feed: dict[str, int] = {}

    for wrapper in entries:
        entry = wrapper.get("entries") or {}
        feed = wrapper.get("feeds") or {}
        entry_id = str(entry.get("id") or "")
        title = entry.get("title") or ""
        source = entry.get("url") or ""
        if not entry_id or not title:
            continue
        if not include_seen and entry_id in (seen.get("entries") or {}):
            stats["seen"] += 1
            continue
        feed_id = str(feed.get("id") or "")
        subscription = feeds.get(feed_id) or feed
        category = subscription.get("category") or ""
        if category == "99归档":
            stats["archived"] += 1
            continue
        tier = tier_for(subscription, tiers)
        if tier == "T3":
            stats["t3"] += 1
            continue
        stats[tier.lower()] += 1
        normalized = normalize_url(source)
        key = title_key(title, source)
        if (normalized and normalized in retained["sources"]) or (
            key and key in retained["title_keys"]
        ):
            stats["retained"] += 1
            continue
        scored = score_entry(entry, tier, config, now)
        if scored["excluded"]:
            stats["excluded"] += 1
            continue
        if tier == "T2" and scored["score"] < min_score:
            stats["below"] += 1
            processed.append(
                {"entry_id": entry_id, "status": "skipped", "score": scored["score"]}
            )
            continue
        if (normalized and normalized in seen_sources) or (
            key and key in seen_title_keys
        ):
            stats["duplicate"] += 1
            continue
        if per_feed.get(feed_id, 0) >= max_per_feed:
            stats["feed_cap"] += 1
            continue
        if normalized:
            seen_sources.add(normalized)
        if key:
            seen_title_keys.add(key)
        per_feed[feed_id] = per_feed.get(feed_id, 0) + 1
        published = scored["published"]
        candidates.append(
            {
                "entry_id": entry_id,
                "title": title,
                "url": source,
                "feed": subscription.get("title") or feed.get("title") or "",
                "tier": tier,
                "score": scored["score"],
                "reasons": scored["reasons"],
                "priority": scored["priority"],
                "published": published,
            }
        )
        processed.append(
            {"entry_id": entry_id, "status": "shown", "score": scored["score"]}
        )

    candidates.sort(
        key=lambda item: (
            item["score"],
            item["published"] or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    now_items = [
        item for item in candidates if item["tier"] == "T1" or item["priority"]
    ][:now_max]
    now_ids = {item["entry_id"] for item in now_items}
    daily_items = [item for item in candidates if item["entry_id"] not in now_ids][
        :daily_max
    ]
    stats["shown"] = len(now_items) + len(daily_items)
    digest = render_digest(now, now_items, daily_items, stats, config)
    return digest, stats, processed


def render_item(item: dict) -> str:
    published = item["published"]
    published_text = published.astimezone().strftime("%Y-%m-%d %H:%M") if published else "未知时间"
    reasons = "；".join(item["reasons"]) or "规则命中"
    return (
        f"- [ ] **{item['title']}** — {item['feed']} · {item['tier']} · {item['score']} 分\n"
        f"  - [原文]({item['url']}) · {published_text}\n"
        f"  - 为什么：{reasons}"
    )


def render_digest(
    now: datetime, now_items: list[dict], daily_items: list[dict], stats: dict, config: dict
) -> str:
    day = now.astimezone().date().isoformat()
    lines = [
        "---",
        f"title: {json.dumps('Folo 日报 ' + day, ensure_ascii=False)}",
        f"created: {json.dumps(day)}",
        "tags:",
        '  - "folo"',
        '  - "digest"',
        "---",
        "",
        f"# Folo 日报 {day}",
        "",
        (
            f"> 窗口 {config.get('window_hours', 24)} 小时 · 时间线 {stats['total']} · "
            f"显示 {stats['shown']} · T1 {stats['t1']} / T2 {stats['t2']} / T3 {stats['t3']} · "
            f"已收藏 {stats['retained']} · 排除 {stats['excluded']} · 低于阈值 {stats['below']}"
        ),
        "",
        "## 现在看",
        "",
    ]
    if now_items:
        lines.extend(render_item(item) for item in now_items)
    else:
        lines.append("- 今天没有 T1 或 priority 命中。")
    lines.extend(["", "## 今日候选", ""])
    if daily_items:
        lines.extend(render_item(item) for item in daily_items)
    else:
        lines.append("- 今天没有达到阈值的 T2 候选。")
    lines.extend(
        [
            "",
            "## 统计",
            "",
            f"- 时间线：{stats['total']}",
            f"- T1：{stats['t1']}；T2：{stats['t2']}；T3 未进入：{stats['t3']}",
            f"- 已收藏/已拉取：{stats['retained']}",
            f"- 排除词命中：{stats['excluded']}",
            f"- T2 低于阈值：{stats['below']}",
            f"- 批内重复：{stats['duplicate']}；单源上限：{stats['feed_cap']}",
            f"- 已看过（状态账本）：{stats['seen']}",
            "",
            "> 这是决策清单，不是剪藏。值得留的条目请加入 Folo Collection，再由 folo-collection-pull 拉进 11-Clippings。",
            "",
        ]
    )
    return "\n".join(lines)


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
        "folo CLI not found. Install folocli or pass --folo-bin pointing to it."
    )


def load_subscriptions(folo_command: list[str]) -> list[dict]:
    payload = run_json([*folo_command, "subscription", "list"])
    data = payload.get("data") or {}
    raw = data.get("subscriptions") or data.get("items") or []
    subscriptions = []
    for item in raw:
        feed = item.get("feeds") or {}
        subscriptions.append(
            {
                "feedId": item.get("feedId") or feed.get("id"),
                "id": feed.get("id"),
                "url": feed.get("url"),
                "title": feed.get("title"),
                "category": item.get("category"),
                "hideFromTimeline": item.get("hideFromTimeline"),
            }
        )
    return subscriptions


def load_timeline_for_feeds(
    folo_command: list[str],
    subscriptions: list[dict],
    tiers: dict,
    per_feed_limit: int,
    since: datetime,
) -> tuple[list[dict], list[str]]:
    collected: list[dict] = []
    errors: list[str] = []
    for subscription in subscriptions:
        feed_id = str(subscription.get("feedId") or subscription.get("id") or "")
        if not feed_id:
            continue
        if tier_for(subscription, tiers) == "T3":
            continue
        try:
            payload = run_json(
                [
                    *folo_command,
                    "timeline",
                    "--feed",
                    feed_id,
                    "--limit",
                    str(per_feed_limit),
                ]
            )
        except Exception as exc:  # noqa: BLE001 - one broken feed should not stop the digest
            errors.append(f"{subscription.get('title') or feed_id}: {exc}")
            continue
        for wrapper in (payload.get("data") or {}).get("entries") or []:
            published = parse_time((wrapper.get("entries") or {}).get("publishedAt"))
            if published and published < since:
                continue
            collected.append(wrapper)
    return collected, errors


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "updated_at": "", "entries": {}}
    data = load_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        raise RuntimeError(f"state file has an unexpected shape: {path}")
    return data


def update_state(state: dict, processed: list[dict], digest_date: str) -> None:
    entries = state.setdefault("entries", {})
    for item in processed:
        entry_id = item["entry_id"]
        previous = entries.get(entry_id) or {}
        entries[entry_id] = {
            "first_seen": previous.get("first_seen") or digest_date,
            "last_seen": digest_date,
            "status": item["status"],
            "score": item["score"],
            "digest_date": digest_date,
        }
    state["updated_at"] = digest_date


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a daily Folo reading digest.")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Config JSON path.")
    parser.add_argument("--vault-root", default="", help="Override vault root.")
    parser.add_argument("--output-dir", default="", help="Override output directory.")
    parser.add_argument("--state-file", default="", help="Override state file.")
    parser.add_argument("--write", action="store_true", help="Write digest and state.")
    parser.add_argument("--include-seen", action="store_true", help="Ignore seen state.")
    parser.add_argument("--from-json", help="Fixture JSON with subscriptions and entries.")
    parser.add_argument("--folo-bin", default="folo", help="Folo CLI binary name.")
    parser.add_argument("--date", default="", help="Digest date YYYY-MM-DD (default: today).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    config_path = Path(args.config).expanduser()
    if not config_path.exists():
        print(
            f"error: config not found: {config_path}\n"
            f"copy config.example.json to {config_path} and edit tiers/keywords",
            file=sys.stderr,
        )
        return 2
    config = load_json(config_path)
    vault_root = Path(args.vault_root or config.get("vault_root") or "").expanduser()
    if not vault_root:
        print("error: vault_root is required in config or --vault-root", file=sys.stderr)
        return 2
    output_dir = Path(
        args.output_dir or config.get("output_dir") or "10-Inbox"
    ).expanduser()
    if not output_dir.is_absolute():
        output_dir = vault_root / output_dir
    state_path = Path(
        args.state_file or config.get("state_file") or DEFAULT_STATE
    ).expanduser()
    now = datetime.now(timezone.utc)
    if args.date:
        day = date.fromisoformat(args.date)
        now = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)

    try:
        state = load_state(state_path)
    except Exception as exc:  # noqa: BLE001 - do not silently re-score
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.from_json:
        fixture = load_json(Path(args.from_json))
        subscriptions = fixture.get("subscriptions") or []
        entries = fixture.get("entries") or []
    else:
        try:
            folo_command = resolve_folo(args.folo_bin)
            subscriptions = load_subscriptions(folo_command)
            since = now - timedelta(hours=int(config.get("window_hours", 72)))
            entries, errors = load_timeline_for_feeds(
                folo_command,
                subscriptions,
                config.get("tiers") or {},
                int(config.get("per_feed_limit", 20)),
                since,
            )
            for error in errors:
                print(f"WARN feed fetch failed: {error}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - top-level CLI failure
            print(f"error: {exc}", file=sys.stderr)
            return 1

    retained = load_retained(vault_root)
    digest, stats, processed = build_digest(
        entries,
        subscriptions,
        config,
        retained,
        state,
        include_seen=args.include_seen,
        now=now,
    )
    print(digest)
    if not args.write:
        print("Dry run: no digest file written, no state updated.")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    day = now.astimezone().date().isoformat()
    output_path = output_dir / f"{DIGEST_PREFIX}{day}.md"
    output_path.write_text(digest, encoding="utf-8")
    update_state(state, processed, day)
    save_json(state_path, state)
    print(f"WROTE {output_path}")
    print(
        f"Summary: {stats['total']} timeline, {stats['shown']} shown, "
        f"{stats['retained']} retained, {stats['excluded']} excluded, "
        f"{stats['below']} below threshold, {stats['duplicate']} duplicate"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
