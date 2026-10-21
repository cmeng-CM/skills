"""Actual v2 gate, inventory, source and recovery boundary regressions."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import delivery
from delivery_v2 import EngineV2


class V2Case(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve()
        self.work = self.project / ".delivery/example"
        self.work.mkdir(parents=True)
        self.counter = 0
        self.write("src/main.txt", "works\n")
        self.write("plan.md", "T1 delivers persistence; A1 observes actual consumer.\n")
        self.write("authorization.md", "User authorizes T1 implementation and local commits, no push.\n")
        self.write(".delivery/example/report.md", "Real activity report, trigger and observed result.\n")
        self.write(".delivery/example/evidence.txt", "Observed required behavior, actual evidence.\n")
        self.write(".delivery/example/closeout.md", "Complete delivery evidence and residual risk.\n")
        self.engine = EngineV2(self.work)
        self.engine.init(self.project, "v2 fixture", "init")
        self.builder = {"id": "builder", "context": "implementation"}
        self.reviewer = {"id": "reviewer", "context": "independent-review"}
        self.verifier = {"id": "verifier", "context": "verification"}
        self.controller = {"id": "coordinator", "context": "control"}
        root = SCRIPTS.parents[1]
        self.config = {"schema_version": 2, "contract_version": 2, "actor": self.controller,
            "plan": {"path": "plan.md", "quote": "T1 delivers persistence"},
            "authorization": {"path": "authorization.md", "quote": "User authorizes T1", "scope": "T1"},
            "mapping_reason": "Read complete source and map actual consumer to required acceptance.",
            "tasks": [{"id": "T1", "scope": ["src"], "depends": []}],
            "reviews": [{"id": "R1", "tasks": ["T1"], "whole": True}],
            "acceptance": [{"id": "A1", "tasks": ["T1"], "required": True, "method": "inspection", "criteria": "Actual consumer observes works", "environment": "isolated fixture"}],
            "source_authors": {"plan": [{"id": "planner", "context": "planning"}], "mapping": [self.controller]},
            "requirements": [{"id": "REQ1", "source": {"path": "plan.md", "quote": "actual consumer"}, "tasks": ["T1"], "acceptance": ["A1"]}],
            "admission_policy": {"plan_review": True, "design_review": False, "reason": "Large initial task", "scale": "large", "significant_replan": False},
            "change": {"category": "initial", "reason": "Initial approved work"},
            "monitor": {"roots": ["."], "exclude": []},
            "skill_sources": [{"name": "delivery-" + name, "root": str(root / ("delivery-" + name)), "contract_version": 2 if name == "orchestrate" else 1} for name in ("orchestrate", "design", "plan", "implement", "review", "verify")]}

    def write(self, path, content):
        p = self.project / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def op(self):
        self.counter += 1
        return f"op-{self.counter}"

    def extra(self, **values):
        return {"schema_version": 2, "contract_version": 2, "actor": self.reviewer, **values}

    def report(self):
        return {"report": {"path": ".delivery/example/report.md"}, "evidence": [{"path": ".delivery/example/evidence.txt"}]}

    def configure(self):
        self.configuration = self.engine.configure(self.config, self.op())
        return self.configuration

    def gate(self, kind, **changes):
        return self.engine.gate(self.extra(config_operation=self.configuration["op"], kind=kind, result="passed", summary="Independent source and mapping review.", **self.report(), **changes), self.op())

    def admitted(self):
        self.configure()
        self.gate("plan_review")
        self.gate("mapping_review")

    def claim(self, kind, target, who, action="claim"):
        config = self.engine.current_config(False)
        resources = self.engine.required_resources(config, kind, target)
        return self.engine.resource(self.extra(actor=who, action=action, resources=resources, reason="Explicit activity ownership/return."), self.op())

    def record(self, kind="implementation", target="T1", result="passed", claim=True, **changes):
        who = {"implementation": self.builder, "review": self.reviewer, "verification": self.verifier}[kind]
        if claim:
            self.claim(kind, target, who)
        request = self.extra(actor=who, kind=kind, target=target, result={"spec": "passed", "quality": "passed"} if kind == "review" and result == "passed" else result, summary="Read actual requirements, product and evidence.", **self.report())
        request.update(changes)
        try:
            return self.engine.record(request, self.op())
        finally:
            if claim:
                self.claim(kind, target, who, "release")

    def completed(self):
        self.admitted()
        self.record()
        self.record("review", "R1")
        self.record("verification", "A1")

    def closing(self, mode="complete"):
        return self.extra(actor=self.controller, mode=mode, summary="Current complete delivery evidence.",
                          report={"path": ".delivery/example/closeout.md"}, exceptions=[])

    def command(self, code=None):
        self.config["acceptance"][0].update(method="command", command=[sys.executable, "-c", code or "from pathlib import Path; assert Path('src/main.txt').read_text() == 'works\\n'; print('observed actual consumer')"])

    def implement_and_review(self):
        self.admitted()
        self.record()
        self.record("review", "R1")

    def execute_run(self, op=None):
        self.claim("verification", "A1", self.verifier)
        try:
            return self.engine.run("A1", self.verifier, 5, op or self.op())
        finally:
            self.claim("verification", "A1", self.verifier, "release")

    def status(self):
        return self.engine.inspect("status")

    def test_full_real_command_delivery_and_close(self):
        self.command()
        self.implement_and_review()
        run = self.execute_run()
        self.assertEqual(run["payload"]["exit_code"], 0)
        self.record("verification", "A1", run_operation=run["op"])
        event = self.engine.close(self.closing(), self.op())
        self.assertEqual(event["payload"]["mode"], "complete")
        self.assertEqual(self.status()["lifecycle"], "closed")

    def test_agent_session_and_dual_task_status(self):
        self.admitted()
        self.record(agent_session="sess-T1")
        event = next(e for e in self.engine.data["events"] if e["kind"] == "record")
        self.assertEqual(event["payload"]["agent_session"], "sess-T1")
        state = self.status()
        self.assertEqual(state["implementation"]["T1"]["implementation_status"], "passed")
        self.assertEqual(state["implementation"]["T1"]["acceptance_status"], "pending")
        self.record("verification", "A1")
        state = self.status()
        self.assertEqual(state["implementation"]["T1"]["acceptance_status"], "passed")

    def test_all_execution_entrypoints_block_without_gates(self):
        self.command()
        self.configure()
        with self.assertRaisesRegex(delivery.DeliveryError, "admission gate"):
            self.record(claim=False)
        with self.assertRaisesRegex(delivery.DeliveryError, "admission gate"):
            self.engine.run("A1", self.verifier, 5, self.op())
        with self.assertRaisesRegex(delivery.DeliveryError, "admission gate"):
            self.engine.close(self.closing("limited"), self.op())
        self.assertFalse(self.engine.inspect("next")["ready"])

    def test_large_task_cannot_disable_plan_gate(self):
        self.config["admission_policy"]["plan_review"] = False
        with self.assertRaisesRegex(delivery.DeliveryError, "requires independent plan"):
            self.configure()

    def test_gate_source_author_and_same_context_rejected(self):
        self.configure()
        for who in (self.controller, {"id": "other", "context": "planning"}):
            with self.assertRaisesRegex(delivery.DeliveryError, "source author"):
                self.engine.gate(self.extra(actor=who, config_operation=self.configuration["op"], kind="mapping_review", result="passed", summary="review", **self.report()), self.op())

    def test_gate_latest_failure_and_mutated_report_block(self):
        self.admitted()
        req = self.extra(config_operation=self.configuration["op"], kind="mapping_review", result="failed", summary="Found missing consumer requirement", **self.report())
        self.engine.gate(req, self.op())
        with self.assertRaisesRegex(delivery.DeliveryError, "admission gate"):
            self.record(claim=False)
        self.gate("mapping_review")
        self.write(".delivery/example/report.md", "Changed after gate")
        self.assertEqual(self.status()["admission"]["mapping_review"]["status"], "stale")

    def test_missing_requirement_mapping_is_rejected(self):
        self.config["requirements"][0]["acceptance"] = ["missing"]
        with self.assertRaises(delivery.DeliveryError):
            self.configure()

    def test_v2_rejects_v1_and_handwritten_skill_revision(self):
        self.config["skill_revision"] = "claimed-pin"
        with self.assertRaisesRegex(delivery.DeliveryError, "unknown"):
            self.configure()
        self.config.pop("skill_revision")
        self.config["schema_version"] = 1
        with self.assertRaisesRegex(delivery.DeliveryError, "v2 work"):
            self.configure()

    def test_work_reports_do_not_trigger_monitor(self):
        self.admitted()
        self.write(".delivery/example/new-report.md", "more evidence")
        self.assertFalse(self.status()["unassessed_changes"])

    def test_exclusion_protects_real_product_and_source(self):
        for path in ("src", "plan.md", ".delivery"):
            self.config["monitor"]["exclude"] = [{"path": path, "reason": "cannot hide true source"}]
            with self.assertRaisesRegex(delivery.DeliveryError, "exclusion overlaps"):
                self.configure()

    def test_explicit_other_run_generated_exclusion_is_allowed(self):
        self.config["monitor"]["exclude"] = [{"path": ".delivery/isolated-eval", "reason": "Other isolated evaluation derived outputs only"}]
        self.admitted()
        self.write(".delivery/isolated-eval/result.md", "generated")
        # The .delivery parent already exists because current work is there.
        self.assertFalse(self.status()["unassessed_changes"])

    def impact(self, effect, targets):
        status = self.status()
        return self.engine.impact(self.extra(config_operation=self.configuration["op"], change_set_hash=status["change_set_hash"], decisions=[{"paths": [c["path"] for c in status["unassessed_changes"]], "effect": effect, "targets": targets, "reason": "Read actual consumer dependency and change."}], **self.report()), self.op())

    def test_outside_change_requires_judgement_and_related_invalidates(self):
        self.completed()
        self.write("shared.cfg", "behavior changed")
        with self.assertRaisesRegex(delivery.DeliveryError, "outside changes"):
            self.engine.close(self.closing(), self.op())
        self.impact("related", [{"kind": "implementation", "id": "T1"}])
        state = self.status()
        self.assertEqual(state["implementation"]["T1"]["status"], "stale")
        self.assertEqual(state["review"]["R1"]["status"], "stale")
        self.record()
        self.record("review", "R1")
        self.record("verification", "A1")
        self.engine.close(self.closing(), self.op())

    def test_unrelated_change_preserves_evidence_and_reedit_needs_judgement(self):
        self.completed()
        self.write("notes.txt", "unrelated")
        self.impact("unrelated", [])
        self.assertEqual(self.status()["verification"]["A1"]["status"], "passed")
        self.write("notes.txt", "changed again")
        self.assertTrue(self.status()["unassessed_changes"])

    def test_stale_impact_hash_rejected(self):
        self.admitted()
        self.write("shared.cfg", "first")
        old = self.status()
        self.write("shared.cfg", "second")
        with self.assertRaisesRegex(delivery.DeliveryError, "stale"):
            self.engine.impact(self.extra(config_operation=self.configuration["op"], change_set_hash=old["change_set_hash"], decisions=[], **self.report()), self.op())

    def test_unsupported_fifo_does_not_open_or_hang_and_is_recoverable(self):
        os.mkfifo(self.project / "fixture.pipe")
        self.admitted()
        self.assertEqual(self.status()["unsupported_entries"][0]["type"], "unsupported")
        with self.assertRaisesRegex(delivery.DeliveryError, "unsupported"):
            self.record(claim=False)
        (self.project / "fixture.pipe").unlink()
        self.impact("unrelated", [])
        self.record()

    def test_symlink_monitor_does_not_follow_outside_tree(self):
        (self.project / "outside-link").symlink_to("/private/tmp")
        self.admitted()
        self.assertFalse(self.status()["unsupported_entries"])
        self.assertFalse(self.status()["unassessed_changes"])

    def test_actual_execution_package_cannot_declare_different_A(self):
        import shutil
        copied = self.work / "fake-orchestrate"
        shutil.copytree(SCRIPTS.parent, copied)
        self.config["skill_sources"][0]["root"] = str(copied)
        with self.assertRaisesRegex(delivery.DeliveryError, "actually executing"):
            self.configure()

    def test_professional_drift_blocks_only_relevant_activity(self):
        import shutil
        root = self.work / "implement-copy"
        shutil.copytree(SCRIPTS.parents[1] / "delivery-implement", root)
        next(s for s in self.config["skill_sources"] if s["name"] == "delivery-implement")["root"] = str(root)
        self.admitted()
        (root / "SKILL.md").write_text((root / "SKILL.md").read_text() + "\nChanged instruction\n")
        self.assertIn("delivery-implement", [d["name"] for d in self.status()["skill_drift"]])
        with self.assertRaisesRegex(delivery.DeliveryError, "source drift"):
            self.record(claim=False)

    def test_source_restore_is_byte_exact_and_refuses_overwrite(self):
        self.admitted()
        result = self.engine.source("delivery-orchestrate", ".delivery/example/restored")
        for entry in self.engine.effective_pins(self.engine.current_config(False))["delivery-orchestrate"]["files"]:
            restored = self.project / result["destination"] / entry["relative_path"]
            self.assertEqual(delivery.digest(restored.read_bytes()), entry["object_hash"])
        with self.assertRaisesRegex(delivery.DeliveryError, "new directory"):
            self.engine.source("delivery-orchestrate", ".delivery/example/restored")

    def test_resource_conflict_and_readers_then_close_without_implementation_lock(self):
        self.admitted()
        self.claim("implementation", "T1", self.builder)
        with self.assertRaisesRegex(delivery.DeliveryError, "resource conflict"):
            self.claim("review", "R1", self.reviewer)
        self.claim("implementation", "T1", self.builder, "release")
        self.record()
        self.claim("review", "R1", self.reviewer)
        self.claim("verification", "A1", self.verifier)
        self.record("review", "R1", claim=False)
        self.record("verification", "A1", claim=False)
        self.engine.close(self.closing(), self.op())

    def test_implementation_without_resource_cannot_be_admitted(self):
        self.admitted()
        with self.assertRaisesRegex(delivery.DeliveryError, "owned resource"):
            self.record(claim=False)

    def unknown(self):
        self.command()
        self.implement_and_review()
        self.claim("verification", "A1", self.verifier)
        with self.engine.locked():
            config = self.engine.current_config()
            item = config["payload"]["spec"]["acceptance"][0]
            before = self.engine.snapshot(["src"])
            self.engine.append("run-started", "interrupted", delivery.digest(b"reservation"), {"acceptance": "A1", "tasks": ["T1"], "config_op": config["op"], "command": item["command"], "actor": self.verifier, "before": before})
        self.claim("verification", "A1", self.verifier, "release")

    def resolve(self):
        self.write(".delivery/example/investigation.md", "Investigated interrupted process and side effects, stopped process, safe repeat.")
        self.write(".delivery/example/investigation.txt", "Actual process and side-effect observations.")
        return self.engine.resolve_run(self.extra(run_operation="interrupted", decision="safe_to_retry", reason="Checked process is stopped, actual side effects isolated; rerun is safe.", report={"path": ".delivery/example/investigation.md"}, evidence=[{"path": ".delivery/example/investigation.txt"}]), self.op())

    def test_release_does_not_unlock_unknown_run(self):
        self.unknown()
        with self.assertRaisesRegex(delivery.DeliveryError, "resolve-run"):
            self.execute_run()
        with self.assertRaisesRegex(delivery.DeliveryError, "resolve-run"):
            self.engine.close(self.closing(), self.op())

    def test_evidenced_resolution_then_replacement_and_verdict_allows_close(self):
        self.unknown()
        resolution = self.resolve()
        with self.assertRaisesRegex(delivery.DeliveryError, "replacement run"):
            self.engine.close(self.closing(), self.op())
        run = self.execute_run()
        self.assertEqual(run["payload"]["recovery_operation"], resolution["op"])
        self.record("verification", "A1", run_operation=run["op"])
        self.engine.close(self.closing(), self.op())
        self.assertEqual(self.status()["runs"]["interrupted"]["status"], "incomplete")

    def test_resolution_evidence_change_reblocks(self):
        self.unknown()
        self.resolve()
        self.write(".delivery/example/investigation.txt", "Changed investigation evidence")
        with self.assertRaises(delivery.DeliveryError):
            self.execute_run()

    def test_identical_failures_need_new_diagnosis_not_waiver(self):
        self.admitted()
        request = self.extra(config_operation=self.configuration["op"], target={"kind": "implementation", "id": "T1"}, failure_key="F-root", facts=self.report()["evidence"], strategy="Same unchanged repair", outcome="failed", report=self.report()["report"])
        self.engine.attempt(request, self.op())
        self.engine.attempt(request, self.op())
        with self.assertRaisesRegex(delivery.DeliveryError, "diagnosis"):
            self.record(claim=False)
        request["strategy"] = "Inspect actual consumer rather than repeat prior repair"
        request["outcome"] = "changed"
        self.engine.attempt(request, self.op())
        self.record()

    def test_configure_full_v2_request_is_bound_to_operation_id(self):
        op = self.op()
        first = self.engine.configure(self.config, op)
        self.assertEqual(first, self.engine.configure(self.config, op))
        changed = copy.deepcopy(self.config)
        changed["admission_policy"]["reason"] = "Changed v2-only field"
        with self.assertRaisesRegex(delivery.DeliveryError, "different request"):
            self.engine.configure(changed, op)

    def test_required_acceptance_weakening_is_material_not_local(self):
        self.admitted()
        self.config["change"] = {"category": "within_grant", "reason": "claimed local", "previous_config": self.configuration["op"]}
        self.config["acceptance"][0]["waivable"] = True
        with self.assertRaisesRegex(delivery.DeliveryError, "weakening"):
            self.configure()

    def test_existing_user_staged_content_is_protected(self):
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.write("user.txt", "user staged bytes")
        subprocess.run(["git", "-C", str(self.project), "add", "--", "user.txt"], check=True)
        self.admitted()
        self.record()
        before = subprocess.check_output(["git", "-C", str(self.project), "show", ":user.txt"])
        self.assertEqual(before, b"user staged bytes")
        self.write("user.txt", "unauthorized index replacement")
        subprocess.run(["git", "-C", str(self.project), "add", "--", "user.txt"], check=True)
        self.impact("unrelated", [])
        with self.assertRaisesRegex(delivery.DeliveryError, "staged entry"):
            self.record()

    def test_latest_failed_run_cannot_be_hidden_by_older_pass(self):
        self.command("from pathlib import Path; import sys; sys.exit(1 if Path('.delivery/example/fail.flag').exists() else 0)")
        self.implement_and_review()
        good = self.execute_run()
        self.record("verification", "A1", run_operation=good["op"])
        self.write(".delivery/example/fail.flag", "trigger actual failure")
        bad = self.execute_run()
        self.assertEqual(bad["payload"]["exit_code"], 1)
        self.assertEqual(self.status()["verification"]["A1"]["status"], "stale")
        with self.assertRaisesRegex(delivery.DeliveryError, "latest actual run"):
            self.record("verification", "A1", run_operation=good["op"])

    def test_resource_can_be_returned_by_same_identity_new_recovery_context(self):
        self.admitted()
        self.claim("implementation", "T1", self.builder)
        returning = {"id": self.builder["id"], "context": "fresh-recovery-session"}
        self.claim("implementation", "T1", returning, "release")
        self.assertFalse(self.status()["resources"])

    def test_compatible_source_update_and_expired_review_reblocks_new_records(self):
        import shutil
        root = self.work / "implement-copy"
        shutil.copytree(SCRIPTS.parents[1] / "delivery-implement", root)
        next(s for s in self.config["skill_sources"] if s["name"] == "delivery-implement")["root"] = str(root)
        self.admitted()
        old = self.engine.effective_pins(self.engine.current_config(False))["delivery-implement"]
        (root / "SKILL.md").write_text((root / "SKILL.md").read_text() + "\nCompatible explanation-only clarification.\n")
        self.write(".delivery/example/source-update.md", "Independent compatibility review of actual diff and behaviors.")
        self.write(".delivery/example/source-update.txt", "Observed unchanged professional interface and quality gates.")
        self.engine.source_update(self.extra(config_operation=self.configuration["op"], name="delivery-implement", old_tree_hash=old["tree_hash"], new_root=str(root), decision="compatible", reason="Independent inspection of actual source diff and behavioral cases.", affected_targets=[], report={"path": ".delivery/example/source-update.md"}, evidence=[{"path": ".delivery/example/source-update.txt"}]), self.op())
        self.record()
        self.write(".delivery/example/source-update.txt", "Changed compatibility evidence")
        self.assertEqual(self.status()["implementation"]["T1"]["status"], "stale")
        with self.assertRaisesRegex(delivery.DeliveryError, "source drift"):
            self.record(claim=False)

    def test_actual_inflight_cli_releases_journal_lock_and_duplicate_does_not_rerun(self):
        import signal
        self.command("from pathlib import Path; import os,time; Path('.delivery/example/child.pid').write_text(str(os.getpid())); time.sleep(5)")
        self.implement_and_review()
        self.claim("verification", "A1", self.verifier)
        argv = [sys.executable, "-B", str(SCRIPTS / "delivery.py"), "run", "--work", str(self.work), "--acceptance", "A1", "--actor", self.verifier["id"], "--context", self.verifier["context"], "--timeout", "8", "--op", "real-interrupted"]
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        marker = self.work / "child.pid"
        deadline = time.monotonic() + 5
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        try:
            self.assertTrue(marker.exists(), "real command must actually start")
            checked = subprocess.run([sys.executable, "-B", str(SCRIPTS / "delivery.py"), "status", "--work", str(self.work)], capture_output=True, text=True, timeout=2)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(json.loads(checked.stdout)["runs"]["real-interrupted"]["status"], "incomplete")
            duplicate = subprocess.run(argv, capture_output=True, text=True, timeout=2)
            self.assertEqual(duplicate.returncode, 0, duplicate.stderr)
            self.assertEqual(json.loads(duplicate.stdout)["kind"], "run-started")
        finally:
            process.terminate()
            process.communicate(timeout=2)
            if marker.exists():
                try:
                    os.killpg(int(marker.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_original_package_restored_elsewhere_can_really_close_from_its_cli(self):
        self.completed()
        restored = ".delivery/example/pinned-orchestrate"
        self.engine.source("delivery-orchestrate", restored)
        request_path = self.write(".delivery/example/close.json", json.dumps(self.closing()))
        command = [sys.executable, "-B", str(self.project / restored / "scripts/delivery.py"), "close", "--work", str(self.work), "--input", str(request_path), "--op", "restored-close"]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["kind"], "close")

    def test_historical_plan_author_cannot_be_removed_by_reconfiguration(self):
        self.admitted()
        previous = self.configuration["op"]
        self.config["source_authors"]["plan"] = [{"id": "new-planner", "context": "new-planning"}]
        self.config["change"] = {"category": "organization", "reason": "Same authorized outcome and acceptance", "previous_config": previous}
        self.configure()
        with self.assertRaisesRegex(delivery.DeliveryError, "historical source author"):
            self.engine.gate(self.extra(actor={"id": "planner", "context": "fresh-but-not-independent"}, config_operation=self.configuration["op"], kind="plan_review", result="passed", summary="Cannot erase actual authorship", **self.report()), self.op())
        self.gate("plan_review")
        self.gate("mapping_review")
        self.gate("change_review")
        self.record()

    def test_unknown_professional_contract_not_hidden_by_supported_input(self):
        import shutil
        root = self.work / "implement-contract-copy"
        shutil.copytree(SCRIPTS.parents[1] / "delivery-implement", root)
        next(s for s in self.config["skill_sources"] if s["name"] == "delivery-implement")["root"] = str(root)
        contract = root / "references/delivery-contract.md"
        contract.write_text(contract.read_text().replace("当前版本为 **1**", "当前版本为 **8**"))
        with self.assertRaisesRegex(delivery.DeliveryError, "actual skill contract"):
            self.configure()

    def source_copy(self):
        import shutil
        root = self.work / "implement-copy"
        shutil.copytree(SCRIPTS.parents[1] / "delivery-implement", root)
        next(s for s in self.config["skill_sources"] if s["name"] == "delivery-implement")["root"] = str(root)
        return root

    def review_source(self, root, label):
        old = self.engine.effective_pins(self.engine.current_config(False))["delivery-implement"]
        self.write(f".delivery/example/{label}.md", "Independent complete source compatibility review")
        self.write(f".delivery/example/{label}.txt", "Current complete behavior evidence")
        return self.engine.source_update(self.extra(config_operation=self.configuration["op"], name="delivery-implement", old_tree_hash=old["tree_hash"], new_root=str(root), decision="compatible", reason="Complete independent reassessment from effective old source", affected_targets=[], report={"path": f".delivery/example/{label}.md"}, evidence=[{"path": f".delivery/example/{label}.txt"}]), self.op())

    def test_IR005_fresh_complete_source_reassessment_recovers_after_stale_review(self):
        root = self.source_copy()
        self.admitted()
        (root / "SKILL.md").write_text((root / "SKILL.md").read_text() + "\nCompatible clarification\n")
        first = self.review_source(root, "source-u1")
        self.write(".delivery/example/source-u1.txt", "First evidence became stale")
        self.assertTrue(self.status()["skill_drift"])
        renewed = self.review_source(root, "source-u2")
        effective = self.engine.effective_pins(self.engine.current_config(False))["delivery-implement"]
        self.assertEqual(effective["tree_hash"], renewed["payload"]["pin"]["tree_hash"])
        self.assertFalse(self.status()["skill_drift"])
        self.record()

    def test_IR005_dependent_incremental_source_review_cannot_bridge_stale_ancestor(self):
        root = self.source_copy()
        self.admitted()
        (root / "SKILL.md").write_text((root / "SKILL.md").read_text() + "\nFirst clarification\n")
        self.review_source(root, "source-u1")
        (root / "SKILL.md").write_text((root / "SKILL.md").read_text() + "\nLater incremental clarification\n")
        self.review_source(root, "source-u2")
        self.write(".delivery/example/source-u1.txt", "Ancestor evidence changed")
        self.assertTrue(self.status()["skill_drift"])
        with self.assertRaisesRegex(delivery.DeliveryError, "source drift"):
            self.record(claim=False)
        self.review_source(root, "source-u3-complete")
        self.record()

    def reviewed_impact(self, label, effect="unrelated", targets=None):
        status = self.status()
        self.write(f".delivery/example/{label}.md", "Independent complete current changeset assessment")
        self.write(f".delivery/example/{label}.txt", "Actual change dependency evidence")
        return self.engine.impact(self.extra(config_operation=self.configuration["op"], change_set_hash=status["change_set_hash"], decisions=[{"paths": [c["path"] for c in status["unassessed_changes"]], "effect": effect, "targets": targets or [], "reason": "Complete current change assessment"}], report={"path": f".delivery/example/{label}.md"}, evidence=[{"path": f".delivery/example/{label}.txt"}]), self.op())

    def test_IR007_fresh_full_impact_reassessment_recovers_without_reviving_old_results(self):
        self.completed()
        self.write("shared.cfg", "Affects consumer")
        self.reviewed_impact("impact-i1", "related", [{"kind": "implementation", "id": "T1"}])
        self.write(".delivery/example/impact-i1.txt", "Prior dependency evidence changed")
        self.assertTrue(self.status()["unassessed_changes"])
        self.reviewed_impact("impact-i2", "unrelated")
        self.assertFalse(self.status()["unassessed_changes"])
        self.assertEqual(self.status()["implementation"]["T1"]["status"], "stale")
        self.record()
        self.assertIn("shared.cfg", self.engine.target_scope(self.engine.current_config(False)["payload"], "implementation", "T1"))

    def test_IR007_incremental_descendant_cannot_hide_stale_impact_ancestor(self):
        self.admitted()
        self.write("note1.md", "first outside change")
        self.reviewed_impact("impact-i1")
        self.write("note2.md", "second outside change")
        self.reviewed_impact("impact-i2")
        self.write(".delivery/example/impact-i1.txt", "Ancestor evidence changed")
        paths = {c["path"] for c in self.status()["unassessed_changes"]}
        self.assertEqual(paths, {"note1.md", "note2.md"})
        with self.assertRaisesRegex(delivery.DeliveryError, "outside changes"):
            self.record(claim=False)
        self.reviewed_impact("impact-i3-complete")
        self.record()

    def reconfigure_after_recovery(self):
        self.config["change"] = {"category": "organization", "reason": "Same authorized recovery goal, refined plan", "previous_config": self.configuration["op"]}
        self.configure()
        self.gate("plan_review")
        self.gate("mapping_review")
        self.gate("change_review")

    def test_IR006_settled_unknown_chain_survives_legitimate_reconfiguration(self):
        self.unknown()
        self.resolve()
        run = self.execute_run()
        self.record("verification", "A1", run_operation=run["op"])
        self.write("plan.md", "T1 delivers persistence; A1 observes actual consumer. Refined organization.\n")
        self.reconfigure_after_recovery()
        self.assertTrue(self.status()["unknown_runs"][0]["settled"])
        self.record()
        self.record("review", "R1")
        new_run = self.execute_run()
        self.record("verification", "A1", run_operation=new_run["op"])
        self.engine.close(self.closing(), self.op())

    def test_IR006_stale_archived_investigation_can_be_reinvestigated_in_current_admission(self):
        self.unknown()
        self.resolve()
        run = self.execute_run()
        self.record("verification", "A1", run_operation=run["op"])
        self.reconfigure_after_recovery()
        self.write(".delivery/example/investigation.txt", "Old investigation evidence changed")
        with self.assertRaisesRegex(delivery.DeliveryError, "resolve-run"):
            self.record(claim=False)
        self.resolve()
        self.record()
        self.record("review", "R1")
        replacement = self.execute_run()
        self.record("verification", "A1", run_operation=replacement["op"])
        self.engine.close(self.closing(), self.op())

    def test_IR006_genuinely_unresolved_run_cannot_be_erased_by_reconfiguration(self):
        self.unknown()
        self.config["change"] = {"category": "organization", "reason": "Cannot skip side effects", "previous_config": self.configuration["op"]}
        with self.assertRaisesRegex(delivery.DeliveryError, "recover incomplete run"):
            self.configure()

    def add_second_command_acceptance(self):
        second = copy.deepcopy(self.config["acceptance"][0])
        second["id"] = "A2"
        second["method"] = "command"
        second["command"] = [sys.executable, "-c", "print('independent second consumer')"]
        self.config["acceptance"].append(second)

    def second_run(self):
        self.claim("verification", "A2", self.verifier)
        try:
            return self.engine.run("A2", self.verifier, 5, self.op())
        finally:
            self.claim("verification", "A2", self.verifier, "release")

    def test_IR008_shared_task_acceptances_keep_recovery_owner_and_close(self):
        self.add_second_command_acceptance()
        self.unknown()
        self.resolve()
        first = self.execute_run()
        self.record("verification", "A1", run_operation=first["op"])
        second = self.second_run()
        self.assertIsNone(second["payload"]["recovery_operation"])
        self.record("verification", "A2", run_operation=second["op"])
        unknown = self.status()["unknown_runs"][0]
        self.assertEqual(unknown["replacement"], first["op"])
        self.assertTrue(unknown["settled"])
        self.engine.close(self.closing(), self.op())

    def test_IR008_other_owner_pass_cannot_settle_unreplaced_original(self):
        self.add_second_command_acceptance()
        self.unknown()
        self.resolve()
        second = self.second_run()
        self.record("verification", "A2", run_operation=second["op"])
        unknown = self.status()["unknown_runs"][0]
        self.assertIsNone(unknown["replacement"])
        self.assertFalse(unknown["settled"])
        with self.assertRaisesRegex(delivery.DeliveryError, "replacement run"):
            self.engine.close(self.closing(), self.op())
        config = self.engine.current_config(False)
        resolution = self.engine.resolutions()["interrupted"]
        self.assertFalse(self.engine.settled_recovery(resolution, second, config))

    def test_IR008_same_owner_later_failure_remains_blocking_even_if_other_passes(self):
        self.command("from pathlib import Path; import sys; sys.exit(1 if Path('.delivery/example/fail.flag').exists() else 0)")
        self.add_second_command_acceptance()
        # Reserve a real shaped unknown without replacing the configured command.
        self.implement_and_review()
        with self.engine.locked():
            config = self.engine.current_config()
            self.engine.append("run-started", "interrupted", delivery.digest(b"reservation"), {"acceptance": "A1", "tasks": ["T1"], "config_op": config["op"], "command": config["payload"]["spec"]["acceptance"][0]["command"], "actor": self.verifier, "before": self.engine.snapshot(["src"])})
        self.resolve()
        first = self.execute_run()
        self.record("verification", "A1", run_operation=first["op"])
        self.write(".delivery/example/fail.flag", "real same-owner failure trigger")
        failed = self.execute_run()
        self.assertEqual(failed["payload"]["exit_code"], 1)
        second = self.second_run()
        self.record("verification", "A2", run_operation=second["op"])
        unknown = self.status()["unknown_runs"][0]
        self.assertEqual(unknown["replacement"], failed["op"])
        self.assertFalse(unknown["settled"])
        with self.assertRaises(delivery.DeliveryError):
            self.engine.close(self.closing(), self.op())

    def reserve_unknown(self, operation, acceptance="A1", recoveries=None):
        with self.engine.locked():
            config = self.engine.current_config()
            item = self.engine.target(config["payload"], "verification", acceptance)
            self.engine.append("run-started", operation, delivery.digest(operation.encode()), {"acceptance": acceptance, "tasks": item["tasks"], "config_op": config["op"], "command": item["command"], "actor": self.verifier, "before": self.engine.snapshot(["src"]), "recovery_operations": recoveries or [], "recovery_operation": (recoveries or [None])[-1]})

    def resolve_named(self, operation, label):
        self.write(f".delivery/example/{label}.md", "Actual interrupted-run process and side-effect investigation; safe retry.")
        self.write(f".delivery/example/{label}.txt", f"Investigated stable run {operation}; process stopped; effects checked.")
        return self.engine.resolve_run(self.extra(run_operation=operation, decision="safe_to_retry", reason="Investigated original owner, process and side effects before retry", report={"path": f".delivery/example/{label}.md"}, evidence=[{"path": f".delivery/example/{label}.txt"}]), self.op())

    def test_IR009_twice_interrupted_owner_binds_all_resolutions_and_survives_reconfigure(self):
        self.unknown()
        first = self.resolve_named("interrupted", "root-one")
        self.reserve_unknown("interrupted-twice", recoveries=[first["op"]])
        second = self.resolve_named("interrupted-twice", "root-two")
        run = self.execute_run()
        self.assertEqual(run["payload"]["recovery_operations"], [first["op"], second["op"]])
        self.record("verification", "A1", run_operation=run["op"])
        self.assertTrue(all(u["settled"] and u["replacement"] == run["op"] for u in self.status()["unknown_runs"]))
        self.reconfigure_after_recovery()
        self.record()
        self.record("review", "R1")
        current = self.execute_run()
        self.record("verification", "A1", run_operation=current["op"])
        self.engine.close(self.closing(), self.op())

    def test_IR009_root_evidence_expiry_blocks_entire_multiple_resolution_chain(self):
        self.unknown()
        first = self.resolve_named("interrupted", "root-one")
        self.reserve_unknown("interrupted-twice", recoveries=[first["op"]])
        self.resolve_named("interrupted-twice", "root-two")
        run = self.execute_run()
        self.record("verification", "A1", run_operation=run["op"])
        self.write(".delivery/example/root-one.txt", "Earliest actual investigation evidence became stale")
        self.assertEqual(self.status()["verification"]["A1"]["status"], "stale")
        self.assertFalse(any(u["settled"] for u in self.status()["unknown_runs"]))
        with self.assertRaisesRegex(delivery.DeliveryError, "resolve-run"):
            self.engine.close(self.closing(), self.op())

    def test_IR008_IR009_cross_owner_unknowns_keep_separate_binding_sets(self):
        self.add_second_command_acceptance()
        self.unknown()
        first = self.resolve_named("interrupted", "owner-a1")
        self.reserve_unknown("a2-interrupted", "A2")
        with self.assertRaisesRegex(delivery.DeliveryError, "resolve-run"):
            self.execute_run()
        second = self.resolve_named("a2-interrupted", "owner-a2")
        a1 = self.execute_run()
        self.assertEqual(a1["payload"]["recovery_operations"], [first["op"]])
        self.record("verification", "A1", run_operation=a1["op"])
        a2 = self.second_run()
        self.assertEqual(a2["payload"]["recovery_operations"], [second["op"]])
        self.record("verification", "A2", run_operation=a2["op"])
        self.engine.close(self.closing(), self.op())
        wrong = copy.deepcopy(a2)
        wrong["payload"]["recovery_operations"] = [first["op"]]
        self.assertFalse(self.engine.valid_run_recoveries(wrong, self.engine.current_config(False)))

    def test_IR009_three_real_cli_interruptions_then_actual_run_verdict_and_close(self):
        import signal
        self.command("from pathlib import Path; import os,time; Path('.delivery/example/child.pid').write_text(str(os.getpid())); time.sleep(30) if not Path('.delivery/example/continue.ok').exists() else print('actual recovered consumer')")
        self.implement_and_review()
        resolutions = []
        marker = self.work / "child.pid"
        for number in range(1, 4):
            operation = f"real-crash-{number}"
            self.claim("verification", "A1", self.verifier)
            marker.unlink(missing_ok=True)
            argv = [sys.executable, "-B", str(SCRIPTS / "delivery.py"), "run", "--work", str(self.work), "--acceptance", "A1", "--actor", self.verifier["id"], "--context", self.verifier["context"], "--timeout", "40", "--op", operation]
            process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            deadline = time.monotonic() + 5
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            try:
                self.assertTrue(marker.exists(), f"actual child {number} must start")
            finally:
                process.terminate()
                process.communicate(timeout=2)
                if marker.exists():
                    try:
                        os.killpg(int(marker.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                self.claim("verification", "A1", self.verifier, "release")
            self.assertEqual(self.status()["runs"][operation]["status"], "incomplete")
            resolution = self.resolve_named(operation, f"actual-investigation-{number}")
            resolutions.append(resolution["op"])
        self.write(".delivery/example/continue.ok", "Side effects investigated; permit actual safe completion")
        final = self.execute_run()
        self.assertEqual(final["payload"]["exit_code"], 0)
        self.assertEqual(final["payload"]["recovery_operations"], resolutions)
        self.record("verification", "A1", run_operation=final["op"])
        self.assertEqual(len(self.status()["unknown_runs"]), 3)
        self.assertTrue(all(u["settled"] for u in self.status()["unknown_runs"]))
        self.engine.close(self.closing(), self.op())

    def test_IR009_explicit_readmission_of_unchanged_recovered_results_keeps_original_chain(self):
        self.unknown()
        first = self.resolve_named("interrupted", "root-one")
        self.reserve_unknown("interrupted-twice", recoveries=[first["op"]])
        self.resolve_named("interrupted-twice", "root-two")
        run = self.execute_run()
        self.record("verification", "A1", run_operation=run["op"])
        records = self.engine.records(self.engine.current_config(False))
        self.config["reuse"] = [{"operation_id": operation, "reason": "Explicit unchanged source/product/report reassessment"} for operation, _ in records.values()]
        self.reconfigure_after_recovery()
        self.assertEqual(self.status()["verification"]["A1"]["status"], "passed")
        self.engine.close(self.closing(), self.op())

    def test_compatible_source_explicit_readmission_preserves_original_report_pin_provenance(self):
        root = self.source_copy()
        self.completed()
        (root / "SKILL.md").write_text((root / "SKILL.md").read_text() + "\nCompatible explanation for future activities\n")
        self.review_source(root, "source-compatible")
        records = self.engine.records(self.engine.current_config(False))
        self.config["reuse"] = [{"operation_id": operation, "reason": "Actual report/product unchanged; source clarification independently compatible"} for operation, _ in records.values()]
        self.reconfigure_after_recovery()
        self.assertEqual(self.status()["implementation"]["T1"]["status"], "passed")
        self.engine.close(self.closing(), self.op())

    def configure_with_current_reuse(self):
        self.config["reuse"] = [{"operation_id": operation, "reason": "Explicit reassessment of latest rebound result"} for operation, _ in self.engine.records(self.engine.current_config(False)).values()]
        self.reconfigure_after_recovery()

    def test_IR010_reused_original_cannot_escape_later_admission_impact(self):
        self.completed()
        self.configure_with_current_reuse()
        self.write("shared.cfg", "Actual consumer changed")
        self.reviewed_impact("c2-related", "related", [{"kind": "implementation", "id": "T1"}])
        self.assertTrue(all(self.status()[kind][target]["status"] == "stale" for kind, target in (("implementation", "T1"), ("review", "R1"), ("verification", "A1"))))
        previous = self.configuration["op"]
        self.config["change"] = {"category": "organization", "reason": "Cannot bypass C2 stale result by going back to C1", "previous_config": previous}
        with self.assertRaisesRegex(delivery.DeliveryError, "stale latest rebound"):
            self.configure()
        self.assertEqual(self.engine.current_config(False)["op"], previous)

    def test_IR010_new_actual_activities_allow_reuse_and_preserve_context(self):
        self.completed()
        self.configure_with_current_reuse()
        self.write("shared.cfg", "Actual shared consumer dependency")
        self.reviewed_impact("c2-related", "related", [{"kind": "implementation", "id": "T1"}])
        self.record()
        self.record("review", "R1")
        self.record("verification", "A1")
        self.configure_with_current_reuse()
        config = self.engine.current_config(False)
        self.assertIn("shared.cfg", self.engine.target_scope(config["payload"], "implementation", "T1"))
        self.assertEqual(self.status()["verification"]["A1"]["status"], "passed")
        self.write("shared.cfg", "Later consumer revision cannot be ignored")
        self.assertEqual(self.status()["implementation"]["T1"]["status"], "stale")
        with self.assertRaisesRegex(delivery.DeliveryError, "outside changes"):
            self.engine.close(self.closing(), self.op())

    def test_IR010_source_text_refinement_still_allows_current_unchanged_rebound(self):
        self.completed()
        self.configure_with_current_reuse()
        self.write("plan.md", "T1 delivers persistence; A1 observes actual consumer. Clarifies same authorized outcome.\n")
        self.configure_with_current_reuse()
        self.assertEqual(self.status()["verification"]["A1"]["status"], "passed")
        self.engine.close(self.closing(), self.op())

    def test_IR010_inherited_context_cannot_be_hidden_by_new_monitor_exclusion(self):
        self.completed()
        self.write("shared.cfg", "Known relevant dependency")
        self.reviewed_impact("c1-related", "related", [{"kind": "implementation", "id": "T1"}])
        self.record()
        self.record("review", "R1")
        self.record("verification", "A1")
        self.config["monitor"]["exclude"] = [{"path": "shared.cfg", "reason": "Must not hide previously related input"}]
        self.config["change"] = {"category": "organization", "reason": "Forbidden exclusion", "previous_config": self.configuration["op"]}
        with self.assertRaisesRegex(delivery.DeliveryError, "exclusion overlaps"):
            self.configure()

    def test_cli_v2_init_status_and_markdown(self):
        work = self.project / ".delivery/new-cli"
        command = [sys.executable, "-B", str(SCRIPTS / "delivery.py")]
        init = subprocess.run(command + ["init", "--project", str(self.project), "--work", str(work), "--title", "CLI", "--contract-version", "2", "--op", "cli-init"], capture_output=True, text=True)
        self.assertEqual(init.returncode, 0, init.stderr)
        status = subprocess.run(command + ["status", "--work", str(work), "--format", "markdown"], capture_output=True, text=True)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("configure_required", status.stdout)

    def test_FR001_gate_pin_expiry_blocks_until_valid_recheck(self):
        import shutil
        root = self.work / "plan-copy"
        shutil.copytree(SCRIPTS.parents[1] / "delivery-plan", root)
        next(s for s in self.config["skill_sources"] if s["name"] == "delivery-plan")["root"] = str(root)
        original = (root / "SKILL.md").read_text()
        self.completed()
        old = self.engine.effective_pins(self.engine.current_config(False))["delivery-plan"]
        (root / "SKILL.md").write_text(original + "\nCompatible method clarification.\n")
        self.write(".delivery/example/compat.md", "Independent compatibility judgement")
        self.write(".delivery/example/compat.txt", "Actual compatibility evidence")
        update = self.engine.source_update(self.extra(config_operation=self.configuration["op"], name="delivery-plan",
            old_tree_hash=old["tree_hash"], new_root=str(root), decision="compatible", reason="Same professional contract",
            affected_targets=[], report={"path": ".delivery/example/compat.md"}, evidence=[{"path": ".delivery/example/compat.txt"}]), self.op())
        reviewed = self.gate("plan_review")
        self.write(".delivery/example/compat.txt", "Compatibility evidence superseded")
        (root / "SKILL.md").write_text(original)
        state = self.status()
        self.assertFalse(state["skill_drift"])
        self.assertEqual(state["admission"]["plan_review"]["status"], "stale")
        self.assertEqual(state["admission"]["mapping_review"]["status"], "passed")
        self.assertTrue(any(d["code"] == "admission_stale" for d in self.engine.inspect("next")["diagnostics"]))
        for action in (lambda: self.record(claim=False), lambda: self.execute_run(), lambda: self.engine.close(self.closing(), self.op())):
            with self.assertRaisesRegex(delivery.DeliveryError, "admission gate"):
                action()
        self.gate("plan_review")
        self.engine.close(self.closing(), self.op())
        self.assertEqual(reviewed["payload"]["skill_pins"]["delivery-plan"], update["payload"]["pin"]["tree_hash"])

    def prepare_replan(self):
        self.write("plan.md", "T1 delivers persistence; A1 observes actual consumer. Use replacement command.\n")
        self.write("authorization.md", "User authorizes T1. Revoke old command; allow replacement, no push.\n")
        self.config["change"] = {"category": "material", "reason": "User revoked old command; retain actual consumer acceptance",
            "previous_config": self.configuration["op"], "authorization": {"path": "authorization.md", "quote": "Revoke old command; allow replacement"}}
        self.command("from pathlib import Path; assert Path('src/main.txt').read_text() == 'works\\n'; print('new authorized consumer check')")

    def investigate_replan(self, operation="interrupted", decision="safe_to_replan", label="replan"):
        self.write(f".delivery/example/{label}.md", "Checked original process and descendants stopped; examined actual product and side effects. Old command revoked; new plan required.")
        self.write(f".delivery/example/{label}.txt", f"Observed run {operation}, stable src, stopped process, reviewed scene. decision={decision}")
        return self.engine.resolve_run(self.extra(run_operation=operation, decision=decision, recovery_contract_version=2,
            reason="Actual safety investigation only; no command replay or acceptance claim",
            report={"path": f".delivery/example/{label}.md"}, evidence=[{"path": f".delivery/example/{label}.txt"}]), self.op())

    def transfer_replan(self, investigation):
        self.config["recovery_transfers"] = [{"recovery_contract_version": 2,
            "run_operation": investigation["payload"]["run_operation"], "investigation_operation": investigation["op"]}]

    def test_FR002_real_interruption_replans_without_replaying_revoked_command(self):
        import signal
        self.command("from pathlib import Path; import os,time; p=Path('.delivery/example/old-count'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1'); Path('.delivery/example/old.pid').write_text(str(os.getpid())); time.sleep(30)")
        self.implement_and_review()
        original_command = list(self.config["acceptance"][0]["command"])
        self.claim("verification", "A1", self.verifier)
        process = subprocess.Popen([sys.executable, "-B", str(SCRIPTS / "delivery.py"), "run", "--work", str(self.work),
            "--acceptance", "A1", "--actor", self.verifier["id"], "--context", self.verifier["context"], "--timeout", "40", "--op", "real-fr002"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        marker = self.work / "old.pid"
        deadline = time.monotonic() + 5
        try:
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists(), "the actual command must start before interrupting its controller")
        finally:
            process.terminate()
            process.communicate(timeout=5)
            if marker.exists():
                try:
                    os.killpg(int(marker.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.claim("verification", "A1", self.verifier, "release")
        self.assertEqual(self.status()["runs"]["real-fr002"]["status"], "incomplete")
        self.prepare_replan()
        with self.assertRaisesRegex(delivery.DeliveryError, "sources changed"):
            self.engine.resolve_run(self.extra(run_operation="real-fr002", decision="safe_to_retry", reason="Legacy unchanged", **self.report()), self.op())
        investigation = self.investigate_replan("real-fr002")
        with self.assertRaisesRegex(delivery.DeliveryError, "recover incomplete run"):
            self.configure()
        self.transfer_replan(investigation)
        self.configure()
        with self.assertRaisesRegex(delivery.DeliveryError, "admission gate"):
            self.record(claim=False)
        for kind in ("plan_review", "mapping_review", "change_review"):
            self.gate(kind)
        self.record()
        self.record("review", "R1")
        with self.assertRaisesRegex(delivery.DeliveryError, "replacement run"):
            self.engine.close(self.closing(), self.op())
        run = self.execute_run()
        self.assertEqual(run["payload"]["recovery_operations"], [investigation["op"]])
        self.assertNotEqual(run["payload"]["command"], original_command)
        with self.assertRaisesRegex(delivery.DeliveryError, "replacement run"):
            self.engine.close(self.closing(), self.op())
        self.record("verification", "A1", run_operation=run["op"])
        self.assertTrue(self.status()["unknown_runs"][0]["settled"])
        self.engine.close(self.closing(), self.op())
        self.assertEqual((self.work / "old-count").read_text(), "1")
        self.assertEqual(self.status()["runs"]["real-fr002"]["status"], "incomplete")
        print("FR-002 actual CLI: interrupted old command -> changed authorization -> investigation -> new independent gates -> replacement run -> verdict -> close; old command executions=1")

    def test_FR002_transfer_requires_current_evidence_and_preserved_owner(self):
        self.unknown()
        self.prepare_replan()
        unknown = self.investigate_replan(decision="unresolved")
        self.transfer_replan(unknown)
        with self.assertRaisesRegex(delivery.DeliveryError, "latest current"):
            self.configure()
        good = self.investigate_replan(label="good")
        self.transfer_replan(good)
        self.write(".delivery/example/good.txt", "Investigation evidence no longer current")
        with self.assertRaisesRegex(delivery.DeliveryError, "latest current"):
            self.configure()
        good = self.investigate_replan(label="renewed")
        self.transfer_replan(good)
        acceptance = self.config["acceptance"][0]
        for field, value in (("method", "inspection"), ("required", False), ("waivable", True)):
            original = copy.deepcopy(acceptance)
            acceptance[field] = value
            if field == "method":
                acceptance.pop("command")
            with self.assertRaises(delivery.DeliveryError):
                self.configure()
            acceptance.clear()
            acceptance.update(original)
        self.configure()
        for kind in ("plan_review", "mapping_review", "change_review"):
            self.gate(kind)
        self.write(".delivery/example/renewed.txt", "Safety facts were corrected after transfer")
        with self.assertRaisesRegex(delivery.DeliveryError, "resolve-run"):
            self.record(claim=False)
        # A full new investigation can recover the current scene, but still
        # needs an explicit newly reviewed transfer and real replacement.
        good = self.investigate_replan(label="current")
        self.transfer_replan(good)
        self.config["change"]["previous_config"] = self.configuration["op"]
        self.configure()
        for kind in ("plan_review", "mapping_review", "change_review"):
            self.gate(kind)
        self.record()
        self.record("review", "R1")
        run = self.execute_run()
        self.record("verification", "A1", run_operation=run["op"])
        self.write("plan.md", "T1 delivers persistence; A1 observes actual consumer. Later lawful refinement.\n")
        self.config.pop("recovery_transfers")
        self.reconfigure_after_recovery()
        self.assertTrue(self.status()["unknown_runs"][0]["settled"])

    def test_FR002_source_assessment_can_repair_stale_admission_without_executing(self):
        root = self.source_copy()
        self.unknown()
        self.prepare_replan()
        (root / "SKILL.md").write_text((root / "SKILL.md").read_text() + "\nCompatible clarification\n")
        self.review_source(root, "stale-plan-source-assessment")
        self.assertFalse(self.status()["skill_drift"])
        with self.assertRaisesRegex(delivery.DeliveryError, "sources changed"):
            self.record(claim=False)


if __name__ == "__main__":
    unittest.main()
