import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "folo_receive.py"
SPEC = importlib.util.spec_from_file_location("folo_receive", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

NOW = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)


def make_entry(entry_id, title, url, feed_id, feed_title, published="2026-10-19T10:00:00Z", description=""):
    return {
        "entries": {
            "id": entry_id,
            "title": title,
            "url": url,
            "description": description,
            "publishedAt": published,
        },
        "feeds": {"id": feed_id, "title": feed_title},
    }


def base_config(vault: Path) -> dict:
    return {
        "vault_root": str(vault),
        "output_dir": "10-Inbox",
        "window_hours": 24,
        "timeline_limit": 200,
        "now_max": 2,
        "daily_max": 5,
        "min_score": 3,
        "max_per_feed": 2,
        "tiers": {"T1": ["T1 Feed"], "T2": ["T2 Feed"]},
        "priority_keywords": ["agent"],
        "include_keywords": ["RAG", "benchmark"],
        "exclude_keywords": ["招聘"],
    }


class MatchTests(unittest.TestCase):
    def test_feed_exact_and_wildcard(self):
        feed = {"id": "123", "url": "https://example.com/feed", "title": "T1 Feed"}
        self.assertTrue(MODULE.feed_matches("T1 Feed", feed))
        self.assertTrue(MODULE.feed_matches("*Feed", feed))
        self.assertFalse(MODULE.feed_matches("T2 Feed", feed))

    def test_keyword_word_boundary(self):
        self.assertTrue(MODULE.keyword_hit("A new RAG pipeline", "RAG"))
        self.assertFalse(MODULE.keyword_hit("storage layer", "RAG"))
        self.assertTrue(MODULE.keyword_hit("新的知识库方案", "知识库"))

    def test_tier_for(self):
        tiers = {"T1": ["T1 Feed"], "T2": ["T2 Feed"]}
        self.assertEqual(MODULE.tier_for({"title": "T1 Feed"}, tiers), "T1")
        self.assertEqual(MODULE.tier_for({"title": "T2 Feed"}, tiers), "T2")
        self.assertEqual(MODULE.tier_for({"title": "Other"}, tiers), "T3")


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.subscriptions = [
            {"feedId": "f1", "title": "T1 Feed", "category": "80深度"},
            {"feedId": "f2", "title": "T2 Feed", "category": "20新闻"},
            {"feedId": "f3", "title": "Pool", "category": "10社区"},
            {"feedId": "f4", "title": "Archive", "category": "99归档"},
        ]
        self.entries = [
            make_entry("e1", "Agent context update", "https://a.com/1", "f1", "T1 Feed"),
            make_entry("e2", "New RAG benchmark", "https://b.com/1", "f2", "T2 Feed"),
            make_entry("e3", "招聘信息", "https://b.com/2", "f2", "T2 Feed"),
            make_entry("e4", "Random pool item", "https://c.com/1", "f3", "Pool"),
            make_entry("e5", "New RAG benchmark", "https://b.com/3", "f2", "T2 Feed"),
            make_entry("e6", "Misc news", "https://b.com/4", "f2", "T2 Feed"),
            make_entry("e7", "Already retained", "https://a.com/2", "f2", "T2 Feed"),
            make_entry("e8", "Archived item", "https://d.com/1", "f4", "Archive"),
        ]
        self.retained = {
            "sources": {"https://a.com/2"},
            "title_keys": set(),
        }

    def test_build_digest_filters_and_scores(self):
        with tempfile.TemporaryDirectory() as temp:
            config = base_config(Path(temp))
            digest, stats, processed = MODULE.build_digest(
                self.entries,
                self.subscriptions,
                config,
                self.retained,
                {"entries": {}},
                include_seen=False,
                now=NOW,
            )
            self.assertEqual(stats["t3"], 1)
            self.assertEqual(stats["archived"], 1)
            self.assertEqual(stats["excluded"], 1)
            self.assertEqual(stats["duplicate"], 1)
            self.assertEqual(stats["below"], 1)
            self.assertEqual(stats["retained"], 1)
            self.assertIn("Agent context update", digest)
            self.assertIn("New RAG benchmark", digest)
            self.assertNotIn("招聘信息", digest)
            self.assertNotIn("Random pool item", digest)
            self.assertNotIn("Misc news", digest)
            self.assertNotIn("Already retained", digest)
            self.assertIn("现在看", digest)
            self.assertIn("今日候选", digest)
            statuses = {item["entry_id"]: item["status"] for item in processed}
            self.assertEqual(statuses["e1"], "shown")
            self.assertEqual(statuses["e2"], "shown")
            self.assertEqual(statuses["e6"], "skipped")

    def test_seen_entry_is_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            config = base_config(Path(temp))
            seen = {"entries": {"e1": {"status": "shown"}, "e2": {"status": "shown"}}}
            digest, stats, _ = MODULE.build_digest(
                self.entries,
                self.subscriptions,
                config,
                self.retained,
                seen,
                include_seen=False,
                now=NOW,
            )
            self.assertEqual(stats["seen"], 2)
            self.assertNotIn("Agent context update", digest)
            self.assertNotIn("https://b.com/1", digest)

    def test_include_seen_reprocesses(self):
        with tempfile.TemporaryDirectory() as temp:
            config = base_config(Path(temp))
            seen = {"entries": {"e1": {"status": "shown"}}}
            digest, _, _ = MODULE.build_digest(
                self.entries,
                self.subscriptions,
                config,
                self.retained,
                seen,
                include_seen=True,
                now=NOW,
            )
            self.assertIn("Agent context update", digest)


class MainTests(unittest.TestCase):
    def fixture(self, vault: Path) -> tuple[Path, Path]:
        subscriptions = [
            {"feedId": "f1", "title": "T1 Feed", "category": "80深度"},
            {"feedId": "f2", "title": "T2 Feed", "category": "20新闻"},
        ]
        entries = [
            make_entry("e1", "Agent context update", "https://a.com/1", "f1", "T1 Feed"),
            make_entry("e2", "New RAG benchmark", "https://b.com/1", "f2", "T2 Feed"),
        ]
        fixture = vault / "fixture.json"
        fixture.write_text(
            json.dumps({"subscriptions": subscriptions, "entries": entries}),
            encoding="utf-8",
        )
        config = vault / "config.json"
        config.write_text(json.dumps(base_config(vault)), encoding="utf-8")
        (vault / "11-Clippings").mkdir()
        (vault / "10-Inbox").mkdir()
        return config, fixture

    def run_main(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = MODULE.main(args)
        return code, output.getvalue()

    def test_dry_run_does_not_write_or_update_state(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            config, fixture = self.fixture(vault)
            state = vault / "state.json"
            code, output = self.run_main(
                [
                    "--config",
                    str(config),
                    "--from-json",
                    str(fixture),
                    "--date",
                    "2026-10-20",
                    "--state-file",
                    str(state),
                ]
            )
            self.assertEqual(code, 0)
            self.assertIn("现在看", output)
            self.assertFalse((vault / "10-Inbox" / "folo-digest-2026-10-20.md").exists())
            self.assertFalse(state.exists())

    def test_write_creates_digest_and_state(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            config, fixture = self.fixture(vault)
            state = vault / "state.json"
            args = [
                "--config",
                str(config),
                "--from-json",
                str(fixture),
                "--date",
                "2026-10-20",
                "--state-file",
                str(state),
                "--write",
            ]
            code, output = self.run_main(args)
            self.assertEqual(code, 0)
            digest_path = vault / "10-Inbox" / "folo-digest-2026-10-20.md"
            self.assertTrue(digest_path.exists())
            digest = digest_path.read_text(encoding="utf-8")
            self.assertIn("Agent context update", digest)
            self.assertIn("New RAG benchmark", digest)
            self.assertIn("WROTE", output)
            saved = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(saved["entries"]["e1"]["status"], "shown")
            self.assertEqual(saved["entries"]["e2"]["status"], "shown")

            code, _ = self.run_main(args)
            self.assertEqual(code, 0)
            saved = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(saved["entries"]["e1"]["last_seen"], "2026-10-20")


if __name__ == "__main__":
    unittest.main()
