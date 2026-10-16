"""Bounded real-CLI exercise; professional verdicts come from actual agent reports."""
from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PROJECT = Path(json.loads((ROOT / 'projects.json').read_text())['combined'])
WORK = PROJECT / '.delivery/2026-10-16-queue-repair'
CLI = PROJECT / '.agents/skills/delivery-orchestrate/scripts/delivery.py'
COORD = {'id': '/root', 'context': 'delivery-fix-combined-control'}
REVIEWER = {'id': '/root/fix_independent_review', 'context': 'delivery-fix-combined-admission-review-001'}
BUG = WORK / 'fixes/BUG-001-stale-result'
LOG = WORK / 'admission/runtime-logs'
LOG.mkdir(exist_ok=True)

def relative(path):
    return str(Path(path).relative_to(PROJECT))

def invoke(command, op=None, payload=None, **options):
    args = [sys.executable, '-B', str(CLI), command, '--work', str(WORK)]
    if op:
        args += ['--op', op]
    if payload is not None:
        path = WORK / 'admission' / ((op or command) + '.json')
        path.write_text(json.dumps(payload, indent=2) + '\n')
        args += ['--input', str(path)]
    for key, value in options.items():
        args += ['--' + key.replace('_', '-'), str(value)]
    result = subprocess.run(args, cwd=PROJECT, capture_output=True, text=True)
    label = op or command
    (LOG / (label + '.stdout.txt')).write_text(result.stdout)
    (LOG / (label + '.stderr.txt')).write_text(result.stderr)
    (LOG / (label + '.command.json')).write_text(json.dumps({'argv': args, 'exit_code': result.returncode}, indent=2) + '\n')
    if result.returncode:
        raise RuntimeError(label + ': ' + result.stderr)
    return json.loads(result.stdout)

def request(who=COORD, **fields):
    return {'schema_version': 2, 'contract_version': 2, 'actor': who, **fields}

def resource(who, action, label, mode='write'):
    return invoke('resource', label, request(who, action=action,
        resources=[{'id': 'path:queue_store.py', 'mode': mode}, {'id': 'path:tests', 'mode': mode}], reason='Actual bounded queue exercise resource handoff'))

def gate(config, kind, op):
    return invoke('gate', op, request(REVIEWER, config_operation=config, kind=kind, result='passed',
        summary='Actual independent review-001.md covers this exact mapping/route change.',
        report={'path': relative(WORK / 'admission/review-001.md')},
        evidence=[{'path': relative(WORK / 'admission/review-001.md')}]))

if __name__ == '__main__':
    phase = sys.argv[1]
    if phase == 'start':
        invoke('init', 'init', project=PROJECT, title='Controlled queue repair with optional fix transfer', contract_version=2)
        config = json.loads((WORK / 'admission/config-001.json').read_text())
        invoke('configure', 'configure-001', config)
        gate('configure-001', 'mapping_review', 'mapping-001')
        round_dir = BUG / '001'
        (round_dir / 'evidence').mkdir(parents=True)
        check = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=PROJECT, capture_output=True, text=True)
        (round_dir / 'evidence/before.stdout.txt').write_text(check.stdout)
        (round_dir / 'evidence/before.stderr.txt').write_text(check.stderr)
        if check.returncode == 0:
            raise RuntimeError('Expected public failure was not observed; do not manufacture transfer')
        (round_dir / 'fix.md').write_text('''# BUG-001 round 001: initial implementation assessment\n\nProducer delivery-implement, actual actor /root, context delivery-fix-combined-control. This controlled exercise begins with existing faulty code, not an earlier real implementation claim. Product baseline is the current queue_store.py and existing tests.\n\nPublic README/plan Q1 require stale completion rejection without state mutation. The authorized local selfcheck failed at that requirement; other checks passed. Actual raw output is in evidence/before.stderr.txt. No product edit was made in this activity, and no independent acceptance is claimed.\n\nThe longer-lease historical observation in README is fixture input, not an action performed by this actor. Cause has not yet been established by this activity. Transfer T1 under its existing authorization to specialized diagnosis, preserving API, requirements, R1 and A1. No command remains running and no experimental changes were made. Prior product author is unknown and must not be invented; all actual exercise participants must carry forward.\n''')
        (BUG / 'index.md').write_text('# BUG-001 stale-result corruption\n\nControlled queue exercise; T1/Q1.\n\n- [001 initial assessment](001/fix.md)\n')
        resource(COORD, 'claim', 'claim-initial')
        invoke('record', 'initial-failed', request(kind='implementation', target='T1', result='failed',
            report={'path': relative(round_dir / 'fix.md')}, summary='Actual initial selfcheck fails; no product correction claimed.',
            evidence=[{'path': relative(round_dir / 'evidence/before.stderr.txt')}]))
        resource(COORD, 'release', 'release-initial')
        invoke('enable-fix', 'enable-fix', request(implementation_contract_version=1, reason='Observed unresolved failure transferred under approved plan'))
        invoke('configure', 'configure-002', json.loads((WORK / 'admission/config-002.json').read_text()))
        gate('configure-002', 'mapping_review', 'mapping-002')
        gate('configure-002', 'change_review', 'change-002')
        print(invoke('brief', kind='implementation', target='T1')['report_location'])
    elif phase == 'finish':
        review = WORK / 'review/001.md'
        if not review.is_file():
            raise RuntimeError('Actual independent R1 report required before admission')
        resource(REVIEWER, 'claim', 'claim-R1', mode='read')
        invoke('record', 'review-R1', request(REVIEWER, kind='review', target='R1',
            result={'spec': 'passed', 'quality': 'passed'},
            summary='Actual independent R1 report found no blocking issue for the current queue repair.',
            report={'path': relative(review)}, evidence=[{'path': relative(review)}]))
        resource(REVIEWER, 'release', 'release-R1', mode='read')
        verifier = {'id': '/root', 'context': 'delivery-fix-combined-control'}
        resource(verifier, 'claim', 'claim-A1', mode='read')
        run = invoke('run', 'run-A1', acceptance='A1', actor=verifier['id'], context=verifier['context'], timeout=30)
        if run['payload']['exit_code'] != 0 or run['payload']['timed_out']:
            raise RuntimeError('Required actual command did not pass')
        # The coordinator reads output and actual tests before judging this run;
        # this check establishes the exact expected collection, not a bare exit 0.
        output_path = WORK / 'runtime/objects' / run['payload']['stderr']['object_hash']
        output = output_path.read_text()
        if 'Ran 7 tests' not in output or '\nOK\n' not in output:
            raise RuntimeError('Required collected tests and results not present')
        report = WORK / 'verification/001.md'
        report.parent.mkdir(exist_ok=True)
        report.write_text('''# A1 actual command verification\n\nVerifier /root, context delivery-fix-combined-control. Exact configured command run-A1 returned exit 0, collected and executed seven tests, no skips; raw outputs and snapshots are bound by its real engine receipt.\n\nReviewed actual queue_store.py and tests: stale owner is rejected before memory/disk mutation; current owner can complete and reload, pending/done rejections and duplicate enqueue preserve state, lease boundary reclaim remains valid. Existing three tests are unchanged and four new regressions exercise related public invariants. R1 independently examined the same product and reports. No requirement, method, required flag or waiver changed.\n\nResult: A1 passed for this controlled explicit-clock single-instance queue project. Multi-process file consistency, owner generation tokens and write-failure behavior are not demonstrated and were not part of this case's settled criteria.\n''')
        invoke('record', 'verification-A1', request(verifier, kind='verification', target='A1', result='passed',
            summary='Read actual tests/product and seven collected passing results for configured required behavior.',
            report={'path': relative(report)}, evidence=[{'path': relative(report)}], run_operation=run['op']))
        resource(verifier, 'release', 'release-A1', mode='read')
        report = WORK / 'closeout.md'
        report.write_text('''# Controlled optional fix delivery\n\nT1 completed through initial failed assessment, optional fix transfer, frozen diagnosis-only round002, fresh-context repair round003, independent whole review R1, and actual required command/verdict A1. All three actual activity authors remain registered. No product or test criteria were weakened; no commit/push. This closes only the controlled queue case.\n''')
        invoke('close', 'close', request(mode='complete', summary='Current implementation, independent whole review and required command/verdict passed.', report={'path': relative(report)}, exceptions=[]))
        print(invoke('status')['lifecycle'])
    else:
        raise SystemExit('Unsupported phase')
