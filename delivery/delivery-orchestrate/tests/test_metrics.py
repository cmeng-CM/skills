"""Metrics collector regression tests."""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import collect_metrics


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.usage = self.root / "usage.csv"
        with self.usage.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["session_id", "model_id", "input_tokens", "output_tokens",
                             "cache_read_input_tokens", "cache_creation_input_tokens", "duration_ms"])
            writer.writerow(["s1", "m1", 1000, 100, 800, 0, 1200])
            writer.writerow(["s1", "m1", 2000, 200, 1600, 0, 1800])
            writer.writerow(["s2", "m2", 500, 50, 0, 0, 300])

    def test_tokens_and_uncached(self):
        total, sessions = collect_metrics.summarize_usage(self.usage, {})
        self.assertEqual(total["requests"], 3)
        self.assertEqual(total["input_tokens"], 3500)
        self.assertEqual(total["uncached_input_tokens"], 1100)
        self.assertEqual(total["cache_read_tokens"], 2400)
        self.assertEqual(total["output_tokens"], 350)
        self.assertIsNone(total["cost"])
        self.assertEqual(sessions["s1"]["requests"], 2)

    def test_cost_requires_all_rows(self):
        price = self.root / "price.csv"
        with price.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["model_id", "input_per_mtok", "output_per_mtok",
                             "cache_read_per_mtok", "cache_write_per_mtok"])
            writer.writerow(["m1", 1, 2, 0.1, 1])
        total, _ = collect_metrics.summarize_usage(self.usage, collect_metrics.load_prices(price))
        self.assertIsNone(total["cost"])
        with price.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["m2", 1, 2, 0.1, 1])
        total, _ = collect_metrics.summarize_usage(self.usage, collect_metrics.load_prices(price))
        self.assertAlmostEqual(total["cost"], 0.00204, places=6)
        self.assertEqual(total["priced_requests"], 3)


if __name__ == "__main__":
    unittest.main()
