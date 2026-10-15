#!/usr/bin/env python3
"""Real CLI smoke with explicitly simulated authorization and actor identities.

This file tests CLI/state transitions; it is NOT a real user's product approval,
an independent review, or evidence of the skill's natural-language behavior.
It refuses to overwrite a previous run. Keep the complete directory as evidence.
"""
from pathlib import Path
import datetime
import hashlib
import json
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[4]
ENGINE = REPO / "delivery-orchestrate/scripts/delivery.py"
PROJECT = ROOT / "fixture-project"
WORK = PROJECT / "docs/delivery/2026-10-15-cli-fixture"
LOGS = ROOT / "commands"
PREFIX = "docs/delivery/2026-10-15-cli-fixture/"
transcript = []


def write(relative, text):
    path = PROJECT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def admission(name, data):
    return write(PREFIX + "admission/" + name + ".json", json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def command(name, args, expected=0):
    argv = [sys.executable, "-B", str(ENGINE), *args, "--work", str(WORK)]
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    completed = subprocess.run(argv, cwd=PROJECT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
    number = len(transcript) + 1
    stem = f"{number:02d}-{name}"
    (LOGS / f"{stem}.stdout.json").write_text(completed.stdout)
    (LOGS / f"{stem}.stderr.txt").write_text(completed.stderr)
    record = {"name": name, "argv": argv, "cwd": str(PROJECT), "started_at": started,
              "returncode": completed.returncode, "expected_returncode": expected,
              "stdout": f"commands/{stem}.stdout.json", "stderr": f"commands/{stem}.stderr.txt"}
    transcript.append(record)
    (ROOT / "transcript.json").write_text(json.dumps(transcript, ensure_ascii=False, indent=2) + "\n")
    assert completed.returncode == expected, (name, completed.returncode, completed.stderr)
    return json.loads(completed.stdout if expected == 0 else completed.stderr)


def record(kind, target, report, actor, context, result="passed", **extra):
    return {"schema_version": 1, "contract_version": 1, "skill_revision": "fixture-only; engine-snapshot.sha256 identifies tested executable",
            "kind": kind, "target": target, "actor": {"id": actor, "context": context},
            "report": {"path": PREFIX + report}, "result": result,
            "summary": "SIMULATED capability admission for real CLI state-transition testing; no actual human authorization or independent review is asserted.",
            "evidence": [{"path": "src/app.py"}], **extra}


def main():
    assert ENGINE.is_file(), ENGINE
    if PROJECT.exists() or LOGS.exists() or (ROOT / "transcript.json").exists():
        raise SystemExit("Existing smoke evidence found; choose a new evidence directory instead of overwriting it.")
    PROJECT.mkdir()
    LOGS.mkdir()
    shutil.copyfile(ENGINE, ROOT / "engine-snapshot.py")
    (ROOT / "engine-snapshot.sha256").write_text(hashlib.sha256(ENGINE.read_bytes()).hexdigest() + "  delivery.py\n")
    write("README.md", "# Isolated CLI fixture\n\nAll actors, approvals, reviews and requirements below are SIMULATED TEST INPUTS.\nThis directory is not a production project and contains no real user authorization.\nThe commands and engine transitions are actually executed and retained.\n")
    write("src/app.py", 'def message():\n    return "works"\n')
    write("tests/check.py", 'from pathlib import Path\nimport runpy\nroot = Path.cwd()\napp = runpy.run_path(str(root / "src/app.py"))\nactual = app["message"]()\nassert actual == "works", repr(actual)\nprint("fixture actual function behavior: works")\n')
    write(PREFIX + "plan.md", "# SIMULATED CLI fixture plan\n\nT1 exposes message() returning works. A1 executes the fixture test. R1 covers all T1.\nActor identities and scope approvals are simulated test data, not human decisions.\n")
    write(PREFIX + "authorization.md", "# SIMULATED authorization fixture\n\nSIMULATED fixture authorization: exercise local CLI transitions for T1 only.\nThis text is synthetic input for testing quote binding. It is not a real user message or permission.\n")
    write(PREFIX + "implementation/001.md", "# Fixture implementation input\n\nThe fixture source exposes message() returning works. This is an input record for state-transition testing.\nNo claim is made that a real delivery skill or independent implementer produced it.\n")
    write(PREFIX + "review/001.md", "# SIMULATED review input\n\nThis fixture encodes a passed spec/quality result under a different actor/context to test admission rules.\nIt is not evidence of an actual independent agent review; runtime actor declarations cannot prove independence.\n")
    write(PREFIX + "verification/001.md", "# Fixture verification observation\n\nThe real run will execute tests/check.py and print fixture actual function behavior: works.\nThe driver checks zero exit, stable before/after hashes and exact stdout before submitting this result.\nThis verifies CLI/evidence behavior for a tiny fixture, not the full delivery suite's semantic quality.\n")
    write(PREFIX + "delivery.md", "# Fixture closure\n\nSynthetic implementation/review records and a real command observation exercise close gates.\nThis is a CLI smoke result, not a real user delivery acceptance.\n")
    command("init", ["init", "--project", str(PROJECT), "--title", "SIMULATED CLI smoke", "--op", "init"])
    config = {
        "schema_version": 1, "contract_version": 1,
        "actor": {"id": "fixture-controller", "context": "fixture-control-context"},
        "skill_revision": "fixture-plan-contract-1", "mapping_reason": "SIMULATED explicit mapping for CLI behavior test only.",
        "plan": {"path": PREFIX + "plan.md", "quote": "T1 exposes message() returning works."},
        "authorization": {"path": PREFIX + "authorization.md", "quote": "SIMULATED fixture authorization: exercise local CLI transitions for T1 only.", "scope": "Isolated fixture T1; no real-world authorization is asserted"},
        "tasks": [{"id": "T1", "scope": ["src", "tests"], "depends": []}],
        "reviews": [{"id": "R1", "tasks": ["T1"], "whole": True}],
        "acceptance": [{"id": "A1", "tasks": ["T1"], "required": True, "method": "command",
                        "command": [sys.executable, "-B", "tests/check.py"],
                        "criteria": "Actual message() behavior returns works", "environment": "Isolated local CLI fixture using current Python executable", "waivable": False,
                        "depends": [{"kind": "review", "id": "R1"}]}],
    }
    config_path = admission("configure", config)
    command("configure", ["configure", "--input", str(config_path), "--op", "configure"])
    implementation = admission("implementation", record("implementation", "T1", "implementation/001.md", "fixture-implementer", "fixture-implementation-context"))
    command("implementation", ["record", "--input", str(implementation), "--op", "implementation"])
    review = admission("review", record("review", "R1", "review/001.md", "fixture-reviewer", "fixture-independent-review-context", {"spec": "passed", "quality": "passed"}))
    command("review", ["record", "--input", str(review), "--op", "review"])
    run = command("run", ["run", "--acceptance", "A1", "--actor", "fixture-verifier", "--context", "fixture-verification-context", "--timeout", "10", "--op", "run-A1"])
    assert run["payload"]["exit_code"] == 0
    assert not run["payload"]["timed_out"]
    assert run["payload"]["before"]["hash"] == run["payload"]["after"]["hash"]
    observed = (WORK / "runtime/objects" / run["payload"]["stdout"]["object_hash"]).read_text()
    assert observed == "fixture actual function behavior: works\n", observed
    (ROOT / "observed-run-stdout.txt").write_text(observed)
    verification = admission("verification", record("verification", "A1", "verification/001.md", "fixture-verifier", "fixture-verification-context", run_operation="run-A1"))
    command("verification", ["record", "--input", str(verification), "--op", "verification"])
    before = command("status-before-close", ["status"])
    assert all(before[group][target]["status"] == "passed" for group, target in (("implementation", "T1"), ("review", "R1"), ("verification", "A1")))
    close_request = admission("close", {"schema_version": 1, "contract_version": 1,
        "actor": {"id": "fixture-controller", "context": "fixture-control-context"}, "mode": "complete",
        "summary": "SIMULATED acceptance inputs plus actual local run complete the CLI fixture; not a real production acceptance.",
        "report": {"path": PREFIX + "delivery.md"}, "exceptions": []})
    close = command("close", ["close", "--input", str(close_request), "--op", "close"])
    check = command("check-closed", ["check"])
    assert check["journal_integrity"] == "passed" and check["lifecycle"] == "closed"
    closed = command("status-closed", ["status"])
    assert closed["lifecycle"] == "closed" and closed["closure"]["mode"] == "complete"
    refusal = command("closed-record-rejected", ["record", "--input", str(implementation), "--op", "must-be-rejected"], expected=2)
    assert "closed journal is immutable" in refusal["error"]
    command("reopen", ["reopen", "--reason", "SIMULATED follow-up tests evidence invalidation; retain prior close event", "--op", "reopen"])
    (ROOT / "product-before-mutation.py.txt").write_text((PROJECT / "src/app.py").read_text())
    write("src/app.py", 'def message():\n    return "changed-after-reopen"\n')
    (ROOT / "product-after-mutation.py.txt").write_text((PROJECT / "src/app.py").read_text())
    (ROOT / "mutation.json").write_text(json.dumps({"action": "explicit fixture-only mutation", "path": str(PROJECT / "src/app.py"),
        "reason": "Test that reopened work invalidates prior scope-bound evidence; actual suite product files unchanged."}, indent=2) + "\n")
    after = command("status-after-mutation", ["status"])
    assert after["lifecycle"] == "active"
    assert all(after[group][target]["status"] == "stale" for group, target in (("implementation", "T1"), ("review", "R1"), ("verification", "A1")))
    command("check-after-mutation", ["check"])
    second_close = command("stale-close-rejected", ["close", "--input", str(close_request), "--op", "must-not-reclose"], expected=2)
    assert "must pass" in second_close["error"]
    journal = json.loads((WORK / "runtime/journal.json").read_text())
    original_close = next(e for e in journal["events"] if e["op"] == "close")
    assert original_close == close
    assert not any(e["op"] in ("must-be-rejected", "must-not-reclose") for e in journal["events"])
    assert hashlib.sha256(ENGINE.read_bytes()).hexdigest() == (ROOT / "engine-snapshot.sha256").read_text().split()[0], "Engine changed during smoke"
    summary = {"result": "passed", "executed_commands": len(transcript), "expected_rejections": 2,
               "actual_command_observation": observed.strip(), "closed_record_rejected": True,
               "reopened_product_change_invalidates_implementation_review_verification": True,
               "original_close_event_preserved": True, "actors_and_authorization": "explicitly simulated fixture only",
               "limits": "CLI/state/evidence smoke only; does not establish real independent review, real user authorization, or full semantic skill quality.",
               "engine_sha256": hashlib.sha256(ENGINE.read_bytes()).hexdigest()}
    (ROOT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    (ROOT / "README.md").write_text("# Real CLI smoke evidence\n\n" +
        "This isolated fixture actually executed every CLI command recorded in transcript.json. Synthetic authorization and reviewer identities are explicitly labeled and are not real approvals or independent reviews.\n\n" +
        "Result: passed. Normal init/configure/implementation/review/run/verification/close completed; check/status confirmed closure. A new record while closed was rejected. After explicit reopen and a fixture product change, implementation/review/verification became stale, close was rejected, and the original close event stayed identical.\n\n" +
        "Files: run_smoke.py retains the driver; engine-snapshot.py and SHA bind the tested executable; commands/ retains every stdout/stderr; fixture-project/ retains exact Markdown, JSON, product files and runtime objects. The fixture is intentionally left active with stale results to show invalidation. It is not a pending production task.\n\n" +
        "Do not rerun in place: the driver refuses to overwrite existing evidence. Copy to a fresh evidence directory and adjust the repository locator when replaying elsewhere.\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
