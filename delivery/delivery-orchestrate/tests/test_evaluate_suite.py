"""Harness regressions use mocked processes; these are not agent behavior results."""
import importlib.util
import contextlib
import io
import sys
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('evaluate_suite', Path(__file__).parents[1] / 'scripts' / 'evaluate_suite.py')
H = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(H)


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        fixture = self.root / 'fixture'
        fixture.mkdir()
        (fixture / 'app.py').write_text('print("original")\n')
        self.skills = self.root / 'skills'
        package = self.skills / 'delivery-review'
        (package / 'tests').mkdir(parents=True)
        (package / 'SKILL.md').write_text('# review\n')
        (package / 'tests' / 'oracle.txt').write_text('PRIVATE_ANSWER')
        self.case = self.root / 'case.json'
        H.save(self.case, {'schema_version':1, 'id':'fixture', 'mode':'standalone', 'skills':['delivery-review'], 'fixture':'fixture', 'prompt':'Review app.py only'})
        self.output = self.root / 'result'
        H.prepare(self.case, self.skills, self.output, 'candidate')
        self.workspace = Path(H.load(self.output / 'evaluation.json')['workspace'])

    def tearDown(self):
        shutil.rmtree(self.workspace, ignore_errors=True)
        self.temp.cleanup()

    def fake_run(self, events=None, last='actual final', returncode=0, communicate_error=None, **options):
        events = events if events is not None else [{'type':'thread.started','thread_id':'test-session'}, {'type':'turn.completed','usage':{'input_tokens':3,'output_tokens':4}}]
        def popen(argv, **kwargs):
            kwargs['stdout'].write(('\n'.join(json.dumps(e) for e in events)+'\n').encode())
            last_path = Path(argv[argv.index('--output-last-message')+1])
            if last is not None:
                last_path.write_text(last)
            class Process:
                pid = 123456
                def __init__(self): self.returncode=returncode
                def communicate(self, *args, **kwargs):
                    if communicate_error: raise communicate_error
                    return None, None
                def wait(self, **kwargs): self.returncode=-15; return -15
            return Process()
        with patch.object(H.platform, 'platform', return_value='test-platform'), patch.object(H.shutil, 'which', return_value='/usr/bin/codex'), patch.object(H.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,'codex test\n','')), patch.object(H, 'configured_model', return_value={'model':'frozen-default','model_reasoning_effort':'xhigh'}), patch.object(H.subprocess,'Popen',side_effect=popen), patch.object(H.os,'killpg'):
            return H.run(self.output, **options)

    def test_prepare_freezes_only_one_skill_and_excludes_oracle(self):
        self.assertFalse((self.workspace/'.git').exists())
        self.assertEqual(['delivery-review'], [p.name for p in (self.workspace/'.agents/skills').iterdir()])
        self.assertFalse((self.workspace/'.agents/skills/delivery-review/tests').exists())
        self.assertNotIn('PRIVATE_ANSWER', json.dumps(H.load(self.output/'case.json')))

    def test_optional_fix_is_a_single_standalone_professional(self):
        package = self.skills / 'delivery-fix'
        package.mkdir()
        (package / 'SKILL.md').write_text('# fix\n')
        case = H.load(self.case)
        case['skills'] = ['delivery-fix']
        H.save(self.case, case)
        output = self.root / 'fix-result'
        result = H.prepare(self.case, self.skills, output, 'candidate')
        workspace = Path(H.load(output / 'evaluation.json')['workspace'])
        self.addCleanup(shutil.rmtree, workspace, ignore_errors=True)
        self.assertEqual(['delivery-fix'], [p.name for p in (workspace / '.agents/skills').iterdir()])
        self.assertFalse((workspace / '.git').exists())

    def test_evaluator_runtime_files_are_excluded_only_at_exact_top_roots(self):
        (self.workspace/'.evaluation-state/state.sqlite').write_text('runtime metadata')
        business=self.workspace/'ledger/.evaluation-state';business.mkdir(parents=True)
        (business/'business.txt').write_text('actual product requirement')
        self.fake_run()
        snapshot=H.load(self.output/'runs/001/after.json')
        self.assertNotIn('.evaluation-state/state.sqlite',snapshot)
        self.assertIn('ledger/.evaluation-state/business.txt',snapshot)
        self.assertFalse((self.output/'runs/001/artifacts/.evaluation-state').exists())
        self.assertTrue((self.output/'runs/001/artifacts/ledger/.evaluation-state/business.txt').exists())
        self.assertTrue((self.output/'runs/001/last-message.txt').exists())
        self.assertEqual(list(H.EVALUATOR_DIRS),H.load(self.output/'evaluation.json')['runs'][0]['product_snapshot_excludes'])

    def test_freeze_is_a_copy_not_live_source(self):
        (self.skills/'delivery-review/SKILL.md').write_text('changed source')
        self.assertEqual('# review\n', (self.workspace/'.agents/skills/delivery-review/SKILL.md').read_text())

    def test_no_clobber_existing_evaluation(self):
        with self.assertRaises(ValueError): H.prepare(self.case, self.skills, self.output, 'candidate')

    def test_fixture_path_escape_rejected(self):
        with self.assertRaises(ValueError): H.confined(self.root,'../outside')

    def test_symlink_input_rejected(self):
        (self.root/'fixture/link').symlink_to(self.root/'case.json')
        with self.assertRaises(ValueError): H.copy_tree(self.root/'fixture',self.root/'copy')

    def test_internal_product_link_is_metadata_and_actual_files_survive(self):
        actual=self.workspace/'.delivery/workflow';actual.mkdir(parents=True)
        (actual/'plan.md').write_text('real workflow plan')
        (self.workspace/'.workflow').symlink_to('.delivery/workflow',target_is_directory=True)
        record=self.fake_run()
        self.assertEqual('executed',record['status'])
        run=self.output/'runs/001'
        self.assertEqual({'.workflow':'.delivery/workflow'},H.load(run/'artifact-symlinks.json')['links'])
        self.assertFalse((run/'artifacts/.workflow').is_symlink())
        self.assertFalse((run/'artifacts/.workflow').exists())
        self.assertEqual('real workflow plan',(run/'artifacts/.delivery/workflow/plan.md').read_text())
        self.assertTrue((run/'artifacts/app.py').is_file())
        self.assertEqual({'symlink':'.delivery/workflow'},H.load(run/'after.json')['.workflow'])

    def test_external_product_links_are_not_opened_or_recreated(self):
        private=self.root/'external';private.mkdir()
        (private/'secret.txt').write_text('EXTERNAL_PRIVATE_CONTENT')
        (self.workspace/'external-dir').symlink_to(private,target_is_directory=True)
        (self.workspace/'external-file').symlink_to(private/'secret.txt')
        original=H.os.open
        opened=[]
        def observe(name,*args,**kwargs):
            opened.append(str(name))
            if str(name) in ('external-dir','external-file',str(private),str(private/'secret.txt')):
                self.fail('collector tried to open a symlink or its external target')
            return original(name,*args,**kwargs)
        with patch.object(H.os,'open',side_effect=observe):
            record=self.fake_run()
        self.assertEqual('executed',record['status'])
        run=self.output/'runs/001'
        self.assertEqual({'external-dir':str(private),'external-file':str(private/'secret.txt')},H.load(run/'artifact-symlinks.json')['links'])
        self.assertFalse((run/'artifacts/external-dir').exists())
        self.assertFalse((run/'artifacts/external-file').is_symlink())
        self.assertNotIn('EXTERNAL_PRIVATE_CONTENT',''.join(p.read_text() for p in (run/'artifacts').rglob('*') if p.is_file()))
        self.assertTrue((run/'artifacts/app.py').is_file())
        self.assertTrue(opened)

    def test_cyclic_and_dangling_links_do_not_discard_other_products(self):
        for name,target in [('cycle-a','cycle-b'),('cycle-b','cycle-a'),('dangling','missing-target')]:
            (self.workspace/name).symlink_to(target)
        record=self.fake_run()
        self.assertEqual('executed',record['status'])
        run=self.output/'runs/001'
        self.assertEqual({'cycle-a':'cycle-b','cycle-b':'cycle-a','dangling':'missing-target'},H.load(run/'artifact-symlinks.json')['links'])
        self.assertTrue((run/'artifacts/app.py').is_file())
        self.assertFalse(any(p.is_symlink() for p in (run/'artifacts').rglob('*')))
        self.assertEqual({'symlink':'missing-target'},H.load(run/'after.json')['dangling'])

    def test_heterogeneous_case_normalization_keeps_answers_private(self):
        for prompt_key, expected_key, forbidden_key in [('prompt','expected','forbidden'),('request','expectations','prohibited')]:
            public, private = H.normalize_behavior_case({'id':'a',prompt_key:'public request',expected_key:['SECRET'],forbidden_key:['PRIVATE'], 'fixture':'defect location'})
            self.assertEqual({'id':'a','prompt':'public request'},public)
            self.assertEqual(['SECRET'],private['expected'])
            self.assertNotIn('defect',json.dumps(public))

    def test_missing_real_interface_is_not_run(self):
        with patch.object(H.shutil,'which',return_value=None): record=H.run(self.output,cli='missing')
        self.assertEqual('not-run', record['status'])
        self.assertIn('not-run',(self.output/'report.md').read_text())
        self.assertNotIn('reviewed-pass',(self.output/'report.md').read_text())

    def test_real_completion_is_execution_only(self):
        record=self.fake_run()
        self.assertEqual('executed',record['status'])
        self.assertEqual('executed',H.load(self.output/'evaluation.json')['status'])
        self.assertTrue((self.output/'runs/001/artifacts/app.py').exists())
        self.assertIn('Pending',(self.output/'report.md').read_text())
        self.assertNotIn('HOME',json.dumps(H.load(self.output/'runs/001/request.json')['environment_keys_changed']))

    def test_completed_event_with_empty_final_is_failure(self):
        self.assertEqual('execution-failed',self.fake_run(last='')['status'])

    def test_failed_turn_is_not_execution_success(self):
        self.assertEqual('execution-failed',self.fake_run(events=[{'type':'turn.failed'}])['status'])

    def test_nonzero_exit_cannot_pass(self):
        self.assertEqual('execution-failed',self.fake_run(returncode=1)['status'])

    def test_timeout_and_partial_artifacts_retained(self):
        record=self.fake_run(communicate_error=subprocess.TimeoutExpired('codex',1))
        self.assertEqual('timeout',record['status'])
        self.assertTrue((self.output/'runs/001/events.jsonl').exists())
        self.assertTrue((self.output/'runs/001/artifacts/app.py').exists())

    def test_interrupted_run_not_auto_retried(self):
        record=self.fake_run(communicate_error=KeyboardInterrupt())
        self.assertEqual('interrupted',record['status'])
        self.assertEqual(1,len(H.load(self.output/'evaluation.json')['runs']))

    def test_filesystem_isolation_required_without_boundary_invalid(self):
        self.assertEqual('invalid-isolation',self.fake_run(required_isolation='filesystem')['status'])

    def test_version_mismatch_prevents_execution(self):
        record=self.fake_run(expected_cli_version='codex other-version')
        self.assertEqual('invalid-version',record['status'])
        self.assertFalse((self.output/'runs/001/events.jsonl').exists())

    def test_malformed_jsonl_cannot_pass(self):
        path=self.root/'malformed.jsonl';path.write_text('{"type":"turn.completed"}\nnot-json\n')
        events,malformed=H.parse_events(path)
        self.assertEqual(1,len(events));self.assertEqual([2],malformed)

    def test_private_canary_failure_prevents_agent_start(self):
        private=self.root/'private';private.mkdir()
        with patch.object(H.platform,'platform',return_value='test-platform'), patch.object(H.shutil,'which',return_value='/usr/bin/tool'), patch.object(H.subprocess,'run',side_effect=[subprocess.CompletedProcess([],0,'codex test',''),subprocess.CompletedProcess([],0,'delivery-evaluation-private-read-canary\n','')]), patch.object(H.subprocess,'Popen') as process:
            record=H.run(self.output,private_dir=private,required_isolation='filesystem')
            self.assertEqual('not-run',record['status']);process.assert_not_called()
        self.assertFalse(H.load(self.output/'runs/001/isolation.json')['passed'])

    def test_cli_prints_compact_summary_but_run_api_keeps_detail(self):
        huge={'id':'001','status':'executed','reason':'awaiting independent artifact review','seconds':1,'mcp_runtime_inventory':{'tools':'x'*500000}}
        output=io.StringIO()
        with patch.object(sys,'argv',['evaluate_suite.py','run','--output',str(self.output)]), patch.object(H,'run',return_value=huge), contextlib.redirect_stdout(output):
            self.assertEqual(0,H.main())
        result=json.loads(output.getvalue())
        self.assertEqual('executed',result['status'])
        self.assertEqual(str(self.output.resolve()),result['output'])
        self.assertNotIn('mcp_runtime_inventory',result)
        self.assertLess(len(output.getvalue()),1000)

    def review_input(self, **changes):
        value={'reviewer':'independent-actor', 'author_identities':['implementation-actor'], 'verdict':'pass', 'summary':'Reviewed actual app and trace', 'evidence':['runs/001/artifacts/app.py','runs/001/events.jsonl'], 'run_id':'001','artifact_inventory_sha256':H.digest(self.output/'runs/001/after.json'),'leakage_audit':'no-leak-observed'}
        value.update(changes)
        H.save(self.root/'review.json',value)
        return self.root/'review.json'

    def test_independent_review_binds_actual_artifacts(self):
        self.fake_run()
        result=H.review(self.output,self.review_input())
        self.assertEqual('reviewed-pass',result['status'])
        self.assertIn('reviewed-pass',(self.output/'report.md').read_text())

    def test_same_run_review_revisions_are_append_only(self):
        self.fake_run()
        H.review(self.output,self.review_input())
        first=(self.output/'reviews/history-001.json').read_bytes()
        H.review(self.output,self.review_input(verdict='inconclusive',summary='Business evidence sufficient; isolation decision pending'))
        self.assertEqual(first,(self.output/'reviews/history-001.json').read_bytes())
        history=[H.load(p) for p in sorted((self.output/'reviews').glob('history-*.json'))]
        self.assertEqual(['pass','inconclusive'],[v['review']['verdict'] for v in history])
        self.assertTrue(all(v['accepted_at'] and v['review']['evidence_versions'] for v in history))
        self.assertEqual([H.load(self.output/'evaluation.json')['id']]*2,[v['evaluation_id'] for v in history])
        self.assertEqual('inconclusive',H.load(self.output/'independent-review.json')['verdict'])
        self.assertEqual('review-inconclusive',H.load(self.output/'evaluation.json')['status'])

    def test_rejected_review_does_not_append_or_replace_accepted_history(self):
        self.fake_run()
        H.review(self.output,self.review_input())
        archived=(self.output/'reviews/history-001.json').read_bytes()
        with self.assertRaises(ValueError):
            H.review(self.output,self.review_input(evidence=['missing-evidence.txt']))
        self.assertEqual(archived,(self.output/'reviews/history-001.json').read_bytes())
        self.assertEqual(1,len(list((self.output/'reviews').glob('history-*.json'))))
        self.assertEqual('pass',H.load(self.output/'independent-review.json')['verdict'])

    def test_same_author_review_rejected(self):
        self.fake_run()
        with self.assertRaises(ValueError): H.review(self.output,self.review_input(reviewer='implementation-actor'))

    def test_stale_review_rejected(self):
        self.fake_run()
        p=self.review_input()
        (self.workspace/'app.py').write_text('changed after execution')
        with self.assertRaises(ValueError): H.review(self.output,p)

    def test_leaked_review_cannot_pass(self):
        self.fake_run()
        with self.assertRaises(ValueError): H.review(self.output,self.review_input(leakage_audit='leaked'))

    def test_resume_is_a_new_real_turn_invalidating_old_review(self):
        self.fake_run()
        H.review(self.output,self.review_input())
        archived=(self.output/'reviews/history-001.json').read_bytes()
        prompt=self.root/'resume.txt';prompt.write_text('Recover from actual disk state')
        self.fake_run(prompt_file=prompt)
        result=H.load(self.output/'evaluation.json')
        self.assertEqual(2,len(result['runs']))
        self.assertNotIn('review',result)
        self.assertFalse((self.output/'independent-review.json').exists())
        self.assertEqual(archived,(self.output/'reviews/history-001.json').read_bytes())
        self.assertIn('Recover from actual disk state',(self.output/'runs/002/prompt.txt').read_text())


if __name__=='__main__': unittest.main()
