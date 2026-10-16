import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from money import to_cents, summarize

ROOT = Path(__file__).resolve().parents[1]


class MoneyTests(unittest.TestCase):
    def test_decimal_boundary_and_large_amount(self):
        self.assertEqual(29, to_cents('0.29'))
        self.assertEqual(9007199254740991, to_cents('90071992547409.91'))
        self.assertEqual(10, to_cents('0.1'))

    def test_actual_cli_and_order(self):
        rows = [{'kind':'income','amount':'3','currency':'USD'},
                {'kind':'income','amount':'0.29','currency':'CNY'},
                {'kind':'expense','amount':'0.01','currency':'CNY'}]
        result = self.cli(rows)
        self.assertEqual(0, result.returncode)
        data = json.loads(result.stdout)
        self.assertEqual(['CNY', 'USD'], list(data))
        self.assertEqual({'income':'0.29','expense':'0.01','net':'0.28'}, data['CNY'])

    def test_empty_and_expense_only(self):
        self.assertEqual({}, summarize([]))
        self.assertEqual('-0.29', summarize([{'kind':'expense','amount':'0.29','currency':'ZZZ'}])['ZZZ']['net'])

    def test_failures_have_no_partial_stdout(self):
        valid = {'kind':'income','amount':'0.29','currency':'CNY'}
        bad_rows = [None, [valid, {'kind':'refund','amount':'2','currency':'CNY'}],
                    [valid, {'kind':'income','amount':'bad','currency':'CNY'}],
                    [{'amount':'2','currency':'CNY'}]]
        for data in bad_rows:
            with self.subTest(data=data):
                result = self.cli(data)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('', result.stdout)

    def cli(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            path.write_text(json.dumps(rows))
            return subprocess.run([sys.executable, '-B', str(ROOT/'app.py'), str(path)], cwd=ROOT, text=True, capture_output=True)
