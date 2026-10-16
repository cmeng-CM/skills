#!/usr/bin/env python3
"""Record two real unchanged-source failures for the ordinary handoff fixture.

Maintenance-side provenance only; it neither invokes a model nor repairs code.
Existing history is never overwritten, and both executions must actually fail.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone


def source_inventory(fixture):
    names = ['README.md', 'money.py', 'app.py', 'transactions.json', 'tests/test_money.py']
    return {name: hashlib.sha256((fixture / name).read_bytes()).hexdigest() for name in names}


def record(fixture):
    fixture = Path(fixture).resolve()
    baseline = source_inventory(fixture)
    for index in (1, 2):
        target = fixture / 'history' / f'attempt-{index:03}.json'
        if target.exists():
            raise ValueError('actual history exists; refusing to overwrite or replay it')
    command = [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v']
    for index in (1, 2):
        before = source_inventory(fixture)
        started = datetime.now(timezone.utc).isoformat()
        result = subprocess.run(command, cwd=fixture, text=True, capture_output=True)
        after = source_inventory(fixture)
        value = {'schema_version': 1, 'activity': 'maintenance-side actual test execution, not a prior LLM implementation attempt',
                 'actor': {'id': 'behavior-harness-asset-author', 'context': '/root/behavior_harness'},
                 'started_at': started, 'completed_at': datetime.now(timezone.utc).isoformat(),
                 'argv': command, 'cwd': str(fixture), 'python_version': sys.version,
                 'source_sha256_before': before, 'source_sha256_after': after,
                 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr,
                 'source_unchanged': baseline == before == after}
        target = fixture / 'history' / f'attempt-{index:03}.json'
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        if result.returncode == 0 or before != baseline or after != baseline:
            raise RuntimeError('expected real unchanged-source failure not established; actual record preserved')
    print(json.dumps({'fixture': str(fixture), 'real_failures': 2, 'unchanged_source': True, 'model_attempts': 0}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture', nargs='?', type=Path, default=Path(__file__).parent / 'fixtures/repeated-failure-project')
    record(parser.parse_args().fixture)
