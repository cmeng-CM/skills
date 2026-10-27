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

    def test_routing_and_evidence_policy_is_present(self):
        implement = self.read("delivery-implement/SKILL.md")
        implement_contract = self.read("delivery-implement/references/delivery-contract.md")
        orchestrate = self.read("delivery-orchestrate/SKILL.md")
        verify_standard = self.read("delivery-verify/references/verification-standard.md")
        review_standard = self.read("delivery-review/references/review-standard.md")
        for hard_feature in ("不可逆 DDL", "生产环境部署"):
            self.assertIn(hard_feature, orchestrate)
            self.assertIn(hard_feature, implement)
        self.assertIn("路由硬特征", orchestrate)
        self.assertIn("单行留痕", implement_contract)
        self.assertIn("部署差异与核验", self.read("delivery-implement/references/implementation-standard.md"))
        self.assertIn("前置满足", verify_standard)
        self.assertIn("不得取「符合」", verify_standard)
        self.assertIn("条件清单", review_standard)
        self.assertIn("待复审", review_standard)

    def test_metrics_input_production_policy_is_present(self):
        metrics = self.read("delivery-orchestrate/references/metrics.md")
        self.assertIn("export_session_usage.py", metrics)
        self.assertIn("UNAVAILABLE.md", metrics)
        self.assertIn("输入生产", metrics)


if __name__ == "__main__":
    unittest.main()
