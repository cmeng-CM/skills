"""Behavioral checks in injected directories, never the user's install roots."""
import errno
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import pty
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ENTRY = Path(__file__).resolve().parents[1] / "skill"
loader = importlib.machinery.SourceFileLoader("local_skill_manager", str(ENTRY))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
loader.exec_module(m)


class TTYInput(io.StringIO):
    def isatty(self):
        return True


class TTYOutput(io.StringIO):
    def isatty(self):
        return True


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="skill-manager-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.repo = self.base / "repo with spaces"
        self.repo.mkdir()
        self.ctx = m.Context(self.repo, {"claude": self.base / "claude", "agents": self.base / "agents"},
                             self.base / "cache/write.lock", cwd=self.base,
                             stdin=io.StringIO(), stdout=io.StringIO(), stderr=io.StringIO())
        self.ctx.vault_root = self.base / "vault"

    def package(self, name="alpha", group=""):
        p = self.repo / group / name
        p.mkdir(parents=True)
        (p / "SKILL.md").write_text("original")
        return p

    def vault_package(self, rel):
        p = self.ctx.vault_root / rel
        p.mkdir(parents=True)
        (p / "SKILL.md").write_text(
            "---\nname: x\ndescription: 测试用 Vault skill\n---\n")
        return p

    def link(self, name, target, client="claude"):
        p = self.ctx.targets[client] / name
        p.parent.mkdir(exist_ok=True)
        p.symlink_to(target)
        return p

    def call(self, *args):
        for stream in (self.ctx.stdout, self.ctx.stderr):
            stream.seek(0)
            stream.truncate()
        return m.main(list(args), self.ctx)

    def files(self):
        return sorted(str(p.relative_to(self.base)) for p in self.base.rglob("*"))

    def test_discovery_scope_excludes_snapshots_archives_aliases(self):
        self.package()
        self.package("beta", "delivery")
        self.package("snapshot", "docs/evidence")
        self.package("old", "Archive")
        self.package("nested", "alpha/references")
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "SKILL.md").write_text("external")
        (self.repo / "alias").symlink_to(outside)
        self.assertEqual(set(m.scan(self.ctx).rows), {"alpha", "beta"})

    def test_status_and_preview_never_create_targets_or_lock(self):
        self.package()
        before = self.files()
        for args in (("status",), ("install", "alpha", "--dry-run"), ("remove", "alpha", "--dry-run")):
            self.assertEqual(self.call(*args), 0)
            self.assertEqual(self.files(), before)
        self.assertFalse(self.ctx.lock_path.parent.exists())

    def test_install_direct_idempotent_and_edits_visible(self):
        source = self.package()
        self.assertEqual(self.call("install", "alpha"), 0)
        slots = [base / "alpha" for base in self.ctx.targets.values()]
        ids = [(p.lstat().st_ino, p.lstat().st_ctime_ns) for p in slots]
        self.assertTrue(all(p.is_symlink() and p.resolve() == source for p in slots))
        self.assertEqual(self.call("install", "alpha", "alpha"), 0)
        self.assertEqual(ids, [(p.lstat().st_ino, p.lstat().st_ctime_ns) for p in slots])
        (source / "SKILL.md").write_text("changed")
        self.assertTrue(all((p / "SKILL.md").read_text() == "changed" for p in slots))

    def test_partial_install_only_fills_missing(self):
        source = self.package()
        slot = self.link("alpha", source)
        inode = slot.lstat().st_ino
        self.assertEqual(self.call("install", "alpha"), 0)
        self.assertEqual(slot.lstat().st_ino, inode)
        self.assertTrue((self.ctx.targets["agents"] / "alpha").is_symlink())

    def test_relative_link_and_legacy_path(self):
        source = self.package("alpha", "delivery")
        self.link("alpha", os.path.relpath(source, self.ctx.targets["claude"]))
        self.assertEqual(m.scan(self.ctx).rows["alpha"]["claude"].state, m.CONNECTED)
        self.assertEqual(self.call("install", str(source.relative_to(self.base))), 0)
        self.assertEqual(self.call("uninstall", str(source)), 0)
        self.assertTrue(source.exists())

    def test_foreign_files_directories_and_links_preserved(self):
        source = self.package()
        slot = self.ctx.targets["claude"] / "alpha"
        slot.parent.mkdir()
        outside = self.base / "outside"
        outside.write_text("sentinel")
        for kind in ("file", "directory", "link"):
            with self.subTest(kind=kind):
                if kind == "file":
                    slot.write_text("sentinel")
                elif kind == "directory":
                    slot.mkdir()
                    (slot / "sentinel").write_text("sentinel")
                else:
                    slot.symlink_to(outside)
                inode = slot.lstat().st_ino
                self.assertEqual(self.call("install", "alpha"), 1)
                self.assertEqual(self.call("remove", "alpha"), 1)
                self.assertEqual(slot.lstat().st_ino, inode)
                self.assertEqual(outside.read_text(), "sentinel")
                self.assertFalse(self.ctx.targets["agents"].exists())
                shutil.rmtree(slot) if kind == "directory" else slot.unlink()
        self.assertEqual((source / "SKILL.md").read_text(), "original")

    def test_target_filter_ignores_other_client_conflict(self):
        self.package()
        slot = self.ctx.targets["agents"] / "alpha"
        slot.parent.mkdir()
        slot.write_text("external")
        self.assertEqual(self.call("install", "alpha", "--target", "claude"), 0)
        self.assertEqual(self.call("remove", "alpha", "--target", "claude"), 0)
        self.assertEqual(slot.read_text(), "external")

    def test_conflict_aborts_whole_batch_before_writing(self):
        self.package()
        self.package("beta")
        self.ctx.targets["agents"].mkdir()
        (self.ctx.targets["agents"] / "beta").write_text("sentinel")
        self.assertEqual(self.call("install", "alpha", "beta"), 1)
        self.assertFalse(self.ctx.targets["claude"].exists())
        self.assertFalse(self.ctx.lock_path.exists())

    def test_duplicate_source_blocks_both_actions(self):
        self.package()
        self.package("alpha", "delivery")
        self.assertEqual(self.call("install", "alpha"), 1)
        self.assertEqual(self.call("remove", "alpha"), 1)

    def test_source_move_repairs_owned_link(self):
        source = self.package()
        slot = self.link("alpha", source)
        destination = self.repo / "delivery/alpha"
        destination.parent.mkdir()
        source.rename(destination)
        self.assertEqual(m.scan(self.ctx).rows["alpha"]["claude"].state, m.STALE)
        self.assertEqual(self.call("install", "alpha"), 0)
        self.assertEqual(slot.resolve(), destination)

    def test_deleted_source_is_cleanup_only(self):
        source = self.package()
        slot = self.link("alpha", source)
        shutil.rmtree(source)
        self.assertEqual(m.scan(self.ctx).rows["alpha"]["claude"].state, m.DELETED)
        self.assertEqual(self.call("install", "alpha"), 1)
        self.assertEqual(self.call("remove", str(source)), 0)
        self.assertFalse(slot.is_symlink())
        self.assertEqual(self.call("remove", "alpha"), 2)

    def test_removed_marker_is_not_a_source(self):
        source = self.package()
        self.link("alpha", source)
        (source / "SKILL.md").unlink()
        self.assertEqual(m.scan(self.ctx).rows["alpha"]["claude"].state, m.DELETED)

    def test_orphan_cleanup_then_later_failure_reports_without_losing_results(self):
        source = self.package()
        self.link("alpha", source)
        shutil.rmtree(source)
        beta = self.package("beta")
        self.link("beta", beta)
        original = Path.unlink
        def remove(path, *args, **kwargs):
            if path.name == "beta":
                raise PermissionError("injected")
            return original(path, *args, **kwargs)
        with patch.object(Path, "unlink", remove):
            self.assertEqual(self.call("remove", "alpha", "beta"), 1)
        self.assertFalse((self.ctx.targets["claude"] / "alpha").is_symlink())
        self.assertTrue((self.ctx.targets["claude"] / "beta").is_symlink())
        self.assertIn("未执行", self.ctx.stdout.getvalue())

    def test_uninstall_idempotent_no_source_deletion_or_new_directories(self):
        source = self.package()
        before = self.files()
        self.assertEqual(self.call("remove", "alpha"), 0)
        self.assertEqual(self.files(), before)
        self.assertEqual(self.call("install", "alpha"), 0)
        self.assertEqual(self.call("remove", "alpha"), 0)
        self.assertEqual(self.call("remove", "alpha"), 0)
        self.assertTrue((source / "SKILL.md").is_file())

    def test_cycles_escapes_and_similar_repo_prefix_not_owned(self):
        self.package()
        outside = self.base / "repo with spaces-other/alpha"
        outside.mkdir(parents=True)
        slot = self.link("alpha", outside)
        self.assertEqual(self.call("remove", "alpha"), 1)
        slot.unlink()
        slot.symlink_to(slot)
        self.assertEqual(self.call("remove", "alpha"), 1)
        slot.unlink()
        shutil.rmtree(self.repo / "alpha")
        (self.repo / "alpha").symlink_to(outside)
        slot.symlink_to(self.repo / "alpha")
        snapshot = m.scan(self.ctx)
        self.assertIn("alpha", snapshot.rows)
        self.assertEqual(snapshot.groups["alpha"], m.GROUP_EXT)
        self.assertEqual(snapshot.rows["alpha"]["claude"].state, m.LINK_OTHER)
        self.assertEqual(self.call("remove", "alpha"), 2)
        self.assertTrue(slot.is_symlink())

    def test_foreign_path_invalid_name_and_unknown_batch_zero_writes(self):
        self.package()
        for arg in ("../alpha", "/elsewhere/alpha", "..", ".", "alpha\n", "unknown"):
            self.assertEqual(self.call("install", "alpha", arg), 2)
        self.assertFalse(self.ctx.targets["claude"].exists())

    def test_inspection_permission_error_is_not_absent(self):
        self.package()
        original = Path.iterdir
        def entries(path):
            if path == self.ctx.targets["agents"]:
                raise PermissionError("denied fixture")
            return original(path)
        with patch.object(Path, "iterdir", entries):
            self.assertEqual(self.call("status"), 1)
            self.assertIn("检查错误", self.ctx.stdout.getvalue())
            self.assertEqual(self.call("install", "alpha"), 1)
            self.assertEqual(self.call("install", "alpha", "--target", "claude"), 0)

    def test_partial_failure_and_retry_preserve_success(self):
        self.package()
        original = Path.symlink_to
        def create(path, *args, **kwargs):
            if path.parent == self.ctx.targets["agents"]:
                raise PermissionError("injected failure")
            return original(path, *args, **kwargs)
        with patch.object(Path, "symlink_to", create):
            self.assertEqual(self.call("install", "alpha"), 1)
        slot = self.ctx.targets["claude"] / "alpha"
        inode = slot.lstat().st_ino
        self.assertEqual(self.call("install", "alpha"), 0)
        self.assertEqual(slot.lstat().st_ino, inode)

    def test_repair_creation_failure_retry(self):
        source = self.package()
        slot = self.link("alpha", source)
        destination = self.repo / "delivery/alpha"
        destination.parent.mkdir()
        source.rename(destination)
        with patch.object(Path, "symlink_to", side_effect=PermissionError("injected")):
            self.assertEqual(self.call("install", "alpha"), 1)
        self.assertFalse(os.path.lexists(slot))
        self.assertEqual(self.call("install", "alpha"), 0)
        self.assertEqual(slot.resolve(), destination)

    def test_interrupt_stops_remaining_items_and_can_retry(self):
        self.package()
        self.package("beta")
        original = Path.symlink_to
        count = 0
        def create(path, *args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise KeyboardInterrupt()
            return original(path, *args, **kwargs)
        with patch.object(Path, "symlink_to", create):
            self.assertEqual(self.call("install", "alpha", "beta"), 130)
        self.assertTrue((self.ctx.targets["claude"] / "alpha").is_symlink())
        self.assertFalse((self.ctx.targets["claude"] / "beta").exists())
        self.assertIn("未执行", self.ctx.stdout.getvalue())
        self.assertEqual(self.call("install", "alpha", "beta"), 0)

    def test_cross_process_lock_contention_and_release(self):
        self.package()
        self.ctx.lock_path.parent.mkdir()
        child = subprocess.Popen([sys.executable, "-c",
            "import fcntl,sys; f=open(sys.argv[1],'a'); fcntl.flock(f,fcntl.LOCK_EX); "
            "print('locked',flush=True); sys.stdin.readline()", str(self.ctx.lock_path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "locked")
            self.assertEqual(self.call("install", "alpha"), 1)
            self.assertIn("另一个", self.ctx.stderr.getvalue())
        finally:
            child.communicate("release\n", timeout=5)
        self.assertEqual(self.call("install", "alpha"), 0)

    def test_expired_menu_confirmation_does_not_execute(self):
        source = self.package()
        plan = m.make_plan(self.ctx, m.scan(self.ctx), "install", ["alpha"])
        self.link("alpha", source)
        with self.assertRaises(m.OperationError):
            m.execute(self.ctx, plan, confirmed=True)
        self.assertFalse(self.ctx.targets["agents"].exists())

    def test_later_slot_changed_after_preflight_stops_batch(self):
        self.package()
        self.package("beta")
        original = Path.symlink_to
        first = True
        def create(path, *args, **kwargs):
            nonlocal first
            result = original(path, *args, **kwargs)
            if first:
                first = False
                self.ctx.targets["agents"].mkdir()
                (self.ctx.targets["agents"] / "alpha").write_text("external arrived")
            return result
        with patch.object(Path, "symlink_to", create):
            self.assertEqual(self.call("install", "alpha", "beta"), 1)
        self.assertEqual((self.ctx.targets["agents"] / "alpha").read_text(), "external arrived")
        self.assertFalse((self.ctx.targets["claude"] / "beta").exists())

    def test_menu_filter_details_batch_dedup_and_confirm_once(self):
        self.package()
        self.package("beta")
        self.ctx.stdin = TTYInput("/alpha\nv 1\ni 1 1\ny\n/\ni 1 2\ny\nr 1 2\ny\nq\n")
        self.ctx.stdout = TTYOutput()
        self.assertEqual(m.main([], self.ctx), 0)
        output = self.ctx.stdout.getvalue()
        self.assertEqual(output.count("执行以上变更？"), 3)
        self.assertIn("源码：", output)
        self.assertFalse((self.ctx.targets["claude"] / "alpha").is_symlink())
        self.assertFalse((self.ctx.targets["agents"] / "beta").is_symlink())

    def test_menu_cancel_eof_bad_selection_empty_state_zero_writes(self):
        self.package()
        for commands in ("i 0\ni 99\ni no\nv 1 2\nq\n", "i 1\nn\nq\n", "i 1\n"):
            self.ctx.stdin = TTYInput(commands)
            self.ctx.stdout = TTYOutput()
            before = self.files()
            self.assertEqual(m.main([], self.ctx), 0)
            self.assertEqual(self.files(), before)
        shutil.rmtree(self.repo / "alpha")
        self.ctx.stdin = TTYInput("i 1\n/\nq\n")
        self.assertEqual(m.main([], self.ctx), 0)
        self.assertIn("没有可管理", self.ctx.stdout.getvalue())

    def test_non_tty_aliases_help_and_argument_errors(self):
        self.package()
        self.assertEqual(self.call(), 0)
        output = self.ctx.stdout.getvalue()
        self.assertNotIn("输入操作", output)
        self.assertEqual(self.call("list"), 0)
        self.assertEqual(self.ctx.stdout.getvalue(), output)
        for args in (("install",), ("remove",), ("bogus",), ("install", "alpha", "--target", "bad")):
            self.assertEqual(self.call(*args), 2)
        self.assertEqual(self.call("--help"), 0)

    def test_direct_entry_preserves_spaced_path_and_reports_errors(self):
        source = self.package("alpha with spaces")
        self.assertEqual(self.call("install", str(source), "--target", "claude"), 0)
        slot = self.ctx.targets["claude"] / source.name
        self.assertEqual(slot.resolve(), source)
        self.assertFalse(self.ctx.targets["agents"].exists())
        self.assertEqual(self.call("remove", str(source), "--target", "claude"), 0)
        self.assertFalse(slot.is_symlink())
        self.assertTrue((source / "SKILL.md").exists())
        self.assertEqual(self.call("install", "/external/alpha with spaces"), 2)

    def test_vault_links_grouped_readonly_with_target_labels(self):
        self.package()
        both = self.vault_package("61-skills/folo")
        single = self.vault_package("61-skills/dupe")
        self.link("folo", both, "claude")
        self.link("folo", both, "agents")
        self.link("dupe", single, "claude")
        snapshot = m.scan(self.ctx)
        self.assertEqual(snapshot.groups["folo"], m.GROUP_VAULT)
        self.assertEqual(snapshot.groups["dupe"], m.GROUP_VAULT)
        self.assertEqual(self.call("status"), 0)
        output = self.ctx.stdout.getvalue()
        self.assertIn("自建 · Obsidian Vault 2 项 · 只读，v 看来源", output)
        self.assertIn("folo", output)
        self.assertIn("两端链接 → 61-skills/folo", output)
        self.assertIn("仅 Claude 链接 → 61-skills/dupe", output)
        self.assertEqual(self.call("install", "folo"), 2)
        self.assertIn("不在安装范围", self.ctx.stderr.getvalue())
        self.assertFalse((self.ctx.targets["agents"] / "dupe").exists())

    def test_external_independent_share_warning_and_json(self):
        for client in self.ctx.targets:
            slot = self.ctx.targets[client] / "twin"
            slot.parent.mkdir(parents=True, exist_ok=True)
            slot.mkdir()
            (slot / "SKILL.md").write_text("---\nname: twin\ndescription: 外部副本\n---\n")
        home = self.ctx.targets["agents"] / "shared"
        home.mkdir(parents=True)
        (home / "SKILL.md").write_text("---\nname: shared\n---\n")
        self.link("shared", home, "claude")
        self.assertEqual(self.call("status"), 0)
        output = self.ctx.stdout.getvalue()
        self.assertIn("两端独立 ⚠ 各一份", output)
        self.assertIn("Claude 共享 · Agents 独立", output)
        self.assertIn("外部 · 独立安装", output)
        self.assertEqual(self.call("status", "--json"), 0)
        payload = json.loads(self.ctx.stdout.getvalue())
        self.assertEqual(payload["summary"]["external"], 2)
        by_name = {item["name"]: item for item in payload["skills"]}
        self.assertEqual(by_name["twin"]["origin"], "external")
        self.assertEqual(by_name["twin"]["claude"]["state"], "independent")
        self.assertEqual(by_name["twin"]["warning"], "independent-copies")
        self.assertEqual(by_name["shared"]["claude"]["state"], "share")
        self.assertEqual(by_name["shared"]["claude"]["target"], str(home))

    def test_group_order_sinks_uninstalled_and_numbers_continue(self):
        self.package("alpha")
        beta = self.package("beta")
        self.link("beta", beta, "claude")
        self.link("beta", beta, "agents")
        vault = self.vault_package("61-skills/pine")
        self.link("pine", vault, "claude")
        self.link("pine", vault, "agents")
        self.assertEqual(self.call("status"), 0)
        output = self.ctx.stdout.getvalue()
        self.assertIn("仓库 · 自建 2 项 · i / r 可管理", output)
        positions = [output.index(text) for text in
                     ("beta", "alpha", "自建 · Obsidian Vault", "pine")]
        self.assertEqual(positions, sorted(positions))
        numbers = [line.split()[0] for line in output.splitlines()
                   if line.strip()[:1].isdigit()]
        self.assertEqual(numbers, ["1", "2", "3"])

    def test_menu_rejects_install_on_readonly_groups_without_writes(self):
        self.package("alpha")
        vault = self.vault_package("61-skills/pine")
        self.link("pine", vault, "claude")
        self.ctx.stdin = TTYInput("i 2\nq\n")
        self.ctx.stdout = TTYOutput()
        self.assertEqual(m.main([], self.ctx), 0)
        output = self.ctx.stdout.getvalue() + self.ctx.stderr.getvalue()
        self.assertIn("2 号属于「自建 · Obsidian Vault」组，不在安装范围。", output)
        self.assertIn("i / r 仅接受「仓库」组编号", output)
        self.assertFalse((self.ctx.targets["claude"] / "alpha").exists())

    def test_detail_shows_description_boundary_and_hash_compare(self):
        for client in self.ctx.targets:
            slot = self.ctx.targets[client] / "twin"
            slot.parent.mkdir(parents=True, exist_ok=True)
            slot.mkdir()
            (slot / "SKILL.md").write_text("---\nname: twin\ndescription: 外部副本\n---\n")
        (self.ctx.targets["agents"] / "twin" / "SKILL.md").write_text(
            "---\nname: twin\ndescription: 外部副本（旧）\n---\n")
        vault = self.vault_package("61-skills/pine")
        self.link("pine", vault, "claude")
        self.link("pine", vault, "agents")
        self.ctx.stdin = TTYInput("v 1\nv 2\nq\n")
        self.ctx.stdout = TTYOutput()
        self.assertEqual(m.main([], self.ctx), 0)
        output = self.ctx.stdout.getvalue()
        self.assertIn("⚠ 两端各一份独立副本，更新互不同步", output)
        self.assertIn("两端不一致（内容哈希不同）", output)
        self.assertIn("说明：外部副本", output)
        self.assertIn("本工具不修改、不删除外部目录", output)
        self.assertIn("本工具不修改此条目；调整请维护 Vault 源目录", output)
        self.assertIn("说明：测试用 Vault skill", output)

    def test_real_pty_menu_on_isolated_context(self):
        self.package()
        runner = self.base / "pty_runner.py"
        runner.write_text(
            "import runpy,sys\nfrom pathlib import Path\n"
            f"m=runpy.run_path({str(ENTRY)!r})\n"
            f"ctx=m['Context'](Path({str(self.repo)!r}),"
            f"{{'claude':Path({str(self.ctx.targets['claude'])!r}),'agents':Path({str(self.ctx.targets['agents'])!r})}},"
            f"Path({str(self.ctx.lock_path)!r}))\n"
            "sys.exit(m['main']([],ctx))\n")
        master, slave = pty.openpty()
        child = subprocess.Popen([sys.executable, "-B", str(runner)], stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        data, sent = b"", False
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as exc:
                        if exc.errno == errno.EIO:
                            break
                        raise
                    if not chunk:
                        break
                    data += chunk
                    if not sent and "输入操作".encode() in data:
                        os.write(master, b"/alpha\nv 1\ni 1\nn\nq\n")
                        sent = True
                if child.poll() is not None and not ready:
                    break
            self.assertEqual(child.wait(timeout=2), 0, data.decode(errors="replace"))
            self.assertIn("源码：", data.decode())
            self.assertIn("已取消", data.decode())
            self.assertFalse(self.ctx.targets["claude"].exists())
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            os.close(master)


if __name__ == "__main__":
    unittest.main()
