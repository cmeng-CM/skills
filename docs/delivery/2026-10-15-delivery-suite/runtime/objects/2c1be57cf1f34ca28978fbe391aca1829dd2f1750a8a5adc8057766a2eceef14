"""Behavioral regressions for the self-contained, standard-library runtime."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

MODULE = Path(__file__).parents[1] / "scripts" / "delivery.py"
spec = importlib.util.spec_from_file_location("delivery", MODULE)
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)
Engine, Error = delivery.Engine, delivery.DeliveryError


class RuntimeCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve()
        self.work = self.project / "docs/delivery/2026-10-15-example"
        self.work.mkdir(parents=True)
        self.write("src/main.txt", "works\n")
        self.write("docs/plan.md", "Implement T1 and check A1. Approved plan.\n")
        self.write("docs/authorization.md", "User authorized implementation and local commits.\n")
        self.write("docs/report.md", "Actual report and observed evidence.\n")
        self.write("docs/evidence.txt", "Observed expected result.\n")
        self.counter = 0
        self.engine = Engine(self.work)
        self.engine.init(self.project, "example", "init")
        self.config = {
            "schema_version": 1, "contract_version": 1,
            "actor": {"id": "controller", "context": "orchestration"},
            "skill_revision": "source-sha256:example", "mapping_reason": "Read approved plan; map T1 and A1 without changing criteria.",
            "plan": {"path": "docs/plan.md", "quote": "Implement T1"},
            "authorization": {"path": "docs/authorization.md", "quote": "User authorized implementation", "scope": "T1"},
            "tasks": [{"id": "T1", "scope": ["src"], "depends": []}],
            "reviews": [{"id": "R1", "tasks": ["T1"], "whole": True}],
            "acceptance": [{"id": "A1", "tasks": ["T1"], "required": True, "method": "inspection",
                            "criteria": "src/main.txt contains works", "environment": "local temporary fixture", "waivable": False}],
        }

    def write(self, path, content):
        target = self.project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target

    def op(self):
        self.counter += 1
        return f"op-{self.counter}"

    def configure(self, config=None):
        return self.engine.configure(config or self.config, self.op())

    def request(self, kind="implementation", target="T1", result="passed", **extra):
        return {
            "schema_version": 1, "contract_version": 1, "skill_revision": "source-sha256:fixture",
            "kind": kind, "target": target,
            "actor": {"id": "reviewer" if kind == "review" else "builder", "context": "independent" if kind == "review" else "build-session"},
            "report": {"path": "docs/report.md"}, "evidence": [{"path": "docs/evidence.txt"}],
            "result": {"spec": "passed", "quality": "passed"} if kind == "review" and result == "passed" else result,
            "summary": "Read actual source and checked expected behavior.", **extra,
        }

    def record(self, kind="implementation", target="T1", result="passed", **extra):
        return self.engine.record(self.request(kind, target, result, **extra), self.op())

    def implemented(self):
        self.configure()
        return self.record()

    def completed(self):
        self.implemented()
        self.record("review", "R1")
        self.record("verification", "A1")

    def closing(self, mode="complete", exceptions=None):
        return {"schema_version": 1, "contract_version": 1, "actor": {"id": "controller", "context": "orchestration"},
                "mode": mode, "summary": "Checked report and evidence.", "report": {"path": "docs/report.md"},
                "exceptions": exceptions or []}

    def status(self):
        return self.engine.inspect("status")

    def command_config(self, code=None):
        self.config["acceptance"][0].update({"method": "command", "command": [sys.executable, "-c", code or "from pathlib import Path; assert Path('src/main.txt').read_text() == 'works\\n'; print('observed works')"]})

    def execute_run(self, op=None, timeout=5):
        return self.engine.run("A1", {"id": "verifier", "context": "verification"}, timeout, op or self.op())

    def exception(self, issues=None):
        self.write("docs/exception.md", "User accepts A1 online-only limitation and documented risk for this delivery.")
        return {"acceptance": "A1", "scope": "Current A1 online-only delivery", "risk": "Offline behavior unavailable",
                "authorization": {"path": "docs/exception.md", "quote": "User accepts A1 online-only limitation", "by": "user", "role": "human"},
                "issues": issues or []}

    def test_full_inspection_delivery_and_close(self):
        self.completed()
        event = self.engine.close(self.closing(), "close")
        self.assertEqual(event["payload"]["mode"], "complete")
        self.assertEqual(self.status()["lifecycle"], "closed")
        self.assertEqual(self.status()["closure"]["state"]["verification"]["A1"]["status"], "passed")

    def test_command_zero_requires_semantic_verdict(self):
        self.command_config()
        self.implemented()
        run = self.execute_run()
        self.assertEqual(run["payload"]["exit_code"], 0)
        self.assertEqual(self.status()["verification"]["A1"]["status"], "pending")
        self.record("verification", "A1", "failed", run_operation=run["op"])
        self.assertEqual(self.status()["verification"]["A1"]["status"], "failed")
        self.record("review", "R1")
        with self.assertRaises(Error):
            self.engine.close(self.closing(), "close")

    def test_command_end_to_end(self):
        self.command_config()
        self.implemented()
        self.record("review", "R1")
        run = self.execute_run()
        self.record("verification", "A1", run_operation=run["op"])
        self.engine.close(self.closing(), "close")
        stdout = self.work / "runtime/objects" / run["payload"]["stdout"]["object_hash"]
        self.assertIn("observed works", stdout.read_text())

    def test_implementation_is_not_acceptance(self):
        self.implemented()
        self.assertEqual(self.status()["verification"]["A1"]["status"], "pending")
        with self.assertRaises(Error):
            self.engine.close(self.closing(), "close")

    def test_joint_dependency_cycle(self):
        self.config["tasks"][0]["depends"] = [{"kind": "acceptance", "id": "A1"}]
        with self.assertRaisesRegex(Error, "cycle"):
            self.configure()

    def test_review_dependency_cycle(self):
        self.config["reviews"][0]["depends"] = [{"kind": "acceptance", "id": "A1"}]
        self.config["acceptance"][0]["depends"] = [{"kind": "review", "id": "R1"}]
        with self.assertRaisesRegex(Error, "cycle"):
            self.configure()

    def test_missing_required_coverage_rejected(self):
        self.config["acceptance"][0]["required"] = False
        with self.assertRaisesRegex(Error, "coverage"):
            self.configure()

    def test_missing_whole_review_rejected(self):
        self.config["reviews"][0]["whole"] = False
        with self.assertRaisesRegex(Error, "whole review"):
            self.configure()

    def test_independent_review_rejects_same_id(self):
        self.implemented()
        with self.assertRaisesRegex(Error, "participated"):
            self.record("review", "R1", actor={"id": "builder", "context": "another-context"})

    def test_independent_review_rejects_same_context(self):
        self.implemented()
        with self.assertRaisesRegex(Error, "participated"):
            self.record("review", "R1", actor={"id": "another-name", "context": "build-session"})

    def test_independence_covers_all_historical_authors(self):
        self.implemented()
        self.record(actor={"id": "builder2", "context": "build2"})
        with self.assertRaisesRegex(Error, "participated"):
            self.record("review", "R1", actor={"id": "builder", "context": "new-context"})

    def test_new_file_invalidates_results(self):
        self.completed()
        self.write("src/new.txt", "unexpected addition")
        state = self.status()
        self.assertTrue(all(state[group][target]["status"] == "stale" for group, target in (("implementation", "T1"), ("review", "R1"), ("verification", "A1"))))

    def test_deleted_file_invalidates_results(self):
        self.completed()
        (self.project / "src/main.txt").unlink()
        self.assertEqual(self.status()["implementation"]["T1"]["status"], "stale")

    def test_changed_file_invalidates_results(self):
        self.completed()
        self.write("src/main.txt", "changed")
        self.assertEqual(self.status()["verification"]["A1"]["status"], "stale")

    def test_executable_bit_change_invalidates_results(self):
        self.completed()
        source = self.project / "src/main.txt"
        source.chmod(source.stat().st_mode | 0o100)
        self.assertEqual(self.status()["review"]["R1"]["status"], "stale")

    def test_missing_file_scope_detects_creation(self):
        self.config["tasks"][0]["scope"] = ["future.txt"]
        self.implemented()
        self.write("future.txt", "new")
        self.assertEqual(self.status()["implementation"]["T1"]["status"], "stale")

    def test_project_scope_excludes_own_work_and_git(self):
        self.config["tasks"][0]["scope"] = ["."]
        self.implemented()
        self.write(".git/fake", "ignore")
        (self.work / "another-report.md").write_text("not product")
        self.assertEqual(self.status()["implementation"]["T1"]["status"], "passed")

    def test_unrelated_file_does_not_invalidate(self):
        self.completed()
        self.write("unrelated.txt", "unrelated")
        self.assertEqual(self.status()["review"]["R1"]["status"], "passed")

    def test_context_scope_change_invalidates_only_related_review(self):
        self.write("shared-contract.txt", "v1")
        self.config["reviews"][0]["context_scope"] = ["shared-contract.txt"]
        self.completed()
        self.write("shared-contract.txt", "v2")
        state = self.status()
        self.assertEqual(state["implementation"]["T1"]["status"], "passed")
        self.assertEqual(state["review"]["R1"]["status"], "stale")

    def test_report_edit_invalidates_record(self):
        self.completed()
        self.write("docs/report.md", "rewritten as success")
        self.assertEqual(self.status()["review"]["R1"]["status"], "stale")

    def test_evidence_deletion_invalidates_record(self):
        self.completed()
        (self.project / "docs/evidence.txt").unlink()
        self.assertEqual(self.status()["verification"]["A1"]["status"], "stale")

    def test_objects_are_integrity_checked(self):
        event = self.implemented()
        key = event["payload"]["references"]["report"]["object_hash"]
        (self.work / "runtime/objects" / key).write_text("tamper")
        with self.assertRaisesRegex(Error, "corrupted"):
            self.status()

    def test_journal_tampering_is_rejected(self):
        self.implemented()
        path = self.work / "runtime/journal.json"
        journal = json.loads(path.read_text())
        journal["events"][0]["payload"]["title"] = "tamper"
        path.write_text(json.dumps(journal))
        with self.assertRaisesRegex(Error, "hash mismatch"):
            self.status()

    def test_blocking_issue_not_erased_by_empty_pass(self):
        self.implemented()
        original = self.record("review", "R1", {"spec": "passed", "quality": "failed"}, issues=[
            {"id": "F1", "summary": "Incorrect boundary", "severity": "high", "blocking": True, "tasks": ["T1"]}])
        with self.assertRaisesRegex(Error, "blocking"):
            self.record("review", "R1", supersedes=original["op"], reason="claims fixed")

    def test_explicit_evidenced_resolution_closes_original_issue(self):
        self.implemented()
        original = self.record("review", "R1", {"spec": "failed", "quality": "passed"}, issues=[
            {"id": "F1", "summary": "Missing boundary", "severity": "high", "blocking": True, "tasks": ["T1"]}])
        self.write("src/main.txt", "works with corrected boundary\n")
        self.record()
        resolution = self.record("review", "R1", supersedes=original["op"], reason="Rechecked corrected boundary", resolutions=[
            {"id": "F1", "reason": "Observed corrected boundary", "evidence": [{"path": "src/main.txt"}]}])
        self.assertEqual(self.status()["issues"]["F1"]["status"], "resolved")
        self.assertEqual(self.status()["review"]["R1"]["operation_id"], resolution["op"])
        self.assertIn(original["op"], [e["op"] for e in self.engine.data["events"]])

    def test_resolution_becomes_stale_when_fix_changes(self):
        self.implemented()
        original = self.record("review", "R1", {"spec": "failed", "quality": "passed"}, issues=[
            {"id": "F1", "summary": "Boundary", "severity": "high", "blocking": True, "tasks": ["T1"]}])
        self.record("review", "R1", supersedes=original["op"], reason="Observed fix", resolutions=[
            {"id": "F1", "reason": "Evidence", "evidence": [{"path": "src/main.txt"}]}])
        self.write("src/main.txt", "regressed")
        self.assertEqual(self.status()["issues"]["F1"]["status"], "open")

    def test_later_same_baseline_review_preserves_resolution(self):
        self.implemented()
        original = self.record("review", "R1", {"spec": "failed", "quality": "passed"}, issues=[
            {"id": "F1", "summary": "Boundary", "severity": "high", "blocking": True, "tasks": ["T1"]}])
        self.record("review", "R1", supersedes=original["op"], reason="Observed fix", resolutions=[
            {"id": "F1", "reason": "Evidence", "evidence": [{"path": "src/main.txt"}]}])
        self.record("review", "R1")
        self.assertEqual(self.status()["issues"]["F1"]["status"], "resolved")
        self.assertEqual(self.status()["review"]["R1"]["status"], "passed")

    def test_failed_run_cannot_support_pass(self):
        self.command_config("raise SystemExit(3)")
        self.implemented()
        run = self.execute_run()
        with self.assertRaisesRegex(Error, "nonzero"):
            self.record("verification", "A1", run_operation=run["op"])
        self.record("verification", "A1", "failed", run_operation=run["op"])

    def test_replan_cannot_orphan_issue_owner(self):
        self.implemented()
        self.record("review", "R1", {"spec": "failed", "quality": "passed"}, issues=[
            {"id": "F1", "summary": "Boundary", "severity": "high", "blocking": True, "tasks": ["T1"]}])
        config = copy.deepcopy(self.config)
        config["reviews"][0]["id"] = "R2"
        with self.assertRaisesRegex(Error, "cannot remove finding owner"):
            self.configure(config)
        self.assertEqual(self.status()["issues"]["F1"]["owner_target"], "R1")

    def test_replan_keeps_resolution_actionable_after_rebinding(self):
        self.implemented()
        failure = self.record("review", "R1", {"spec": "failed", "quality": "passed"}, issues=[
            {"id": "F1", "summary": "Boundary", "severity": "high", "blocking": True, "tasks": ["T1"]}])
        self.record("review", "R1", supersedes=failure["op"], reason="Fix checked", resolutions=[
            {"id": "F1", "reason": "Evidence", "evidence": [{"path": "src/main.txt"}]}])
        latest = self.record("review", "R1")
        config = copy.deepcopy(self.config)
        implementation = self.status()["implementation"]["T1"]["operation_id"]
        config["reuse"] = [{"operation_id": implementation, "reason": "Unchanged implementation"},
                           {"operation_id": latest["op"], "reason": "Unchanged review and resolution"}]
        self.configure(config)
        self.assertEqual(self.status()["issues"]["F1"]["status"], "resolved")
        self.assertEqual(self.status()["review"]["R1"]["status"], "passed")

    def test_timeout_is_preserved_and_cannot_pass(self):
        self.command_config("import time; print('start', flush=True); time.sleep(3)")
        self.implemented()
        run = self.execute_run(timeout=0.05)
        self.assertTrue(run["payload"]["timed_out"])
        with self.assertRaisesRegex(Error, "timed-out"):
            self.record("verification", "A1", run_operation=run["op"])

    def test_command_modifying_product_cannot_support_pass(self):
        self.command_config("from pathlib import Path; Path('src/main.txt').write_text('changed')")
        self.implemented()
        run = self.execute_run()
        self.record()
        with self.assertRaisesRegex(Error, "changed product"):
            self.record("verification", "A1", run_operation=run["op"])

    def test_command_receipt_required(self):
        self.command_config()
        self.implemented()
        with self.assertRaisesRegex(Error, "actual completed run"):
            self.record("verification", "A1")
        self.record("verification", "A1", "unknown")

    def test_manual_pass_requires_item_specific_human_source(self):
        self.config["acceptance"][0]["method"] = "manual"
        self.implemented()
        with self.assertRaises(Error):
            self.record("verification", "A1")
        self.write("docs/manual.md", "Alice personally checked A1 in the installed app and confirmed it.")
        confirmation = {"path": "docs/manual.md", "quote": "Alice personally checked A1", "acceptance": "A1", "by": "Alice", "role": "human"}
        self.record("verification", "A1", confirmation=confirmation)
        self.assertEqual(self.status()["verification"]["A1"]["status"], "passed")

    def test_manual_wrong_target_and_model_role_rejected(self):
        self.config["acceptance"][0]["method"] = "manual"
        self.implemented()
        for target, role in (("A2", "human"), ("A1", "model")):
            with self.assertRaises(Error):
                self.record("verification", "A1", confirmation={"path": "docs/report.md", "quote": "Actual report", "acceptance": target, "by": "author", "role": role})

    def test_limited_close_preserves_failure(self):
        self.config["acceptance"][0]["waivable"] = True
        self.implemented()
        self.record("review", "R1")
        self.record("verification", "A1", "failed")
        self.engine.close(self.closing("limited", [self.exception()]), "close")
        state = self.status()
        self.assertEqual(state["closure"]["mode"], "limited")
        self.assertEqual(state["verification"]["A1"]["status"], "failed")

    def test_limited_close_cannot_hide_unknown(self):
        self.config["acceptance"][0]["waivable"] = True
        self.implemented()
        self.record("review", "R1")
        self.record("verification", "A1", "unknown")
        with self.assertRaisesRegex(Error, "not unknown"):
            self.engine.close(self.closing("limited", [self.exception()]), "close")

    def test_nonwaivable_failure_cannot_be_excepted(self):
        self.implemented()
        self.record("review", "R1")
        self.record("verification", "A1", "failed")
        with self.assertRaisesRegex(Error, "non-waivable"):
            self.engine.close(self.closing("limited", [self.exception()]), "close")

    def test_blocking_verification_issue_requires_explicit_exception(self):
        self.config["acceptance"][0]["waivable"] = True
        self.implemented()
        self.record("review", "R1")
        self.record("verification", "A1", "failed", issues=[{"id": "F1", "summary": "Offline unavailable", "severity": "medium", "blocking": True, "tasks": ["T1"]}])
        with self.assertRaisesRegex(Error, "unresolved blocking"):
            self.engine.close(self.closing("limited", [self.exception()]), "close")
        self.engine.close(self.closing("limited", [self.exception(["F1"])]), "close2")
        self.assertEqual(self.status()["issues"]["F1"]["status"], "open")

    def test_closed_mutations_rejected_and_reopen_preserves_history(self):
        self.completed()
        closed = self.engine.close(self.closing(), "close")
        with self.assertRaisesRegex(Error, "immutable"):
            self.record()
        self.write("src/main.txt", "later change")
        self.engine.reopen("Explicit continuation after new evidence", "reopen")
        self.assertEqual(self.status()["lifecycle"], "active")
        self.assertEqual(self.status()["implementation"]["T1"]["status"], "stale")
        retained = next(e for e in self.engine.data["events"] if e["op"] == "close")
        self.assertEqual(retained, closed)

    def test_exact_retry_is_idempotent_payload_conflict_rejected(self):
        self.configure()
        request = self.request()
        first = self.engine.record(request, "record-once")
        second = self.engine.record(request, "record-once")
        self.assertEqual(first, second)
        request["summary"] = "different"
        with self.assertRaisesRegex(Error, "different request"):
            self.engine.record(request, "record-once")

    def test_run_retry_does_not_execute_twice(self):
        self.command_config("from pathlib import Path; p=Path('counter'); p.write_text(p.read_text()+'x' if p.exists() else 'x')")
        self.implemented()
        first = self.execute_run("once")
        second = self.execute_run("once")
        self.assertEqual(first, second)
        self.assertEqual((self.project / "counter").read_text(), "x")

    def test_crashed_run_reservation_is_not_reexecuted(self):
        self.command_config("from pathlib import Path; Path('should-not-exist').write_text('x')")
        self.implemented()
        who = {"id": "verifier", "context": "verification"}
        request = {"kind": "run", "acceptance": "A1", "actor": who, "timeout": 5}
        with self.engine.locked():
            key, _ = self.engine.duplicate("reserved", request)
            self.engine.append("run-started", "reserved", key, {"acceptance": "A1"})
        retry = self.execute_run("reserved")
        self.assertEqual(retry["kind"], "run-started")
        self.assertFalse((self.project / "should-not-exist").exists())

    def test_plan_change_requires_explicit_reconfigure(self):
        self.completed()
        self.write("docs/plan.md", "Implement T1 and check A1. New unrelated planning explanation.")
        self.assertEqual(self.status()["configuration"], "stale")
        with self.assertRaisesRegex(Error, "configure"):
            self.record()
        with self.assertRaisesRegex(Error, "configure"):
            self.engine.close(self.closing(), "close")

    def test_explicit_unchanged_readmission_reuses_results(self):
        self.completed()
        old = self.status()
        self.write("docs/plan.md", "Implement T1 and check A1. Wording clarified without changing scope.")
        config = copy.deepcopy(self.config)
        config["reuse"] = [{"operation_id": old[group][target]["operation_id"], "reason": "Checked wording-only change; requirement and product unchanged"}
                           for group, target in (("implementation", "T1"), ("review", "R1"), ("verification", "A1"))]
        self.configure(config)
        self.assertEqual(self.status()["verification"]["A1"]["status"], "passed")
        self.engine.close(self.closing(), "close")

    def test_changed_criterion_cannot_reuse_old_verification(self):
        self.completed()
        old = self.status()["verification"]["A1"]["operation_id"]
        config = copy.deepcopy(self.config)
        config["acceptance"][0]["criteria"] = "new behavior"
        config["reuse"] = [{"operation_id": old, "reason": "claim same"}]
        with self.assertRaisesRegex(Error, "changed task/target"):
            self.configure(config)

    def test_readmission_cannot_select_older_pass_over_new_failure(self):
        self.completed()
        old = self.status()["verification"]["A1"]["operation_id"]
        self.record("verification", "A1", "failed", supersedes=old, reason="New observation exposes failure")
        config = copy.deepcopy(self.config)
        config["reuse"] = [{"operation_id": old, "reason": "Try old favorable result"}]
        with self.assertRaisesRegex(Error, "latest admitted result"):
            self.configure(config)

    def test_changed_environment_cannot_reuse_old_verification(self):
        self.completed()
        old = self.status()["verification"]["A1"]["operation_id"]
        config = copy.deepcopy(self.config)
        config["acceptance"][0]["environment"] = "production"
        config["reuse"] = [{"operation_id": old, "reason": "claim same"}]
        with self.assertRaises(Error):
            self.configure(config)

    def test_changed_product_cannot_be_readmitted(self):
        old = self.implemented()
        self.write("src/main.txt", "different")
        config = copy.deepcopy(self.config)
        config["reuse"] = [{"operation_id": old["op"], "reason": "claim same"}]
        with self.assertRaisesRegex(Error, "stale product"):
            self.configure(config)

    def test_unknown_schema_and_fields_fail_closed(self):
        for field in ("schema_version", "contract_version"):
            config = copy.deepcopy(self.config)
            config[field] = 2
            with self.assertRaisesRegex(Error, "unsupported"):
                self.configure(config)
        config = copy.deepcopy(self.config)
        config["unexpected"] = True
        with self.assertRaisesRegex(Error, "unknown"):
            self.configure(config)

    def test_parent_traversal_and_absolute_scope_rejected(self):
        for path in ("../escape", str(self.project / "src")):
            config = copy.deepcopy(self.config)
            config["tasks"][0]["scope"] = [path]
            with self.assertRaisesRegex(Error, "unsafe"):
                self.configure(config)

    def test_symlink_source_and_product_rejected(self):
        (self.project / "link").symlink_to(self.project / "src", target_is_directory=True)
        self.config["tasks"][0]["scope"] = ["link"]
        with self.assertRaisesRegex(Error, "symlink"):
            self.configure()
        self.config["tasks"][0]["scope"] = ["src"]
        self.configure()
        (self.project / "src/link").symlink_to(self.project / "docs/report.md")
        with self.assertRaisesRegex(Error, "symlink"):
            self.record()

    def test_git_and_work_product_scopes_rejected(self):
        for path in (".git", self.work.relative_to(self.project).as_posix()):
            self.config["tasks"][0]["scope"] = [path]
            with self.assertRaises(Error):
                self.configure()

    def test_quoted_authorization_must_exist(self):
        self.config["authorization"]["quote"] = "fabricated text"
        with self.assertRaisesRegex(Error, "quoted"):
            self.configure()

    def test_typed_dependency_requires_review_before_next_task(self):
        self.write("second/file", "second")
        self.config["tasks"].append({"id": "T2", "scope": ["second"], "depends": [{"kind": "review", "id": "R1"}]})
        self.config["reviews"][0]["whole"] = False
        self.config["reviews"].append({"id": "R2", "tasks": ["T1", "T2"], "whole": True})
        self.config["acceptance"][0]["tasks"] = ["T1", "T2"]
        self.implemented()
        with self.assertRaisesRegex(Error, "prerequisite"):
            self.record("implementation", "T2")
        self.record("review", "R1")
        self.record("implementation", "T2")
        self.write("src/main.txt", "T1 changed")
        state = self.status()
        self.assertEqual(state["implementation"]["T2"]["status"], "blocked")

    def test_check_does_not_claim_semantic_pass(self):
        self.implemented()
        result = self.engine.inspect("check")
        self.assertIn("does not establish semantic", result["note"])

    def test_cli_returns_nonzero_on_rejected_input(self):
        request = self.project / "bad.json"
        request.write_text('{"schema_version": 999}')
        result = subprocess.run([sys.executable, str(MODULE), "configure", "--work", str(self.work), "--op", "bad", "--input", str(request)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("error", json.loads(result.stderr))

    def test_two_processes_same_run_operation_execute_once(self):
        self.command_config("from pathlib import Path; import time; time.sleep(0.05); p=Path('counter'); p.write_text(p.read_text()+'x' if p.exists() else 'x')")
        self.implemented()
        command = [sys.executable, "-B", str(MODULE), "run", "--work", str(self.work), "--acceptance", "A1",
                   "--actor", "verifier", "--context", "verification", "--timeout", "5", "--op", "concurrent"]
        first = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        second = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        one, one_error = first.communicate(timeout=10)
        two, two_error = second.communicate(timeout=10)
        self.assertEqual(first.returncode, 0, one_error)
        self.assertEqual(second.returncode, 0, two_error)
        self.assertEqual(json.loads(one), json.loads(two))
        self.assertEqual((self.project / "counter").read_text(), "x")

    def test_incomplete_run_is_visible_in_status(self):
        self.command_config()
        self.implemented()
        with self.engine.locked():
            key, _ = self.engine.duplicate("reserved", {"kind": "test-run-reservation"})
            self.engine.append("run-started", "reserved", key, {"acceptance": "A1"})
        self.assertEqual(self.status()["runs"]["reserved"]["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
