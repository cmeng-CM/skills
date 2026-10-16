"""Regression boundaries for the two independently reproduced gate gaps."""
import copy
import shutil
from pathlib import Path
import unittest

import test_delivery_fix as fix


class GateRepairCase(fix.FixFixture, unittest.TestCase):
    def completed_fix(self):
        self.command()
        source = self.fix_config()
        self.fix_record()
        self.record("review", "R1")
        run = self.execute_run()
        self.record("verification", "A1", run_operation=run["op"])
        return source, run

    def repeat_failure(self):
        request = self.extra(config_operation=self.configuration["op"],
            target={"kind": "implementation", "id": "T1"}, failure_key="BUG-001-root",
            facts=self.report()["evidence"], strategy="Inspect current owner before durable update",
            outcome="failed", report=self.report()["report"])
        self.engine.attempt(request, self.op())
        self.engine.attempt(request, self.op())
        return request

    def reconfigure(self):
        previous = self.configuration["op"]
        self.config["change"] = {"category": "organization", "previous_config": previous,
                                 "reason": "Only coordinator organization changes; no new diagnostic facts"}
        self.configure()
        self.gate("plan_review")
        self.gate("mapping_review")
        self.gate("change_review")

    def test_used_fix_drift_blocks_close_and_restore_reuses_existing_results(self):
        source, run = self.completed_fix()
        skill = source / "SKILL.md"
        original = skill.read_bytes()
        skill.write_bytes(original + b"\nChanged current professional instructions.\n")
        self.assertIn("delivery-fix", [d["name"] for d in self.status()["skill_drift"]])
        for mode in ("complete", "limited"):
            with self.assertRaisesRegex(fix.delivery.DeliveryError, "source drift"):
                self.engine.close(self.closing(mode), self.op())
        skill.write_bytes(original)
        self.engine.close(self.closing(), self.op())
        self.assertEqual(self.status()["lifecycle"], "closed")
        self.assertEqual(sum(e["kind"] == "run" for e in self.engine.data["events"]), 1)

    def test_explicit_compatible_fix_update_allows_unchanged_evidence_close(self):
        source, run = self.completed_fix()
        pin = self.engine.effective_pins(self.engine.current_config())["delivery-fix"]
        skill = source / "SKILL.md"
        skill.write_text(skill.read_text() + "\nCompatible explanatory addition.\n")
        with self.assertRaisesRegex(fix.delivery.DeliveryError, "source drift"):
            self.engine.close(self.closing(), self.op())
        self.engine.source_update(self.extra(config_operation=self.configuration["op"], name="delivery-fix",
            old_tree_hash=pin["tree_hash"], new_root=str(source), decision="compatible",
            reason="Fixture independent assessment: explanatory change, existing product evidence valid",
            affected_targets=[], **self.report()), self.op())
        self.engine.close(self.closing(), self.op())
        self.assertEqual(sum(e["kind"] == "run" for e in self.engine.data["events"]), 1)

    def test_unused_optional_fix_drift_does_not_block_default_delivery(self):
        self.enable()
        source = self.work / "unused-fix"
        shutil.copytree(fix.SCRIPTS.parents[1] / "delivery-fix", source)
        self.config["skill_sources"].append({"name": "delivery-fix", "root": str(source), "contract_version": 1})
        self.configure()
        self.gate("plan_review")
        self.gate("mapping_review")
        self.record()
        self.record("review", "R1")
        self.record("verification", "A1")
        (source / "SKILL.md").write_text((source / "SKILL.md").read_text() + "\nUnused change.\n")
        self.engine.close(self.closing(), self.op())
        self.assertEqual(self.status()["lifecycle"], "closed")

    def test_diagnosis_survives_reconfiguration_and_requires_current_new_evidence(self):
        self.fix_config()
        request = self.repeat_failure()
        self.assertTrue(self.status()["diagnosis_required"])
        self.reconfigure()
        self.reconfigure()
        self.assertTrue(self.status()["diagnosis_required"])
        with self.assertRaisesRegex(fix.delivery.DeliveryError, "diagnosis"):
            self.fix_record()
        with self.assertRaisesRegex(fix.delivery.DeliveryError, "diagnosis"):
            self.engine.close(self.closing(), self.op())
        request["config_operation"] = self.configuration["op"]
        request["outcome"] = "changed"
        request["facts"] *= 2  # Duplicating the same source is not new evidence.
        self.engine.attempt(request, self.op())
        self.assertTrue(self.status()["diagnosis_required"])
        path = ".delivery/example/new-observation.txt"
        original = "New observed call chain distinguishes an earlier hypothesis.\n"
        self.write(path, original)
        request["facts"] = [{"path": path}]
        self.engine.attempt(request, self.op())
        self.assertFalse(self.status()["diagnosis_required"])
        self.write(path, "Evidence changed after assessment.\n")
        self.assertTrue(self.status()["diagnosis_required"])
        self.write(path, original)
        self.fix_record()

    def test_same_bug_task_handoff_inherits_diagnosis(self):
        self.fix_config()
        request = self.repeat_failure()
        self.config["tasks"].append({"id": "T2", "scope": ["src"], "depends": []})
        for group in ("reviews", "acceptance", "requirements"):
            self.config[group][0]["tasks"].append("T2")
        self.config["implementation_routes"]["T2"] = copy.deepcopy(self.config["implementation_routes"]["T1"])
        self.reconfigure()
        targets = {d["id"] for d in self.status()["diagnosis_required"]}
        self.assertEqual(targets, {"T1", "T2"})
        request.update(config_operation=self.configuration["op"], target={"kind": "implementation", "id": "T2"},
                       strategy="Inspect a different consumer with a documented changed strategy", outcome="changed")
        self.engine.attempt(request, self.op())
        self.assertFalse(self.status()["diagnosis_required"])


if __name__ == "__main__":
    unittest.main()
