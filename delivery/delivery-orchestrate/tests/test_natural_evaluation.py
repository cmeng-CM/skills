"""Deterministic natural-input/catalog checks, not real model routing scores."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'scripts' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


H, S, C = (module(name) for name in ('evaluate_suite', 'external_seatbelt', 'check_suite'))


class NaturalEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.skills = self.root / 'skills'
        for name in H.NATURAL_SKILLS:
            package = self.skills / name
            (package / 'agents').mkdir(parents=True)
            (package / 'SKILL.md').write_text('---\nname: ' + name + '\ndescription: Public purpose\n---\n')
            (package / 'agents/openai.yaml').write_text('policy:\n  allow_implicit_invocation: true\n')
        (self.root / 'fixture').mkdir()
        (self.root / 'fixture/app.py').write_text('print("current")\n')
        self.case = {'schema_version': 1, 'id': 'natural-unit', 'activation': 'natural',
                     'mode': 'standalone', 'skills': list(H.NATURAL_SKILLS), 'fixture': 'fixture',
                     'prompt': '请给命令增加可选的输出文件参数，检查后完成修改。',
                     'expected': ['PRIVATE_ROUTE'], 'forbidden': ['PRIVATE_ANSWER'],
                     'requirements': ['正常调用结果保持兼容'], 'allowed_changes': ['代码和必要测试']}
        self.case_path = self.root / 'case.json'
        H.save(self.case_path, self.case)
        self.output = self.root / 'output'

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self):
        H.prepare(self.case_path, self.skills, self.output, 'candidate')
        workspace = Path(H.load(self.output / 'evaluation.json')['workspace'])
        self.addCleanup(shutil.rmtree, workspace, ignore_errors=True)
        return workspace

    def test_natural_supply_all_seven_but_public_request_does_not_reveal_route(self):
        workspace = self.prepare()
        self.assertEqual(set(H.NATURAL_SKILLS), {p.name for p in (workspace / '.agents/skills').iterdir()})
        public = H.load(self.output / 'case.json')
        prompt = H.build_prompt(public, public['prompt'])
        for secret in ('PRIVATE_ROUTE', 'PRIVATE_ANSWER', '.agents/skills', 'Read the explicitly', 'Standalone requests') + H.NATURAL_SKILLS:
            self.assertNotIn(secret, prompt)
        self.assertNotIn('expected', public)
        self.assertIn('.evaluation-state/', prompt)
        self.assertEqual('natural', H.load(self.output / 'evaluation.json')['activation'])

    def test_default_explicit_prompt_preserves_original_loading_and_boundary(self):
        case = dict(self.case, skills=['delivery-review'])
        case.pop('activation')
        prompt = H.build_prompt(case, 'Review app.py')
        self.assertEqual('explicit', H.activation(case))
        self.assertIn('Read the explicitly supplied frozen skill(s):\n- .agents/skills/delivery-review/SKILL.md', prompt)
        self.assertIn('Standalone requests must not invoke other skills or auto-start a workflow.', prompt)

    def test_unknown_activation_and_incomplete_or_duplicate_supply_rejected(self):
        for change in ({'activation': 'implicit'}, {'skills': list(H.NATURAL_SKILLS[:-1])},
                       {'skills': list(H.NATURAL_SKILLS) + ['delivery-fix']},
                       {'skills': [{}] * 7}, {'requirements': 'not an array'},
                       {'skills': 'delivery-implement'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                H.validate_natural_input(dict(self.case, **change))

    def test_skill_hints_in_all_public_channels_rejected(self):
        for field, value in (('prompt', 'use delivery-implement'), ('requirements', ['read SKILL.md']),
                             ('allowed_changes', ['.agents/skills/x']), ('prompt', 'USE DELIVERY-PLAN')):
            with self.subTest(field=field), self.assertRaises(ValueError):
                H.validate_natural_input(dict(self.case, **{field: value}))
        with self.assertRaises(ValueError):
            H.build_prompt(self.case, 'use delivery-plan')

    def test_natural_prompt_file_and_unaudited_adapter_never_start_cli(self):
        self.prepare()
        with patch.object(H.platform, 'platform', return_value='unit-platform'), patch.object(H.subprocess, 'run') as cli:
            value = H.run(self.output, prompt_file=self.root / 'not-even-readable', sandbox_strategy='external-seatbelt', required_isolation='filesystem')
            self.assertIn('prompt-file', value['reason'])
            value = H.run(self.output)
            self.assertIn('catalog audit', value['reason'])
            cli.assert_not_called()

    def test_changed_frozen_skill_cannot_become_new_unrecorded_input(self):
        workspace = self.prepare()
        (workspace / '.agents/skills/delivery-plan/SKILL.md').write_text('modified content')
        with patch.object(H.platform, 'platform', return_value='unit-platform'), patch.object(H.subprocess, 'run') as cli:
            value = H.run(self.output, sandbox_strategy='external-seatbelt', required_isolation='filesystem')
            self.assertIn('snapshot changed', value['reason'])
            cli.assert_not_called()

    def test_policy_true_and_missing_default_allowed_false_or_malformed_rejected(self):
        path = self.root / 'openai.yaml'
        self.assertEqual('default', C.implicit_policy(path))
        for body in ('interface:\n  display_name: "label"\n', 'policy:\n',
                     'policy:\n  allow_implicit_invocation: true # native default enabled\n'):
            path.write_text(body)
            self.assertIn(C.implicit_policy(path), ('true', 'default'))
        for body in ('policy:\n  allow_implicit_invocation: false\n',
                     'policy:\n  allow_implicit_invocation: "true"\n',
                     'policy:\n  allow_implicit_invocation: yes\n',
                     'policy: {allow_implicit_invocation: false}\n',
                     'policy :\n  allow_implicit_invocation: false\n',
                     'policy:\n  allow_implicit_invocation: true\n  allow_implicit_invocation: false\n',
                     'policy:\npolicy:\n', 'policy:\n  unknown_policy: true\n'):
            path.write_text(body)
            with self.subTest(body=body), self.assertRaises(ValueError):
                C.implicit_policy(path)
        (self.skills / 'delivery-plan/agents/openai.yaml').write_text('policy:\n  allow_implicit_invocation: false\n')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_launch_overrides_preserve_existing_rules_and_only_enable_frozen_paths(self):
        import tomllib
        expected = H.natural_skill_sources(self.skills, H.NATURAL_SKILLS)
        prior = {'skills': {'config': [{'path': '/other/SKILL.md', 'enabled': False}]}}
        rules = tomllib.loads('skills.config=' + S.natural_skill_config(prior, expected))['skills']['config']
        self.assertEqual(prior['skills']['config'], rules[:1])
        self.assertTrue(all(rule.get('enabled') is False for rule in rules[1:8]))
        self.assertEqual({item['path'] for item in expected.values()}, {rule['path'] for rule in rules[8:]})
        self.assertTrue(all(rule['enabled'] for rule in rules[8:]))
        with self.assertRaises(ValueError):
            S.natural_skill_config({'skills': {'config': [{'name': 'x', 'enabled': 'false'}]}}, expected)

    def test_package_checker_accepts_default_and_rejects_disabled_policy(self):
        for name in H.NATURAL_SKILLS:
            with (self.skills / name / 'SKILL.md').open('a') as stream:
                stream.write('\n## Working Protocol\n\n## Exit Criteria\n\n## Exit Protocol\n')
        self.assertTrue(C.check(self.skills, require_fix=True)['ok'])
        policy = self.skills / 'delivery-plan/agents/openai.yaml'
        policy.write_text('policy:\n  allow_implicit_invocation: false\n')
        result = C.check(self.skills, require_fix=True)
        self.assertFalse(result['ok'])
        self.assertTrue(any('implicit invocation is disabled' in error for error in result['errors']))
        policy.unlink()
        self.assertTrue(C.check(self.skills, require_fix=True)['ok'])

    def test_catalog_requires_exact_frozen_enabled_paths_and_unchanged_policy(self):
        expected = H.natural_skill_sources(self.skills, H.NATURAL_SKILLS)
        rows = [{'name': name, 'description': 'Professional purpose', 'scope': 'repo', 'path': item['path'], 'enabled': True} for name, item in expected.items()]
        def inventory(selected):
            return {'data': [{'cwd': str(self.root.resolve()), 'skills': selected, 'errors': []}]}
        disabled_global = {'name': 'delivery-plan', 'description': 'Old global purpose', 'scope': 'user', 'path': '/global/old/SKILL.md', 'enabled': False}
        audit = S.audit_skill_catalog(inventory(rows + [disabled_global]), self.root, expected)
        self.assertTrue(audit['passed'])
        self.assertEqual([disabled_global], audit['external_skills'])
        bad_inventory = inventory(rows)
        bad_inventory['data'][0]['errors'] = [{'path': '/unreadable/SKILL.md', 'message': 'load failure'}]
        with self.assertRaises(RuntimeError):
            S.audit_skill_catalog(bad_inventory, self.root, expected)
        bad_rows = [rows[:-1], rows + [rows[0]], rows + [dict(disabled_global, enabled=True)],
                    [dict(rows[0], enabled=False)] + rows[1:],
                    [dict(rows[0], path='/global/old/SKILL.md')] + rows[1:],
                    [dict(rows[0], enabled=1)] + rows[1:],
                    [dict(rows[0], description='')] + rows[1:]]
        for bad in bad_rows:
            with self.subTest(rows=bad), self.assertRaises(RuntimeError):
                S.audit_skill_catalog(inventory(bad), self.root, expected)
        policy = self.skills / 'delivery-plan/agents/openai.yaml'
        policy.write_text('policy:\n  allow_implicit_invocation: false\n')
        with self.assertRaises(RuntimeError):
            S.audit_skill_catalog(inventory(rows), self.root, expected)


if __name__ == '__main__':
    unittest.main()
