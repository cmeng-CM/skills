import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_doc.py"
spec = importlib.util.spec_from_file_location("check_doc", SCRIPT)
checker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = checker
spec.loader.exec_module(checker)


class DocumentChecks(unittest.TestCase):
    def document(self, extra=""):
        names = [name for name, required in checker.load_chapters() if required]
        return "# 设计\n\n" + "\n\n".join(f"## {i}. {name}\n\n已明确的行为与依据。" for i, name in enumerate(names, 1)) + "\n\n" + extra

    def errors(self, text, profile="feature-change"):
        return [f for f in checker.check_document(text, profile) if f.level == "ERROR"]

    def test_valid_document_omits_optional_chapters_and_renumbers(self):
        self.assertEqual(self.errors(self.document()), [])

    def test_optional_content_can_be_merged(self):
        text = self.document().replace("## 6.", "数据与兼容约束合并在此；无独立可选章。\n\n## 6.")
        self.assertEqual(self.errors(text), [])

    def test_missing_and_duplicate_required_chapters(self):
        name = checker.load_chapters()[0][0]
        text = self.document().replace(f"## 1. {name}", "## 1. 未覆盖该章")
        self.assertIn("missing-chapter", [f.code for f in self.errors(text)])
        text = self.document(f"## {name}\n重复内容。")
        self.assertIn("duplicate-chapter", [f.code for f in self.errors(text)])

    def test_body_mentions_do_not_replace_required_heading(self):
        name = checker.load_chapters()[0][0]
        text = self.document().replace(f"## 1. {name}", f"本文涉及{name}，但没有该章。")
        self.assertIn("missing-chapter", [f.code for f in self.errors(text)])

    def test_generic_template_does_not_require_default_titles(self):
        self.assertEqual(self.errors("# 外部模板\n\n## 运行边界\n内容完整性由语义审阅判断。", "generic"), [])

    def test_standard_changes_are_read_at_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "standard.md"
            path.write_text("**1. 新的必选内容——必选**\n**2. 新的可选内容——可选**\n")
            findings = checker.check_document("## 新的必选内容\n已写明。", standard=path)
            self.assertFalse(any(f.level == "ERROR" for f in findings))
            path.write_text("无法解释的规范")
            with self.assertRaises(ValueError):
                checker.check_document("正文", standard=path)

    def test_empty_section_and_child_content(self):
        findings = self.errors("## 空章\n<!-- 注释 -->\n## 有子节\n### 子节\n内容", "generic")
        self.assertEqual([(f.code, f.line) for f in findings], [("empty-section", 1)])

    def test_code_only_section_is_not_empty(self):
        self.assertEqual(self.errors("## 示例\n```python\nprint('hello')\n```", "generic"), [])

    def test_literal_comments_in_code_do_not_hide_content(self):
        for example in ["```html\n<!-- 注释示例 -->\n```", "    <!-- 注释示例 -->", "`<!-- 注释示例 -->`"]:
            with self.subTest(example=example):
                self.assertEqual(self.errors("## 示例\n" + example, "generic"), [])

    def test_open_comment_in_code_does_not_swallow_later_errors(self):
        for example in ["```html\n<!--\n```", "    <!--", "`<!--`"]:
            with self.subTest(example=example):
                text = "## 示例\n" + example + "\n\n## 规则\n采用 D-99。"
                errors = self.errors(text, "generic")
                self.assertEqual([f.code for f in errors], ["undefined-decision"])
                self.assertEqual(errors[0].line, len(text.splitlines()))

    def test_quoted_code_is_explicitly_unchecked(self):
        text = "## 示例\n> ```markdown\n> ## 假标题\n> D-99\n> [示例](#missing)\n> ```"
        findings = checker.check_document(text, "generic")
        self.assertFalse(any(f.level == "ERROR" for f in findings), findings)
        self.assertTrue(any(f.code == "unchecked-blockquote" for f in findings))

    def test_possible_quoted_anchors_remain_uncertain(self):
        for example, target in [
            ("> ## 机制\n> 引用内容。", "机制"),
            ("> > ## 机制 {#custom}\n> > 引用内容。", "custom"),
            ("> 机制\n> ----\n> 引用内容。", "机制"),
            ('> <a id="custom"></a>', "custom"),
        ]:
            with self.subTest(example=example):
                text = example + f"\n\n[见机制](#{target})\n[错误](#actually-missing)"
                findings = checker.check_document(text, "generic")
                errors = [f for f in findings if f.level == "ERROR"]
                self.assertEqual([f.code for f in errors], ["missing-anchor"])
                self.assertIn("actually-missing", errors[0].message)
                self.assertTrue(any(f.code == "unchecked-anchor" for f in findings))

    def test_nested_short_fences_are_examples_not_structure(self):
        text = self.document("## 示例\n````markdown\n```\n## 假标题\nD-99\n[假链接](#missing)\n```\n````")
        self.assertEqual(self.errors(text), [])

    def test_frontmatter_comments_and_indented_code_are_not_references(self):
        text = "---\ndecision: D-98\n---\n" + self.document("<!--\nD-99\n## 空章\n-->\n\n    D-97\n    [假链接](#none)\n")
        self.assertEqual(self.errors(text), [])

    def test_decision_definition_and_repeated_references(self):
        text = self.document("| 编号 | 决定 |\n|---|---|\n| **D-01** | 保留行为 |\n\n采用 D-01，与 `D-01` 相同。")
        self.assertEqual(self.errors(text), [])

    def test_definition_column_need_not_be_first(self):
        text = self.document("| 决定 | ID |\n|---|---|\n| 保留行为 | D-01 |\n\n引用 D-01。")
        self.assertEqual(self.errors(text), [])

    def test_combined_identifier_and_decision(self):
        text = self.document("| 编号与决定 | 理由 |\n|---|---|\n| D-01 保持默认行为 | 兼容 |\n\n引用 D-01。")
        self.assertEqual(self.errors(text), [])

    def test_pipe_tables_allow_optional_outer_pipes(self):
        for header, separator, row in [
            ("编号 | 决定", "--- | ---", "D-01 | 保持兼容"),
            ("| 编号 | 决定", "| --- | ---", "| D-01 | 保持兼容"),
            ("编号 | 决定 |", "--- | --- |", "D-01 | 保持兼容 |"),
        ]:
            with self.subTest(header=header):
                text = "## 决策\n" + "\n".join([header, separator, row]) + "\n\n采用 D-01。"
                self.assertEqual(self.errors(text, "generic"), [])

    def test_references_in_other_table_columns_are_not_definitions(self):
        text = self.document("### D-01 保持默认\n已确认。\n\n| 验收项 | 决策引用 |\n|---|---|\n| A1 | D-01 |\n| A2 | D-01 |")
        self.assertEqual(self.errors(text), [])

    def test_duplicate_and_undefined_decisions_have_locations(self):
        text = "## D-01 首个决定\n内容。\n## D-01 第二个决定\n引用 D-02。"
        findings = self.errors(text, "generic")
        self.assertEqual([(f.code, f.line) for f in findings], [("duplicate-decision", 3), ("undefined-decision", 4)])

    def test_linked_external_decisions_are_not_local(self):
        text = self.document("引用 [D-99](other-design.md#d-99) 与 [D-98][upstream]。\n\n[upstream]: other.md#d-98")
        self.assertEqual(self.errors(text), [])

    def test_shortcut_and_collapsed_external_decisions(self):
        text = "## 内容\n引用 [D-99] 和 [D-98][]。\n\n[D-99]: other.md#d-99\n[D-98]: other.md#d-98"
        self.assertEqual(self.errors(text, "generic"), [])

    def test_local_links_still_require_decision_definitions(self):
        for link, definition in [
            ("[缺失决定 D-99](#内容)", ""),
            ("[缺失决定 D-99][local]", "[local]: #内容"),
            ("[D-99][]", "[D-99]: #内容"),
            ("[D-99]", "[D-99]: #内容"),
        ]:
            with self.subTest(link=link):
                text = "## 内容\n" + link + "\n\n" + definition
                self.assertEqual([f.code for f in self.errors(text, "generic")], ["undefined-decision"])

    def test_unknown_link_target_is_unchecked_not_inferred_local(self):
        findings = checker.check_document("## 内容\n[D-99][absent]", "generic")
        self.assertFalse(any(f.level == "ERROR" for f in findings), findings)
        self.assertTrue(any(f.code == "unchecked-decision" for f in findings))

    def test_pending_status_is_not_a_placeholder_or_error(self):
        findings = checker.check_document(self.document("事项待确认；效果待实测；当前未实施。"))
        self.assertEqual(findings, [])

    def test_placeholder_is_only_a_warning(self):
        findings = checker.check_document(self.document("TODO: 补充内容；{{owner}}"))
        self.assertEqual([f.level for f in findings], ["WARNING"])

    def test_local_anchors_with_duplicates_and_percent_encoding(self):
        text = "## 标题\n内容。\n## 标题\n内容。\n[再次](#标题-1) [编码](#%E6%A0%87%E9%A2%98)"
        self.assertEqual(self.errors(text, "generic"), [])

    def test_inline_code_link_is_not_an_active_link(self):
        self.assertEqual(self.errors("## 示例\n`[示意](#no-anchor)`", "generic"), [])

    def test_missing_anchor_and_reference_style_anchor(self):
        text = "## 说明\n[有效][good] 与 [错误](#不存在)\n\n[good]: #说明"
        findings = self.errors(text, "generic")
        self.assertEqual([(f.code, f.line) for f in findings], [("missing-anchor", 2)])

    def test_shortcut_anchors_are_checked(self):
        text = "## 内容\n[错误] [正确]\n\n[错误]: #missing\n[正确]: #内容"
        self.assertEqual([(f.code, f.line) for f in self.errors(text, "generic")], [("missing-anchor", 2)])

    def test_escaped_brackets_are_not_active_links(self):
        text = "## 内容\n\\[示例](#missing) \\[示例][missing]"
        self.assertEqual(checker.check_document(text, "generic"), [])
        # Two backslashes escape each other; the following link is active.
        self.assertEqual([f.code for f in self.errors("## 内容\n\\\\[示例](#missing)", "generic")], ["missing-anchor"])

    def test_emphasized_anchors_keep_literal_underscores(self):
        for title, anchor in [("__行为约束__", "行为约束"), ("_行为约束_", "行为约束"), ("render_label", "render_label"), ("`_literal_`", "_literal_")]:
            with self.subTest(title=title):
                self.assertEqual(self.errors(f"## {title}\n内容。\n[引用](#{anchor})", "generic"), [])

    def test_explicit_html_anchor(self):
        self.assertEqual(self.errors('<a id="custom"></a>\n[引用](#custom)', "generic"), [])

    def test_unsupported_extended_anchor_is_unchecked_not_false_error(self):
        findings = checker.check_document("## 名称 {#custom}\n内容。\n[引用](#custom)", "generic")
        self.assertFalse(any(f.level == "ERROR" for f in findings))
        self.assertTrue(any(f.level == "WARNING" for f in findings))

    def test_other_html_and_setext_anchors_are_unchecked(self):
        for text in ['<div id="custom">内容</div>\n[引用](#custom)', 'Setext\n======\n内容。\n[引用](#setext)']:
            findings = checker.check_document(text, "generic")
            self.assertFalse(any(f.level == "ERROR" for f in findings), findings)
            self.assertTrue(any(f.level == "WARNING" for f in findings))

    def test_uncertain_heading_does_not_become_false_missing_chapter(self):
        name = checker.load_chapters()[0][0]
        heading = f"## 1. {name}"
        for replacement in [heading + " {#custom}", f"1. {name}\n-----"]:
            with self.subTest(replacement=replacement):
                text = self.document().replace(heading, replacement)
                findings = checker.check_document(text)
                self.assertFalse(any(f.level == "ERROR" for f in findings), findings)
                self.assertTrue(any(f.code == "unchecked-chapter" for f in findings))
                # Uncertainty about this chapter must not hide a genuinely missing one.
                text = text.replace("## 2. 现状分析与影响范围", "## 2. 其他内容")
                errors = self.errors(text)
                self.assertEqual([f.code for f in errors], ["missing-chapter"])
                self.assertIn("现状分析与影响范围", errors[0].message)

    def test_unparsed_table_definition_is_not_reported_as_missing(self):
        text = self.document('| ID | 内容 |\n|---|---|\n| D-01 | a | b |\n\n引用 D-01。')
        findings = checker.check_document(text)
        self.assertFalse(any(f.level == "ERROR" for f in findings), findings)
        self.assertTrue(any(f.code == "unchecked-decision" for f in findings))

    def test_future_file_links_are_not_checked_for_existence(self):
        self.assertEqual(self.errors(self.document("计划新增 [模块](../not-created-yet.py)；没有虚构存在状态。")), [])

    def test_empty_document_is_reported(self):
        self.assertIn("empty-document", [f.code for f in self.errors("<!-- empty -->", "generic")])

    def test_cli_exit_codes_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            for text, expected in [(self.document(), 0), (self.document("TODO"), 0), (self.document("D-99"), 1)]:
                path.write_text(text, encoding="utf-8")
                before = hashlib.sha256(path.read_bytes()).digest()
                result = subprocess.run([sys.executable, "-B", str(SCRIPT), str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)
                self.assertEqual(list(Path(tmp).iterdir()), [path])
            missing = subprocess.run([sys.executable, "-B", str(SCRIPT), str(Path(tmp) / "missing.md")], capture_output=True)
            self.assertEqual(missing.returncode, 2)
            path.write_bytes(b"\xff\xfe\x00")
            invalid = subprocess.run([sys.executable, "-B", str(SCRIPT), str(path)], capture_output=True)
            self.assertEqual(invalid.returncode, 2)

    def test_invalid_profile_is_input_error(self):
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), "unused.md", "--profile", "other"], capture_output=True)
        self.assertEqual(result.returncode, 2)


class SkillResources(unittest.TestCase):
    def test_runtime_standard_retains_six_required_five_optional(self):
        chapters = checker.load_chapters()
        self.assertEqual(len(chapters), 11)
        self.assertEqual(sum(required for _, required in chapters), 6)
        self.assertEqual(len({title for title, _ in chapters}), 11)

    def test_local_resource_links_are_reachable(self):
        paths = [ROOT / "SKILL.md", *sorted((ROOT / "references").glob("*.md"))]
        for path in paths:
            for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
                if "://" not in target and not target.startswith("#") and "<" not in target:
                    self.assertTrue((path.parent / target.split("#", 1)[0]).exists(), (path, target))

    def test_old_test_file_removed_and_new_cases_have_observable_criteria(self):
        self.assertFalse((ROOT / "test-prompts.json").exists())
        cases = json.loads((ROOT / "tests/behavior-cases.json").read_text())
        self.assertGreaterEqual(len(cases["cases"]), 6)
        identifiers = [case["id"] for case in cases["cases"]]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        for case in cases["cases"]:
            self.assertTrue(case["prompt"] and case["expected"] and case["forbidden"])


if __name__ == "__main__":
    unittest.main()
