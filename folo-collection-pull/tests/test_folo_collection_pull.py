import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "folo_collection_pull.py"
SPEC = importlib.util.spec_from_file_location("folo_collection_pull", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def make_entry(entry_id, title, url, description="", author="Alice"):
    return {
        "entries": {
            "id": entry_id,
            "title": title,
            "url": url,
            "description": description,
            "author": author,
            "publishedAt": "2026-10-19T00:00:00Z",
        },
        "feeds": {"title": "Test Feed"},
    }


def write_existing(clippings: Path, name: str, title: str, source: str) -> Path:
    path = clippings / name
    path.write_text(
        f'---\ntitle: "{title}"\nsource: "{source}"\n---\n\nbody\n',
        encoding="utf-8",
    )
    return path


class NormalizeUrlTests(unittest.TestCase):
    def test_removes_tracking_and_fragment(self):
        self.assertEqual(
            MODULE.normalize_url("https://Example.com/a/?utm_source=x&b=2#frag"),
            "https://example.com/a?b=2",
        )

    def test_keeps_wechat_identity_params(self):
        url = "https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1&sn=xyz&poc_token=drop"
        self.assertEqual(
            MODULE.normalize_url(url),
            "https://mp.weixin.qq.com/s?__biz=abc&idx=1&mid=123&sn=xyz",
        )

    def test_empty(self):
        self.assertEqual(MODULE.normalize_url(""), "")


class HtmlCleanupTests(unittest.TestCase):
    def test_unwraps_div_and_span_wrappers(self):
        try:
            import bs4  # noqa: F401
        except ImportError:
            self.skipTest("beautifulsoup4 not installed")
        cleaned = MODULE.clean_html(
            '<div><span><p>Hello</p></span></div><iframe src="https://example.com/player"></iframe>'
        )
        self.assertNotIn("<div", cleaned)
        self.assertNotIn("<span", cleaned)
        self.assertNotIn("<iframe", cleaned)
        self.assertIn("Hello", cleaned)


class FilenameTests(unittest.TestCase):
    def test_replaces_illegal_characters(self):
        self.assertEqual(
            MODULE.sanitize_filename('a/b:c?d*e"f<g>h|i', "id"),
            "a-b-c-d-e-f-g-h-i",
        )

    def test_uses_fallback_when_empty(self):
        self.assertEqual(MODULE.sanitize_filename(" / : ", "entry-id"), "clipping-entry-id")


class FrontmatterTests(unittest.TestCase):
    def test_pending_tag_and_fields(self):
        entry = make_entry("e1", "Title", "https://example.com/a")
        text = MODULE.render_frontmatter(entry["entries"], entry["entries"]["url"], True)
        self.assertIn('title: "Title"', text)
        self.assertIn('source: "https://example.com/a"', text)
        self.assertIn('  - "clippings"', text)
        self.assertIn('  - "待整理"', text)
        self.assertIn('description: ""', text)

    def test_no_pending_tag(self):
        entry = make_entry("e1", "Title", "https://example.com/a")
        text = MODULE.render_frontmatter(entry["entries"], entry["entries"]["url"], False)
        self.assertNotIn("待整理", text)


class ExistingSourceTests(unittest.TestCase):
    def test_reads_quoted_source_and_path(self):
        with tempfile.TemporaryDirectory() as temp:
            clippings = Path(temp) / "11-Clippings"
            clippings.mkdir()
            path = write_existing(
                clippings,
                "one.md",
                "One",
                "https://example.com/a?utm_source=x",
            )
            sources = MODULE.load_existing_sources(clippings)
            self.assertEqual(sources["https://example.com/a"], path)

    def test_reads_title_key_with_host(self):
        with tempfile.TemporaryDirectory() as temp:
            clippings = Path(temp) / "11-Clippings"
            clippings.mkdir()
            path = write_existing(
                clippings,
                "one.md",
                "Same Article",
                "https://mp.weixin.qq.com/s/old",
            )
            keys = MODULE.load_existing_title_keys(clippings)
            self.assertEqual(
                keys[
                    MODULE.title_key(
                        "Same Article", "https://mp.weixin.qq.com/s/new"
                    )
                ],
                path,
            )

    def test_ignores_files_without_frontmatter(self):
        with tempfile.TemporaryDirectory() as temp:
            clippings = Path(temp) / "11-Clippings"
            clippings.mkdir()
            (clippings / "one.md").write_text("no frontmatter\n", encoding="utf-8")
            self.assertEqual(MODULE.load_existing_sources(clippings), {})


class StateTests(unittest.TestCase):
    def test_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.json"
            state = {"version": 1, "updated_at": "", "entries": {}}
            entry = make_entry("e1", "Title", "https://example.com/a")["entries"]
            MODULE.record_state(state, entry, "pulled", "11-Clippings/a.md")
            MODULE.save_state(path, state)
            loaded = MODULE.load_state(path)
            record = loaded["entries"]["e1"]
            self.assertEqual(record["pull_status"], "pulled")
            self.assertEqual(record["process_status"], "unprocessed")
            self.assertEqual(record["clipping"], "11-Clippings/a.md")
            self.assertTrue(record["pulled_at"])

    def test_state_preserves_process_status(self):
        state = {"version": 1, "updated_at": "", "entries": {}}
        entry = make_entry("e1", "Title", "https://example.com/a")["entries"]
        MODULE.record_state(state, entry, "pulled", "11-Clippings/a.md")
        MODULE.update_process_status(state, ["e1"], "processed")
        MODULE.record_state(state, entry, "existing", "11-Clippings/a.md")
        self.assertEqual(state["entries"]["e1"]["process_status"], "processed")
        self.assertTrue(state["entries"]["e1"]["processed_at"])

    def test_state_index(self):
        state = {
            "version": 1,
            "entries": {
                "e1": {
                    "normalized_source": "https://example.com/a",
                    "title_key": "title@example.com",
                }
            },
        }
        ids, sources, keys = MODULE.state_index(state)
        self.assertEqual(ids, {"e1"})
        self.assertEqual(sources, {"https://example.com/a"})
        self.assertEqual(keys, {"title@example.com"})

    def test_corrupt_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                MODULE.load_state(path)


class PlanTests(unittest.TestCase):
    def test_deduplicates_existing_and_within_batch(self):
        with tempfile.TemporaryDirectory() as temp:
            clippings = Path(temp) / "11-Clippings"
            clippings.mkdir()
            existing = {"https://example.com/a": clippings / "a.md"}
            entries = [
                make_entry("e1", "Duplicate", "https://example.com/a?utm_source=x"),
                make_entry("e2", "New", "https://example.com/b"),
                make_entry("e3", "Same batch", "https://example.com/b"),
            ]
            plan = MODULE.build_plan(
                entries,
                existing,
                {},
                set(),
                set(),
                set(),
                lambda entry_id: "<p>body</p>" if entry_id == "e2" else "",
                clippings,
                pending=True,
                pandoc_bin="definitely-missing-pandoc",
            )
            statuses = [item["status"] for item in plan]
            self.assertEqual(statuses, ["duplicate", "add", "duplicate"])

    def test_pulled_id_is_skipped_without_fetching(self):
        with tempfile.TemporaryDirectory() as temp:
            clippings = Path(temp) / "11-Clippings"
            clippings.mkdir()
            entries = [make_entry("e1", "Already pulled", "https://example.com/a")]

            def should_not_be_called(entry_id):
                raise AssertionError("content should not be fetched for a pulled entry")

            plan = MODULE.build_plan(
                entries,
                {},
                {},
                {"e1"},
                set(),
                set(),
                should_not_be_called,
                clippings,
                pending=True,
                pandoc_bin="definitely-missing-pandoc",
            )
            self.assertEqual(plan[0]["status"], "duplicate")

    def test_link_only_when_description_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            clippings = Path(temp) / "11-Clippings"
            clippings.mkdir()
            entries = [
                make_entry(
                    "e1",
                    "Video",
                    "https://example.com/video",
                    description="A short video description",
                )
            ]
            plan = MODULE.build_plan(
                entries,
                {},
                {},
                set(),
                set(),
                set(),
                lambda entry_id: "",
                clippings,
                pending=True,
                pandoc_bin="definitely-missing-pandoc",
            )
            self.assertEqual(plan[0]["status"], "add")
            self.assertTrue(plan[0]["link_only"])
            self.assertIn("> 原文：", plan[0]["markdown"])

    def test_deduplicates_by_title_when_wechat_short_link_differs(self):
        with tempfile.TemporaryDirectory() as temp:
            clippings = Path(temp) / "11-Clippings"
            clippings.mkdir()
            entries = [
                make_entry(
                    "e1",
                    "Same Article",
                    "https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=1&sn=xyz",
                )
            ]
            plan = MODULE.build_plan(
                entries,
                {},
                {
                    MODULE.title_key(
                        "Same Article", "https://mp.weixin.qq.com/s/old"
                    ): clippings / "old.md"
                },
                set(),
                set(),
                set(),
                lambda entry_id: "<p>body</p>",
                clippings,
                pending=True,
                pandoc_bin="definitely-missing-pandoc",
            )
            self.assertEqual(plan[0]["status"], "duplicate")
            self.assertEqual(plan[0]["existing_path"].name, "old.md")

    def test_no_content_is_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            clippings = Path(temp) / "11-Clippings"
            clippings.mkdir()
            entries = [make_entry("e1", "Empty", "https://example.com/empty")]
            plan = MODULE.build_plan(
                entries,
                {},
                {},
                set(),
                set(),
                set(),
                lambda entry_id: "",
                clippings,
                pending=True,
                pandoc_bin="definitely-missing-pandoc",
            )
            self.assertEqual(plan[0]["status"], "no_content")


class MainTests(unittest.TestCase):
    def fixture(self, vault: Path, extra_entries=None) -> Path:
        entries = [
            make_entry("e1", "Existing", "https://example.com/existing?utm_source=x"),
            make_entry("e2", "New / Article", "https://example.com/new"),
            make_entry(
                "e3",
                "Video",
                "https://example.com/video",
                description="Video description",
            ),
            make_entry("e4", "Empty", "https://example.com/empty"),
        ]
        if extra_entries:
            entries.extend(extra_entries)
        fixture = {
            "entries": entries,
            "contents": {
                "e2": "<h2>Hello</h2><p>World</p>",
            },
        }
        path = vault / "fixture.json"
        path.write_text(json.dumps(fixture), encoding="utf-8")
        return path

    def run_main(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = MODULE.main(args)
        return code, output.getvalue()

    def default_args(self, vault: Path, fixture: Path) -> list[str]:
        return [
            "--vault-root",
            str(vault),
            "--from-json",
            str(fixture),
            "--pandoc-bin",
            "definitely-missing-pandoc",
        ]

    def test_dry_run_does_not_write_or_create_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            clippings = vault / "11-Clippings"
            clippings.mkdir()
            write_existing(clippings, "existing.md", "Existing", "https://example.com/existing")
            fixture = self.fixture(vault)
            code, output = self.run_main(self.default_args(vault, fixture))
            self.assertEqual(code, 0)
            self.assertIn("Dry run", output)
            self.assertEqual(sorted(path.name for path in clippings.glob("*.md")), ["existing.md"])
            self.assertFalse((clippings / MODULE.LEDGER_NAME).exists())

    def test_write_creates_files_and_second_run_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            clippings = vault / "11-Clippings"
            clippings.mkdir()
            existing = write_existing(
                clippings, "existing.md", "Existing", "https://example.com/existing"
            )
            original = existing.read_text(encoding="utf-8")
            fixture = self.fixture(vault)
            args = self.default_args(vault, fixture) + ["--write"]
            code, _ = self.run_main(args)
            self.assertEqual(code, 0)
            self.assertEqual(existing.read_text(encoding="utf-8"), original)
            first_names = sorted(
                path.name for path in clippings.glob("*.md")
            )
            self.assertEqual(len(first_names), 3)
            new_file = clippings / "New - Article.md"
            self.assertTrue(new_file.exists())
            content = new_file.read_text(encoding="utf-8")
            self.assertIn('title: "New / Article"', content)
            self.assertIn('  - "待整理"', content)
            self.assertIn("Hello", content)
            self.assertIn("World", content)
            video = clippings / "Video.md"
            self.assertTrue(video.exists())
            self.assertIn("> 原文：", video.read_text(encoding="utf-8"))

            ledger_path = clippings / MODULE.LEDGER_NAME
            self.assertTrue(ledger_path.exists())
            saved = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["entries"]["e2"]["pull_status"], "pulled")
            self.assertEqual(saved["entries"]["e2"]["process_status"], "unprocessed")
            self.assertEqual(saved["entries"]["e3"]["pull_status"], "pulled")
            self.assertEqual(saved["entries"]["e1"]["pull_status"], "existing")

            code, output = self.run_main(args)
            self.assertEqual(code, 0)
            second_names = sorted(path.name for path in clippings.glob("*.md"))
            self.assertEqual(second_names, first_names)
            self.assertIn("0 add", output)

    def test_baseline_skips_current_then_pulls_only_new_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            clippings = vault / "11-Clippings"
            clippings.mkdir()
            fixture = self.fixture(vault)
            baseline_args = self.default_args(vault, fixture) + ["--baseline"]
            code, output = self.run_main(baseline_args)
            self.assertEqual(code, 0)
            self.assertIn("BASELINE", output)
            self.assertEqual(list(clippings.glob("*.md")), [])
            ledger_path = clippings / MODULE.LEDGER_NAME
            saved = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["entries"]), 4)
            self.assertEqual(saved["entries"]["e1"]["pull_status"], "baseline")
            self.assertEqual(saved["entries"]["e1"]["process_status"], "unprocessed")

            write_args = self.default_args(vault, fixture) + ["--write"]
            code, output = self.run_main(write_args)
            self.assertEqual(code, 0)
            self.assertEqual(list(clippings.glob("*.md")), [])
            self.assertIn("0 add", output)

            new_fixture = self.fixture(
                vault,
                extra_entries=[make_entry("e5", "Fresh", "https://example.com/fresh")],
            )
            new_fixture_data = json.loads(new_fixture.read_text(encoding="utf-8"))
            new_fixture_data["contents"]["e5"] = "<p>Fresh content</p>"
            new_fixture.write_text(json.dumps(new_fixture_data), encoding="utf-8")
            code, _ = self.run_main(
                self.default_args(vault, new_fixture) + ["--write"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(
                sorted(path.name for path in clippings.glob("*.md")), ["Fresh.md"]
            )
            saved = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["entries"]["e5"]["pull_status"], "pulled")

    def test_include_pulled_can_pull_baseline_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            clippings = vault / "11-Clippings"
            clippings.mkdir()
            fixture = self.fixture(vault)
            self.run_main(self.default_args(vault, fixture) + ["--baseline"])
            code, _ = self.run_main(
                self.default_args(vault, fixture) + ["--write", "--include-pulled"]
            )
            self.assertEqual(code, 0)
            names = sorted(path.name for path in clippings.glob("*.md"))
            self.assertEqual(names, ["New - Article.md", "Video.md"])

    def test_mark_processed_ignored_and_show_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            clippings = vault / "11-Clippings"
            clippings.mkdir()
            fixture = self.fixture(vault)
            self.run_main(self.default_args(vault, fixture) + ["--write"])
            code, output = self.run_main(
                ["--vault-root", str(vault), "--mark-processed", "e2"]
            )
            self.assertEqual(code, 0)
            self.assertIn("processed", output)
            saved = json.loads(
                (clippings / MODULE.LEDGER_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual(saved["entries"]["e2"]["process_status"], "processed")
            self.assertTrue(saved["entries"]["e2"]["processed_at"])

            code, output = self.run_main(
                ["--vault-root", str(vault), "--mark-ignored", "e3"]
            )
            self.assertEqual(code, 0)
            saved = json.loads(
                (clippings / MODULE.LEDGER_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual(saved["entries"]["e3"]["process_status"], "ignored")

            code, output = self.run_main(
                ["--vault-root", str(vault), "--show-ledger"]
            )
            self.assertEqual(code, 0)
            self.assertIn("LEDGER", output)
            self.assertIn("processed", output)
            self.assertIn("ignored", output)
            self.assertIn("unprocessed", output)

    def test_corrupt_ledger_blocks_write(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            clippings = vault / "11-Clippings"
            clippings.mkdir()
            ledger_path = clippings / MODULE.LEDGER_NAME
            ledger_path.write_text("{not json", encoding="utf-8")
            fixture = self.fixture(vault)
            code, _ = self.run_main(self.default_args(vault, fixture) + ["--write"])
            self.assertEqual(code, 1)
            self.assertEqual(list(clippings.glob("*.md")), [])


if __name__ == "__main__":
    unittest.main()
