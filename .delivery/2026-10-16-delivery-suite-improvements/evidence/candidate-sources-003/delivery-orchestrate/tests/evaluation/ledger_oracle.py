#!/usr/bin/env python3
"""Private evaluator: run the actual consumer; never supplied to a tested agent."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

CASES = [
    ('mixed', [{'kind':'income','amount':'10.10','currency':'CNY'}, {'kind':'expense','amount':'2.05','currency':'CNY'}, {'kind':'income','amount':'3.00','currency':'USD'}], {'CNY':{'income':'10.10','expense':'2.05','net':'8.05'},'USD':{'income':'3.00','expense':'0.00','net':'3.00'}}),
    ('reverse-currency-input', [{'kind':'income','amount':'3.00','currency':'USD'}, {'kind':'income','amount':'10.10','currency':'CNY'}, {'kind':'expense','amount':'2.05','currency':'CNY'}], {'CNY':{'income':'10.10','expense':'2.05','net':'8.05'},'USD':{'income':'3.00','expense':'0.00','net':'3.00'}}),
    ('empty', [], {}),
    ('decimal', [{'kind':'income','amount':'0.10','currency':'ZZZ'},{'kind':'income','amount':'0.20','currency':'ZZZ'}], {'ZZZ':{'income':'0.30','expense':'0.00','net':'0.30'}}),
    ('bad-kind', [{'kind':'refund','amount':'1.00','currency':'CNY'}], None),
    ('missing-kind', [{'amount':'1.00','currency':'CNY'}], None),
    ('bad-amount', [{'kind':'income','amount':'not-a-number','currency':'CNY'}], None),
    ('negative-amount', [{'kind':'expense','amount':'-2.00','currency':'CNY'}], None),
    ('not-list', {'kind':'income','amount':'1.00','currency':'CNY'}, None),
    ('no-partial-result', [{'kind':'income','amount':'3.00','currency':'CNY'}, {'kind':'refund','amount':'1.00','currency':'CNY'}], None),
]


def evaluate(workspace):
    workspace = Path(workspace).resolve()
    manifest = workspace / 'delivery-object.json'
    entry = workspace / (json.loads(manifest.read_text())['entry'] if manifest.exists() else 'app.py')
    if not entry.resolve().is_relative_to(workspace) or not entry.is_file():
        return {'verdict':'fail','reason':'actual delivery entry is missing or outside fixture','cases':[]}
    records=[]
    with tempfile.TemporaryDirectory(prefix='ledger-oracle-') as directory:
        for name, data, expected in CASES:
            source=Path(directory)/(name+'.json');source.write_text(json.dumps(data))
            try:
                result=subprocess.run([sys.executable,str(entry),str(source)],cwd=workspace,text=True,capture_output=True,timeout=15)
                actual=None
                if result.stdout.strip():
                    try: actual=json.loads(result.stdout)
                    except json.JSONDecodeError: actual='invalid JSON'
                ordered_currency_keys = isinstance(actual, dict) and list(actual) == sorted(actual)
                passed=(result.returncode!=0 and not result.stdout.strip()) if expected is None else (result.returncode==0 and actual==expected and ordered_currency_keys)
                records.append({'id':name,'passed':passed,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr,'expected':expected,'actual':actual,'ordered_currency_keys':ordered_currency_keys})
            except subprocess.TimeoutExpired:
                records.append({'id':name,'passed':False,'reason':'actual consumer timed out'})
    return {'verdict':'pass' if all(c['passed'] for c in records) else 'fail','actual_entry':str(entry),'cases':records}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--workspace',required=True);parser.add_argument('--output')
    args=parser.parse_args();value=evaluate(args.workspace);text=json.dumps(value,ensure_ascii=False,indent=2)
    if args.output: Path(args.output).write_text(text+'\n')
    print(text);raise SystemExit(0 if value['verdict']=='pass' else 1)
