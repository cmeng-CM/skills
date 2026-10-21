"""Policy documentation regression for the quality-cost workflow."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class QualityCostPolicyTests(unittest.TestCase):
    def read(self, relative):
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_design_and_plan_policy_is_present(self):
        design = self.read("delivery-design/SKILL.md")
        plan = self.read("delivery-plan/SKILL.md")
        self.assertIn("合同包", design)
        self.assertIn("真实入口", design)
        self.assertIn("任务图", plan)
        self.assertIn("final/close", plan)
        self.assertIn("独立 review/verify", plan)

    def test_implementation_and_verification_policy_is_present(self):
        implement = self.read("delivery-implement/SKILL.md")
        verify = self.read("delivery-verify/SKILL.md")
        self.assertIn("只消费", implement)
        self.assertIn("红测", implement)
        self.assertIn("所有功能任务", verify)
        self.assertIn("first-pass", verify)

    def test_review_and_orchestration_policy_is_present(self):
        review = self.read("delivery-review/SKILL.md")
        orchestrate = self.read("delivery-orchestrate/SKILL.md")
        metrics = self.read("delivery-orchestrate/references/metrics.md")
        self.assertIn("blocker、defect、observation", review)
        self.assertIn("verifier", review)
        self.assertIn("final whole review", orchestrate)
        self.assertIn("review_protocol=2", orchestrate)
        self.assertIn("usage_by_task_phase.csv", metrics)


if __name__ == "__main__":
    unittest.main()
