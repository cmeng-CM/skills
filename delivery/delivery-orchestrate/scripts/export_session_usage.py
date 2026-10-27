#!/usr/bin/env python3
"""Export request-level model usage from a local session database.

Usage:
  python3 -B export_session_usage.py --source zcode [--db PATH]
      [--sessions ID ...] [--since ISO8601] [--until ISO8601] [--output PATH]

v1 supports the ZCode session database (default ~/.zcode/cli/db/db.sqlite,
table model_usage). Claude Code / Codex stores are future extensions and
fail fast with a clear message.

CSV columns match collect_metrics.py input expectations:
session_id,turn_id,started_at,model_id,input_tokens,output_tokens,
cache_read_input_tokens,cache_creation_input_tokens,duration_ms

started_at stays as epoch milliseconds. input_tokens includes
cache_read_input_tokens; the collector derives uncached. The database is
opened read-only (mode=ro); missing file or table exits 2 with the reason.
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

FIELDS = [
    "session_id", "turn_id", "started_at", "model_id", "input_tokens",
    "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
    "duration_ms",
]

DEFAULT_ZCODE_DB = Path.home() / ".zcode" / "cli" / "db" / "db.sqlite"


def local_epoch_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return int(parsed.timestamp() * 1000)


def export(db_path: Path, sessions, since_ms, until_ms):
    uri = f"file:{db_path}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        rows = connection.execute(
            "SELECT session_id, turn_id, started_at, model_id, input_tokens, "
            "output_tokens, cache_read_input_tokens, "
            "cache_creation_input_tokens, duration_ms FROM model_usage"
        ).fetchall()
    finally:
        connection.close()
    result = []
    for row in rows:
        if sessions and row[0] not in sessions:
            continue
        if since_ms is not None and row[2] < since_ms:
            continue
        if until_ms is not None and row[2] > until_ms:
            continue
        result.append(row)
    result.sort(key=lambda r: (r[2], r[0]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default="zcode", choices=["zcode"],
                        help="usage store; zcode v1, others fail fast as future work")
    parser.add_argument("--db", type=Path, default=DEFAULT_ZCODE_DB,
                        help="session database path (default %(default)s)")
    parser.add_argument("--sessions", nargs="+", default=None,
                        help="only export these session ids")
    parser.add_argument("--since", default=None,
                        help="ISO8601 lower bound on started_at (local when no offset)")
    parser.add_argument("--until", default=None,
                        help="ISO8601 upper bound on started_at (local when no offset)")
    parser.add_argument("--output", default="-",
                        help="CSV output path, '-' for stdout (default stdout)")
    args = parser.parse_args()

    if not args.db.is_file():
        print(f"session database not found: {args.db}", file=sys.stderr)
        return 2
    try:
        since_ms = local_epoch_ms(args.since) if args.since else None
        until_ms = local_epoch_ms(args.until) if args.until else None
        rows = export(args.db, set(args.sessions or []), since_ms, until_ms)
    except (sqlite3.Error, ValueError) as exc:
        print(f"usage export failed: {exc}", file=sys.stderr)
        return 2

    if args.output == "-":
        writer = csv.writer(sys.stdout)
        writer.writerow(FIELDS)
        writer.writerows(rows)
    else:
        with open(args.output, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(FIELDS)
            writer.writerows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
