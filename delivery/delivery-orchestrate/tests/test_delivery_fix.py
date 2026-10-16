"""Optional fix admission boundaries. These fixtures do not establish agent quality."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

import test_delivery_v2 as legacy

delivery = legacy.delivery
SCRIPTS = legacy.SCRIPTS


class FixCase(unittest.TestCase):
    # Reuse the public fixture helpers, without inheriting/rerunning its tests.
    setUp = legacy.V2Case.setUp
    write = legacy.V2Case.write
    op = legacy.V2Case.op
    extra = legacy.V2Case.extra
    report = legacy.V2Case.report
    configure = legacy.V2Case.configure
    gate = legacy.V2Case.gate
    claim = legacy.V2Case.claim
    record = legacy.V2Case.record
    closing = legacy.V2Case.closing
    command = legacy.V2Case.command
    execute_run = legacy.V2Case.execute_run
    status = legacy.V2Case.status

    def enable(self, op=None):
        return self.engine.enable_fix(self.extra(implementation_contract_version=1, reason="Explicit complex fault capability"), op or self.op())

    def fix_config(self):
        self.enable()
        source = self.work / "fix-package"
        shutil.copytree(SCRIPTS.parents[1] / "delivery-fix", source)
        self.config["skill_sources"] = [p for p in self.config["skill_sources"] if p["name"] != "delivery-implement"]
        self.config["skill_sources"].append({"name": "delivery-fix", "root": str(source), "contract_version": 1})
        self.bug_path = ".delivery/example/fixes/BUG-001-persistence"
        self.config["implementation_routes"] = {"T1": {"skill": "delivery-fix", "bug_id": "BUG-001", "bug_path": self.bug_path}}
        self.fix_report = {"path": self.bug_path + "/001/fix.md"}
        self.write(self.fix_report["path"], "Observed failure, diagnosis, authorized correction, selfcheck, pending independent review.\n")
        self.configure()
        self.gate("plan_review")
        self.gate("mapping_review")
        return source

    def fix_record(self, **changes):
        fields = dict(report=self.fix_report, implementation_skill="delivery-fix", implementation_authors=[self.builder])
        fields.update(changes)
        return self.record(**fields)

    def test_original_work_without_fix_source_still_closes(self):
        self.command()
        self.configure()
        self.gate("plan_review")
        self.gate("mapping_review")
        record = self.record()
        self.assertEqual(record["payload"]["skill_pin"]["name"], "delivery-implement")
        self.assertNotIn("implementation_skill", record["payload"])
        self.record("review", "R1")
        run = self.execute_run()
        self.record("verification", "A1", run_operation=run["op"])
        self.engine.close(self.closing(), self.op())
        self.assertFalse(self.engine.fix_enabled())

    def test_enable_cli_idempotence_and_unknown_contract(self):
        input_path = self.write(".delivery/example/enable.json", json.dumps(self.extra(implementation_contract_version=1, reason="Explicit selection")))
        command = [sys.executable, "-B", str(SCRIPTS / "delivery.py"), "enable-fix", "--work", str(self.work), "--input", str(input_path), "--op", "enable"]
        first = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        retry = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(json.loads(first.stdout), json.loads(retry.stdout))
        with self.engine.locked():
            self.assertEqual(sum(e["kind"] == "implementation-protocol" for e in self.engine.data["events"]), 1)
        with self.assertRaisesRegex(delivery.DeliveryError, "unsupported implementation contract"):
            self.engine.enable_fix(self.extra(implementation_contract_version=True, reason="bad"), self.op())

    def test_routes_need_enable_and_valid_sources(self):
        self.config["implementation_routes"] = {"T1": {"skill": "delivery-implement"}}
        with self.assertRaisesRegex(delivery.DeliveryError, "enable-fix"):
            self.configure()
        self.enable()
        self.config["implementation_routes"] = {"T1": {"skill": "delivery-fix", "bug_id": "BUG-001", "bug_path": ".delivery/example/fixes/BUG-001"}}
        with self.assertRaisesRegex(delivery.DeliveryError, "missing used professional source: delivery-fix"):
            self.configure()

    def test_fix_uses_actual_pin_report_and_full_author_exclusions(self):
        self.fix_config()
        earlier = {"id": "earlier-author", "context": "earlier-implementation"}
        record = self.fix_record(implementation_authors=[self.builder, earlier])
        self.assertEqual(record["payload"]["skill_pin"]["name"], "delivery-fix")
        self.assertIn(earlier, self.engine.brief("review", "R1")["excluded_implementation_authors"])
        brief = self.engine.brief("implementation", "T1")
        self.assertEqual(brief["skill"], "delivery-fix")
        self.assertEqual(brief["report_location"], self.bug_path + "/NNN/fix.md")
        self.claim("review", "R1", earlier)
        try:
            with self.assertRaisesRegex(delivery.DeliveryError, "participated in implementation"):
                self.record("review", "R1", actor=earlier, claim=False)
        finally:
            self.claim("review", "R1", earlier, "release")
        # A later author list cannot erase a prior contributor.
        self.write(self.bug_path + "/002/fix.md", "Second round with inherited diagnosis.\n")
        second = self.fix_record(report={"path": self.bug_path + "/002/fix.md"})
        self.assertIn(earlier, second["payload"]["implementation_authors"])
        self.assertTrue(self.engine.independent(self.reviewer, ["T1"]))

    def test_same_bug_new_task_inherits_known_authors(self):
        self.fix_config()
        self.fix_record()
        previous = self.configuration["op"]
        self.config["tasks"].append({"id": "T2", "scope": ["src"], "depends": []})
        self.config["reviews"][0]["tasks"].append("T2")
        self.config["acceptance"][0]["tasks"].append("T2")
        self.config["requirements"][0]["tasks"].append("T2")
        self.config["implementation_routes"]["T2"] = copy.deepcopy(self.config["implementation_routes"]["T1"])
        self.config["change"] = {"category": "within_grant", "previous_config": previous, "reason": "Follow-up activity on the same bug"}
        self.configure()
        self.assertFalse(self.engine.independent(self.builder, ["T2"]))
        self.assertIn(self.builder, self.engine.brief("review", "R1")["excluded_implementation_authors"])

    def test_invalid_fix_record_and_partial_diagnosis_cannot_close(self):
        self.fix_config()
        with self.assertRaisesRegex(delivery.DeliveryError, "fix requires explicit"):
            self.record(report=self.fix_report)
        with self.assertRaisesRegex(delivery.DeliveryError, "does not match"):
            self.fix_record(implementation_skill="delivery-implement")
        with self.assertRaisesRegex(delivery.DeliveryError, "NNN/fix.md"):
            self.fix_record(report={"path": ".delivery/example/report.md"})
        self.fix_record(result="unknown")
        with self.assertRaises(delivery.DeliveryError):
            self.engine.close(self.closing(), self.op())
        self.fix_record(supersedes=self.status()["implementation"]["T1"]["operation_id"], reason="Actual implementation now established")
        with self.assertRaises(delivery.DeliveryError):
            self.engine.close(self.closing(), self.op())

    def test_fix_source_and_evidence_changes_invalidate(self):
        source = self.fix_config()
        self.fix_record()
        self.record("review", "R1")
        self.record("verification", "A1")
        self.write(self.fix_report["path"], "Changed report must not retain approval.\n")
        self.assertEqual(self.status()["implementation"]["T1"]["status"], "stale")
        with self.assertRaises(delivery.DeliveryError):
            self.engine.close(self.closing(), self.op())
        (source / "SKILL.md").write_text((source / "SKILL.md").read_text() + "\nChanged actual fix instructions.\n")
        self.assertNotIn("T1", [row["target"] for row in self.engine.inspect("next")["ready"]])
        with self.assertRaisesRegex(delivery.DeliveryError, "source drift"):
            self.fix_record()

    def test_transfer_preserves_authors_and_rejects_old_result_reuse(self):
        self.configure()
        self.gate("plan_review")
        self.gate("mapping_review")
        old = self.record()
        previous_config = self.configuration["op"]
        self.enable()
        self.config["implementation_routes"] = {"T1": {"skill": "delivery-fix", "bug_id": "BUG-001", "bug_path": ".delivery/example/fixes/BUG-001"}}
        self.config["skill_sources"].append({"name": "delivery-fix", "root": str(SCRIPTS.parents[1] / "delivery-fix"), "contract_version": 1})
        self.config["change"] = {"category": "within_grant", "previous_config": previous_config, "reason": "New diagnosis required"}
        self.config["reuse"] = [{"operation_id": old["op"], "reason": "Attempted reuse of old pass"}]
        with self.assertRaisesRegex(delivery.DeliveryError, "changed implementation route"):
            self.configure()
        self.config.pop("reuse")
        self.configure()
        self.assertEqual(self.status()["implementation"]["T1"]["status"], "pending")
        self.assertIn(self.builder, self.engine.brief("review", "R1")["excluded_implementation_authors"])
        with self.assertRaises(delivery.DeliveryError):
            self.engine.close(self.closing(), self.op())
        # Omitting routes or moving the same bug to a new folder is rejected.
        self.config["change"]["previous_config"] = self.configuration["op"]
        saved = self.config.pop("implementation_routes")
        with self.assertRaisesRegex(delivery.DeliveryError, "preserve or replace"):
            self.configure()
        self.config["implementation_routes"] = copy.deepcopy(saved)
        self.config["implementation_routes"]["T1"]["bug_path"] += "-moved"
        with self.assertRaisesRegex(delivery.DeliveryError, "same bug"):
            self.configure()

    def test_fix_real_command_close_and_frozen_rounds(self):
        self.command()
        self.fix_config()
        self.fix_record()
        self.record("review", "R1")
        run = self.execute_run()
        self.record("verification", "A1", run_operation=run["op"])
        self.engine.close(self.closing(), self.op())
        self.assertEqual(self.status()["lifecycle"], "closed")
        self.assertEqual((self.project / self.fix_report["path"]).read_text(), "Observed failure, diagnosis, authorized correction, selfcheck, pending independent review.\n")


class PackageCase(unittest.TestCase):
    def test_optional_package_absence_and_explicit_requirement(self):
        spec = importlib.util.spec_from_file_location("check_fix_packages", SCRIPTS / "check_suite.py")
        package = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(package)
        root = SCRIPTS.parents[1]
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            selected = Path(folder)
            for name in package.NAMES:
                shutil.copytree(root / name, selected / name)
            self.assertTrue(package.check(selected)["ok"])
            self.assertFalse(package.check(selected, require_fix=True)["ok"])


if __name__ == "__main__":
    unittest.main()
