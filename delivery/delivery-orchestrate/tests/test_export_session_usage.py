"""Export session usage regression tests against a fixture sqlite database."""
import csv
import io
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def build_fixture(db_path: Path):
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE model_usage (session_id TEXT, turn_id TEXT, started_at INTEGER,"
        " model_id TEXT, input_tokens INTEGER, output_tokens INTEGER,"
        " cache_read_input_tokens INTEGER, cache_creation_input_tokens INTEGER,"
        " duration_ms INTEGER)"
    )
    rows = [
        ("main", "t1", 1000, "GLM-5.3", 1000, 100, 800, 0, 1200),
        ("sub", "t2", 2000, "GLM-5.3", 500, 50, 400, 0, 300),
        ("main", "t3", 3000, "GLM-5.3", 2000, 200, 1600, 0, 1800),
    ]
    connection.executemany("INSERT INTO model_usage VALUES (?,?,?,?,?,?,?,?,?)", rows)
    connection.commit()
    connection.close()


class ExportSessionUsageTests(unittest.TestCase):
    def run_export(self, *extra, db=None):
        db = db or self.db
        proc = subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / "export_session_usage.py"),
             "--source", "zcode", "--db", str(db), *extra],
            capture_output=True, text=True,
        )
        return proc

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "db.sqlite"
        build_fixture(self.db)

    def test_exports_all_rows_sorted_with_header(self):
        proc = self.run_export()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = list(csv.reader(io.StringIO(proc.stdout)))
        self.assertEqual(rows[0][0], "session_id")
        self.assertEqual([r[2] for r in rows[1:]], ["1000", "2000", "3000"])
        self.assertEqual(rows[1][4], "1000")
        self.assertEqual(rows[1][6], "800")

    def test_session_and_time_filters(self):
        proc = self.run_export("--sessions", "main")
        ids = {r[0] for r in list(csv.reader(io.StringIO(proc.stdout)))[1:]}
        self.assertEqual(ids, {"main"})
        proc = self.run_export("--since", "1970-01-01T00:00:02+00:00",
                               "--until", "1970-01-01T00:00:02+00:00")
        rows = list(csv.reader(io.StringIO(proc.stdout)))[1:]
        self.assertEqual([r[2] for r in rows], ["2000"])

    def test_missing_db_and_future_source_fail_fast(self):
        proc = self.run_export(db=Path(self.temp.name) / "nope.sqlite")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not found", proc.stderr)
        proc = subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / "export_session_usage.py"),
             "--source", "claude"], capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
