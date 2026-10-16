#!/usr/bin/env python3
"""Run bounded packaging and deterministic regressions; no semantic verdict."""
import argparse
import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import time


def validate(root, output):
    root, output = root.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    commands = [("packaging", [sys.executable, "-B", str(root / "delivery-orchestrate/scripts/check_suite.py"),
                                "--skills-root", str(root), "--json"])]
    for name in ("design", "plan", "orchestrate"):
        commands.append((name, [sys.executable, "-B", "-m", "unittest", "discover", "-s",
                                str(root / ("delivery-" + name) / "tests"), "-p", "test_*.py", "-v"]))
    results, stop_reason = [], None
    def captured(value):
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")
    for name, command in commands:
        started = time.monotonic()
        row = {"name": name, "argv": command, "exit_code": None,
               "status": "not-run", "stdout": name + ".stdout.txt", "stderr": name + ".stderr.txt"}
        stdout, stderr = "", ""
        if stop_reason:
            row["reason"] = stop_reason
        else:
            try:
                run = subprocess.run(command, capture_output=True, text=True, timeout=300)
                stdout, stderr = run.stdout, run.stderr
                row.update(exit_code=run.returncode, status="passed" if run.returncode == 0 else "failed")
                if name != "packaging" and run.returncode == 0:
                    count = re.search(r"Ran (\d+) tests? in", stderr)
                    if not count or int(count[1]) == 0:
                        row.update(status="failed", reason="No positive unittest execution count; exit 0 alone is insufficient")
                    else:
                        row["tests_run"] = int(count[1])
            except subprocess.TimeoutExpired as exc:
                stdout, stderr = captured(exc.stdout), captured(exc.stderr)
                row.update(status="timeout", reason="Check timed out; partial output retained")
                stop_reason = "Not executed after an interrupted/timed-out check; start a new evidence run"
            except OSError as exc:
                row.update(status="not-run", reason=str(exc))
                stderr = str(exc)
                stop_reason = "Not executed after process startup failure; restore execution environment"
        (output / row["stdout"]).write_text(stdout, encoding="utf-8")
        (output / row["stderr"]).write_text(stderr, encoding="utf-8")
        row["seconds"] = round(time.monotonic() - started, 3)
        results.append(row)
    report = {"ok": all(r["status"] == "passed" for r in results),
              "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "skills_root": str(root), "checks": results,
              "scope": "Packaging and deterministic tests only; independent semantic review and real agent evaluation are separate."}
    (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Delivery 机械验证", "", report["scope"], "", "| 检查 | 结果 | 原始输出 |", "| --- | --- | --- |"]
    for r in results:
        lines.append(f"| {r['name']} | {r['status']} | [stdout]({r['stdout']}) / [stderr]({r['stderr']}) |")
    for row in results:
        if row.get("reason"):
            lines.extend(["", f"{row['name']}: {row['reason']}"])
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True, help="New evidence directory, outside skill source packages")
    args = parser.parse_args()
    for package in args.skills_root.resolve().glob("delivery-*"):
        if args.output.resolve().is_relative_to(package.resolve()):
            parser.error("evidence output must be outside skill packages")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("output directory must be empty; preserve earlier results")
    try:
        report = validate(args.skills_root, args.output)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
