import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EntryTests(unittest.TestCase):
    def invoke(self, directory):
        return subprocess.run([sys.executable, '-B', str(directory / 'app.py')], cwd=directory, text=True, capture_output=True, timeout=10)

    def test_actual_current_entry_and_readonly_settings(self):
        path = ROOT / 'settings.json'
        before = path.read_bytes()
        expected = 2 * json.loads(before)['factor']
        result = self.invoke(ROOT)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({'result': expected}, json.loads(result.stdout))
        self.assertEqual('', result.stderr)
        self.assertEqual(before, path.read_bytes())

    def test_configuration_is_read_again_each_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            shutil.copyfile(ROOT / 'app.py', target / 'app.py')
            for factor in (-3, 5, 0):
                with self.subTest(factor=factor):
                    (target / 'settings.json').write_text(json.dumps({'factor': factor}))
                    result = self.invoke(target)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual({'result': 2 * factor}, json.loads(result.stdout))

    def test_configuration_errors_have_no_partial_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            shutil.copyfile(ROOT / 'app.py', target / 'app.py')
            for payload in (None, '[', '[]', '{}', '{"factor":true}', '{"factor":"2"}', '{"factor":2.5}'):
                with self.subTest(payload=payload):
                    config = target / 'settings.json'
                    if payload is None:
                        config.unlink(missing_ok=True)
                    else:
                        config.write_text(payload)
                    result = self.invoke(target)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual('', result.stdout)
                    self.assertTrue(result.stderr)
