#!/usr/bin/env python3
"""Create only a real pending v2 candidate; explicit actor is the actual caller.

No gate, implementation, review, verification or closure result is fabricated.
The evaluator must independently bootstrap current facts before model recovery.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(output, actor_id, actor_context):
    output = Path(output).resolve()
    evaluation = json.loads((output / 'evaluation.json').read_text())
    if evaluation['case_id'] != 'delivery-external-settings-resume' or evaluation['status'] != 'prepared' or evaluation['runs']:
        raise ValueError('requires this case freshly prepared with no model run')
    evidence = output / 'trusted-preparation'
    if evidence.exists():
        raise ValueError('preparation exists; do not overwrite history')
    evidence.mkdir()
    project = Path(evaluation['workspace']).resolve()
    work = project / '.delivery/external-settings'
    if work.exists():
        raise ValueError('existing work must not be rebuilt')
    actor = {'id': actor_id, 'context': actor_context}
    author = {'id': '/root/behavior_harness', 'context': '/root/behavior_harness'}
    original = {p.name: digest(p) for p in (output / 'sources.json', output / 'before.json')}
    config = {
        'schema_version': 2, 'contract_version': 2, 'actor': actor,
        'design': {'path': 'design.md', 'quote': '# 外部配置乘法命令技术方案'},
        'plan': {'path': 'plan.md', 'quote': '# 外部配置乘法命令实现计划'},
        'authorization': {'path': 'authorization.md', 'quote': '完成本项目README中已明确的单任务目标，允许质量优先的局部实施与必要验证，不push。', 'scope': '本地单任务及真实核验；外部配置由其所有者维护，不由实施者改写'},
        'mapping_reason': '从完整README与设计、计划映射真实配置消费者、失败原子性和只读约束；外部配置不归任务所有，保留全树monitor先观察再判断的显式组织选择。',
        'tasks': [{'id': 'T-01', 'scope': ['app.py', 'tests'], 'depends': []}],
        'reviews': [{'id': 'R-01', 'tasks': ['T-01'], 'whole': True}],
        'acceptance': [{'id': 'V-01', 'tasks': ['T-01'], 'required': True, 'method': 'command', 'command': ['python3', '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v'], 'criteria': '实际入口读取当前整数factor输出2乘factor；重复调用重新读取；错误配置非零无部分stdout；原外部配置不改写；仅标准库。', 'environment': '当前隔离项目与实际settings.json；失败及变化测试使用独立临时目录，不改原配置', 'waivable': False}],
        'source_authors': {'design': [author], 'plan': [author], 'mapping': [author]},
        'requirements': [
            {'id': 'REQ-01', 'source': {'path': 'README.md', 'quote': 'factor是可变外部运行配置，必须每次实际读取，不得硬编码样例值。'}, 'tasks': ['T-01'], 'acceptance': ['V-01']},
            {'id': 'REQ-02', 'source': {'path': 'README.md', 'quote': '文件缺失、JSON错误、非对象、缺factor或类型不合法时非零退出，stderr提供诊断，stdout不得留部分结果。'}, 'tasks': ['T-01'], 'acceptance': ['V-01']},
            {'id': 'REQ-03', 'source': {'path': 'README.md', 'quote': '命令不得修改配置；仅Python标准库，不增加网络、数据库或持久副作用。'}, 'tasks': ['T-01'], 'acceptance': ['V-01']}],
        'admission_policy': {'plan_review': True, 'design_review': False, 'reason': '小任务无新高风险机制；要求真实独立计划与映射审阅，代码另经独立实现审查。', 'scale': 'small', 'significant_replan': False},
        'change': {'category': 'initial', 'reason': '仅创建待独立核验的初始候选，现有代码不是预先接纳通过'},
        'monitor': {'roots': ['.'], 'exclude': [{'path': name, 'reason': '评测器派生运行设施，仅排除该精确路径，不是业务配置或专业产物。'} for name in ('.evaluation-state', '.evaluation-log', '.evaluation-tmp', '.evaluation-output')]},
        'skill_sources': [{'name': 'delivery-' + name, 'root': str(project / '.agents/skills' / ('delivery-' + name)), 'contract_version': 2 if name == 'orchestrate' else 1} for name in ('orchestrate', 'design', 'plan', 'implement', 'review', 'verify')],
        'resources': []}
    config_path = work / 'admission/config-001.json'
    save(config_path, config)
    cli = project / '.agents/skills/delivery-orchestrate/scripts/delivery.py'
    commands = [
        [sys.executable, '-B', str(cli), 'init', '--project', str(project), '--work', str(work), '--title', '外部配置乘法命令', '--contract-version', '2', '--op', 'bootstrap-init-001'],
        [sys.executable, '-B', str(cli), 'configure', '--work', str(work), '--input', str(config_path), '--op', 'bootstrap-config-001'],
        [sys.executable, '-B', str(cli), 'check', '--work', str(work)],
        [sys.executable, '-B', str(cli), 'status', '--work', str(work)]]
    for number, argv in enumerate(commands, 1):
        started = datetime.now(timezone.utc).isoformat()
        result = subprocess.run(argv, cwd=project, text=True, capture_output=True)
        save(evidence / f'command-{number:03}.json', {'argv': argv, 'cwd': str(project), 'started_at': started, 'completed_at': datetime.now(timezone.utc).isoformat(), 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
        if result.returncode:
            raise RuntimeError(f'actual preparation command {number} failed; preserve raw evidence')
    if original != {name: digest(output / name) for name in original}:
        raise RuntimeError('original harness snapshots changed')
    save(evidence / 'preparation.json', {'generator_sha256': digest(Path(__file__)), 'generated_at': datetime.now(timezone.utc).isoformat(), 'actual_config_actor': actor, 'source_authors': config['source_authors'], 'source_implementation_author': author, 'original_snapshots_unchanged': original, 'config_sha256': digest(config_path), 'work': str(work), 'accepted_results_registered': 0, 'model_runs': 0})
    save(evidence / 'bootstrap-inputs.pending.json', {'not_a_runtime_request': True, 'state': 'pending-actual-independent-evaluation', 'actual_config_actor': actor, 'actual_source_and_code_author': author, 'independent_reviewer': None, 'activities': [{'kind': 'plan_review', 'result': None}, {'kind': 'mapping_review', 'result': None}, {'kind': 'implementation', 'target': 'T-01', 'result': None, 'actual_author': author, 'report_source': 'implementation.md'}, {'kind': 'review', 'target': 'R-01', 'result': None}, {'kind': 'verification', 'target': 'V-01', 'result': None}], 'instructions': 'Real non-author review and actual command evidence must precede genuine admission. Coordinator records actual identities, author history and results; leave active, never prefill passed or close in bootstrap.'})
    print(json.dumps({'output': str(output), 'work': str(work), 'status': 'pending-independent-bootstrap', 'actor': actor, 'accepted_results_registered': 0}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--actor-id', required=True, help='truthful actual configure caller identity')
    parser.add_argument('--actor-context', required=True, help='truthful actual configure caller context')
    args = parser.parse_args()
    prepare(args.output, args.actor_id, args.actor_context)
