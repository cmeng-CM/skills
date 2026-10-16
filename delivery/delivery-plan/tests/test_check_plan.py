import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'check_plan.py'
spec = importlib.util.spec_from_file_location('implementation_plan_check', SCRIPT)
checker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = checker
spec.loader.exec_module(checker)


def codes(report):
    return {finding['code'] for finding in report['findings']}


def definitions(*ids):
    return '\n| ID | 含义 |\n| --- | --- |\n' + ''.join(f'| {key} | 对象 |\n' for key in ids)


def relations(*edges):
    return '\n| 满足条件 | 后续对象 | 依赖类型 | 前置对象 |\n| --- | --- | --- | --- |\n' + ''.join(
        f'| {condition} | {after} | {kind} | {before} |\n' for before, after, kind, condition in edges)


class PlanCheckTests(unittest.TestCase):
    def test_duplicate_primary_heading_but_allow_summary_and_record_views(self):
        text = definitions('T-01') + '\n## T-01 成果\n' + definitions('T-01')
        self.assertTrue(checker.check_text(text)['ok'])
        self.assertIn('duplicate-heading-id', codes(checker.check_text(text + '\n## T-01 另一成果\n')))

    def test_duplicate_rows_inside_definition_table(self):
        self.assertIn('duplicate-table-id', codes(checker.check_text(definitions('AC-01', 'AC-01'))))

    def test_unknown_internal_id_and_explicit_external_source(self):
        report = checker.check_text(definitions('T-01') + '\nT-01 覆盖 AC-99。\n')
        self.assertFalse(report['ok'])
        self.assertIn('unresolved-reference', codes(report))
        external = '\n## 外部引用\n| ID | 来源 |\n| --- | --- |\n| AC-99 | design.md 第 10 章，v2 |\n'
        self.assertTrue(checker.check_text(definitions('T-01') + external + '\nAC-99\n')['ok'])

    def test_external_reference_requires_source(self):
        report = checker.check_text('## 外部引用\n| ID | 来源 |\n| --- | --- |\n| AC-99 | |\n')
        self.assertIn('external-source-empty', codes(report))

    def test_cycle_combines_task_and_verification_gate(self):
        text = definitions('T-01', 'T-02', 'V-01') + relations(
            ('T-01', 'T-02', '产物可接入', '契约可用'),
            ('T-02', 'V-01', '验证前置', '接线完成'),
            ('V-01', 'T-01', '验证通过', '必需验证'))
        report = checker.check_text(text)
        self.assertIn('dependency-cycle', codes(report))
        self.assertTrue(all(finding['line'] > 0 for finding in report['findings']))

    def test_joint_verification_does_not_create_gate(self):
        text = definitions('T-01', 'T-02', 'V-01') + relations(
            ('T-01', 'T-02', '产物可接入', '接口已实现'),
            ('T-01', 'V-01', '验证前置', '产物存在'),
            ('T-02', 'V-01', '验证前置', '接线完成'))
        self.assertTrue(checker.check_text(text)['ok'])
        self.assertEqual(checker.check_text(text)['counts']['dependency_edges'], 3)

    def test_missing_conditions_and_unparsed_relation_are_disclosed(self):
        text = definitions('T-01', 'T-02') + relations(('T-01', 'T-02', '产物可接入', ''))
        self.assertIn('dependency-condition-empty', codes(checker.check_text(text)))
        text = definitions('T-01', 'T-02') + relations(('T-01', 'T-02', '自行决定', '约定'))
        report = checker.check_text(text)
        self.assertIn('dependency-type-unparsed', codes(report))
        self.assertEqual(report['counts']['dependency_edges'], 0)

    def test_future_task_may_defer_details(self):
        text = '## T-02 后续成果\n| 字段 | 内容 |\n| --- | --- |\n| 细化状态 | 待细化 |\n| 待细化说明 | T-01 形成后核对真实接口再补步骤 |\n' + definitions('T-01')
        self.assertTrue(checker.check_text(text)['ok'])
        self.assertIn('refinement-condition-empty', codes(checker.check_text(text.replace('T-01 形成后核对真实接口再补步骤', ''))))

    def test_detailed_card_requires_fields_and_steps(self):
        text = '## T-01 成果\n| 字段 | 内容 |\n| --- | --- |\n| 细化状态 | 已细化 |\n'
        report = checker.check_text(text)
        self.assertIn('task-field-empty', codes(report))
        self.assertIn('task-steps-empty', codes(report))
        fields = ['目标与交付物', '设计引用', '修改边界', '启动条件', '必读材料', '涉及文件', '验收归属', '反馈触发']
        for label in fields:
            text += f'| {label} | 明确引用 |\n'
        text += '\n1. 修改入口并形成产物。\n'
        self.assertTrue(checker.check_text(text)['ok'])

    def test_ignore_fences_comments_and_link_destinations(self):
        text = definitions('T-01') + '\n```markdown\n## T-01 重复示例\nAC-99\n```\n<!-- V-99 -->\n[T-01](https://example.test/AC-98)\n'
        self.assertTrue(checker.check_text(text)['ok'])

    def test_repeated_task_conditions_cannot_silently_override(self):
        text = '## T-01 成果\n| 字段 | 内容 |\n| --- | --- |\n| 启动条件 | 无 |\n| 启动条件 | 等待确认 |\n'
        self.assertIn('duplicate-task-field', codes(checker.check_text(text)))

    def test_unstructured_document_discloses_unchecked_scope(self):
        report = checker.check_text('# 计划\n随后实现并验证。\n')
        self.assertIn('no-recognized-ids', codes(report))
        self.assertTrue(any('未检查联合依赖循环' in item for item in report['scope']))

    def test_markdown_pipes_do_not_corrupt_columns(self):
        self.assertEqual(checker.cells('| a | `x|y` | a\\|b |'), ['a', '`x|y`', 'a\\|b'])
        self.assertNotIn('table-width', codes(checker.check_text(definitions('T-01') + '| T-02 | `x|y` |\n')))

    def test_cli_is_read_only_and_json_exit_codes_are_meaningful(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'plan.md'
            path.write_text(definitions('T-01'), encoding='utf-8')
            before = path.read_bytes()
            good = subprocess.run([sys.executable, '-B', str(SCRIPT), str(path), '--json'], capture_output=True, text=True)
            self.assertEqual(good.returncode, 0)
            self.assertTrue(json.loads(good.stdout)['ok'])
            self.assertEqual(path.read_bytes(), before)
            path.write_text('AC-99', encoding='utf-8')
            bad = subprocess.run([sys.executable, '-B', str(SCRIPT), str(path), '--json'], capture_output=True, text=True)
            self.assertEqual(bad.returncode, 1)
            missing = subprocess.run([sys.executable, '-B', str(SCRIPT), str(path.with_name('missing.md')), '--json'], capture_output=True, text=True)
            self.assertEqual(missing.returncode, 2)
            self.assertIn('input_error', json.loads(missing.stdout))


if __name__ == '__main__':
    unittest.main()
