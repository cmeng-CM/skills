"""Operational regressions for P0-P2: preflight, snapshots, gate reuse, guard,
status view, batch verification, rejection audit and preclose checks."""
import copy
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import delivery
from delivery_monitor import preflight
from delivery_v2 import EngineV2, STATUS_START, STATUS_END
import test_delivery_v2 as fixture


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve()
        self.work = self.project / ".delivery/work"
        self.work.mkdir(parents=True)
        self.write("src/app.py", "print('x')\n")
        for index in range(4):
            self.write("node_modules/pkg%d/index.js" % index, "module\n")
        self.write("dist/bundle.js", "bundle\n")
        self.write(".venv/lib/site.py", "venv\n")

    def write(self, path, content):
        target = self.project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def test_preflight_reports_candidates_without_changing_state(self):
        result = preflight(self.project, self.work, 3)
        candidates = {item["path"]: item for item in result["candidates"]}
        self.assertEqual(candidates["node_modules"]["files"], 4)
        self.assertTrue(candidates["node_modules"]["high_yield"])
        self.assertEqual(candidates["node_modules"]["kind"], "dependency")
        self.assertEqual(candidates[".venv"]["kind"], "dependency")
        self.assertEqual(candidates["dist"]["kind"], "generated")
        self.assertTrue(candidates["dist"]["confirmation_required"])
        self.assertEqual(result["unreadable"], [])
        self.assertFalse((self.work / "runtime").exists())

    def test_threshold_marks_low_yield_candidates(self):
        result = preflight(self.project, self.work, 100)
        candidates = {item["path"]: item for item in result["candidates"]}
        self.assertFalse(candidates["node_modules"]["high_yield"])
        self.assertEqual(candidates["node_modules"]["bytes"], 4 * len("module\n"))

    def test_preflight_rejects_symlinked_project_path(self):
        link = self.project.parent / "linked-project"
        link.symlink_to(self.project, target_is_directory=True)
        self.addCleanup(link.unlink)
        with self.assertRaisesRegex(delivery.DeliveryError, "symlink"):
            preflight(link, link / ".delivery/work", 3)


class OperationsFixture:
    # Reuse public fixture helpers without inheriting and rerunning V2Case tests.
    setUp = fixture.V2Case.setUp
    write = fixture.V2Case.write
    op = fixture.V2Case.op
    extra = fixture.V2Case.extra
    report = fixture.V2Case.report
    configure = fixture.V2Case.configure
    gate = fixture.V2Case.gate
    admitted = fixture.V2Case.admitted
    claim = fixture.V2Case.claim
    record = fixture.V2Case.record
    completed = fixture.V2Case.completed
    closing = fixture.V2Case.closing
    implement_and_review = fixture.V2Case.implement_and_review
    status = fixture.V2Case.status
    impact = fixture.V2Case.impact


class OperationsCase(OperationsFixture, unittest.TestCase):
    def gate_operations(self):
        result = {}
        for event in self.engine.data["events"]:
            if event["kind"] == "gate" and event["payload"]["config_op"] == self.configuration["op"]:
                result[event["payload"]["kind"]] = event["op"]
        return result

    def organization_config(self, **changes):
        config = copy.deepcopy(self.config)
        config["change"] = {"category": "organization",
                            "reason": "Only the monitored generated output changed",
                            "previous_config": self.configuration["op"]}
        for key, value in changes.items():
            config[key] = value
        return config

    def test_snapshot_objects_schema_two_and_backup(self):
        self.configure()
        journal = json.loads((self.work / "runtime/journal.json").read_text())
        self.assertEqual(journal["schema_version"], 2)
        configure = next(event for event in journal["events"] if event["kind"] == "configure")
        baseline = configure["payload"]["monitor_baseline"]
        self.assertIn("object_hash", baseline)
        self.assertNotIn("entries", baseline)
        snapshot = self.engine.load_snapshot(baseline)
        self.assertEqual(snapshot["hash"], baseline["entries_hash"])
        self.assertEqual(len(snapshot["entries"]), baseline["entries_count"])
        backup = self.work / "runtime/journal.schema1.bak"
        self.assertTrue(backup.is_file())
        backup_data = json.loads(backup.read_text())
        self.assertEqual(backup_data["schema_version"], 1)
        delivery.validate_events(backup_data["events"])

    def test_status_uses_one_inventory_scan_per_command(self):
        self.configure()
        state = EngineV2(self.work).inspect("status")
        self.assertEqual(state["inventory"]["inventory_calls"], 1)
        self.assertGreater(state["inventory"]["entries"], 0)
        self.assertEqual(state["inventory"]["excluded_paths"], [])

    def test_reconfiguration_scans_old_and_new_once(self):
        self.admitted()
        operations = self.gate_operations()
        config = self.organization_config(
            monitor={"roots": ["."], "exclude": [{"path": "node_modules", "reason": "Dependency output only"}]},
            reuse_gates=[{"kind": "plan_review", "operation_id": operations["plan_review"], "reason": "Same plan"},
                         {"kind": "mapping_review", "operation_id": operations["mapping_review"], "reason": "Same mapping"}])
        engine = EngineV2(self.work)
        engine.configure(config, self.op())
        self.assertEqual(engine._inventory_scans, 2)

    def test_impact_inventory_is_also_objectized(self):
        self.configure()
        self.write("notes.txt", "unrelated\n")
        self.assertTrue(self.status()["unassessed_changes"])
        event = self.impact("unrelated", [])
        self.assertIn("object_hash", event["payload"]["inventory"])
        self.assertNotIn("entries", event["payload"]["inventory"])
        self.assertEqual(self.engine.load_snapshot(event["payload"]["inventory"])["hash"],
                         event["payload"]["inventory"]["entries_hash"])
        self.assertFalse(self.status()["unassessed_changes"])

    def test_reuse_gates_allows_only_monitor_exclude_change(self):
        self.admitted()
        operations = self.gate_operations()
        config = self.organization_config(
            monitor={"roots": ["."], "exclude": [{"path": "node_modules", "reason": "Dependency output only"}]},
            reuse_gates=[{"kind": "plan_review", "operation_id": operations["plan_review"], "reason": "Same plan and sources"},
                         {"kind": "mapping_review", "operation_id": operations["mapping_review"], "reason": "Same mapping"}])
        new = self.engine.configure(config, self.op())
        self.assertEqual({item["kind"] for item in new["payload"]["reused_gates"]},
                         {"plan_review", "mapping_review"})
        state = self.engine.gate_state(new)
        self.assertEqual(state["plan_review"]["status"], "passed")
        self.assertEqual(state["plan_review"]["reused_from"], self.configuration["op"])
        self.assertFalse(state["plan_review"]["legacy"])
        self.assertEqual(state["change_review"]["status"], "pending")
        self.engine.gate(self.extra(config_operation=new["op"], kind="change_review", result="passed",
                                    summary="Independent review of the organization-only exclusion",
                                    **self.report()), self.op())
        self.record()

    def test_reuse_gates_rejects_any_real_input_change(self):
        self.admitted()
        operations = self.gate_operations()
        reuse = [{"kind": "plan_review", "operation_id": operations["plan_review"], "reason": "Same plan"},
                 {"kind": "mapping_review", "operation_id": operations["mapping_review"], "reason": "Same mapping"}]
        mutations = [
            lambda config: config["requirements"][0].update(id="REQ2"),
            lambda config: config.__setitem__("resources", [{"id": "path:src", "mode": "read", "tasks": ["T1"]}]),
            lambda config: config["acceptance"][0].update(criteria="Different acceptance"),
            lambda config: config["authorization"].update(scope="Broader scope"),
            lambda config: config["admission_policy"].update(reason="Different policy reason"),
        ]
        for mutate in mutations:
            config = self.organization_config(reuse_gates=copy.deepcopy(reuse))
            mutate(config)
            with self.assertRaisesRegex(delivery.DeliveryError, "unchanged admission inputs"):
                self.engine.configure(config, self.op())
        config = self.organization_config(reuse_gates=copy.deepcopy(reuse))
        config["change"]["category"] = "within_grant"
        with self.assertRaisesRegex(delivery.DeliveryError, "organization"):
            self.engine.configure(config, self.op())

    def test_reuse_gates_rejects_changed_plan_source(self):
        self.admitted()
        operations = self.gate_operations()
        self.write("plan.md", "T1 delivers persistence; A1 observes actual consumer. Scope changed.\n")
        config = self.organization_config(
            reuse_gates=[{"kind": "plan_review", "operation_id": operations["plan_review"], "reason": "Same plan"},
                         {"kind": "mapping_review", "operation_id": operations["mapping_review"], "reason": "Same mapping"}])
        with self.assertRaisesRegex(delivery.DeliveryError, "unchanged admission inputs"):
            self.engine.configure(config, self.op())

    def test_gate_protocol_and_legacy_cutoff(self):
        self.configure()
        config = self.engine.current_config(False)
        cutoff = self.engine.legacy_cutoff()
        self.assertEqual(cutoff, self.configuration["seq"])
        base = {"payload": {"kind": "plan_review", "result": "passed", "references": {}, "skill_pins": {}}}
        matches, legacy, issue = self.engine.gate_source_state(config, {**base, "seq": cutoff + 1})
        self.assertFalse(matches)
        self.assertFalse(legacy)
        self.assertEqual(issue, "post_cutoff_gate_without_source_hashes")
        matches, legacy, issue = self.engine.gate_source_state(config, {**base, "seq": 0})
        self.assertTrue(matches)
        self.assertTrue(legacy)
        self.assertIsNone(issue)
        protocol = {"seq": cutoff + 1,
                    "payload": {"kind": "plan_review", "result": "passed", "references": {},
                                "skill_pins": {}, "gate_protocol": 2}}
        matches, legacy, issue = self.engine.gate_source_state(config, protocol)
        self.assertEqual(issue, "gate_protocol_without_source_hashes")
        hashes_only = {"seq": cutoff + 1,
                       "payload": {"kind": "plan_review", "result": "passed", "references": {},
                                   "skill_pins": {}, "source_hashes": {"plan": "x"}}}
        matches, legacy, issue = self.engine.gate_source_state(config, hashes_only)
        self.assertEqual(issue, "source_hashes_without_gate_protocol")
        gate = self.gate("plan_review")
        self.assertEqual(gate["payload"]["gate_protocol"], 2)
        self.assertEqual(set(gate["payload"]["source_hashes"]), {"plan"})

    def test_reuse_gates_rejects_record_reuse_addition(self):
        self.completed()
        operations = self.gate_operations()
        records = self.engine.records(self.engine.current_config(False))
        operation = next(iter(records.values()))[0]
        config = self.organization_config(
            reuse=[{"operation_id": operation, "reason": "Explicit readmission of an unchanged result"}],
            reuse_gates=[{"kind": "plan_review", "operation_id": operations["plan_review"], "reason": "Same plan"},
                         {"kind": "mapping_review", "operation_id": operations["mapping_review"], "reason": "Same mapping"}])
        with self.assertRaisesRegex(delivery.DeliveryError, "unchanged admission inputs"):
            self.engine.configure(config, self.op())

    def test_legacy_gate_reuse_without_design_source(self):
        self.admitted()
        operations = self.gate_operations()
        path = self.work / "runtime/journal.json"
        data = json.loads(path.read_text())
        configure = next(event for event in data["events"] if event["kind"] == "configure")
        snapshot = self.engine.load_snapshot(configure["payload"]["monitor_baseline"])
        configure["payload"]["monitor_baseline"] = {
            "entries": snapshot["entries"], "hash": snapshot["hash"],
            "unsupported": snapshot["unsupported"]}
        for event in data["events"]:
            if event["kind"] == "gate" and event["payload"].get("config_op") == self.configuration["op"]:
                event["payload"].pop("source_hashes", None)
                event["payload"].pop("gate_protocol", None)
        previous = "0" * 64
        for number, event in enumerate(data["events"], 1):
            event["seq"] = number
            event["previous"] = previous
            body = {key: value for key, value in event.items() if key != "hash"}
            event["hash"] = delivery.digest(delivery.canonical(body))
            previous = event["hash"]
        data["schema_version"] = 1
        path.write_text(json.dumps(data))
        engine = EngineV2(self.work)
        config = self.organization_config(
            monitor={"roots": ["."], "exclude": [{"path": "vendor", "reason": "Dependency output only"}]},
            reuse_gates=[{"kind": "plan_review", "operation_id": operations["plan_review"], "reason": "Same plan"},
                         {"kind": "mapping_review", "operation_id": operations["mapping_review"], "reason": "Same mapping"}])
        new = engine.configure(config, self.op())
        self.assertTrue(all(item["legacy"] for item in new["payload"]["reused_gates"]))
        state = engine.gate_state(new)
        self.assertEqual(state["plan_review"]["status"], "passed")
        self.assertTrue(state["plan_review"]["legacy"])
        self.assertEqual(state["mapping_review"]["status"], "passed")

    def test_configure_warns_on_unexcluded_dependency_directory(self):
        self.write("node_modules/pkg/index.js", "module\n")
        self.configure()
        self.assertTrue(any(item["path"] == "node_modules" for item in self.engine.last_warnings),
                        self.engine.last_warnings)

    def test_schema_upgrade_backup_failure_leaves_schema_one(self):
        path = self.work / "runtime/journal.json"
        original = self.engine.atomic

        def failing(target, data):
            if Path(target).name == "journal.schema1.bak":
                raise OSError("backup failed")
            return original(target, data)

        self.engine.atomic = failing
        try:
            with self.assertRaises(OSError):
                self.engine.configure(self.config, self.op())
        finally:
            self.engine.atomic = original
        data = json.loads(path.read_text())
        self.assertEqual(data["schema_version"], 1)
        self.assertFalse(any(event["kind"] == "configure" for event in data["events"]))

    def test_snapshot_object_tamper_and_missing_fail_closed(self):
        self.configure()
        ref = self.engine.current_config(False)["payload"]["monitor_baseline"]
        with self.assertRaisesRegex(delivery.DeliveryError, "entries hash mismatch"):
            self.engine.load_snapshot({**ref, "entries_hash": "0" * 64})
        object_path = self.work / "runtime/objects" / ref["object_hash"]
        object_path.unlink()
        with self.assertRaisesRegex(delivery.DeliveryError, "missing or corrupted"):
            self.engine.load_snapshot(ref)

    def test_preclose_rejects_non_object_input(self):
        self.configure()
        with self.assertRaisesRegex(delivery.DeliveryError, "must be an object"):
            self.engine.preclose([])

    def test_status_write_failure_preserves_previous_view(self):
        self.configure()
        self.engine.write_status()
        path = self.work / "status.md"
        previous = path.read_bytes()
        original = self.engine.state
        self.engine.state = lambda: (_ for _ in ()).throw(delivery.DeliveryError("inventory failed"))
        try:
            with self.assertRaisesRegex(delivery.DeliveryError, "inventory failed"):
                self.engine.write_status()
        finally:
            self.engine.state = original
        self.assertEqual(path.read_bytes(), previous)

    def test_rejected_log_redacts_quoted_credentials(self):
        text = delivery.redact_rejection('{"secret": "s3cr3t", "api_key": "xyz", "token": "abc"}')
        self.assertIn("<redacted>", text)
        for value in ("s3cr3t", "xyz", "abc"):
            self.assertNotIn(value, text)

    def test_guard_blocks_then_releases_and_brief_refuses(self):
        self.configure()
        command = [sys.executable, "-B", str(SCRIPTS / "delivery.py"), "guard",
                   "--work", str(self.work), "--kind", "task", "--target", "T1"]
        blocked = self.engine.guard("task", "T1")
        self.assertFalse(blocked["ready"])
        self.assertTrue(any("gate" in reason for reason in blocked["blocked_reasons"]))
        self.assertEqual(subprocess.run(command, capture_output=True, text=True).returncode, 1)
        with self.assertRaisesRegex(delivery.DeliveryError, "guard"):
            self.engine.brief("implementation", "T1")
        self.gate("plan_review")
        self.gate("mapping_review")
        ready = self.engine.guard("task", "T1")
        self.assertTrue(ready["ready"], ready["blocked_reasons"])
        self.assertTrue(all(row["claimable"] for row in ready["resources"]))
        self.assertEqual(subprocess.run(command, capture_output=True, text=True).returncode, 0)
        brief = self.engine.brief("implementation", "T1")
        self.assertTrue(brief["guard"]["ready"])
        self.assertIn("plan", brief["source_sections"])
        self.claim("implementation", "T1", self.builder)
        blocked_actor = self.engine.guard("task", "T1", self.reviewer)
        self.assertFalse(blocked_actor["ready"])
        self.assertTrue(any("resource conflict" in reason for reason in blocked_actor["blocked_reasons"]))
        anonymous = self.engine.guard("task", "T1")
        self.assertFalse(anonymous["ready"])
        self.assertTrue(any("rerun guard with --actor" in reason for reason in anonymous["blocked_reasons"]))
        owned = self.engine.guard("task", "T1", self.builder)
        self.assertTrue(owned["ready"], owned["blocked_reasons"])
        self.claim("implementation", "T1", self.builder, "release")

    def test_close_requires_preclose_and_replays_idempotently(self):
        self.completed()
        original = self.engine.preclose
        self.engine.preclose = lambda request=None: {"ready": False, "blocking": ["synthetic preclose blocker"], "warnings": []}
        try:
            with self.assertRaisesRegex(delivery.DeliveryError, "preclose blocked"):
                self.engine.close(self.closing(), self.op())
        finally:
            self.engine.preclose = original
        self.assertEqual(self.status()["lifecycle"], "active")
        op = self.op()
        first = self.engine.close(self.closing(), op)
        before = len(self.engine.data["events"])
        second = self.engine.close(self.closing(), op)
        self.assertEqual(first["op"], second["op"])
        self.assertEqual(len(self.engine.data["events"]), before)

    def test_guard_checks_reviewer_independence(self):
        self.completed()
        builder = self.engine.guard("review", "R1", self.builder)
        self.assertFalse(builder["ready"])
        self.assertTrue(any("participated in implementation" in reason for reason in builder["blocked_reasons"]), builder)
        anonymous = self.engine.guard("review", "R1")
        self.assertFalse(anonymous["ready"])
        self.assertTrue(any("actor/context required" in reason for reason in anonymous["blocked_reasons"]), anonymous)
        independent = self.engine.guard("review", "R1", self.reviewer)
        self.assertTrue(independent["ready"], independent["blocked_reasons"])

    def test_guard_and_status_include_protected_index(self):
        subprocess.run(["git", "init", "-q"], cwd=self.project, check=True)
        self.write("protected.txt", "original user staging\n")
        subprocess.run(["git", "add", "protected.txt"], cwd=self.project, check=True)
        self.configure()
        self.gate("plan_review")
        self.gate("mapping_review")
        self.write("protected.txt", "changed user staging\n")
        subprocess.run(["git", "add", "protected.txt"], cwd=self.project, check=True)
        state = self.status()
        self.assertFalse(state["ready_to_implement"])
        self.assertTrue(any("staged entries changed" in reason for reason in state["blocked_reason"]), state)
        guard = self.engine.guard("task", "T1")
        self.assertFalse(guard["ready"])
        self.assertTrue(any("staged entries changed" in reason for reason in guard["blocked_reasons"]), guard)
        next_state = self.engine.inspect("next")
        self.assertFalse(next_state["ready_to_implement"])
        self.assertTrue(any("staged entries changed" in reason for reason in next_state["blocked_reason"]), next_state)
        self.write("protected.txt", "original user staging\n")
        subprocess.run(["git", "add", "protected.txt"], cwd=self.project, check=True)
        self.assertTrue(self.engine.guard("task", "T1")["ready"])

    def test_status_view_preserves_manual_region_and_detects_staleness(self):
        self.admitted()
        self.engine.write_status()
        path = self.work / "status.md"
        text = path.read_text()
        self.assertIn(STATUS_START, text)
        self.assertIn(STATUS_END, text)
        self.assertIn("- T1: pending", text)
        path.write_text(text.rstrip() + "\n\n## 人工补充\n\n- deployed: staging\n")
        self.engine.write_status()
        self.assertIn("deployed: staging", path.read_text())
        self.record()
        stale = self.engine.preclose()
        self.assertTrue(any("status.md is stale" in warning for warning in stale["warnings"]), stale)
        self.engine.write_status()
        fresh = self.engine.preclose()
        self.assertFalse(any("status.md is stale" in warning for warning in fresh["warnings"]), fresh)

    def test_preclose_blocks_approved_source_edit_and_accepts_close_request(self):
        self.completed()
        original = (self.project / "plan.md").read_text()
        ready = self.engine.preclose()
        self.assertTrue(ready["ready"], ready["blocking"])
        self.assertTrue(any("status.md is missing" in warning for warning in ready["warnings"]))
        self.write("plan.md", original + "Edited after approval.\n")
        edited = self.engine.preclose()
        self.assertFalse(edited["ready"])
        self.assertTrue(any("edited after approval" in item or "sources changed" in item
                            for item in edited["blocking"]), edited)
        self.write("plan.md", original)
        accepted = self.engine.preclose(self.closing())
        self.assertTrue(accepted["ready"], accepted["blocking"])

    def test_rejected_log_serializes_concurrent_attempts(self):
        self.configure()
        request = {"same": "request"}
        error = delivery.DeliveryError("same rejection")
        threads = [threading.Thread(target=delivery.record_rejection,
                                    args=(self.work, "record", "same-op", self.builder, request, error))
                   for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        lines = [json.loads(line) for line in (self.work / "runtime/rejected.jsonl").read_text().splitlines()]
        self.assertEqual(len(lines), 8)
        self.assertEqual(sorted(line["attempt"] for line in lines), list(range(1, 9)))
        self.assertEqual(len({line["id"] for line in lines}), 1)
        self.assertTrue(all(line["retry_of"] == lines[0]["id"] for line in lines[1:]))

    def test_rejected_log_is_append_only_and_skips_read_only_commands(self):
        self.configure()
        request = self.extra(actor=self.builder, kind="implementation", target="T1",
                             result="passed", summary="Attempt before gates", **self.report())
        path = self.write(".delivery/example/record.json", json.dumps(request))
        command = [sys.executable, "-B", str(SCRIPTS / "delivery.py"), "record",
                   "--work", str(self.work), "--input", str(path), "--op", "rejected-record"]
        first = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(first.returncode, 2)
        log = self.work / "runtime/rejected.jsonl"
        lines = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(lines[-1]["attempt"], 1)
        self.assertIsNone(lines[-1]["retry_of"])
        self.assertEqual(lines[-1]["error_code"], "gate_not_passed")
        second = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(second.returncode, 2)
        lines = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(lines[-1]["attempt"], 2)
        self.assertEqual(lines[-1]["retry_of"], lines[0]["id"])
        report = self.engine.rejection_report()
        self.assertEqual(report["root_details"][0]["attempts"], 2)
        self.assertEqual(report["root_details"][0]["error_code"], "gate_not_passed")
        before = len(lines)
        brief = subprocess.run([sys.executable, "-B", str(SCRIPTS / "delivery.py"), "brief",
                                "--work", str(self.work), "--kind", "implementation", "--target", "T1"],
                               capture_output=True, text=True)
        self.assertEqual(brief.returncode, 2)
        self.assertEqual(len(log.read_text().splitlines()), before)

    def test_verify_batch_is_atomic_idempotent_and_rejects_partial_replay(self):
        second = copy.deepcopy(self.config["acceptance"][0])
        second["id"] = "A2"
        self.config["acceptance"].append(second)
        self.implement_and_review()
        for target in ("A1", "A2"):
            self.claim("verification", target, self.verifier)
        items = [{**self.extra(actor=self.verifier, kind="verification", target=target,
                               result="passed", summary="Inspected actual consumer", **self.report()),
                  "op": self.op(), "config_operation": self.configuration["op"]}
                 for target in ("A1", "A2")]
        batch = {"schema_version": 2, "contract_version": 2, "batch_id": "batch-1", "items": items}
        self.engine = EngineV2(self.work)
        self.engine.load()
        before = len(self.engine.data["events"])
        result = self.engine.verify_batch(batch, "batch-call-1")
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(len(self.engine.data["events"]), before + 2)
        self.assertEqual(self.engine._inventory_scans, 1)
        replay = self.engine.verify_batch(batch, "batch-call-2")
        self.assertIn("Idempotent replay", replay["note"])
        self.assertEqual(len(self.engine.data["events"]), before + 2)
        admission = self.work / "admission"
        admission.mkdir(exist_ok=True)
        (admission / "verify-batch-001.json").write_text(json.dumps(batch))
        orphans, matched = self.engine.orphan_admissions()
        self.assertEqual(orphans, [])
        self.assertGreaterEqual(matched, 1)
        wrong_kind = copy.deepcopy(batch)
        wrong_kind["items"][0]["kind"] = "review"
        with self.assertRaisesRegex(delivery.DeliveryError, "kind must be verification"):
            self.engine.verify_batch(wrong_kind, "batch-call-review")
        wrong = copy.deepcopy(batch)
        wrong["items"] = [{**item, "config_operation": "config-other"} for item in items]
        with self.assertRaisesRegex(delivery.DeliveryError, "another configuration"):
            self.engine.verify_batch(wrong, "batch-call-wrong")
        partial = copy.deepcopy(batch)
        partial["items"] = [items[0], {**items[1], "op": "batch-new-a2"}]
        with self.assertRaisesRegex(delivery.DeliveryError, "partially exists"):
            self.engine.verify_batch(partial, "batch-call-3")
        failing = {"schema_version": 2, "contract_version": 2, "batch_id": "batch-fail",
                   "items": [{**items[0], "op": "fresh-a1"},
                             {**items[1], "op": "fresh-a2", "target": "MISSING"}]}
        with self.assertRaises(delivery.DeliveryError):
            self.engine.verify_batch(failing, "batch-call-4")
        self.assertFalse(any(event["op"] in ("fresh-a1", "fresh-a2") for event in self.engine.data["events"]))

    def test_cli_status_write_preclose_and_doctor(self):
        self.completed()
        command = [sys.executable, "-B", str(SCRIPTS / "delivery.py")]
        status = subprocess.run(command + ["status", "--work", str(self.work), "--write-status"],
                                capture_output=True, text=True)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertTrue((self.work / "status.md").is_file())
        check = subprocess.run(command + ["check", "--work", str(self.work), "--preclose"],
                               capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertTrue(json.loads(check.stdout)["ready"])
        close_request = self.write(".delivery/example/close.json", json.dumps(self.closing()))
        checked = subprocess.run(command + ["check", "--work", str(self.work), "--preclose",
                                            "--input", str(close_request)],
                                 capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        doctor = subprocess.run(command + ["doctor", "--work", str(self.work)],
                                capture_output=True, text=True)
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        self.assertEqual(json.loads(doctor.stdout)["rollback_backup"]["status"], "readable")

    def test_doctor_reports_skill_drift(self):
        self.completed()
        original = self.engine.state
        def drifted():
            state = original()
            state["skill_drift"] = [{"name": "delivery-plan", "detail": "changed"}]
            return state
        self.engine.state = drifted
        try:
            report = self.engine.doctor()
        finally:
            self.engine.state = original
        self.assertEqual(report["state"]["skill_drift"], [{"name": "delivery-plan", "detail": "changed"}])
        self.assertTrue(any("skill source drift: delivery-plan" in warning for warning in report["warnings"]), report)

    def test_doctor_matches_admission_by_request_projection(self):
        self.configure()
        admission = self.work / "admission"
        admission.mkdir()
        (admission / "config-001.json").write_text(json.dumps(self.config))
        orphans, matched = self.engine.orphan_admissions()
        self.assertEqual(matched, 1)
        self.assertEqual(orphans, [])

    def test_doctor_reports_backup_orphan_admission_and_rejection(self):
        self.admitted()
        admission = self.work / "admission"
        admission.mkdir()
        (admission / "orphan.json").write_text(json.dumps({"op": "not-a-journal-request"}))
        report = self.engine.doctor()
        self.assertEqual(report["rollback_backup"]["status"], "readable")
        self.assertEqual([item["path"] for item in report["admission"]["orphans"]], ["orphan.json"])
        self.assertTrue(report["warnings"])


if __name__ == "__main__":
    unittest.main()
