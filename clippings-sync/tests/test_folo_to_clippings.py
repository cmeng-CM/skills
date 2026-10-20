import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "folo_to_clippings.py"
SPEC = importlib.util.spec_from_file_location("folo_to_clippings", SCRIPT)
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
    def test_reads_quoted_source(self):
        with tempfile.TemporaryDirectory() as temp:
            clippings = Path(temp) / "11-Clippings"
            clippings.mkdir()
            (clippings / "one.md").write_text(
                '---\ntitle: "One"\nsource: "https://example.com/a?utm_source=x"\n---\n\nbody\n',
                encoding="utf-8",
            )
            sources = MODULE.load_existing_sources(clippings)
            self.assertIn("https://example.com/a", sources)

    def test_ignores_files_without_frontmatter(self):
        with tempfile.TemporaryDirectory() as temp:
            clippings = Path(temp) / "11-Clippings"
            clippings.mkdir()
            (clippings / "one.md").write_text("no frontmatter\n", encoding="utf-8")
            self.assertEqual(MODULE.load_existing_sources(clippings), set())


class PlanTests(unittest.TestCase):
    def test_deduplicates_existing_and_within_batch(self):
        with tempfile.TemporaryDirectory() as temp:
            clippings = Path(temp) / "11-Clippings"
            clippings.mkdir()
            existing = {"https://example.com/a"}
            entries = [
                make_entry("e1", "Duplicate", "https://example.com/a?utm_source=x"),
                make_entry("e2", "New", "https://example.com/b"),
                make_entry("e3", "Same batch", "https://example.com/b"),
            ]
            plan = MODULE.build_plan(
                entries,
                existing,
                set(),
                lambda entry_id: "<p>body</p>" if entry_id == "e2" else "",
                clippings,
                pending=True,
                pandoc_bin="definitely-missing-pandoc",
            )
            statuses = [item["status"] for item in plan]
            self.assertEqual(statuses, ["duplicate", "add", "duplicate"])

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
                set(),
                {"samearticle"},
                lambda entry_id: "<p>body</p>",
                clippings,
                pending=True,
                pandoc_bin="definitely-missing-pandoc",
            )
            self.assertEqual(plan[0]["status"], "duplicate")

    def test_no_content_is_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            clippings = Path(temp) / "11-Clippings"
            clippings.mkdir()
            entries = [make_entry("e1", "Empty", "https://example.com/empty")]
            plan = MODULE.build_plan(
                entries,
                set(),
                set(),
                lambda entry_id: "",
                clippings,
                pending=True,
                pandoc_bin="definitely-missing-pandoc",
            )
            self.assertEqual(plan[0]["status"], "no_content")


class MainTests(unittest.TestCase):
    def fixture(self, vault: Path) -> Path:
        fixture = {
            "entries": [
                make_entry("e1", "Existing", "https://example.com/existing?utm_source=x"),
                make_entry("e2", "New / Article", "https://example.com/new"),
                make_entry(
                    "e3",
                    "Video",
                    "https://example.com/video",
                    description="Video description",
                ),
                make_entry("e4", "Empty", "https://example.com/empty"),
            ],
            "contents": {
                "e2": "<h2>Hello</h2><p>World</p>",
            },
        }
        path = vault / "fixture.json"
        path.write_text(json.dumps(fixture), encoding="utf-8")
        return path

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            clippings = vault / "11-Clippings"
            clippings.mkdir()
            (clippings / "existing.md").write_text(
                '---\ntitle: "Existing"\nsource: "https://example.com/existing"\n---\n\nbody\n',
                encoding="utf-8",
            )
            fixture = self.fixture(vault)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = MODULE.main(
                    [
                        "--vault-root",
                        str(vault),
                        "--from-json",
                        str(fixture),
                        "--pandoc-bin",
                        "definitely-missing-pandoc",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("Dry run", output.getvalue())
            self.assertEqual(sorted(path.name for path in clippings.glob("*.md")), ["existing.md"])

    def test_write_creates_files_without_touching_existing(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            clippings = vault / "11-Clippings"
            clippings.mkdir()
            existing = clippings / "existing.md"
            original = (
                '---\ntitle: "Existing"\nsource: "https://example.com/existing"\n---\n\nbody\n'
            )
            existing.write_text(original, encoding="utf-8")
            fixture = self.fixture(vault)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = MODULE.main(
                    [
                        "--vault-root",
                        str(vault),
                        "--from-json",
                        str(fixture),
                        "--pandoc-bin",
                        "definitely-missing-pandoc",
                        "--write",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(existing.read_text(encoding="utf-8"), original)
            names = sorted(path.name for path in clippings.glob("*.md"))
            self.assertEqual(len(names), 3)
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


if __name__ == "__main__":
    unittest.main()
