import unittest

from label import label


class LabelContractTests(unittest.TestCase):
    def test_default_call_keeps_previous_trim_behavior(self):
        self.assertEqual(label(" x "), "x")
        self.assertEqual(label("\t旧调用\n"), "旧调用")

    def test_prefix_whitespace_is_preserved_without_separator(self):
        self.assertEqual(label(" x ", prefix=" p "), " p x")
        self.assertEqual(label("\n正文\t", prefix="\t前缀\n"), "\t前缀\n正文")

    def test_empty_body_retains_only_prefix(self):
        self.assertEqual(label("   ", prefix="p"), "p")
        self.assertEqual(label("", prefix=""), "")

    def test_chinese_prefix_is_literal(self):
        self.assertEqual(label(" x ", prefix="中文"), "中文x")

    def test_prefix_cannot_be_passed_positionally(self):
        with self.assertRaises(TypeError):
            label("x", "p")


if __name__ == "__main__":
    unittest.main()
