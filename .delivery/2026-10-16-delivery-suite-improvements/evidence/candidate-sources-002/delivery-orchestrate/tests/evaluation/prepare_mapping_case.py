#!/usr/bin/env python3
"""Create a truthful pending v2 candidate after frozen harness preparation.

This maintenance-side generator is not copied into the agent fixture. It does
not register any review result or edit the runner's original source snapshots.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(output):
    output = Path(output).resolve()
    evaluation = json.loads((output / 'evaluation.json').read_text())
    if evaluation['case_id'] != 'delivery-mapping-existing-review' or evaluation['status'] != 'prepared' or evaluation['runs']:
        raise ValueError('requires this case freshly prepared, with no model run')
    evidence = output / 'trusted-preparation'
    if evidence.exists():
        raise ValueError('preparation exists; inspect it rather than overwrite history')
    evidence.mkdir()
    project = Path(evaluation['workspace']).resolve()
    work = project / '.delivery/mapping'
    if work.exists():
        raise ValueError('work already exists; will not invent or replace history')
    scripts = project / '.agents/skills/delivery-orchestrate/scripts'
    cli = scripts / 'delivery.py'
    immutable = {str(p.relative_to(output)): sha(p) for p in (output / 'sources.json', output / 'before.json')}
    author = {'id': 'behavior-harness-asset-author', 'context': '/root/behavior_harness'}
    actor = {'id': 'trusted-case-preparer', 'context': 'script:prepare_mapping_case.py'}
    config = {
        'schema_version': 2, 'contract_version': 2, 'actor': actor,
        'plan': {'path': 'plan.md', 'quote': '# 账本汇总命令实现计划'},
        'authorization': {'path': 'authorization.md', 'quote': '按README和plan.md准备候选运行配置，进行独立正文与控制映射审阅。', 'scope': '候选配置与独立审阅；未准入前不实施'},
        'mapping_reason': '读取既有计划，将共享模块、实际CLI与联合验证组织为两个任务和整体验收。',
        'tasks': [{'id': 'T-01', 'scope': ['ledger.py', 'tests/test_ledger.py'], 'depends': []},
                  {'id': 'T-02', 'scope': ['app.py', 'tests/test_cli.py', 'USAGE.md'], 'depends': [{'kind': 'implementation', 'id': 'T-01'}]}],
        'reviews': [{'id': 'R-01', 'tasks': ['T-01', 'T-02'], 'whole': True}],
        'acceptance': [
            {'id': 'AC-01', 'tasks': ['T-01', 'T-02'], 'required': True, 'method': 'command', 'command': ['python3', '-B', '-m', 'unittest', 'discover', '-s', 'tests'], 'criteria': 'CNY收入10.10、支出2.05时输出收入10.10、支出2.05、净额8.05；金额精确到分。', 'environment': '本项目隔离测试数据', 'waivable': False},
            {'id': 'AC-02', 'tasks': ['T-01', 'T-02'], 'required': True, 'method': 'command', 'command': ['python3', '-B', '-m', 'unittest', 'discover', '-s', 'tests'], 'criteria': '多币种分别汇总，空列表返回空对象；输出币种键排序。', 'environment': '本项目隔离测试数据', 'waivable': False}],
        'source_authors': {'plan': [author], 'mapping': [actor]},
        'requirements': [
            {'id': 'REQ-01', 'source': {'path': 'plan.md', 'quote': 'CNY收入10.10、支出2.05时输出收入10.10、支出2.05、净额8.05'}, 'tasks': ['T-01', 'T-02'], 'acceptance': ['AC-01']},
            {'id': 'REQ-02', 'source': {'path': 'plan.md', 'quote': '多币种分别汇总，空列表返回空对象；输出币种键排序'}, 'tasks': ['T-01', 'T-02'], 'acceptance': ['AC-02']}],
        'admission_policy': {'plan_review': True, 'design_review': False, 'reason': '当前准备活动要求独立计划与映射审阅；尚无实施或审阅通过。', 'scale': 'small', 'significant_replan': False},
        'change': {'category': 'initial', 'reason': '首次保存既有计划的候选控制配置。'},
        'monitor': {'roots': ['.'], 'exclude': [{'path': name, 'reason': '评测器派生运行设施，不是业务输入或产物。'} for name in ('.evaluation-state', '.evaluation-log', '.evaluation-tmp', '.evaluation-output')]},
        'skill_sources': [{'name': 'delivery-' + name, 'root': str(project / '.agents/skills' / ('delivery-' + name)), 'contract_version': 2 if name == 'orchestrate' else 1} for name in ('orchestrate', 'design', 'plan', 'implement', 'review', 'verify')],
        'resources': []}
    config_path = work / 'admission/config-001.json'
    save(config_path, config)
    commands = [
        [sys.executable, '-B', str(cli), 'init', '--project', str(project), '--work', str(work), '--title', '账本控制映射独立审阅', '--contract-version', '2', '--op', 'trusted-init-001'],
        [sys.executable, '-B', str(cli), 'configure', '--work', str(work), '--input', str(config_path), '--op', 'trusted-config-001'],
        [sys.executable, '-B', str(cli), 'check', '--work', str(work)],
        [sys.executable, '-B', str(cli), 'status', '--work', str(work)]]
    records = []
    for number, argv in enumerate(commands, 1):
        started = datetime.now(timezone.utc).isoformat()
        result = subprocess.run(argv, cwd=project, text=True, capture_output=True)
        record = {'argv': argv, 'cwd': str(project), 'started_at': started, 'completed_at': datetime.now(timezone.utc).isoformat(), 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
        records.append(record)
        save(evidence / f'command-{number:03}.json', record)
        if result.returncode:
            raise RuntimeError(f'preparation command {number} failed; raw evidence preserved')
    if immutable != {name: sha(output / name) for name in immutable}:
        raise RuntimeError('original harness snapshots changed')
    save(evidence / 'preparation.json', {'generator': str(Path(__file__).resolve()), 'generator_sha256': sha(Path(__file__)), 'generated_at': datetime.now(timezone.utc).isoformat(), 'source_authors': config['source_authors'], 'actor': actor, 'config_sha256': sha(config_path), 'original_snapshots_unchanged': immutable, 'model_runs': 0, 'review_results_registered': 0, 'commands': len(records), 'workspace': str(project), 'work': str(work)})
    print(json.dumps({'output': str(output), 'workspace': str(project), 'work': str(work), 'status': 'pending-independent-review', 'model_runs': 0}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    prepare(parser.parse_args().output)
