"""Prove discriminating power; this does not claim agents discovered defects."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SPEC=importlib.util.spec_from_file_location('oracle',Path(__file__).parent/'evaluation/ledger_oracle.py')
ORACLE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(ORACLE)
CORRECT='''import json, sys
from decimal import Decimal
try:
 rows=json.load(open(sys.argv[1])); assert isinstance(rows,list)
 out={}
 for r in rows:
  assert r['kind'] in ('income','expense')
  value=Decimal(r['amount']); assert value.is_finite() and value>0
  d=out.setdefault(r['currency'],dict(income=Decimal('0'),expense=Decimal('0')))
  d[r['kind']]+=value
 print(json.dumps({c:dict(income=format(d['income'],'.2f'),expense=format(d['expense'],'.2f'),net=format(d['income']-d['expense'],'.2f')) for c,d in sorted(out.items())}))
except Exception as error:
 print(str(error),file=sys.stderr);sys.exit(2)
'''


class OracleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'app.py').write_text('print("{}")\n')
        (self.root/'tests').mkdir()
    def tearDown(self):self.temp.cleanup()
    def green_tests(self,body):
        (self.root/'tests/test_green.py').write_text(body)
        run=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=self.root,text=True,capture_output=True)
        self.assertEqual(0,run.returncode,run.stderr)
    def test_disconnected_consumer_with_passing_library_tests_fails(self):
        (self.root/'report.py').write_text('def total(): return "8.05"\n')
        self.green_tests('import unittest\nimport report\nclass Test(unittest.TestCase):\n def test_total(self): self.assertEqual("8.05",report.total())\n')
        self.assertEqual('fail',ORACLE.evaluate(self.root)['verdict'])
    def test_all_skipped_tests_cannot_prove_actual_behavior(self):
        self.green_tests('import unittest\n@unittest.skip("later")\nclass Test(unittest.TestCase):\n def test_live(self): self.fail()\n')
        self.assertEqual('fail',ORACLE.evaluate(self.root)['verdict'])
    def test_mock_integration_cannot_prove_actual_consumer(self):
        self.green_tests('import unittest\nfrom unittest.mock import Mock\nclass Test(unittest.TestCase):\n def test_report(self): self.assertEqual("8.05",Mock(return_value="8.05")())\n')
        self.assertEqual('fail',ORACLE.evaluate(self.root)['verdict'])
    def test_correct_source_wrong_actual_delivery_object_fails(self):
        (self.root/'app.py').write_text(CORRECT)
        (self.root/'installed.py').write_text('print("{}")\n')
        (self.root/'delivery-object.json').write_text('{"entry":"installed.py"}')
        self.assertEqual('fail',ORACLE.evaluate(self.root)['verdict'])
    def test_correct_actual_delivery_passes(self):
        (self.root/'app.py').write_text(CORRECT)
        self.assertEqual('pass',ORACLE.evaluate(self.root)['verdict'])
    def test_reverse_output_currency_order_fails_despite_equal_mapping(self):
        (self.root/'app.py').write_text(CORRECT.replace('sorted(out.items())','reversed(sorted(out.items()))'))
        result=ORACLE.evaluate(self.root)
        mixed=next(item for item in result['cases'] if item['id']=='mixed')
        self.assertEqual(mixed['expected'],mixed['actual'])
        self.assertFalse(mixed['ordered_currency_keys'])
        self.assertEqual('fail',result['verdict'])
    def test_input_insertion_order_does_not_satisfy_sorted_output(self):
        (self.root/'app.py').write_text(CORRECT.replace('sorted(out.items())','out.items()'))
        result=ORACLE.evaluate(self.root)
        normal=next(item for item in result['cases'] if item['id']=='mixed')
        reverse=next(item for item in result['cases'] if item['id']=='reverse-currency-input')
        self.assertTrue(normal['passed'])
        self.assertFalse(reverse['passed'])
        self.assertEqual('fail',result['verdict'])
    def test_equivalent_correct_organization_passes(self):
        (self.root/'business.py').write_text(CORRECT)
        (self.root/'app.py').write_text('import business\n')
        self.assertEqual('pass',ORACLE.evaluate(self.root)['verdict'])


if __name__=='__main__':unittest.main()
