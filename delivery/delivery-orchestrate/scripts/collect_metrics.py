#!/usr/bin/env python3
"""Generate a minimal delivery metrics summary.

Usage:
  python3 -B collect_metrics.py --work WORK --usage usage.csv --output metrics --price price.csv

The usage CSV is request-level and should contain at least:
session_id, model_id, input_tokens, output_tokens, cache_read_input_tokens,
cache_creation_input_tokens, duration_ms.

input_tokens is assumed to include cache_read_input_tokens. Cost is calculated
only when every request has a matching price row; otherwise cost is null.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def number(value):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_prices(path):
    if not path:
        return {}
    prices = {}
    for row in read_csv(path):
        model = (row.get("model_id") or "").strip()
        if not model:
            continue
        prices[model] = {
            "input": float(row.get("input_per_mtok") or 0),
            "output": float(row.get("output_per_mtok") or 0),
            "cache_read": float(row.get("cache_read_per_mtok") or 0),
            "cache_write": float(row.get("cache_write_per_mtok") or 0),
        }
    return prices


def summarize_usage(path, prices):
    rows = read_csv(path)
    sessions = defaultdict(lambda: {"requests": 0, "input_tokens": 0, "uncached_input_tokens": 0,
                                    "cache_read_tokens": 0, "cache_write_tokens": 0,
                                    "output_tokens": 0, "duration_ms": 0, "cost": None})
    total = {"requests": 0, "input_tokens": 0, "uncached_input_tokens": 0,
             "cache_read_tokens": 0, "cache_write_tokens": 0, "output_tokens": 0,
             "duration_ms": 0, "cost": 0.0, "priced_requests": 0}
    for row in rows:
        session = row.get("session_id") or "(unknown)"
        inputs = number(row.get("input_tokens"))
        cache_read = number(row.get("cache_read_input_tokens"))
        cache_write = number(row.get("cache_creation_input_tokens"))
        output = number(row.get("output_tokens"))
        uncached = max(inputs - cache_read, 0)
        duration = number(row.get("duration_ms"))
        values = {"requests": 1, "input_tokens": inputs, "uncached_input_tokens": uncached,
                  "cache_read_tokens": cache_read, "cache_write_tokens": cache_write,
                  "output_tokens": output, "duration_ms": duration}
        for key, value in values.items():
            sessions[session][key] += value
            total[key] += value
        price = prices.get(row.get("model_id") or "")
        if price:
            cost = (uncached * price["input"] + cache_read * price["cache_read"]
                    + cache_write * price["cache_write"] + output * price["output"]) / 1_000_000
            sessions[session]["cost"] = (sessions[session]["cost"] or 0.0) + cost
            total["cost"] += cost
            total["priced_requests"] += 1
    if total["priced_requests"] != total["requests"]:
        total["cost"] = None
        for value in sessions.values():
            value["cost"] = None
    return total, dict(sessions)


def journal_summary(path):
    if not path:
        return None
    journal = Path(path) / "runtime" / "journal.json"
    if not journal.is_file():
        return None
    data = json.loads(journal.read_text())
    events = data.get("events", [])
    if not events:
        return {"events": 0}
    first = events[0]["at"]
    last = events[-1]["at"]
    def parse(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    try:
        wall_min = (parse(last) - parse(first)).total_seconds() / 60
    except ValueError:
        wall_min = None
    kinds = defaultdict(int)
    gates = defaultdict(int)
    records = defaultdict(int)
    for event in events:
        kinds[event.get("kind", "?")] += 1
        payload = event.get("payload") or {}
        if event.get("kind") == "gate":
            gates[payload.get("kind", "?")] += 1
        if event.get("kind") == "record":
            records[payload.get("kind", "?")] += 1
    return {"events": len(events), "first_at": first, "last_at": last,
            "wall_min": round(wall_min, 2) if wall_min is not None else None,
            "kinds": dict(kinds), "gates": dict(gates), "records": dict(records)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work")
    parser.add_argument("--usage", required=True)
    parser.add_argument("--price")
    parser.add_argument("--output", default="metrics")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    total, sessions = summarize_usage(args.usage, load_prices(args.price))
    by_session = output / "usage_by_session.csv"
    fields = ["session_id", "requests", "input_tokens", "uncached_input_tokens",
              "cache_read_tokens", "cache_write_tokens", "output_tokens", "duration_ms", "cost"]
    with by_session.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for session, row in sorted(sessions.items()):
            writer.writerow({"session_id": session, **row})
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "usage": total,
        "journal": journal_summary(args.work),
        "cost_note": "cost is null unless every request has a matching price row",
        "files": [str(by_session)],
    }
    (output / "metrics_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
