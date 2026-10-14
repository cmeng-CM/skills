"""真实 CLI 回归；所有仓库、命令及旧账本均为隔离 fixture。"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "workflow.py"
SPEC = importlib.util.spec_from_file_location("workflow", SCRIPT)
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)


class WorkflowCLI(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-q")
        (self.root / "source.py").write_text("def test_example():\n    return True\n")
        self.git("add", "source.py")
        self.commit()
        self.make_plan()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True,
                              text=True, check=True).stdout.strip()

    def commit(self):
        self.git("-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", "fixture")

    def cli(self, *args, expected=0):
        process = subprocess.run([sys.executable, "-B", str(SCRIPT), *args, "--json"],
                                 cwd=self.root, capture_output=True, text=True)
        self.assertEqual(process.returncode, expected, process.stdout + process.stderr)
        try:
            return json.loads(process.stdout)
        except ValueError:
            self.fail(process.stdout + process.stderr)

    def make_plan(self, slug="probe", command="true", rows=None, version=1,
                  status="complete", after_command="", goal="fixture"):
        if not (self.root / ".workflow" / slug).exists():
            self.cli("init", slug, "--goal", goal)
        if rows is None:
            rows = ["| A1 | `source.py::test_example` | 自动化 | 必需 | |"]
        text = (f"**Goal**: {goal}\n**格式**: {version}\n"
                "**设计文档**: 无 — 独立临时回归测试不需要单独设计文档\n"
                "## 方案\nfixture scheme\n"
                f"## 验证命令\n```sh\n{command}\n```\n{after_command}\n"
                "## 决策\n| ID | 决策 | 来源 | 理由 |\n|---|---|---|---|\n"
                "| D-01 | fixture decision | 用户 | fixture rationale |\n"
                "## 验证覆盖\n| 对象 | 验证手段 | 类型 | 必需性 | 证据 |\n|---|---|---|---|---|\n"
                + "\n".join(rows) + "\n## 阶段\n#### T1 fixture\n"
                "- **验收**：结果正确\n- **失败信号**：结果错误\n"
                f"- **状态**：{status}\n")
        self.plan(slug).write_text(text)

    def plan(self, slug="probe"):
        return self.root / ".workflow" / slug / "plan.md"

    def events(self, slug="probe"):
        path = self.root / ".workflow" / slug / "events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def confirm(self, *items, slug="probe", command="confirm", expected=0, **extra):
        checklist = self.cli("acceptance", slug)["checklist"]
        args = [command, slug, "--checklist", checklist, "--by", "用户已核对明确清单 A1/A2 并通过",
                "--source", "conversation:fixture#user-7"]
        for item in items:
            args.extend(["--item", item])
        for key, value in extra.items():
            args.extend(["--" + key.replace("_", "-"), value])
        return self.cli(*args, expected=expected)

    def legacy_close(self, slug="probe", after=""):
        path = self.root / ".workflow" / slug / "ledger.md"
        with path.open("a") as fh:
            fh.write("\n## 收尾\n| 时间 | 完成 | 指纹 | 下一步 |\n|---|---|---|---|\n"
                     "| 2026-01-01 12:00 | 1/1 | 0123456789abcdef | — |\n" + after)

    def test_fenced_pipeline_and_multiline_roundtrip(self):
        command = "printf 'a|b\\n' | cat\nprintf 'second\\n'"
        self.make_plan(command=command, after_command="> explanation is not a command")
        result = self.cli("verify", "probe")
        self.assertEqual(result["command"], command)
        self.assertEqual(result["output_tail"], ["a|b", "second"])
        event = self.events()[-1]
        self.assertEqual(event["data"]["command"], command)
        self.assertEqual(event["data"]["exit_code"], 0)
        self.cli("close", "probe")
        self.cli("sync", "probe")
        ledger = (self.root / ".workflow/probe/ledger.md").read_text()
        self.assertIn("&#124;", ledger)
        self.assertIn("<br>", ledger)

    def test_failure_returns_nonzero_and_generic_manual_cannot_bypass(self):
        self.make_plan(command="false")
        result = self.cli("verify", "probe", expected=2)
        self.assertEqual(result["exit_code"], 1)
        self.assertFalse(result["passed"])
        self.cli("close", "probe", expected=1)
        self.cli("close", "probe", "--manual-confirmed", "all accepted", expected=1)
        self.confirm("A1", expected=1)
        self.confirm("A1", command="waive", reason="用户明确取消该覆盖项")
        self.cli("close", "probe", expected=1)

    def test_command_override_is_diagnostic_only(self):
        self.make_plan(command="false")
        result = self.cli("verify", "probe", "--command", "true", expected=2)
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("实际命令", "".join(result["blockers"]))
        self.cli("close", "probe", expected=1)

    def test_manual_pending_partial_batch_and_per_item_events(self):
        self.make_plan(rows=["| A1 | 打开页面，预期显示完整 | 人工 | 必需 | |",
                             "| A2 | 点击按钮，预期打开弹窗 | 人工 | 必需 | |"])
        result = self.cli("verify", "probe", expected=2)
        self.assertEqual(len(result["pending"]), 2)
        self.assertTrue(result["command_passed"])
        self.assertIn("等待人工验收", self.cli("status", "probe")["stage"])
        self.confirm("A1")
        self.cli("close", "probe", expected=1)
        self.confirm("A1", "A2")
        records = [e for e in self.events() if e["type"] == "manual"]
        self.assertEqual([e["data"]["item"] for e in records], ["A1", "A1", "A2"])
        self.assertEqual(records[-1]["data"]["source"], records[-2]["data"]["source"])
        self.cli("close", "probe")

    def test_optional_manual_and_unknown_do_not_block(self):
        self.make_plan(rows=["| A1 | `source.py` | 自动化 | 必需 | |",
                             "| feedback | 可选反馈 | 人工 | 可选 | |",
                             "| diagnostic | descriptive words | 自动化 | 可选 | |"])
        result = self.cli("verify", "probe")
        self.assertFalse(result["pending"])
        self.assertFalse(result["unknown"])
        self.cli("close", "probe")

    def test_unknown_required_blocks_and_supplement_does_not_execute(self):
        command = "printf run >> .workflow/probe/counter"
        self.make_plan(command=command, rows=["| A1 | inspect test result | 自动化 | 必需 | |"])
        result = self.cli("verify", "probe", expected=2)
        self.assertEqual(len(result["unknown"]), 1)
        self.cli("close", "probe", expected=1)
        self.cli("evidence", "probe", "--verify", result["event"], "--item", "A1",
                 "--ref", "source.py", "--source", "关联本次测试源文件及结果")
        self.assertEqual((self.root / ".workflow/probe/counter").read_text(), "run")
        self.cli("close", "probe")

    def test_independent_reference_can_be_corrected_without_rerun(self):
        self.make_plan(rows=["| A1 | inspect test result | 自动化 | 必需 | `missing.py` |"])
        self.cli("verify", "probe", expected=2)
        self.plan().write_text(self.plan().read_text().replace("`missing.py`", "`source.py`"))
        self.cli("close", "probe")

    def test_changed_means_with_same_path_invalidates_and_cannot_supplement(self):
        result = self.cli("verify", "probe")
        self.plan().write_text(self.plan().read_text().replace("`source.py::test_example`", "`source.py::test_example` 新预期"))
        self.cli("evidence", "probe", "--verify", result["event"], "--item", "A1",
                 "--ref", "source.py", "--source", "原引用仍然存在", expected=1)
        self.cli("close", "probe", expected=1)

    def test_manual_instruction_change_invalidates_confirmation(self):
        self.make_plan(command="", rows=["| A1 | 打开页面，预期显示完整 | 人工 | 必需 | |"])
        self.confirm("A1")
        self.plan().write_text(self.plan().read_text().replace("预期显示完整", "预期自动保存"))
        result = self.cli("verify", "probe", expected=2)
        self.assertEqual(len(result["pending"]), 1)

    def test_bookkeeping_preserves_binding_and_version_changes_invalidate(self):
        result = self.cli("verify", "probe")
        (self.root / ".workflow/probe/note.md").write_text("只是记账")
        self.cli("sync", "probe")
        state = self.cli("status", "probe")
        self.assertEqual(state["acceptance"]["fingerprint"], result["fingerprint"])
        (self.root / "source.py").write_text("changed\n")
        self.cli("close", "probe", expected=1)

    def test_head_changes_invalidate_active_but_not_closed(self):
        self.cli("verify", "probe")
        self.git("-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "--allow-empty", "-qm", "new head")
        self.cli("close", "probe", expected=1)
        self.cli("verify", "probe")
        self.cli("close", "probe")
        (self.root / "unrelated").write_text("x")
        self.git("add", "unrelated")
        self.commit()
        self.assertTrue(self.cli("status", "probe")["closed"])

    def test_large_untracked_same_size_change_invalidates(self):
        path = self.root / "large output.bin"
        path.write_bytes(b"a" * (1024 * 1024 + 17))
        self.cli("verify", "probe")
        path.write_bytes(b"b" * (1024 * 1024 + 17))
        self.cli("close", "probe", expected=1)

    def test_worktree_drift_during_verification_is_not_valid(self):
        self.make_plan(command="printf changed >> source.py")
        result = self.cli("verify", "probe", expected=2)
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(self.events()[-1]["data"]["stable"])
        self.cli("close", "probe", expected=1)

    def test_acceptance_drift_during_verification_is_not_valid(self):
        self.make_plan(command="printf '\\n- **预期**：changed\\n' >> .workflow/probe/plan.md")
        self.cli("verify", "probe", expected=2)
        self.assertFalse(self.events()[-1]["data"]["stable"])

    def test_latest_failure_cannot_be_skipped_by_supplement(self):
        self.make_plan(command="test ! -f .workflow/probe/fail")
        first = self.cli("verify", "probe")
        (self.root / ".workflow/probe/fail").touch()
        self.cli("verify", "probe", expected=2)
        self.cli("evidence", "probe", "--verify", first["event"], "--item", "A1",
                 "--ref", "source.py", "--source", "旧成功", expected=1)

    def test_missing_or_damaged_receipt_cannot_close_or_supplement(self):
        result = self.cli("verify", "probe")
        path = self.root / self.events()[-1]["data"]["receipt"]
        path.write_text('{"exit_code": 0}')
        self.cli("close", "probe", expected=1)
        self.cli("evidence", "probe", "--verify", result["event"], "--item", "A1",
                 "--ref", "source.py", "--source", "试图补证", expected=1)

    def test_corrupt_events_never_fall_back_to_legacy_pass(self):
        self.cli("verify", "probe")
        path = self.root / ".workflow/probe/events.jsonl"
        with path.open("a") as fh:
            fh.write('{"type":')
        self.legacy_close()
        self.cli("status", "probe", expected=1)
        self.cli("verify", "probe", expected=1)
        self.cli("close", "probe", expected=1)

    def test_schema_invalid_event_is_not_ignored(self):
        self.cli("verify", "probe")
        path = self.root / ".workflow/probe/events.jsonl"
        data = self.events()
        data[-1]["schema"] = 999
        path.write_text("".join(json.dumps(e) + "\n" for e in data))
        self.cli("status", "probe", expected=1)

    def test_legacy_closed_preserved_and_no_close_remains_active(self):
        self.legacy_close()
        (self.root / "unrelated").write_text("later work")
        self.assertTrue(self.cli("status", "probe")["closed"])
        self.assertTrue(self.cli("close", "probe")["already_closed"])
        self.assertEqual(self.events(), [])
        self.make_plan(slug="active")
        self.assertFalse(self.cli("status", "active")["closed"])
        self.assertEqual(self.cli("status")["slug"], "active")

    def test_legacy_later_execution_or_appended_tasks_is_active(self):
        self.legacy_close(after="\n## 验证记录\n| 2026-01-01 12:01 | new | abc | `true` | 0 | 0123456789abcdef | PASS |\n")
        self.assertFalse(self.cli("status", "probe")["closed"])
        self.make_plan(slug="appended")
        self.legacy_close("appended")
        with self.plan("appended").open("a") as fh:
            fh.write("\n#### T2 added\n- **状态**：complete\n")
        self.assertFalse(self.cli("status", "appended")["closed"])

    def test_legacy_pass_has_no_historical_acceptance_binding(self):
        path = self.root / ".workflow/probe/ledger.md"
        with path.open("a") as fh:
            fh.write("\n## 验证记录\n| 2026-01-01 12:01 | new | abc | `true` | 0 | 0123456789abcdef | PASS |\n")
        self.cli("close", "probe", expected=1)
        self.cli("evidence", "probe", "--verify", "legacy-pass", "--item", "A1",
                 "--ref", "source.py", "--source", "旧 PASS", expected=1)

    def test_malformed_legacy_pipe_and_multiline_are_not_guessed(self):
        path = self.root / ".workflow/probe/ledger.md"
        with path.open("a") as fh:
            fh.write("\n## 验证记录\n| 2026-01-01 12:01 | new | abc | `true | cat` | 0 | 0123456789abcdef | PASS |\n"
                     "| 2026-01-01 12:02 | new | abc | `true\ntrue` | 0 | 0123456789abcdef | PASS |\n")
        self.assertEqual(workflow._read_verify_records(str(self.root), "probe"), [])
        self.cli("close", "probe", expected=1)

    def test_close_idempotent_and_all_mutation_entrypoints_guarded(self):
        self.cli("verify", "probe")
        first = self.cli("close", "probe")
        count = len(self.events())
        self.cli("close", "probe")
        self.assertEqual(count, len(self.events()))
        self.cli("verify", "probe", expected=1)
        self.confirm("A1", command="waive", reason="closed", expected=1)
        self.confirm("A1", expected=1)
        self.cli("record", "probe", "T1", "--commits", "HEAD..HEAD", expected=1)
        self.cli("evidence", "probe", "--verify", first["event"], "--item", "A1",
                 "--ref", "source.py", "--source", "closed", expected=1)

    def test_reopen_retains_close_and_requires_new_cycle_evidence(self):
        self.cli("verify", "probe")
        self.cli("close", "probe")
        result = self.cli("reopen", "probe", "--reason", "原目标遗漏", "--by", "请修复该遗漏", "--work", "修补遗漏")
        self.assertEqual(result["cycle"], 2)
        self.assertEqual(result["task"], "T2")
        self.assertEqual(len([e for e in self.events() if e["type"] == "close"]), 1)
        self.cli("close", "probe", expected=1)
        self.plan().write_text(self.plan().read_text().replace("：pending", "：complete"))
        self.cli("close", "probe", expected=1)
        self.cli("verify", "probe")
        self.cli("close", "probe")
        self.assertEqual(len([e for e in self.events() if e["type"] == "close"]), 2)

    def test_legacy_reopen_preserves_legacy_close_snapshot(self):
        self.legacy_close()
        self.cli("reopen", "probe", "--reason", "原目标遗漏", "--by", "请修复", "--work", "修补遗漏")
        self.assertTrue(self.events()[0]["data"]["legacy_closed"])
        self.assertEqual(self.events()[0]["data"]["legacy_close"]["closed_at"], "2026-01-01 12:00")
        self.assertEqual(self.events()[-1]["cycle"], 2)

    def test_new_goal_init_links_source_without_mutation(self):
        self.legacy_close()
        before = self.plan().read_bytes()
        result = self.cli("init", "new-goal", "--goal", "另一个目标", "--from", "probe")
        self.assertEqual(result["source_workflow"], "probe")
        self.assertIn("**来源工作流**: probe", self.plan("new-goal").read_text())
        self.assertEqual(self.plan().read_bytes(), before)
        self.assertTrue(self.cli("status", "probe")["closed"])

    def test_old_three_column_formats_remain_parseable(self):
        for version in (1, 2, 3):
            self.make_plan(version=version)
            text = self.plan().read_text().replace(" | 必需性 | 证据", "").replace("|---|---|---|---|---|", "|---|---|---|")
            text = text.replace(" | 必需 | |", " |")
            self.plan().write_text(text)
            result = self.cli("verify", "probe")
            self.assertTrue(result["coverage"][0]["required"])

    def test_manual_only_requires_explicit_acceptance_not_empty(self):
        self.make_plan(command="", rows=[])
        self.cli("verify", "probe", expected=2)
        self.cli("close", "probe", expected=1)
        self.make_plan(command="", rows=["| A1 | 打开界面，预期内容完整 | 人工 | 必需 | |"])
        self.cli("verify", "probe", expected=2)
        self.confirm("A1")
        self.cli("verify", "probe")
        self.cli("close", "probe")

    def test_ambiguous_ids_and_stale_checklist_rejected(self):
        self.make_plan(command="", rows=["| A1 | 打开界面 | 人工 | 必需 | |"])
        checklist = self.cli("acceptance", "probe")["checklist"]
        self.plan().write_text(self.plan().read_text().replace("打开界面", "点击界面"))
        self.cli("confirm", "probe", "--item", "A1", "--checklist", checklist,
                 "--by", "确认", "--source", "reply", expected=1)
        self.make_plan(rows=["| A1 | `source.py` | 自动化 | 必需 | |"] * 2)
        self.cli("acceptance", "probe", expected=1)

    def test_legacy_approvals_remain_enforced(self):
        text = self.plan().read_text().replace("| A1 |", "| D-01 |")
        text = text.replace("## 阶段", "### 不验证的部分\n- 无\n## 阶段\n### Phase 1: fixture")
        text = text.replace("- **验收**", "- **决策**：D-01\n- **验收**")
        self.plan().write_text(text)
        self.cli("record", "probe", "T1", "--commits", "HEAD..HEAD", expected=1)
        self.cli("approve", "probe", "方案", "--by", "用户确认方案")
        self.cli("approve", "probe", "计划", "--by", "用户确认计划")
        self.cli("record", "probe", "T1", "--commits", "HEAD..HEAD", "--note", "fixture 不改代码")

    def test_multiline_command_keeps_blank_lines_inside_heredoc(self):
        command = "cat <<'END'\nfirst\n\nlast\nEND"
        self.make_plan(command=command)
        result = self.cli("verify", "probe")
        self.assertEqual(result["command"], command)
        self.assertEqual(result["output_tail"], ["first", "", "last"])

    def test_multiline_task_acceptance_change_invalidates(self):
        self.plan().write_text(self.plan().read_text().replace("- **验收**：结果正确", "- **验收**：结果正确\n  - 预期输出 A"))
        self.cli("verify", "probe")
        self.plan().write_text(self.plan().read_text().replace("预期输出 A", "预期输出 B"))
        self.cli("close", "probe", expected=1)

    def test_empty_acceptance_with_successful_command_does_not_pass(self):
        self.make_plan(rows=[])
        self.cli("verify", "probe", expected=2)
        self.cli("close", "probe", expected=1)

    def test_valid_json_but_incomplete_close_snapshot_is_corrupt(self):
        self.cli("verify", "probe")
        self.cli("close", "probe")
        data = self.events()
        data[-1]["data"]["snapshot"] = {}
        path = self.root / ".workflow/probe/events.jsonl"
        path.write_text("".join(json.dumps(e) + "\n" for e in data))
        self.cli("status", "probe", expected=1)
        self.cli("close", "probe", expected=1)

    def test_supplement_missing_artifact_is_rejected(self):
        result = self.cli("verify", "probe")
        self.cli("evidence", "probe", "--verify", result["event"], "--item", "A1",
                 "--ref", ".workflow/probe/missing.json", "--source", "缺失产物", expected=1)

    def test_supplement_artifact_changes_under_workflow_invalidate(self):
        self.make_plan(rows=["| A1 | inspect test output | 自动化 | 必需 | |"])
        artifact = self.root / ".workflow/probe/output.txt"
        artifact.write_text("original verified output")
        result = self.cli("verify", "probe", expected=2)
        self.cli("evidence", "probe", "--verify", result["event"], "--item", "A1",
                 "--ref", ".workflow/probe/output.txt", "--source", "关联输出")
        artifact.write_text("later different output")
        self.cli("close", "probe", expected=1)

    def test_rejected_manual_item_blocks_until_explicit_new_conclusion(self):
        self.make_plan(command="", rows=["| A1 | 打开界面，预期内容完整 | 人工 | 必需 | |"])
        self.confirm("A1", status="rejected")
        self.cli("close", "probe", expected=1)
        self.confirm("A1", status="passed")
        self.cli("close", "probe")

    def test_unknown_required_can_be_explicitly_waived(self):
        self.make_plan(rows=["| A1 | inspect test output | 自动化 | 必需 | |"])
        self.cli("verify", "probe", expected=2)
        self.confirm("A1", command="waive", reason="用户明确取消该项要求")
        self.cli("close", "probe")

    def test_explicit_ids_can_disambiguate_repeated_target_names(self):
        self.make_plan(command="", rows=["| A1 | 点击操作，预期打开窗口 | 人工 | 必需 | |"])
        text = self.plan().read_text().replace("| 对象 | 验证手段 | 类型 | 必需性 | 证据 |", "| ID | 对象 | 验证手段 | 类型 | 必需性 | 证据 |")
        text = text.replace("| A1 | 点击操作，预期打开窗口 | 人工 | 必需 | |",
                            "| M1 | 同一对象 | 点击操作，预期打开窗口 | 人工 | 必需 | |\n| M2 | 同一对象 | 关闭操作，预期窗口消失 | 人工 | 必需 | |")
        self.plan().write_text(text)
        self.confirm("M1", "M2")
        self.cli("close", "probe")


if __name__ == "__main__":
    unittest.main()
