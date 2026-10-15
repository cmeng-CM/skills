"""真实 CLI 回归与解析输入矩阵；所有仓库、命令及旧账本均为隔离 fixture。"""
import importlib.util
import hashlib
import json
from pathlib import Path
import re
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
        self.make_plan(command="printf run >> .workflow/probe/counter",
                       rows=["| A1 | inspect test result | 自动化 | 必需 | `missing.py` |"])
        result = self.cli("verify", "probe", expected=2)
        self.plan().write_text(self.plan().read_text().replace("`missing.py`", "`source.py`"))
        self.cli("close", "probe", expected=1)
        self.cli("evidence", "probe", "--verify", result["event"], "--item", "A1",
                 "--ref", "source.py", "--source", "原验收引用拼写修正，关联原命令结果")
        self.cli("close", "probe")
        self.assertEqual((self.root / ".workflow/probe/counter").read_text(), "run")

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
        text = text.replace("|---|---|---|---|---|", "|---|---|---|---|---|---|")
        text = text.replace("| A1 | 点击操作，预期打开窗口 | 人工 | 必需 | |",
                            "| M1 | 同一对象 | 点击操作，预期打开窗口 | 人工 | 必需 | |\n| M2 | 同一对象 | 关闭操作，预期窗口消失 | 人工 | 必需 | |")
        self.plan().write_text(text)
        self.confirm("M1", "M2")
        self.cli("close", "probe")

    def test_review_i1_independent_workflow_artifact_mutation_blocks_close(self):
        artifact = self.root / ".workflow/probe/result.txt"
        artifact.write_text("verified result")
        self.make_plan(rows=["| A1 | inspect output | 自动化 | 必需 | `.workflow/probe/result.txt` |"])
        self.cli("verify", "probe")
        artifact.write_text("different result")
        self.assertFalse(self.cli("status", "probe")["acceptance"]["passed"])
        self.cli("close", "probe", expected=1)

    def test_review_i1_means_workflow_artifact_also_has_content_binding(self):
        artifact = self.root / ".workflow/probe/result.txt"
        artifact.write_text("verified result")
        self.make_plan(rows=["| A1 | `.workflow/probe/result.txt` | 自动化 | 必需 | |"])
        self.cli("verify", "probe")
        artifact.write_text("different result")
        self.cli("close", "probe", expected=1)

    def test_review_i1_changed_artifact_cannot_be_reblessed_by_evidence(self):
        artifact = self.root / ".workflow/probe/result.txt"
        artifact.write_text("verified result")
        self.make_plan(rows=["| A1 | inspect output | 自动化 | 必需 | `.workflow/probe/result.txt` |"])
        result = self.cli("verify", "probe")
        artifact.write_text("different result")
        self.cli("evidence", "probe", "--verify", result["event"], "--item", "A1",
                 "--ref", ".workflow/probe/result.txt", "--source", "试图更新为新输出", expected=1)
        self.cli("close", "probe", expected=1)

    def test_review_i2_checkpoint_change_invalidates_acceptance(self):
        self.plan().write_text(self.plan().read_text().replace("#### T1", "### Phase 1: fixture\n**Checkpoint**: 输出 A\n#### T1"))
        self.cli("verify", "probe")
        self.plan().write_text(self.plan().read_text().replace("输出 A", "输出 B"))
        self.cli("close", "probe", expected=1)

    def test_review_i2_fenced_constraints_and_additional_acceptance_are_bound(self):
        for before, after in [("## 全局约束\n```\n最大值 A\n```", "## 全局约束\n```\n最大值 B\n```"),
                              ("## 额外验收说明\n预期 A", "## 额外验收说明\n预期 B")]:
            with self.subTest(before=before):
                self.make_plan()
                self.plan().write_text(self.plan().read_text() + "\n" + before + "\n")
                self.cli("verify", "probe")
                self.plan().write_text(self.plan().read_text().replace(before, after))
                self.cli("close", "probe", expected=1)

    def test_review_i3_legacy_next_step_date_is_not_close_timestamp(self):
        self.legacy_close(after="\n## 验证记录\n| 2026-01-02 12:00 | later | abc | `false` | 1 | 0123456789abcdef | FAIL |\n")
        ledger = self.root / ".workflow/probe/ledger.md"
        ledger.write_text(ledger.read_text().replace("0123456789abcdef | — |", "0123456789abcdef | 2026-01-03 09:00 检查发布 |"))
        self.assertFalse(self.cli("status", "probe")["closed"])
        self.cli("close", "probe", expected=1)

    def test_review_m1_bookkeeping_after_legacy_close_does_not_reopen(self):
        self.legacy_close(after="\n## 裁决\n| 2026-01-02 12:00 | 已通知用户 | 未变更任务与验收 | — |\n")
        self.assertTrue(self.cli("status", "probe")["closed"])
        self.assertTrue(self.cli("close", "probe")["already_closed"])

    def test_residual_i1_repeated_supplement_cannot_rebind_changed_artifact(self):
        artifact = self.root / ".workflow/probe/output.txt"
        artifact.write_text("original output")
        self.make_plan(rows=["| A1 | inspect test output | 自动化 | 必需 | |"])
        result = self.cli("verify", "probe", expected=2)
        arguments = ["evidence", "probe", "--verify", result["event"], "--item", "A1",
                     "--ref", ".workflow/probe/output.txt", "--source", "关联原验证输出"]
        self.cli(*arguments)
        artifact.write_text("changed output")
        self.assertFalse(self.cli("status", "probe")["acceptance"]["passed"])
        self.cli(*arguments, expected=1)
        self.cli("close", "probe", expected=1)

    def test_residual_i1_different_path_cannot_replace_damaged_original(self):
        artifact = self.root / ".workflow/probe/output.txt"
        artifact.write_text("original output")
        (self.root / ".workflow/probe/replacement.txt").write_text("original output")
        self.make_plan(rows=["| A1 | `.workflow/probe/output.txt` | 自动化 | 必需 | |"])
        result = self.cli("verify", "probe")
        artifact.write_text("changed output")
        self.cli("evidence", "probe", "--verify", result["event"], "--item", "A1",
                 "--ref", ".workflow/probe/replacement.txt", "--source", "试图换路径", expected=1)
        self.cli("close", "probe", expected=1)

    def test_residual_i1_superseded_reference_remains_in_close_chain(self):
        artifact = self.root / ".workflow/probe/output.txt"
        artifact.write_text("original output")
        (self.root / ".workflow/probe/replacement.txt").write_text("original output")
        self.make_plan(rows=["| A1 | `.workflow/probe/output.txt` | 自动化 | 必需 | |"])
        result = self.cli("verify", "probe")
        self.cli("evidence", "probe", "--verify", result["event"], "--item", "A1",
                 "--ref", ".workflow/probe/replacement.txt", "--source", "原件完整，同内容引用")
        artifact.unlink()
        self.assertFalse(self.cli("status", "probe")["acceptance"]["passed"])
        self.cli("close", "probe", expected=1)

    def test_residual_i1_equivalent_reference_with_intact_chain_needs_no_rerun(self):
        (self.root / ".workflow/probe/output.txt").write_text("original output")
        (self.root / ".workflow/probe/replacement.txt").write_text("original output")
        self.make_plan(command="printf run >> .workflow/probe/counter",
                       rows=["| A1 | `.workflow/probe/output.txt` | 自动化 | 必需 | |"])
        result = self.cli("verify", "probe")
        self.cli("evidence", "probe", "--verify", result["event"], "--item", "A1",
                 "--ref", ".workflow/probe/replacement.txt", "--source", "原件完整，同内容引用")
        self.cli("close", "probe")
        self.assertEqual((self.root / ".workflow/probe/counter").read_text(), "run")

    def test_overall_i1_supplement_does_not_hide_changed_declaration(self):
        for reference in ("missing.py", "source.py::absent_symbol", "unparseable reference"):
            with self.subTest(reference=reference):
                self.make_plan(rows=["| A1 | inspect test output | 自动化 | 必需 | `source.py` |"])
                result = self.cli("verify", "probe")
                self.cli("evidence", "probe", "--verify", result["event"], "--item", "A1",
                         "--ref", "source.py", "--source", "fixture 原始关联")
                self.plan().write_text(self.plan().read_text().replace("`source.py`", f"`{reference}`"))
                self.assertFalse(self.cli("status", "probe")["acceptance"]["passed"])
                self.cli("close", "probe", expected=1)

    def test_overall_i1_new_declared_reference_needs_adoption_then_no_rerun(self):
        replacement = ".workflow/probe/replacement.txt"
        (self.root / replacement).write_text("intact replacement")
        self.make_plan(command="printf run >> .workflow/probe/counter",
                       rows=["| A1 | inspect test output | 自动化 | 必需 | `source.py` |"])
        result = self.cli("verify", "probe")
        self.cli("evidence", "probe", "--verify", result["event"], "--item", "A1",
                 "--ref", "source.py", "--source", "fixture 原始关联")
        self.plan().write_text(self.plan().read_text().replace("`source.py`", f"`{replacement}`"))
        self.cli("close", "probe", expected=1)
        self.cli("evidence", "probe", "--verify", result["event"], "--item", "A1",
                 "--ref", replacement, "--source", "fixture 当前声明关联")
        self.cli("close", "probe")
        self.assertEqual((self.root / ".workflow/probe/counter").read_text(), "run")

    def retire(self, verification, slug="probe", expected=0, **extra):
        values = {"verify": verification, "checklist": self.cli("acceptance", slug)["checklist"],
                  "by": "fixture 用户明确取消旧命令要求，改为当前人工清单", "source": "fixture:change#1",
                  "reason": "当前目标改用人工验收"}
        values.update(extra)
        args = ["retire-command", slug]
        for key, value in values.items():
            args.extend(["--" + key, value])
        return self.cli(*args, expected=expected)

    def manual_plan(self, slug="probe"):
        self.make_plan(slug, command="", rows=["| M1 | 打开页面，预期结果正确 | 人工 | 必需 | |"])

    def test_overall_i2_explicit_retirement_allows_manual_contract_preserves_history(self):
        for command, exit_code in (("true", 0), ("false", 1)):
            with self.subTest(command=command):
                slug = "manual-" + command
                self.make_plan(slug, command=command)
                old = self.cli("verify", slug, expected=0 if exit_code == 0 else 2)
                original = self.events(slug)[-1]
                receipt = self.root / original["data"]["receipt"]
                receipt_bytes = receipt.read_bytes()
                self.manual_plan(slug)
                listing = self.cli("acceptance", slug)
                self.assertEqual(listing["command_change"]["previous"]["command"], command)
                self.assertEqual(listing["command_change"]["current"]["command"], "")
                self.assertNotEqual(listing["command_change"]["previous"]["acceptance"], listing["acceptance"])
                self.confirm("M1", slug=slug)
                self.cli("close", slug, expected=1)
                retired = self.retire(old["event"], slug)
                result = self.cli("verify", slug)
                self.assertTrue(result["passed"])
                self.assertFalse(result["executed"])
                self.assertEqual(result["command_status"], "retired")
                self.assertIsNone(result["command_passed"])
                self.assertIsNone(result["command_exit_code"])
                self.assertIsNone(result["verification"])
                self.assertFalse(result["command_required"])
                self.assertEqual(result["retired_verification"]["exit_code"], exit_code)
                self.assertEqual(result["command_retirement"], retired["event"])
                self.cli("close", slug)
                self.assertTrue(self.cli("status", slug)["closed"])
                self.cli("sync", slug)
                self.cli("close", slug)
                self.assertEqual([e for e in self.events(slug) if e["type"] == "verify"], [original])
                self.assertEqual(receipt.read_bytes(), receipt_bytes)

    def test_overall_i1_every_declared_reference_must_be_adopted(self):
        extra = ".workflow/probe/extra.txt"
        (self.root / extra).write_text("additional original result")
        self.make_plan(rows=["| A1 | inspect output | 自动化 | 必需 | `source.py` |"])
        result = self.cli("verify", "probe")
        self.cli("evidence", "probe", "--verify", result["event"], "--item", "A1",
                 "--ref", "source.py", "--source", "fixture 关联")
        self.plan().write_text(self.plan().read_text().replace("`source.py`", f"`source.py` `{extra}`"))
        self.cli("close", "probe", expected=1)
        self.cli("evidence", "probe", "--verify", result["event"], "--item", "A1",
                 "--ref", extra, "--source", "fixture 补齐第二条当前引用")
        # 当前声明来自 verify + 两条补证的并集，不要求只匹配最后一次补证。
        self.cli("close", "probe")

    def test_retirement_is_not_implied_by_confirm_waive_or_deleting_command(self):
        self.make_plan(command="false")
        self.cli("verify", "probe", expected=2)
        self.manual_plan()
        self.cli("close", "probe", expected=1)
        self.confirm("M1", by="fixture 泛继续，不能当撤销命令授权")
        self.cli("close", "probe", expected=1)
        self.confirm("M1", command="waive", reason="fixture 仅豁免 M1")
        self.cli("close", "probe", expected=1)
        self.cli("close", "probe", "--manual-confirmed", "泛确认", expected=1)
        self.assertFalse(any(e["type"] == "command_retired" for e in self.events()))

    def test_retirement_requires_latest_identity_and_all_authorization_fields(self):
        self.make_plan(command="false")
        first = self.cli("verify", "probe", expected=2)
        last = self.cli("verify", "probe", expected=2)
        self.manual_plan()
        self.retire(first["event"], expected=1)
        self.retire("not-a-verification", expected=1)
        for field in ("by", "source", "reason"):
            with self.subTest(field=field):
                self.retire(last["event"], expected=1, **{field: " "})
        old_checklist = self.cli("acceptance", "probe")["checklist"]
        self.plan().write_text(self.plan().read_text().replace("结果正确", "结果完整正确"))
        self.retire(last["event"], checklist=old_checklist, expected=1)
        self.assertFalse(any(e["type"] == "command_retired" for e in self.events()))

    def test_retirement_rejects_current_command_required_auto_empty_and_bug(self):
        result = self.cli("verify", "probe")
        self.retire(result["event"], expected=1)  # 当前命令仍存在。
        self.make_plan(command="")  # 当前仍有必验自动化项。
        self.retire(result["event"], expected=1)
        self.make_plan(command="", rows=[])
        self.retire(result["event"], expected=1)
        self.manual_plan()
        self.plan().write_text("**类型**: bug\n" + self.plan().read_text())
        self.retire(result["event"], expected=1)
        self.manual_plan("no-history")
        self.retire(result["event"], slug="no-history", expected=1)

    def test_retirement_after_specific_auto_waiver_still_requires_manual_result(self):
        self.make_plan(command="false")
        result = self.cli("verify", "probe", expected=2)
        self.make_plan(command="", rows=["| A1 | `source.py` | 自动化 | 必需 | |",
                                         "| M1 | 打开页面，预期结果正确 | 人工 | 必需 | |"])
        self.retire(result["event"], expected=1)
        self.confirm("A1", command="waive", reason="fixture 用户明确取消 A1 自动化要求")
        self.retire(result["event"])
        self.assertIn("等待人工验收", self.cli("status", "probe")["stage"])
        self.cli("close", "probe", expected=1)
        self.confirm("M1")
        self.cli("close", "probe")

    def test_retirement_binding_invalidates_on_plan_and_worktree_changes(self):
        for mutation in ("plan", "worktree"):
            with self.subTest(mutation=mutation):
                slug = mutation
                self.make_plan(slug, command="false")
                result = self.cli("verify", slug, expected=2)
                self.manual_plan(slug)
                self.retire(result["event"], slug)
                self.confirm("M1", slug=slug)
                if mutation == "plan":
                    self.plan(slug).write_text(self.plan(slug).read_text() + "\n## 额外验收\n新增结果要求\n")
                else:
                    (self.root / "source.py").write_text("changed source\n")
                self.confirm("M1", slug=slug)
                self.assertIsNone(self.cli("status", slug)["acceptance"]["command_retirement"])
                self.cli("close", slug, expected=1)

    def test_retirement_does_not_cover_later_verification(self):
        self.make_plan(command="false")
        old = self.cli("verify", "probe", expected=2)
        self.manual_plan()
        self.retire(old["event"])
        self.confirm("M1")
        self.cli("verify", "probe", "--command", "false", expected=2)
        self.assertIsNone(self.cli("status", "probe")["acceptance"]["command_retirement"])
        self.retire(old["event"], expected=1)
        self.cli("close", "probe", expected=1)

    def test_retirement_closed_guard_and_reopen_do_not_reuse_authorization(self):
        self.make_plan(command="false")
        old = self.cli("verify", "probe", expected=2)
        self.manual_plan()
        self.retire(old["event"])
        self.confirm("M1")
        self.cli("close", "probe")
        self.assertFalse(self.cli("acceptance", "probe")["command_change"]["retirement_eligible"])
        self.retire(old["event"], expected=1)
        self.cli("reopen", "probe", "--reason", "原目标遗漏", "--by", "fixture 请修补", "--work", "修补遗漏")
        self.retire(old["event"], expected=1)
        self.plan().write_text(self.plan().read_text().replace("：pending", "：complete"))
        current = self.cli("status", "probe")["acceptance"]
        self.assertIsNone(current["command_retirement"])
        self.assertTrue(current["pending"])
        self.cli("close", "probe", expected=1)

    def test_retirement_requires_intact_old_receipt_at_append_and_close(self):
        self.make_plan(command="false")
        old = self.cli("verify", "probe", expected=2)
        receipt = self.root / self.events()[-1]["data"]["receipt"]
        original = receipt.read_bytes()
        self.manual_plan()
        receipt.write_text("damaged")
        self.retire(old["event"], expected=1)
        receipt.write_bytes(original)
        self.retire(old["event"])
        self.confirm("M1")
        receipt.unlink()
        self.cli("close", "probe", expected=1)

    def test_retirement_corrupt_previous_binding_is_rejected(self):
        self.make_plan(command="false")
        old = self.cli("verify", "probe", expected=2)
        self.manual_plan()
        self.retire(old["event"])
        events = self.events()
        events[-1]["data"]["previous"]["exit_code"] = 0
        path = self.root / ".workflow/probe/events.jsonl"
        path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events))
        self.cli("status", "probe", expected=1)
        self.cli("close", "probe", expected=1)

    def test_retired_close_cannot_claim_old_command_passed(self):
        self.make_plan(command="false")
        old = self.cli("verify", "probe", expected=2)
        self.manual_plan()
        self.retire(old["event"])
        self.confirm("M1")
        self.cli("close", "probe")
        events = self.events()
        events[-1]["data"]["snapshot"]["command_passed"] = True
        (self.root / ".workflow/probe/events.jsonl").write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events))
        self.cli("status", "probe", expected=1)

    def test_legacy_structured_close_without_command_status_remains_readable(self):
        self.cli("verify", "probe")
        self.cli("close", "probe")
        events = self.events()
        for key in ("command_status", "command_required", "command_change", "command_retirement", "retired_verification"):
            events[-1]["data"]["snapshot"].pop(key)
        (self.root / ".workflow/probe/events.jsonl").write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events))
        self.assertTrue(self.cli("status", "probe")["closed"])
        self.assertTrue(self.cli("close", "probe")["already_closed"])

    def test_replanned_i1_space_path_cannot_disappear_from_declaration(self):
        extra = ".workflow/probe/new evidence.txt"
        (self.root / extra).write_text("original extra output")
        self.make_plan(rows=["| A1 | inspect output | 自动化 | 必需 | `source.py` |"])
        old = self.cli("verify", "probe")
        self.cli("evidence", "probe", "--verify", old["event"], "--item", "A1",
                 "--ref", "source.py", "--source", "fixture original")
        self.plan().write_text(self.plan().read_text().replace("`source.py`", f"`source.py` `{extra}`"))
        self.assertFalse(self.cli("status", "probe")["acceptance"]["passed"])
        self.cli("close", "probe", expected=1)

    def test_replanned_i1_residual_text_cannot_disappear_from_declaration(self):
        extra = ".workflow/probe/extra.txt"
        (self.root / extra).write_text("original extra output")
        self.make_plan(rows=["| A1 | inspect output | 自动化 | 必需 | `source.py` |"])
        old = self.cli("verify", "probe")
        self.cli("evidence", "probe", "--verify", old["event"], "--item", "A1",
                 "--ref", "source.py", "--source", "fixture original")
        self.plan().write_text(self.plan().read_text().replace("`source.py`", f"`source.py` {extra}"))
        self.assertFalse(self.cli("status", "probe")["acceptance"]["passed"])
        self.cli("close", "probe", expected=1)

    def test_replanned_i1_extra_table_cell_is_not_truncated(self):
        self.make_plan(command="printf run >> .workflow/probe/counter",
                       rows=["| A1 | inspect output | 自动化 | 必需 | `source.py` | `.workflow/probe/extra.txt` |"])
        self.cli("verify", "probe", expected=1)
        self.assertFalse((self.root / ".workflow/probe/counter").exists())
        self.cli("close", "probe", expected=1)

    def coverage_table(self, text, slug="probe"):
        path = self.plan(slug)
        prefix, rest = path.read_text().split("## 验证覆盖\n", 1)
        _, suffix = rest.split("## 阶段\n", 1)
        path.write_text(prefix + "## 验证覆盖\n" + text + "\n## 阶段\n" + suffix)
        return workflow.load_plan(str(self.root), slug)

    def test_declaration_syntax_consumes_all_paths_matrix(self):
        cases = [
            ("source.py", "", ["source.py"]),
            ("中文文件", "", ["中文文件"]),
            ("inspect output", "", None),
            ("检查 页面", "  ", None),
            ("source.py", " ", ["source.py"]),
            ("说明 `source.py` 与 `结果 文件.txt` 都必须核对", "", ["source.py", "结果 文件.txt"]),
            ("ignored", "结果 文件.txt", ["结果 文件.txt"]),
            ("ignored", "`结果 文件.txt`", ["结果 文件.txt"]),
        ]
        for separator in (" ", "\t", ",", "，", "、", ";", "；", "+", " , + "):
            cases.append(("ignored", f"`source.py::test_example`{separator}`结果 文件.txt`",
                          ["source.py", "结果 文件.txt"]))
        for means, evidence, expected in cases:
            with self.subTest(means=means, evidence=evidence):
                parsed = workflow.reference_declaration({"means": means, "evidence": evidence})
                self.assertEqual(parsed["state"], "none" if expected is None else "declared")
                self.assertEqual([token["path"] for token in parsed["tokens"]], expected or [])
        for evidence in ("``", "` `", "`source.py", "source.py`", "`source.py::`",
                         "`::test_example`", "`source.py::::test_example`", "source.py::",
                         "`source.py``extra.txt`", "`source.py` extra.txt", "bad `source.py`",
                         "`source.py` | `extra.txt`", "source.py\nextra.txt"):
            with self.subTest(invalid=evidence):
                parsed = workflow.reference_declaration({"means": "ignored", "evidence": evidence})
                self.assertEqual(parsed["state"], "invalid")
                self.assertEqual(parsed["tokens"], [])

    def test_inserted_declaration_fragment_never_preserves_pass_cli_matrix(self):
        extra = ".workflow/probe/额外 输出.txt"
        (self.root / extra).write_text("not yet adopted")
        self.make_plan(command="printf run >> .workflow/probe/counter",
                       rows=["| A1 | inspect output | 自动化 | 必需 | `source.py` `source.py::test_example` |"])
        original = self.plan().read_text()
        declaration = "`source.py` `source.py::test_example`"
        verified = self.cli("verify", "probe")
        fragments = [f"`{extra}`", "`missing.txt`", "`source.py::missing_symbol`",
                     "``", "` `", "`source.py::`", "`unterminated", "residual.txt"]
        for fragment in fragments:
            variants = [f"{fragment} {declaration}",
                        f"`source.py` {fragment} `source.py::test_example`",
                        f"{declaration} {fragment}"]
            for position, changed in enumerate(variants):
                with self.subTest(fragment=fragment, position=position):
                    self.plan().write_text(original.replace(declaration, changed))
                    self.assertFalse(self.cli("status", "probe")["acceptance"]["passed"])
                    self.cli("close", "probe", expected=1)
        self.plan().write_text(original.replace(declaration, f"{declaration} `{extra}`"))
        self.cli("evidence", "probe", "--verify", verified["event"], "--item", "A1",
                 "--ref", extra, "--source", "fixture 两份输出均属于原验证")
        self.cli("close", "probe")
        self.assertEqual((self.root / ".workflow/probe/counter").read_text(), "run")

    def test_malformed_means_cannot_use_supplement_but_prose_can(self):
        for index, means in enumerate(("inspect output", "检查 页面", "说明 `source.py` 和 `missing.txt`",
                                       "说明 `source.py` 和 ``", "说明 `source.py` 后有 `未闭合")):
            slug = f"means-{index}"
            with self.subTest(means=means):
                self.make_plan(slug, rows=[f"| A1 | {means} | 自动化 | 必需 | |"])
                result = self.cli("verify", slug, expected=2)
                invalid = index >= 3
                self.cli("evidence", slug, "--verify", result["event"], "--item", "A1",
                         "--ref", "source.py", "--source", "fixture 原验证关联",
                         expected=1 if invalid else 0)
                self.cli("close", slug, expected=0 if index < 2 else 1)

    def test_valid_space_chinese_bare_and_manual_paths_cli(self):
        for filename in ("中文文件", "结果 文件.txt"):
            (self.root / filename).write_text("marker")
        self.make_plan(rows=[
            "| A1 | 中文文件 | 自动化 | 必需 | |",
            "| A2 | inspect result | 自动化 | 必需 | 结果 文件.txt |",
            "| A3 | 说明 `source.py::test_example` 和 `结果 文件.txt::marker` | 自动化 | 必需 | |",
            "| M1 | 执行 `tool --missing arg` 并观察结果 | 人工 | 必需 | `not-a-file` |"])
        result = self.cli("verify", "probe", expected=2)
        self.assertFalse(result["unknown"])
        self.assertFalse(result["gaps"])
        self.assertEqual([item["id"] for item in result["pending"]], ["M1"])
        self.confirm("M1")
        self.cli("close", "probe")

    def test_unknown_declaration_respects_required_optional_and_waiver(self):
        for index, evidence in enumerate(("`source.py` ``", "`source.py` `missing.txt`")):
            slug = f"optional-{index}"
            with self.subTest(evidence=evidence):
                self.make_plan(slug, rows=[f"| A1 | inspect output | 自动化 | 必需 | {evidence} |",
                                           f"| A2 | inspect output | 自动化 | 可选 | {evidence} |"])
                failed = self.cli("verify", slug, expected=2)
                self.assertFalse(failed["passed"])
                self.confirm("A1", slug=slug, command="waive", reason="用户明确取消 A1 要求")
                accepted = self.cli("status", slug)["acceptance"]
                self.assertTrue(accepted["passed"])
                self.assertIn(accepted["coverage"][1]["status"], ("unknown", "missing"))
                self.cli("close", slug)

    def test_coverage_table_valid_layout_matrix(self):
        cases = [
            ("| A1 | source.py | 自动化 |", "A1", True),
            ("| A1 | source.py | 自动化 | 可选 |", "A1", False),
            ("| 对象 | 验证手段 | 类型 |\n|---|---|---|\n| --合法对象 | source.py | 自动化 |", "--合法对象", True),
            ("| ID | 证据 | 类型 | 对象 | 必需 | 验证手段 |\n|:---|---:|:---:|---|---|---|\n"
             "| A1 | `source.py` | 自动化 | D-01 | optional | inspect output |", "A1", False),
        ]
        for table, identity, required in cases:
            with self.subTest(table=table):
                plan = self.coverage_table(table)
                self.assertFalse(plan.coverage_errors)
                self.assertEqual(len(plan.coverage), 1)
                self.assertEqual(plan.coverage[0]["id"], identity)
                self.assertEqual(plan.coverage[0]["required"], required)
                self.assertEqual(workflow.audit_coverage(str(self.root), plan)[0]["status"], "ok")
        for index, (table, _, _) in enumerate(cases):
            slug = f"layout-{index}"
            self.make_plan(slug)
            self.coverage_table(table, slug)
            self.cli("verify", slug)
            self.cli("close", slug)

    def test_coverage_structure_errors_reject_active_before_execution_matrix(self):
        cases = [
            "| 对象 | 验证手段 | 类型 |\n| A1 | source.py | 自动化 | extra |",
            "| 对象 | 验证手段 | 类型 |\n| A1 | source.py |",
            "| 对象 | 验证手段 | 类型 | 类型 |\n| A1 | source.py | 自动化 | 自动化 |",
            "| 对象 | 类型 |\n| A1 | 自动化 |",
            "| 对象 | 验证手段 | 类型 | 必需 | 必需性 |\n| A1 | source.py | 自动化 | 必需 | 可选 |",
            "| 对象 | 验证手段 | 类型 | 备注 |\n| A1 | source.py | 自动化 | ignore |",
            "| 对象 | 验证手段 | 类型 | 自动化 |\n| A1 | source.py | 自动化 | ignore |",
            "| Unknown | Columns | Here |\n|---|---|---|\n| A1 | source.py | 自动化 |",
            "| A1 | source.py | 自动化 | 可选 | extra |",
            "| A1 | source.py |",
            "| 对象 | 验证手段 | 类型 |\n|---|---|---|---|\n| A1 | source.py | 自动化 |",
            "| 对象 | 验证手段 | 类型 |\n|---|---|---|\n| A1 | source.py | 自动化",
            "| 对象 | 验证手段 | 类型 | 证据 |\n| A1 | inspect result | 自动化 | `source.py|extra` |",
        ]
        for index, table in enumerate(cases):
            with self.subTest(table=table):
                slug = f"bad-{index}"
                self.make_plan(slug, command=f"printf run > .workflow/{slug}/counter")
                plan = self.coverage_table(table, slug)
                self.assertTrue(plan.coverage_errors)
                self.assertTrue(all(error["text"] in table for error in plan.coverage_errors))
                checked = self.cli("check", slug, expected=2)
                self.assertTrue(any("覆盖表 L" in error["message"] for error in checked["errors"]))
                self.cli("verify", slug, expected=1)
                self.assertFalse((self.root / f".workflow/{slug}/counter").exists())
                self.cli("close", slug, expected=1)
                self.assertFalse(self.events(slug))

    def test_partial_separator_is_data_and_cannot_hide_required_row(self):
        plan = self.coverage_table("| 对象 | 验证手段 | 类型 |\n|---|---|---|\n| -- | source.py | 自动化 |")
        self.assertEqual([entry["id"] for entry in plan.coverage], ["--"])
        self.cli("verify", "probe")
        self.cli("close", "probe")
        self.make_plan("invalid-separator")
        self.coverage_table("| 对象 | 验证手段 | 类型 |\n|---|---|oops|\n| A1 | source.py | 自动化 |", "invalid-separator")
        self.cli("verify", "invalid-separator", expected=1)

    def test_structural_error_cannot_be_waived_and_legacy_closed_stays_readable(self):
        self.cli("verify", "probe")
        self.confirm("A1", command="waive", reason="fixture 取消 A1")
        bad_table = "| 对象 | 验证手段 | 类型 | 证据 |\n| A1 | inspect | 自动化 | `source.py` | lost |"
        self.coverage_table(bad_table)
        self.cli("acceptance", "probe", expected=1)
        self.cli("close", "probe", expected=1)
        self.make_plan("old")
        self.coverage_table(bad_table, "old")
        self.legacy_close("old")
        original = (self.root / ".workflow/old/ledger.md").read_bytes()
        state = self.cli("status", "old")
        self.assertTrue(state["closed"])
        self.assertTrue(state["coverage_errors"])
        self.assertTrue(self.cli("close", "old")["already_closed"])
        self.assertEqual((self.root / ".workflow/old/ledger.md").read_bytes(), original)
        self.assertFalse(self.events("old"))

    def test_scope_exclusions_end_at_sibling_or_new_coverage_section(self):
        for index, heading in enumerate(("## 验证覆盖：额外必验", "### 补充验证", "### 必验分组")):
            with self.subTest(heading=heading):
                slug = f"scope-{index}"
                self.make_plan(slug)
                plan = self.coverage_table(
                    "| 对象 | 验证手段 | 类型 | 必需性 | 证据 |\n|---|---|---|---|---|\n"
                    "| D-01 | `source.py` | 自动化 | 必需 | |\n"
                    "### 不验证的部分\n- 无\n" + heading + "\n"
                    "| 对象 | 验证手段 | 类型 |\n|---|---|---|\n| A2 | `missing.txt` | 自动化 |", slug)
                result = self.cli("verify", slug, expected=2)
                self.assertEqual([item["id"] for item in result["gaps"]], ["A2"])
                self.assertEqual([item["id"] for item in plan.coverage], ["D-01", "A2"])
                self.assertTrue(plan.exclusions_present)
                self.cli("close", slug, expected=1)

    def test_scope_nested_exclusion_stays_excluded_until_equal_depth(self):
        self.coverage_table(
            "| 对象 | 验证手段 | 类型 |\n|---|---|---|\n| A1 | `source.py` | 自动化 |\n"
            "### 不验证的部分\n#### 排除依据\n"
            "| 对象 | 验证手段 | 类型 |\n|---|---|---|\n| excluded | `missing.txt` | 自动化 |")
        result = self.cli("verify", "probe")
        self.assertEqual([item["id"] for item in result["coverage"]], ["A1"])
        self.cli("close", "probe")

    def test_scope_exclusion_condition_table_is_fully_bound(self):
        original = self.plan().read_text().replace("## 阶段", "### 不验证的部分\n"
            "| 排除项 | 范围 | 依据 | 负责人 | 排除成立条件 |\n|---|---|---|---|---|\n"
            "| 外部集成 | 发布环境 | 已批准 | 控制器 | 仅无需发布时排除 |\n## 阶段")
        self.plan().write_text(original)
        verified = self.cli("verify", "probe")
        self.plan().write_text(original.replace("仅无需发布时排除", "所有发布情况均排除"))
        result = self.cli("status", "probe")["acceptance"]
        self.assertNotEqual(result["acceptance"], verified["acceptance"])
        self.assertFalse(result["passed"])
        self.cli("close", "probe", expected=1)

    def test_scope_indented_evidence_correction_preserves_binding_without_rerun(self):
        for index, indent in enumerate((" ", "  ", "\t")):
            with self.subTest(indent=repr(indent)):
                slug = f"indent-{index}"
                self.make_plan(slug, command=f"printf run >> .workflow/{slug}/counter",
                               rows=["| A1 | inspect output | 自动化 | 必需 | `missing.txt` |"])
                table = "\n".join(indent + line for line in (
                    "| 对象 | 验证手段 | 类型 | 必需性 | 证据 |", "|---|---|---|---|---|",
                    "| A1 | inspect output | 自动化 | 必需 | `missing.txt` |"))
                self.coverage_table(table, slug)
                result = self.cli("verify", slug, expected=2)
                original = self.plan(slug).read_text()
                self.plan(slug).write_text(original.replace("`missing.txt`", "`source.py`"))
                self.assertEqual(self.cli("status", slug)["acceptance"]["acceptance"], result["acceptance"])
                self.cli("evidence", slug, "--verify", result["event"], "--item", "A1",
                         "--ref", "source.py", "--source", "fixture 纯引用拼写修正")
                self.cli("close", slug)
                self.assertEqual((self.root / f".workflow/{slug}/counter").read_text(), "run")

    def test_scope_resumed_table_structure_and_requirement_changes_are_checked(self):
        self.coverage_table("| 对象 | 验证手段 | 类型 |\n| A1 | source.py | 自动化 |\n"
            "### 不验证的部分\n#### 排除依据\n| 说明 | 未验证条件 |\n"
            "### 必验分组\n| 对象 | 验证手段 | 类型 |\n| A2 | source.py | 自动化 | extra |")
        self.cli("verify", "probe", expected=1)
        self.cli("close", "probe", expected=1)
        self.make_plan("bound")
        self.coverage_table(" | 对象 | 验证手段 | 类型 | 证据 |\n |---|---|---|---|\n"
                            " | A1 | inspect output | 自动化 | source.py |", "bound")
        self.cli("verify", "bound")
        self.plan("bound").write_text(self.plan("bound").read_text().replace("inspect output", "inspect new requirement"))
        self.assertFalse(self.cli("status", "bound")["acceptance"]["passed"])
        self.cli("close", "bound", expected=1)

    def test_status_binding_non_task_requirements_cannot_be_skipped(self):
        for index, section in enumerate(("全局约束", "额外验收")):
            with self.subTest(section=section):
                slug = f"requirement-{index}"
                self.make_plan(slug)
                self.plan(slug).write_text(self.plan(slug).read_text().replace("## 方案",
                    f"## {section}\n- **状态**：离线模式下也必须返回成功\n\n## 方案"))
                verified = self.cli("verify", slug)
                self.plan(slug).write_text(self.plan(slug).read_text().replace(
                    "离线模式下也必须返回成功", "离线模式下必须拒绝执行"))
                state = self.cli("status", slug)["acceptance"]
                self.assertNotEqual(state["acceptance"], verified["acceptance"])
                self.assertFalse(state["passed"])
                self.cli("close", slug, expected=1)

    def test_status_binding_parsed_task_bookkeeping_keeps_acceptance(self):
        for index, spaces in enumerate((" ", "  ")):
            with self.subTest(spaces=repr(spaces)):
                slug = f"task-status-{index}"
                self.make_plan(slug)
                original = self.plan(slug).read_text().replace("- **状态**：complete", f"-{spaces}**状态**：complete")
                self.plan(slug).write_text(original)
                verified = self.cli("verify", slug)
                for status in ("pending", "in_progress"):
                    self.plan(slug).write_text(original.replace("**状态**：complete", f"**状态**：{status}"))
                    self.assertEqual(workflow.load_plan(str(self.root), slug).tasks[0].status, status)
                    self.assertEqual(self.cli("acceptance", slug)["acceptance"], verified["acceptance"])
                    self.cli("close", slug, expected=1)
                self.plan(slug).write_text(original)
                self.cli("close", slug)
                self.assertEqual(len([event for event in self.events(slug) if event["type"] == "verify"]), 1)

    def test_status_binding_fenced_text_stays_bound_even_inside_task(self):
        for location in ("global", "task"):
            with self.subTest(location=location):
                slug = f"fenced-status-{location}"
                self.make_plan(slug)
                text = self.plan(slug).read_text()
                fenced = "```text\n- **状态**：离线模式下也必须返回成功\n```\n"
                text = text.replace("## 方案", "## 全局约束\n" + fenced + "\n## 方案") if location == "global" else text + fenced
                self.plan(slug).write_text(text)
                verified = self.cli("verify", slug)
                self.plan(slug).write_text(text.replace("离线模式下也必须返回成功", "离线模式下必须拒绝执行"))
                self.assertEqual(workflow.load_plan(str(self.root), slug).tasks[0].status, "complete")
                state = self.cli("status", slug)["acceptance"]
                self.assertNotEqual(state["acceptance"], verified["acceptance"])
                self.assertFalse(state["passed"])
                self.cli("close", slug, expected=1)

    def approval_plan(self, slug="probe", spaces=" ", extra="", mode=None):
        if mode:
            options = ["--execution", "--execution-reason", "fixture 范围和验收已明确"] if mode == "execution" else ["--bug"]
            self.cli("init", slug, "--goal", "fixture", *options)
        self.make_plan(slug, status="pending")
        text = self.plan(slug).read_text().replace("| A1 |", "| D-01 |")
        text = text.replace("## 阶段", "### 不验证的部分\n- 无\n## 阶段\n### Phase 1: fixture")
        text = text.replace("- **验收**", "- **决策**：D-01\n- **验收**")
        text += "#### T2 followup\n- **依赖**：T1\n- **决策**：D-01\n- **验收**：后续结果正确\n- **失败信号**：后续结果错误\n- **状态**：pending\n"
        text = text.replace("- **状态**：pending", f"-{spaces}**状态**：pending")
        text = text.replace("## 方案", extra + "## 方案")
        if mode == "execution":
            text = "**审批模式**: execution\n**审批模式依据**: fixture 范围和验收已明确\n" + text
        elif mode == "bug":
            text = "**类型**: bug\n" + text
            text += "## 复现\n运行 fixture 会失败\n## 根因\nfixture 的边界处理遗漏\n"
            text = text.replace("| D-01 | `source.py::test_example`", "| D-01 回归测试 | `source.py::test_example`")
        self.plan(slug).write_text(text)

    def legacy_approval_hash(self, path):
        with path.open(encoding="utf-8") as fh:
            text = fh.read()
        replaced = re.sub(r"^- \*\*状态\*\*[:：].*$", "- **状态**：<忽略>", text, flags=re.M)
        return hashlib.sha256(replaced.encode()).hexdigest()[:16]

    def add_legacy_plan_approval(self, slug="probe"):
        digest = self.legacy_approval_hash(self.plan(slug))
        row = f"| 2026-01-01 12:00 | 计划 | {digest} | fixture 原始旧审批 |"
        workflow.ledger_append(str(self.root), slug, "审批", row)
        return row

    def test_approval_hash_non_task_requirements_block_slice_and_record(self):
        for index, extra in enumerate((
            "## 全局约束\n- **状态**：原要求\n",
            "## 额外验收\n- **状态**：原要求\n",
            "## 全局约束\n```text\n- **状态**：原要求\n```\n")):
            with self.subTest(extra=extra):
                slug = f"approval-requirement-{index}"
                self.approval_plan(slug, extra=extra)
                self.cli("approve", slug, "方案", "--by", "fixture 原方案确认")
                self.cli("approve", slug, "计划", "--by", "fixture 原计划确认")
                self.cli("slice", slug, "T1")
                self.plan(slug).write_text(self.plan(slug).read_text().replace("原要求", "新要求"))
                self.assertIn("计划", self.cli("slice", slug, "T1", expected=1)["error"])
                self.assertIn("计划", self.cli("record", slug, "T1", "--commits", "HEAD..HEAD", "--note", "fixture", expected=1)["error"])
                self.cli("verify", slug)
                self.cli("record", slug, "T1", "--commits", "HEAD..HEAD", "--note", "新验证不代审批", expected=1)
                self.cli("slice", slug, "T1", expected=1)

    def test_approval_hash_real_task_record_preserves_next_task_access(self):
        for index, (spaces, colon) in enumerate(((" ", "："), (" ", ":"), ("  ", "："), ("\t", ":"))):
            with self.subTest(spaces=repr(spaces), colon=colon):
                slug = f"approval-record-{index}"
                self.approval_plan(slug, spaces=spaces)
                self.plan(slug).write_text(self.plan(slug).read_text().replace("**状态**：", f"**状态**{colon}"))
                self.cli("approve", slug, "方案", "--by", "fixture 原方案确认")
                approval = self.cli("approve", slug, "计划", "--by", "fixture 原计划确认")
                self.cli("slice", slug, "T1")
                self.cli("record", slug, "T1", "--commits", "HEAD..HEAD", "--note", "fixture 无代码变更")
                self.assertEqual(workflow.plan_content_hash(self.plan(slug)), approval["fingerprint"])
                self.cli("slice", slug, "T2")
                self.cli("record", slug, "T2", "--commits", "HEAD..HEAD", "--note", "fixture 后续完成")

    def test_approval_hash_standard_legacy_digest_and_line_endings(self):
        text = "## 阶段\n#### T1 fixture\n- **状态**：pending\n- **验收**：保留尾部要求\n"
        path = self.root / ".workflow/probe/hash-fixture.md"
        observed = {}
        for colon in ("：", ":"):
            for ending in ("\n", "\r\n", "\r"):
                for final_newline in (True, False):
                    with self.subTest(colon=colon, ending=repr(ending), final_newline=final_newline):
                        sample = (text if final_newline else text.rstrip("\n")).replace("**状态**：", f"**状态**{colon}")
                        path.write_bytes(sample.replace("\n", ending).encode())
                        digest = workflow.plan_content_hash(path)
                        self.assertEqual(digest, self.legacy_approval_hash(path))
                        self.assertEqual(len(digest), 16)
                        observed[colon, ending, final_newline] = digest
                        path.write_bytes(sample.replace("保留尾部要求", "修改尾部要求").replace("\n", ending).encode())
                        self.assertNotEqual(workflow.plan_content_hash(path), digest)
        self.assertEqual(len({digest for (_, _, final), digest in observed.items() if final}), 1)
        self.assertEqual(len({digest for (_, _, final), digest in observed.items() if not final}), 1)
        self.assertNotEqual(observed["：", "\n", True], observed["：", "\n", False])
        path.write_text("## 阶段\n#### T1 fixture\n- **状态**：pending")
        self.assertEqual(workflow.plan_content_hash(path), self.legacy_approval_hash(path))

    def test_approval_hash_standard_old_approval_remains_usable(self):
        self.approval_plan()
        self.cli("approve", "probe", "方案", "--by", "fixture 原方案确认")
        old_row = self.add_legacy_plan_approval()
        self.assertEqual(workflow.plan_content_hash(self.plan()), self.legacy_approval_hash(self.plan()))
        self.cli("slice", "probe", "T1")
        self.cli("record", "probe", "T1", "--commits", "HEAD..HEAD", "--note", "fixture")
        self.cli("slice", "probe", "T2")
        ledger = (self.root / ".workflow/probe/ledger.md").read_text()
        self.assertIn(old_row, ledger)
        self.assertEqual(ledger.count("fixture 原始旧审批"), 1)

    def test_approval_hash_legacy_placeholder_ambiguity_never_reuses_old_authorization(self):
        for index, extra in enumerate(("## 全局约束\n- **状态**：原要求\n",
                                       "## 额外验收\n- **状态**：原要求\n",
                                       "## 全局约束\n```text\n- **状态**：原要求\n```\n")):
            with self.subTest(extra=extra):
                slug = f"legacy-placeholder-{index}"
                self.approval_plan(slug, extra=extra)
                self.cli("approve", slug, "方案", "--by", "fixture 原方案确认")
                old_row = self.add_legacy_plan_approval(slug)
                old_hash = self.legacy_approval_hash(self.plan(slug))
                self.plan(slug).write_text(self.plan(slug).read_text().replace("原要求", "<忽略>"))
                self.assertEqual(self.legacy_approval_hash(self.plan(slug)), old_hash)
                self.assertNotEqual(workflow.plan_content_hash(self.plan(slug)), old_hash)
                self.cli("slice", slug, "T1", expected=1)
                self.cli("verify", slug)
                self.cli("record", slug, "T1", "--commits", "HEAD..HEAD", "--note", "fixture", expected=1)
                self.cli("approve", slug, "计划", "--by", "fixture 核对当前完整要求后明确确认")
                self.cli("slice", slug, "T1")
                self.cli("record", slug, "T1", "--commits", "HEAD..HEAD", "--note", "fixture 新审批后继续")
                self.cli("slice", slug, "T2")
                self.assertIn(old_row, (self.root / f".workflow/{slug}/ledger.md").read_text())

    def test_approval_hash_does_not_rewrite_historical_closed_or_approval(self):
        self.make_plan()
        self.plan().write_text(self.plan().read_text().replace("## 方案", "## 全局约束\n- **状态**：原要求\n## 方案"))
        old_row = self.add_legacy_plan_approval()
        self.legacy_close()
        ledger = self.root / ".workflow/probe/ledger.md"
        original = ledger.read_bytes()
        self.plan().write_text(self.plan().read_text().replace("原要求", "<忽略>"))
        self.assertTrue(self.cli("status", "probe")["closed"])
        self.assertTrue(self.cli("close", "probe")["already_closed"])
        self.cli("slice", "probe", "T1", expected=1)
        self.cli("record", "probe", "T1", expected=1)
        self.assertEqual(ledger.read_bytes(), original)
        self.assertIn(old_row, ledger.read_text())

    def test_approval_hash_keeps_execution_bug_and_scheme_gates(self):
        for mode in ("execution", "bug"):
            with self.subTest(mode=mode):
                self.approval_plan(mode, extra="## 全局约束\n- **状态**：原要求\n", mode=mode)
                self.plan(mode).write_text(self.plan(mode).read_text().replace("原要求", "新要求"))
                self.cli("slice", mode, "T1")
                self.cli("record", mode, "T1", "--commits", "HEAD..HEAD", "--note", "fixture 免门模式")
                self.cli("slice", mode, "T2")
                self.assertNotIn("计划", workflow._read_approvals(str(self.root), mode))
        self.approval_plan()
        self.cli("approve", "probe", "方案", "--by", "fixture 原方案确认")
        self.cli("approve", "probe", "计划", "--by", "fixture 原计划确认")
        self.plan().write_text(self.plan().read_text().replace("fixture scheme", "changed scheme"))
        self.assertIn("方案", self.cli("slice", "probe", "T1", expected=1)["error"])

    def node_block(self, nid, tasks, name="fixture", deps="无", final="否", pred=None,
                   omit=None):
        """一个审查节点块（格式 4）；omit 用来制造「缺必填字段」反例。"""
        fields = {
            "归属任务": tasks,
            "分组理由": "fixture 分组理由：功能完整性与下游依赖",
            "审查职责": "逐任务一行结论 + 节点整体结论",
            "依赖节点": deps,
            "送审条件": "归属任务全部已实现，必要验证完成，未解决事项列明",
            "兼任终审": final,
        }
        if pred is not None:
            fields["前身"] = pred
        lines = [f"### {nid} {name}", ""]
        for key, value in fields.items():
            if key == omit:
                continue
            lines.append(f"- **{key}**：{value}")
        return "\n".join(lines) + "\n"

    def v4_tasks(self, pairs=(("T1", "无"), ("T2", "T1"))):
        return "\n".join(
            f"#### {tid} fixture\n"
            "- **文件**：source.py\n"
            f"- **依赖**：{deps}\n"
            "- **并行**：否\n"
            "- **做法**：fixture 做法：只改夹具文本\n"
            "- **接口**：consumes 无 / produces 无\n"
            "- **预期**：fixture 预期结果\n"
            "- **验收**：结果正确\n"
            "- **失败信号**：结果错误\n"
            "- **决策**：D-01\n"
            "- **状态**：pending\n"
            for tid, deps in pairs)

    def make_v4_plan(self, slug="v4", nodes=None, tasks=None, version=4, events=None,
                     section=True):
        """格式 4 fixture；nodes=None 时用合法的「单节点兼任终审」段。"""
        if not (self.root / ".workflow" / slug).exists():
            self.cli("init", slug, "--goal", "fixture v4")
        if tasks is None:
            tasks = self.v4_tasks()
        if nodes is None:
            nodes = self.node_block("N1", "T1, T2", final="是")
        head = (
            "**Goal**: fixture\n"
            f"**格式**: {version}\n"
            "**设计文档**: 无 — 独立临时回归测试不需要单独设计文档\n"
            "## 方案\n### 背景与目标\nfixture 为什么做、做完是什么样\n"
            "## 验证命令\n```sh\ntrue\n```\n"
            "## 决策\n| ID | 决策 | 来源 | 理由 |\n|---|---|---|---|\n"
            "| D-01 | fixture decision | 用户 | fixture rationale |\n"
            "## 验证覆盖\n| 对象 | 验证手段 | 类型 | 必需性 | 证据 |\n|---|---|---|---|---|\n"
            "| D-01 | `source.py::test_example` | 自动化 | 必需 | |\n"
            "### 不验证的部分\n- 无\n")
        middle = ("## 审查节点\n\n" + nodes + "\n") if section else ""
        self.plan(slug).write_text(head + middle + "## 阶段\n### Phase 1: fixture\n\n" + tasks)
        if events is not None:
            (self.root / ".workflow" / slug / "events.jsonl").write_text(
                "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events))

    def node_event(self, node, lineage, event_id="evt-1"):
        return {"schema": 1, "id": event_id, "type": "node_review",
                "time": "2026-10-15T10:00:00+08:00", "workflow": "fixture", "cycle": 1,
                "data": {"节点": node, "谱系": lineage}}

    def check_messages(self, slug="v4", expected=2):
        return [error["message"] for error in self.cli("check", slug, expected=expected)["errors"]]

    def test_review_nodes_legal_v4_parses_fields_and_zero_errors(self):
        nodes = (self.node_block("N1", "T1")
                 + self.node_block("N2", "T2", deps="N1", final="是"))
        self.make_v4_plan(slug="legal", nodes=nodes,
                          tasks=self.v4_tasks((("T1", "无"), ("T2", "T1"))))
        result = self.cli("check", "legal")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["errors"], [])
        plan = workflow.load_plan(str(self.root), "legal")
        self.assertTrue(plan.is_v4)
        self.assertTrue(plan.has_node_section)
        self.assertEqual([node.id for node in plan.nodes], ["N1", "N2"])
        first, second = plan.nodes
        self.assertEqual(first.tasks, ["T1"])
        self.assertEqual(first.deps, [])
        self.assertFalse(first.is_final)
        self.assertEqual(first.predecessors, [])
        self.assertEqual(first.get("分组理由"), "fixture 分组理由：功能完整性与下游依赖")
        self.assertEqual(first.get("审查职责"), "逐任务一行结论 + 节点整体结论")
        self.assertEqual(first.get("送审条件"), "归属任务全部已实现，必要验证完成，未解决事项列明")
        self.assertEqual(second.tasks, ["T2"])
        self.assertEqual(second.deps, ["N1"])
        self.assertTrue(second.is_final)
        # 等待图：等待者 → 被等待者；终审边＝终审 → 每个其它节点（D-10/D-21）。
        self.assertEqual(workflow.wait_graph(plan), {"N1": set(), "N2": {"N1"}})

    def test_review_nodes_wait_graph_merges_task_and_declared_and_final_edges(self):
        nodes = (self.node_block("N1", "T1")
                 + self.node_block("N2", "T2", deps="N1")
                 + self.node_block("N3", "T3", deps="N2", final="是"))
        self.make_v4_plan(slug="graph", nodes=nodes,
                          tasks=self.v4_tasks((("T1", "无"), ("T2", "T1"), ("T3", "T2"))))
        self.assertEqual(self.cli("check", "graph")["errors"], [])
        plan = workflow.load_plan(str(self.root), "graph")
        self.assertEqual(workflow.wait_graph(plan),
                         {"N1": set(), "N2": {"N1"}, "N3": {"N1", "N2"}})

    def test_review_nodes_wait_cycle_from_declaration_only(self):
        nodes = (self.node_block("N1", "T1", deps="N2")
                 + self.node_block("N2", "T2", deps="N1")
                 + self.node_block("N3", "T3", final="是"))
        self.make_v4_plan(slug="decl-cycle", nodes=nodes,
                          tasks=self.v4_tasks((("T1", "无"), ("T2", "无"), ("T3", "无"))))
        self.assertEqual(
            self.check_messages("decl-cycle"),
            ["节点等待图存在环（等待者 → 被等待者）：N1 → N2 → N1——"
             "两条来源（任务依赖导出的跨节点边 ∪ 显式声明的节点依赖边）合并后判环。"],
        )

    def test_review_nodes_wait_cycle_from_mixed_sources(self):
        """任务依赖 A→B ＋ 声明 B→A：各自无环、合并成环（第七轮审阅用例）。"""
        mixed = (self.node_block("N1", "T1")
                 + self.node_block("N2", "T2", deps="N1")
                 + self.node_block("N3", "T3", final="是"))
        tasks = self.v4_tasks((("T1", "T2"), ("T2", "无"), ("T3", "无")))
        self.make_v4_plan(slug="mixed", nodes=mixed, tasks=tasks)
        plan = workflow.load_plan(str(self.root), "mixed")
        self.assertEqual(workflow.wait_cycles(workflow.wait_graph(plan)), [["N1", "N2", "N1"]])
        self.assertEqual(
            self.check_messages("mixed"),
            ["节点等待图存在环（等待者 → 被等待者）：N1 → N2 → N1——"
             "两条来源（任务依赖导出的跨节点边 ∪ 显式声明的节点依赖边）合并后判环。"],
        )
        # 单来源各自无环：去掉声明边 → 无环；去掉任务依赖 → 无环。
        self.make_v4_plan(slug="mixed-task-only",
                          nodes=(self.node_block("N1", "T1")
                                 + self.node_block("N2", "T2")
                                 + self.node_block("N3", "T3", final="是")),
                          tasks=tasks)
        self.assertEqual(self.cli("check", "mixed-task-only")["errors"], [])
        self.make_v4_plan(slug="mixed-declared-only",
                          nodes=(self.node_block("N1", "T1")
                                 + self.node_block("N2", "T2", deps="N1")
                                 + self.node_block("N3", "T3", final="是")),
                          tasks=self.v4_tasks((("T1", "无"), ("T2", "无"), ("T3", "无"))))
        self.assertEqual(self.cli("check", "mixed-declared-only")["errors"], [])

    def test_review_nodes_final_scheduling_constraints(self):
        self.make_v4_plan(slug="two-finals",
                          nodes=(self.node_block("N1", "T1", final="是")
                                 + self.node_block("N2", "T2", final="是")))
        self.assertEqual(
            self.check_messages("two-finals"),
            ["格式 4 计划必须恰有一个『兼任终审：是』的审查节点，当前是 2 个（N1、N2）。"],
        )
        self.make_v4_plan(slug="final-waited",
                          nodes=(self.node_block("N1", "T1", deps="N2")
                                 + self.node_block("N2", "T2", final="是")))
        messages = self.check_messages("final-waited")
        self.assertEqual(len(messages), 2)
        self.assertIn("节点等待图存在环（等待者 → 被等待者）：N1 → N2 → N1", messages[0])
        self.assertEqual(
            messages[1],
            "终审节点 N2 不得为其它节点的上游，但 N1 在等它——终审等待全部验收，不能反过来被别人等待。",
        )

    def test_review_nodes_missing_and_invalid_fields_carry_node_id(self):
        self.make_v4_plan(slug="missing", nodes=self.node_block(
            "N1", "T1, T2", final="是", omit="分组理由"))
        self.assertEqual(
            self.check_messages("missing"),
            ["审查节点 N1 缺少『分组理由』字段（六项必填，缺一不可）。"],
        )
        self.make_v4_plan(slug="bad-verdict", nodes=self.node_block("N1", "T1, T2", final="yes"))
        messages = self.check_messages("bad-verdict")
        self.assertIn("审查节点 N1 的『兼任终审』只能是『是』或『否』，当前是『yes』。", messages)
        self.make_v4_plan(slug="empty-owner", nodes=self.node_block("N1", "", final="是"))
        messages = self.check_messages("empty-owner")
        self.assertIn("审查节点 N1 缺少『归属任务』字段（六项必填，缺一不可）。", messages)
        self.assertNotIn("审查节点 N1 的『归属任务』没有列出真实任务 ID。", messages)
        self.make_v4_plan(slug="prose-owner", nodes=self.node_block(
            "N1", "见分组理由", final="是"))
        self.assertIn("审查节点 N1 的『归属任务』没有列出真实任务 ID。",
                      self.check_messages("prose-owner"))

    def test_review_nodes_reference_errors(self):
        nodes = (self.node_block("N1", "T1", deps="N9")
                 + self.node_block("N2", "T2", final="是"))
        self.make_v4_plan(slug="dep-missing", nodes=nodes)
        self.assertEqual(self.check_messages("dep-missing"),
                         ["审查节点 N1 依赖的节点 N9 不存在。"])
        nodes = (self.node_block("N1", "T1", pred="N9")
                 + self.node_block("N2", "T2", final="是"))
        self.make_v4_plan(slug="pred-missing", nodes=nodes)
        self.assertEqual(
            self.check_messages("pred-missing"),
            ["审查节点 N1 的前身 N9 解析不到——"
             "前身须存在于当前计划文本或本工作流的历史记录（审查记录与事件）中。"],
        )
        self.make_v4_plan(slug="task-unknown", nodes=self.node_block("N1", "T1, T9", final="是"))
        messages = self.check_messages("task-unknown")
        self.assertEqual(messages, [
            "审查节点 N1 的归属任务 T9 不存在。",
            "任务 T2 不属于任何审查节点——格式 4 下每个任务恰属一个节点。",
        ])
        self.make_v4_plan(slug="task-shared",
                          nodes=(self.node_block("N1", "T1", final="是")
                                 + self.node_block("N2", "T1, T2")))
        self.assertIn("任务 T1 同时归属审查节点 N1、N2——每个任务恰属一个节点。",
                      self.check_messages("task-shared"))
        self.make_v4_plan(slug="no-section", section=False)
        self.assertEqual(
            self.check_messages("no-section"),
            ["格式 4 计划缺少 `## 审查节点` 段——节点是格式 4 的验收单位，"
             "每个任务必须恰属一个节点。"],
        )
        self.make_v4_plan(slug="no-blocks", nodes="")
        self.assertEqual(
            self.check_messages("no-blocks"),
            ["『审查节点』段里没有任何节点块（形如 `### N1 <名称>`）。"],
        )
        self.make_v4_plan(slug="bad-heading", nodes="### 说明\n\n一些说明文字\n"
                          + self.node_block("N1", "T1, T2", final="是"))
        self.assertTrue(any("三级标题必须是节点块" in message and "### 说明" in message
                            for message in self.check_messages("bad-heading")))

    def test_review_nodes_merge_rejected_and_legal_splits_accepted(self):
        self.make_v4_plan(slug="multi-pred", nodes=self.node_block(
            "N1", "T1, T2", pred="N7, N8", final="是"))
        self.assertEqual(
            self.check_messages("multi-pred"),
            ["审查节点 N1 声明了多个前身（N7、N8）——"
             "首版不支持已送审节点合并，每个新节点最多承接一个前身。"],
        )
        self.make_v4_plan(slug="pred-in-use",
                          nodes=(self.node_block("N1", "T1", pred="N2")
                                 + self.node_block("N2", "T2", final="是")))
        self.assertEqual(
            self.check_messages("pred-in-use"),
            ["审查节点 N1 的前身 N2 仍是本计划中在用的节点——"
             "调整应替换或移除原节点，而不是并列引用。"],
        )
        history = [self.node_event("N0", "L1")]
        self.make_v4_plan(slug="split-history",
                          nodes=(self.node_block("N1", "T1", pred="N0")
                                 + self.node_block("N2", "T2", final="是")),
                          events=history)
        self.assertEqual(self.cli("check", "split-history")["errors"], [])
        self.make_v4_plan(slug="split-lineage",
                          nodes=(self.node_block("N1", "T1", pred="L1")
                                 + self.node_block("N2", "T2", final="是")),
                          events=history)
        self.assertEqual(self.cli("check", "split-lineage")["errors"], [])
        # 同一前身由多个子节点分别承接（拆分场景，④）：各自继承同一谱系根。
        self.make_v4_plan(slug="split-shared",
                          nodes=(self.node_block("N1", "T1", pred="N0")
                                 + self.node_block("N2", "T2", pred="N0")
                                 + self.node_block("N3", "T3", final="是")),
                          tasks=self.v4_tasks((("T1", "无"), ("T2", "无"), ("T3", "无"))),
                          events=history)
        self.assertEqual(self.cli("check", "split-shared")["errors"], [])
        ambiguous = [self.node_event("N0", "L1", "evt-1"), self.node_event("N0", "L2", "evt-2")]
        self.make_v4_plan(slug="pred-ambiguous",
                          nodes=(self.node_block("N1", "T1", pred="N0")
                                 + self.node_block("N2", "T2", final="是")),
                          events=ambiguous)
        self.assertEqual(
            self.check_messages("pred-ambiguous"),
            ["审查节点 N1 的前身 N0 在历史记录里映射到多个谱系根（L1、L2）——"
             "解析歧义，须人工裁定后重写。"],
        )

    def test_review_nodes_format3_ignores_section_and_init_stays_v3(self):
        self.cli("init", "fresh", "--goal", "fixture")
        self.assertIn("**格式**: 3", self.plan("fresh").read_text())
        self.assertEqual(workflow.PLAN_FORMAT_CURRENT, 3)
        self.make_v4_plan(slug="old", version=3)
        before = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "check", "old"],
            cwd=self.root, capture_output=True, text=True)
        self.assertEqual(before.returncode, 0, before.stdout + before.stderr)
        plan = workflow.load_plan(str(self.root), "old")
        self.assertEqual(plan.nodes, [])
        self.assertFalse(plan.has_node_section)
        illegal = ("### N1 只有一个字段\n\n- **归属任务**：T1\n- **依赖节点**：N9\n"
                   "- **兼任终审**：是\n- **前身**：N8, N7\n\n"
                   "### 说明\n\n### N2 另一个终审\n\n- **归属任务**：T9\n- **兼任终审**：是\n")
        self.make_v4_plan(slug="old", version=3, nodes=illegal)
        after = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "check", "old"],
            cwd=self.root, capture_output=True, text=True)
        self.assertEqual(after.returncode, 0, after.stdout + after.stderr)
        self.assertEqual(before.stdout, after.stdout)
        self.assertEqual(before.stderr, after.stderr)
        self.assertEqual(workflow.load_plan(str(self.root), "old").nodes, [])


if __name__ == "__main__":
    unittest.main()
