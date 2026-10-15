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
        if not path.exists():
            return []
        # 与引擎同源的行切分：只按 \n 切（splitlines 还会在 U+2028/U+2029 断开）。
        return [json.loads(line) for line in path.read_text().split("\n") if line]

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
                     section=True, section_name="审查节点"):
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
        middle = (f"## {section_name}\n\n" + nodes + "\n") if section else ""
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
        self.make_v4_plan(slug="none-owner", nodes=self.node_block(
            "N1", "无（原 T3 拆分）", final="是"))
        messages = self.check_messages("none-owner")
        self.assertIn("审查节点 N1 的『归属任务』没有列出真实任务 ID。", messages)
        self.assertNotIn("审查节点 N1 的『归属任务』字段值非法（剥离尾部括号注解后没有可解析内容）"
                         "——只接受『无』或逗号分隔的 ID 列表。", messages)

    def test_review_nodes_duplicate_ids_rejected(self):
        duplicate = self.node_block("N1", "T1", final="是") + "\n" + self.node_block("N1", "T1")
        self.make_v4_plan(slug="dup-id", nodes=duplicate)
        messages = self.check_messages("dup-id")
        self.assertIn(
            "审查节点 ID 重复：N1——两个以上的节点块共用一个 ID，"
            "归属、终审与等待图都会塌缩到同一节点上（节点 ID 是稳定身份）。",
            messages)
        self.assertFalse(any("同时归属" in message for message in messages))
        self.assertFalse(any("N1、N1" in message for message in messages))
        self.assertEqual(len([m for m in messages if "节点 ID 重复" in m]), 1)

    def test_review_nodes_field_values_strip_annotation_and_stay_strict(self):
        # `无（注解）` 不产生等待边：注解里的 N3 恰是终审节点，旧实现会误加边并报假环。
        nodes = (self.node_block("N1", "T1", deps="无（原 N3 已并入）")
                 + self.node_block("N2", "T2", deps="无（上游已完成）")
                 + self.node_block("N3", "T3", final="是"))
        self.make_v4_plan(slug="annotated-none", nodes=nodes,
                          tasks=self.v4_tasks((("T1", "无"), ("T2", "无"), ("T3", "无"))))
        self.assertEqual(self.cli("check", "annotated-none")["errors"], [])
        plan = workflow.load_plan(str(self.root), "annotated-none")
        self.assertEqual(workflow.wait_graph(plan), {"N1": set(), "N2": set(), "N3": {"N1", "N2"}})
        # `N0（注解）` 是单前身（注解里的谱系 ID 不算第二前身），经历史记录解析通过。
        self.make_v4_plan(slug="annotated-pred",
                          nodes=(self.node_block("N1", "T1", pred="N0（原谱系 L1）")
                                 + self.node_block("N2", "T2", final="是")),
                          events=[self.node_event("N0", "L1")])
        self.assertEqual(self.cli("check", "annotated-pred")["errors"], [])
        self.assertEqual(workflow.load_plan(str(self.root), "annotated-pred").nodes[0].predecessors,
                         ["N0"])
        # 剥注解后仍是多前身 → 合并拒绝。
        self.make_v4_plan(slug="annotated-merge",
                          nodes=self.node_block("N1", "T1, T2", pred="N7, N8（原两节点合并）", final="是"))
        self.assertEqual(
            self.check_messages("annotated-merge"),
            ["审查节点 N1 声明了多个前身（N7、N8）——"
             "首版不支持已送审节点合并，每个新节点最多承接一个前身。"],
        )
        # 严格解析：无法解析的值报「字段值非法」，不静默降级为空集。
        self.make_v4_plan(slug="bad-dep",
                          nodes=(self.node_block("N1", "T1", deps="hello")
                                 + self.node_block("N2", "T2", final="是")))
        self.assertEqual(
            self.check_messages("bad-dep"),
            ["审查节点 N1 的『依赖节点』字段值非法（无法解析的列表项：hello）——"
             "只接受『无』或逗号分隔的 ID 列表。"],
        )
        self.make_v4_plan(slug="bad-owner-value", nodes=self.node_block("N1", "T1 与 T2", final="是"))
        self.assertIn(
            "审查节点 N1 的『归属任务』字段值非法（无法解析的列表项：T1 与 T2）——"
            "只接受『无』或逗号分隔的 ID 列表。",
            self.check_messages("bad-owner-value"))
        self.make_v4_plan(slug="annotation-only",
                          nodes=(self.node_block("N1", "T1", deps="（原 N3 已并入）")
                                 + self.node_block("N2", "T2", final="是")))
        self.assertIn(
            "审查节点 N1 的『依赖节点』字段值非法（剥离尾部括号注解后没有可解析内容）——"
            "只接受『无』或逗号分隔的 ID 列表。",
            self.check_messages("annotation-only"))

    def test_review_nodes_parsing_compatibility_matrix(self):
        # 围栏内的假节点标题不算节点块；半角冒号可解析；未知字段忽略不报错。
        nodes = ("```\n### N9 围栏里的假标题\n```\n\n"
                 "### N1 全量验收\n\n"
                 "- **归属任务**: T1, T2\n"
                 "- **分组理由**：fixture 分组理由\n"
                 "- **审查职责**：逐任务一行\n"
                 "- **依赖节点**: 无\n"
                 "- **送审条件**：归属任务全部已实现\n"
                 "- **兼任终审**：是\n"
                 "- **备注**：未知字段应被忽略\n")
        self.make_v4_plan(slug="compat", nodes=nodes)
        self.assertEqual(self.cli("check", "compat")["errors"], [])
        plan = workflow.load_plan(str(self.root), "compat")
        self.assertEqual([node.id for node in plan.nodes], ["N1"])
        self.assertEqual(plan.nodes[0].tasks, ["T1", "T2"])
        self.assertEqual(plan.nodes[0].deps, [])
        self.assertEqual(plan.nodes[0].get("备注"), "未知字段应被忽略")

    def test_review_nodes_section_name_is_exact_and_repeats_union(self):
        # 近似段名（带后缀）不是节点段：`## 审查节点与边界` 里的块不被解析。
        self.make_v4_plan(slug="near-name", section_name="审查节点与边界")
        self.assertEqual(
            self.check_messages("near-name"),
            ["格式 4 计划缺少 `## 审查节点` 段——节点是格式 4 的验收单位，"
             "每个任务必须恰属一个节点。"],
        )
        self.assertEqual(workflow.load_plan(str(self.root), "near-name").nodes, [])
        # 重复同名段沿用引擎既有的段处理行为：段正文合并，两块都被解析。
        nodes = (self.node_block("N1", "T1", final="是") + "\n## 审查节点\n\n"
                 + self.node_block("N2", "T2"))
        self.make_v4_plan(slug="repeat-section", nodes=nodes,
                          tasks=self.v4_tasks((("T1", "无"), ("T2", "无"))))
        self.assertEqual(self.cli("check", "repeat-section")["errors"], [])
        self.assertEqual(
            [node.id for node in workflow.load_plan(str(self.root), "repeat-section").nodes],
            ["N1", "N2"],
        )

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

    # ------------------------------------------------ 格式 4 两态记账（T2）

    def approve_v4(self, slug="v4"):
        self.cli("approve", slug, "方案", "--by", "fixture 方案确认")
        self.cli("approve", slug, "计划", "--by", "fixture 计划确认")

    def cli_text(self, *args, expected=0):
        """不带 --json 跑一次，返回显示文案（receipt.text 只有这条路径可观察）。"""
        process = subprocess.run([sys.executable, "-B", str(SCRIPT), *args],
                                 cwd=self.root, capture_output=True, text=True)
        self.assertEqual(process.returncode, expected, process.stdout + process.stderr)
        return process.stdout.strip()

    def record_v4(self, *task_ids, slug="v4", operation_id="rv-N1-1",
                  evidence="跑 `true`：退出码 0；失败信号自查无", commits="HEAD..HEAD",
                  note="fixture 本任务无新提交（空范围豁免）", expected=0, text=False, **extra):
        args = ["record", slug, *task_ids, "--commits", commits,
                "--evidence", evidence, "--operation-id", operation_id]
        if note is not None:
            args.extend(["--note", note])
        for key, value in extra.items():
            args.extend(["--" + key.replace("_", "-"), value])
        return (self.cli_text(*args, expected=expected) if text
                else self.cli(*args, expected=expected))

    def implemented_events(self, slug="v4"):
        return [event for event in self.events(slug) if event["type"] == "implemented"]

    def repair_events(self, slug="v4"):
        return [event for event in self.events(slug) if event["type"] == "projection_repair"]

    def assert_replay_matches(self, replay, original):
        """幂等重放＝原结果逐字段相同 ＋ 一条「历史回放」提示（裁决 6）。"""
        self.assertEqual(replay["warnings"][:-1], original["warnings"])
        self.assertIn("幂等重放", replay["warnings"][-1])
        self.assertEqual({k: v for k, v in replay.items() if k != "warnings"},
                         {k: v for k, v in original.items() if k != "warnings"})

    def rollback_status(self, slug="v4", status="pending"):
        """把已实现任务的计划状态手工回退。"""
        self.plan(slug).write_text(
            self.plan(slug).read_text().replace("- **状态**：implemented", f"- **状态**：{status}"))

    def erase_ledger_lines(self, slug, *needles):
        """抹掉账本里含指定片段的整行（构造「状态与账本行都未回写」的真实中断残留态）。"""
        path = self.root / ".workflow" / slug / "ledger.md"
        kept = [line for line in path.read_text().splitlines()
                if not any(needle in line for needle in needles)]
        path.write_text("\n".join(kept) + "\n")

    def interrupt_after_event(self, slug, note_marker="fixture 本任务无新提交"):
        """真实中断残留态：事件已落盘；计划状态与账本行（完成记录＋裁决）都未写——
        写入顺序是 事件 → 计划状态 → 账本行，中断只能停在这两步之前。"""
        self.rollback_status(slug)
        self.erase_ledger_lines(slug, "已实现（操作 ", note_marker)

    def test_two_state_record_requires_evidence_and_operation_id(self):
        self.make_v4_plan(slug="t2", nodes=self.node_block("N1", "T1, T2", final="是"))
        self.approve_v4("t2")
        message = self.record_v4("T1", slug="t2", verdict="clean", expected=1)["error"]
        self.assertIn("--verdict", message)
        self.assertIn("--evidence", message)
        args = ["record", "t2", "T1", "--commits", "HEAD..HEAD", "--note", "fixture 空范围豁免",
                "--operation-id", "rv-N1-9"]
        self.assertIn("--evidence", self.cli(*args, expected=1)["error"])
        self.assertIn("--evidence", self.record_v4("T1", slug="t2", evidence="  ", expected=1)["error"])
        args = ["record", "t2", "T1", "--commits", "HEAD..HEAD", "--note", "fixture 空范围豁免",
                "--evidence", "证据"]
        self.assertIn("--operation-id", self.cli(*args, expected=1)["error"])
        self.assertIn("空白", self.record_v4("T1", slug="t2", operation_id="rv N1 1", expected=1)["error"])
        self.assertIn("--operation-id", self.record_v4("T1", slug="t2", operation_id="", expected=1)["error"])
        self.assertEqual(self.events("t2"), [])
        self.assertEqual(workflow.load_plan(str(self.root), "t2").tasks[0].status, "pending")

    def test_two_state_duplicate_task_ids_rejected_without_write(self):
        """M1：重复任务 ID 直接拒绝（不得先落盘一条自己读不了的事件）。"""
        self.make_v4_plan(slug="t2dup", nodes=self.node_block("N1", "T1, T2", final="是"))
        self.approve_v4("t2dup")
        message = self.record_v4("T2", "T2", slug="t2dup", operation_id="rv-N1-8", expected=1)["error"]
        self.assertIn("重复的任务 ID：T2", message)
        self.assertFalse((self.root / ".workflow/t2dup/events.jsonl").exists())
        self.assertEqual(workflow.load_plan(str(self.root), "t2dup").tasks[1].status, "pending")

    def test_two_state_prewrite_selfcheck_blocks_unreadable_event(self):
        """M1 防线：要 append 的事件先按 read_events 同一套判据自校验，不合法不落盘。"""
        start = {"schema": 1, "id": "s", "type": "start", "time": "2026-10-15T10:00:00+08:00",
                 "workflow": "v4", "cycle": 1,
                 "data": {"legacy_closed": False, "legacy_close": None}}
        bad = {"schema": 1, "id": "b", "type": "implemented", "time": "2026-10-15T10:00:00+08:00",
               "workflow": "v4", "cycle": 1, "data": {"tasks": ["T1", "T1"]}}
        with self.assertRaises(workflow.WorkflowError) as caught:
            workflow.validate_event_batch([start], [bad], "v4")
        self.assertIn("未通过结构自校验", str(caught.exception))
        self.assertIn("已实现事件缺少任务清单", str(caught.exception))
        with self.assertRaises(workflow.WorkflowError):
            workflow.validate_event_batch([], [], "v4")   # 空集合读校验同样拒绝

    def test_two_state_event_line_split_matches_reader(self):
        """N-1：写侧与读侧同一行切分——evidence 含 U+2028/U+2029 不被自校验误拦。"""
        self.make_v4_plan(slug="t2u", nodes=self.node_block("N1", "T1, T2", final="是"))
        self.approve_v4("t2u")
        evidence = "跑 `true`：退出码 0\u2028失败信号自查无\u2029第二段"
        result = self.record_v4("T1", slug="t2u", evidence=evidence)
        self.assertEqual(result["evidence"], evidence)
        records = self.implemented_events("t2u")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["data"]["evidence"], evidence)
        self.assertEqual(records[0]["data"]["receipt"]["result"]["evidence"], evidence)
        # 写侧接受的必须被读侧接受：read_events 读回同一序列且内容一致
        self.assertEqual([event["type"] for event in workflow.read_events(str(self.root), "t2u")],
                         ["start", "implemented"])
        # 行切分同源：写侧自校验对同一文本得出的行数与读侧一致（不因 U+2028 多切）
        text = workflow.serialize_events(self.events("t2u"))
        self.assertEqual(len(list(workflow.event_lines(text))), len(self.events("t2u")))
        # 同请求重放仍幂等（evidence 逐字参与请求身份）
        self.assert_replay_matches(self.record_v4("T1", slug="t2u", evidence=evidence), result)

    def test_two_state_ledger_row_split_matches_append(self):
        """修复轮 3：账本行切分按 \\n——`--note` 含 U+2028/U+2029 时重放不重复追加裁决行。"""
        self.make_v4_plan(slug="t2n", nodes=self.node_block("N1", "T1, T2", final="是"))
        self.approve_v4("t2n")
        note = "fixture 空范围豁免\u2028第二段\u2029第三段"
        ledger_path = self.root / ".workflow/t2n/ledger.md"
        result = self.record_v4("T1", slug="t2n", note=note)
        self.assertIn(note, ledger_path.read_text())

        def note_rows():
            # 只数「裁决」区里的行——事件视图区会带出 receipt 里的同一段文本。
            section = ledger_path.read_text().split("## 裁决", 1)[1].split("\n## ", 1)[0]
            return [line for line in section.split("\n") if "fixture 空范围豁免" in line]

        self.assertEqual(len(note_rows()), 1)
        for _ in range(2):   # 重放两次：账本行数不变（行身份按 \n 判定）
            self.assert_replay_matches(self.record_v4("T1", slug="t2n", note=note), result)
        self.assertEqual(len(note_rows()), 1)
        self.assertEqual(len(self.implemented_events("t2n")), 1)

    def test_two_state_legacy_plan_rejects_v4_only_parameters(self):
        """M2：格式 ≤3 上给 --evidence/--operation-id 必须明确拒绝，不得静默忽略。"""
        self.make_v4_plan(slug="v3rec", version=3)
        self.approve_v4("v3rec")
        message = self.cli("record", "v3rec", "T1", "--commits", "HEAD..HEAD",
                           "--note", "fixture 空范围豁免", "--evidence", "我以为是格式 4",
                           "--operation-id", "rv-N1-1", expected=1)["error"]
        self.assertIn("--evidence", message)
        self.assertIn("--operation-id", message)
        self.assertIn("格式 3", message)
        self.assertEqual(workflow.load_plan(str(self.root), "v3rec").tasks[0].status, "pending")
        # 旧输入空间照旧：不带新参数仍按 ≤3 语义记账
        result = self.cli("record", "v3rec", "T1", "--commits", "HEAD..HEAD", "--note", "fixture 空范围豁免")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(self.events("v3rec"), [])

    def test_two_state_record_writes_event_then_status_and_ledger(self):
        self.make_v4_plan(slug="t2", nodes=self.node_block("N1", "T1, T2", final="是"))
        self.approve_v4("t2")
        result = self.record_v4("T1", slug="t2")
        self.assertEqual(result["status"], "implemented")
        self.assertEqual(result["tasks"], ["T1"])
        self.assertEqual(result["operation_id"], "rv-N1-1")
        self.assertEqual(workflow.load_plan(str(self.root), "t2").tasks[0].status, "implemented")
        self.assertEqual(workflow.load_plan(str(self.root), "t2").tasks[1].status, "pending")
        records = self.implemented_events("t2")
        self.assertEqual(len(records), 1)
        data = records[0]["data"]
        self.assertEqual(data["tasks"], ["T1"])
        self.assertEqual(data["operation_id"], "rv-N1-1")
        self.assertEqual(data["commits"], "HEAD..HEAD")
        self.assertIn("失败信号自查", data["evidence"])
        self.assertEqual(data["entry"], "record")
        self.assertEqual(data["receipt"]["result"]["event"], records[0]["id"])
        self.assertIn("| T1 | HEAD..HEAD |", (self.root / ".workflow/t2/ledger.md").read_text())
        # 空提交范围的 --note 豁免在格式 ≥4 同样适用；不写 --note 仍按 ≤3 规则拦下。
        self.assertTrue(any("没有产生提交" in message for message in result["warnings"]))
        self.record_v4("T2", slug="t2", operation_id="rv-N1-2", note=None, expected=1)

    def test_two_state_record_idempotent_replay_and_conflict_rejected(self):
        self.make_v4_plan(slug="t2", nodes=self.node_block("N1", "T1, T2", final="是"))
        self.approve_v4("t2")
        first = self.record_v4("T1", slug="t2")
        events, plan_text = self.events("t2"), self.plan("t2").read_text()
        ledger = (self.root / ".workflow/t2/ledger.md").read_text()
        # 同 ID＋相同请求 → 幂等重放：原结果逐字段相同＋回放提示；计划、事件与账本均不重复
        self.assert_replay_matches(self.record_v4("T1", slug="t2"), first)
        self.assertEqual(self.events("t2"), events)
        self.assertEqual(self.plan("t2").read_text(), plan_text)
        self.assertEqual((self.root / ".workflow/t2/ledger.md").read_text(), ledger)
        # 同 ID＋不同请求 → 拒绝（证据、任务集合、提交范围任一不同）
        self.assertIn("请求摘要不符", self.record_v4(
            "T1", slug="t2", evidence="另一份证据", expected=1)["error"])
        self.assertIn("请求摘要不符", self.record_v4("T2", slug="t2", expected=1)["error"])
        self.assertIn("请求摘要不符", self.record_v4(
            "T1", slug="t2", commits="deadbee..HEAD", expected=1)["error"])
        self.assertEqual(len(self.implemented_events("t2")), 1)
        self.assertEqual(workflow.load_plan(str(self.root), "t2").tasks[1].status, "pending")

    def test_two_state_record_interrupt_after_event_recovers_projection(self):
        """真实中断残留态（事件在、状态与账本行都没写）→ 携原 ID 重放三步齐备：
        事件不重复、状态修复、账本完成记录行补写；返回原结果（含显示文案）。"""
        self.make_v4_plan(slug="t2", nodes=self.node_block("N1", "T1, T2", final="是"))
        self.approve_v4("t2")
        shown = self.record_v4("T1", slug="t2", text=True)
        self.assertIn("已实现（evidence 已记", shown)
        ledger_path = self.root / ".workflow/t2/ledger.md"
        self.interrupt_after_event("t2")
        self.assertNotIn("| T1 | HEAD..HEAD |", ledger_path.read_text())
        self.assertNotIn("fixture 本任务无新提交", ledger_path.read_text())
        self.assertEqual(workflow.load_plan(str(self.root), "t2").tasks[0].status, "pending")
        # 携原 ID 重试：入口投影检查先修复状态，重放再补账本行并返回原结果＋回放提示
        replay_text = self.record_v4("T1", slug="t2", text=True)
        self.assertTrue(replay_text.startswith(shown), replay_text)
        self.assertIn("幂等重放", replay_text)
        self.assertEqual(workflow.load_plan(str(self.root), "t2").tasks[0].status, "implemented")
        self.assertEqual([event["type"] for event in self.events("t2")].count("implemented"), 1)
        text = ledger_path.read_text()
        self.assertIn("| T1 | HEAD..HEAD | 已实现（操作 rv-N1-1） |", text)
        self.assertIn("fixture 本任务无新提交", text)
        repairs = self.repair_events("t2")
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0]["data"]["entry"], "record")
        self.assertEqual(repairs[0]["data"]["repairs"],
                         [{"task": "T1", "from": "pending", "to": "implemented"}])
        # 再次重放：账本行不重复追加
        self.assertTrue(self.record_v4("T1", slug="t2", text=True).startswith(shown))
        self.assertEqual(ledger_path.read_text().count("已实现（操作 rv-N1-1） |"), 1)

    def test_two_state_complete_without_pass_support_is_repaired_down(self):
        """M5 的 T3 更新（裁决 2）：`complete` 现有推导来源＝节点审查 `pass`（D-18）；
        有实现证据但没有 `pass` 支撑 → 按事件推导**修复下**（`fail` 后中断的合法
        残留态），不再报「无法由事件重放推导」——这是 T3 的合法演进。"""
        self.make_v4_plan(slug="t2done", nodes=self.node_block("N1", "T1, T2", final="是"))
        self.approve_v4("t2done")
        self.record_v4("T1", slug="t2done", operation_id="rv-N1-9")
        self.plan("t2done").write_text(
            self.plan("t2done").read_text().replace("- **状态**：implemented", "- **状态**：complete", 1))
        self.cli("slice", "t2done", "T2")
        self.assertEqual(workflow.load_plan(str(self.root), "t2done").tasks[0].status, "implemented")
        repairs = self.repair_events("t2done")
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0]["data"]["repairs"],
                         [{"task": "T1", "from": "complete", "to": "implemented"}])

    def test_two_state_close_checks_closed_before_projection(self):
        """M4：已关闭周期先返回 already-closed，不向关闭周期追加修复事件。"""
        self.make_v4_plan(slug="t2closed", nodes=self.node_block("N1", "T1, T2", final="是"))
        self.plan("t2closed").write_text(
            self.plan("t2closed").read_text().replace("- **状态**：pending", "- **状态**：complete"))
        with (self.root / ".workflow/t2closed/ledger.md").open("a") as fh:
            fh.write("\n## 收尾\n| 时间 | 完成 | 指纹 | 下一步 |\n|---|---|---|---|\n"
                     "| 2026-01-01 12:00 | 2/2 | 0123456789abcdef | — |\n")
        result = self.cli("close", "t2closed")
        self.assertTrue(result["already_closed"])
        self.assertFalse((self.root / ".workflow/t2closed/events.jsonl").exists())

    def test_two_state_event_referencing_unknown_task_is_refused_with_identity(self):
        """M6：事件引用计划里没有的任务 → 拒绝并给出事件 ID 与任务 ID（T3/T5 再放宽）。"""
        self.make_v4_plan(slug="t2ghost", nodes=self.node_block("N1", "T1, T2", final="是"))
        self.approve_v4("t2ghost")
        self.record_v4("T1", slug="t2ghost")
        event_id = self.implemented_events("t2ghost")[0]["id"]
        rewritten = []
        for event in self.events("t2ghost"):
            if event["type"] == "implemented":
                event["data"]["tasks"] = ["T9"]
            rewritten.append(event)
        (self.root / ".workflow/t2ghost/events.jsonl").write_text(
            "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in rewritten))
        message = self.cli("slice", "t2ghost", "T2", expected=1)["error"]
        self.assertIn(event_id, message)
        self.assertIn("T9", message)

    def test_two_state_projection_repair_on_entries_and_missing_event_refused(self):
        self.make_v4_plan(slug="t2", nodes=self.node_block("N1", "T1, T2", final="是"))
        self.approve_v4("t2")
        self.record_v4("T1", slug="t2")
        # slice 入口：投影落后 → 自动修复并留 projection_repair（含触发入口与 from→to）
        self.rollback_status("t2")
        self.cli("slice", "t2", "T2")
        self.assertEqual(workflow.load_plan(str(self.root), "t2").tasks[0].status, "implemented")
        self.assertEqual([event["data"]["entry"] for event in self.repair_events("t2")], ["slice"])
        # close 入口：同样先修复；随后因未完成验收而拒绝收尾
        self.rollback_status("t2")
        self.cli("close", "t2", expected=1)
        self.assertEqual([event["data"]["entry"] for event in self.repair_events("t2")], ["slice", "close"])
        self.assertEqual(workflow.load_plan(str(self.root), "t2").tasks[0].status, "implemented")
        # 事件缺失（计划写了已实现、没有对应事件）→ 拒绝继续，不静默按计划回退
        kept = [event for event in self.events("t2") if event["type"] != "implemented"]
        path = self.root / ".workflow/t2/events.jsonl"
        path.write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in kept))
        message = self.cli("slice", "t2", "T2", expected=1)["error"]
        self.assertIn("领先于事件重放推导", message)
        self.assertIn("T1", message)
        self.assertIn("领先于事件重放推导", self.record_v4("T1", slug="t2", expected=1)["error"])
        self.assertIn("领先于事件重放推导", self.cli("close", "t2", expected=1)["error"])
        self.assertEqual(len(self.implemented_events("t2")), 0)

    def test_two_state_repair_function_is_noop_when_consistent_or_legacy(self):
        self.make_v4_plan(slug="t2", nodes=self.node_block("N1", "T1, T2", final="是"))
        self.assertIsNone(workflow.repair_projection(str(self.root), "t2"))
        self.assertEqual(self.events("t2"), [])
        self.assertIsNone(workflow.repair_projection(str(self.root), "t2", "test"))
        # 格式 ≤3 不参与投影核对（本任务不接管旧格式）
        self.make_v4_plan(slug="v3noop", version=3)
        self.assertIsNone(workflow.repair_projection(str(self.root), "v3noop", "test"))
        self.assertEqual(self.events("v3noop"), [])

    def test_two_state_status_split_by_format_and_v3_record_unchanged(self):
        self.make_v4_plan(slug="v4-status", nodes=self.node_block("N1", "T1, T2", final="是"))
        self.plan("v4-status").write_text(
            self.plan("v4-status").read_text().replace("- **状态**：pending", "- **状态**：in_progress", 1))
        self.assertIn("状态 'in_progress' 非法，只能是 pending/implemented/complete。",
                      self.check_messages("v4-status"))
        self.plan("v4-status").write_text(
            self.plan("v4-status").read_text().replace("- **状态**：in_progress", "- **状态**：blocked", 1))
        self.assertIn("状态 'blocked' 非法，只能是 pending/implemented/complete。",
                      self.check_messages("v4-status"))
        # 格式 ≤3：原集合与原消息逐字不变
        self.make_v4_plan(slug="v3-status", version=3)
        self.plan("v3-status").write_text(
            self.plan("v3-status").read_text().replace("- **状态**：pending", "- **状态**：in_progress", 1))
        self.cli("check", "v3-status")
        self.plan("v3-status").write_text(
            self.plan("v3-status").read_text().replace("- **状态**：in_progress", "- **状态**：weird", 1))
        self.assertIn("状态 'weird' 非法，只能是 pending/in_progress/complete/blocked。",
                      self.check_messages("v3-status"))
        # 格式 ≤3 的 record：不要求 evidence/operation-id，状态与判词沿用旧语义
        self.make_v4_plan(slug="v3-rec", version=3)
        self.approve_v4("v3-rec")
        result = self.cli("record", "v3-rec", "T1", "--commits", "HEAD..HEAD", "--note", "fixture 空范围豁免")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["verdict"], "clean")
        self.assertEqual(self.events("v3-rec"), [])
        self.assertEqual(workflow.load_plan(str(self.root), "v3-rec").tasks[0].status, "complete")

    def test_two_state_record_batch_is_one_event_and_replays_identically(self):
        tasks = self.v4_tasks((("T1", "无"), ("T2", "无")))
        self.make_v4_plan(slug="t2b", nodes=self.node_block("N1", "T1, T2", final="是"), tasks=tasks)
        self.approve_v4("t2b")
        first = self.record_v4("T1", "T2", slug="t2b")
        self.assertEqual(first["tasks"], ["T1", "T2"])
        self.assertTrue(first["batch"])
        records = self.implemented_events("t2b")
        self.assertEqual(len(records), 1)   # 一次操作只写一条事件
        self.assertEqual(records[0]["data"]["tasks"], ["T1", "T2"])
        statuses = [task.status for task in workflow.load_plan(str(self.root), "t2b").tasks]
        self.assertEqual(statuses, ["implemented", "implemented"])
        ledger = (self.root / ".workflow/t2b/ledger.md").read_text()
        self.assertIn("| T1 | HEAD..HEAD |", ledger)
        self.assertIn("| T2 | HEAD..HEAD |", ledger)
        counts = len(self.events("t2b"))
        self.assert_replay_matches(self.record_v4("T2", "T1", slug="t2b"), first)   # 集合一致即同请求
        self.assertEqual(len(self.events("t2b")), counts)

    def test_two_state_record_refuses_cleanly_without_status_line(self):
        self.make_v4_plan(slug="nostatus", nodes=self.node_block("N1", "T1, T2", final="是"))
        self.plan("nostatus").write_text(
            self.plan("nostatus").read_text().replace("- **状态**：pending\n", "", 1))
        self.approve_v4("nostatus")
        message = self.record_v4("T1", slug="nostatus", expected=1)["error"]
        self.assertIn("缺少『状态』字段行", message)
        self.assertFalse((self.root / ".workflow/nostatus/events.jsonl").exists())
        self.assertIn("- **状态**：pending", self.plan("nostatus").read_text())

    def test_two_state_corrupt_implemented_event_is_never_ignored(self):
        self.make_v4_plan(slug="t2c", nodes=self.node_block("N1", "T1, T2", final="是"))
        self.approve_v4("t2c")
        self.record_v4("T1", slug="t2c")
        path = self.root / ".workflow/t2c/events.jsonl"
        broken = []
        for event in self.events("t2c"):
            if event["type"] == "implemented":
                event["data"].pop("receipt")
            broken.append(event)
        path.write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in broken))
        for args in (("slice", "t2c", "T2"), ("record", "t2c", "T2", "--commits", "HEAD..HEAD",
                                             "--evidence", "证据", "--operation-id", "rv-N1-3")):
            message = self.cli(*args, expected=1)["error"]
            self.assertIn("结构化证据损坏", message)
            self.assertIn("receipt", message)

    # ------------------------------------------------ 节点审查 review（T3）

    def commit_range(self):
        """制造一个真实提交，返回 `<base7>..<head7>` 范围的字符串。"""
        base = self.git("rev-parse", "--short", "HEAD")
        self.git("-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "--allow-empty", "-qm", "work")
        return f"{base}..HEAD"

    def review_lines(self, *pairs):
        return "；".join(f"{tid}: {conclusion}" for tid, conclusion in pairs)

    def review_v4(self, node="N1", slug="v4", verdict="pass", operation_id="rv-N1-1",
                  lines=None, evidence="审查依据：读 git diff 与 record 证据，逐任务结论见 --lines",
                  commits="HEAD..HEAD", expected=0, text=False, **extra):
        if lines is None:
            lines = self.review_lines(
                ("T1", "依据 record 证据（跑 `true` 退出码 0），实现符合规格"),
                ("T2", "同 T1；组内集成关系已查，无新问题"))
        args = ["review", slug, node, "--verdict", verdict, "--commits", commits,
                "--lines", lines, "--evidence", evidence, "--operation-id", operation_id]
        for key, value in extra.items():
            args.extend(["--" + key.replace("_", "-"), value])
        return (self.cli_text(*args, expected=expected) if text
                else self.cli(*args, expected=expected))

    def node_review_events(self, slug="v4"):
        return [event for event in self.events(slug) if event["type"] == "node_review"]

    def ledger_body(self, slug="v4"):
        """账本在事件视图之前的部分——审查/修复不得新增账本行。"""
        path = self.root / ".workflow" / slug / "ledger.md"
        return path.read_text().split(workflow.VIEW_MARKER)[0]

    def node_review_plan(self, slug="t3", nodes=None, tasks=None):
        """节点 N1（T1、T2）＋节点 N2（T3，依赖 N1，兼任终审）：下游派发观察位。"""
        if nodes is None:
            nodes = (self.node_block("N1", "T1, T2")
                     + self.node_block("N2", "T3", deps="N1", final="是"))
        if tasks is None:
            tasks = self.v4_tasks((("T1", "无"), ("T2", "无"), ("T3", "T1")))
        self.make_v4_plan(slug=slug, nodes=nodes, tasks=tasks)
        self.approve_v4(slug)

    def test_three_review_pass_maps_members_complete_and_releases_downstream(self):
        self.node_review_plan()
        self.record_v4("T1", slug="t3", operation_id="rec-t1")
        self.record_v4("T2", slug="t3", operation_id="rec-t2")
        plan = workflow.load_plan(str(self.root), "t3")
        self.assertEqual([task.status for task in plan.tasks], ["implemented", "implemented", "pending"])
        self.assertEqual(plan.states()["T3"], "BLOCKED")   # 上游未验收：跨节点下游阻塞
        self.assertNotIn("T3", [item["id"] for item in self.cli("next", "t3")["ready"]])

        span = self.commit_range()
        body = self.ledger_body("t3")
        result = self.review_v4("N1", slug="t3", commits=span, operation_id="rv-N1-1")
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["node"], "N1")
        self.assertEqual(result["mapped_status"], workflow.STATUS_COMPLETE)
        self.assertEqual(result["tasks"], ["T1", "T2"])
        self.assertEqual(result["rounds"], 0)
        self.assertEqual(result["warnings"], [])
        self.assertTrue(result["lineage"].startswith("N1-"), result["lineage"])

        plan = workflow.load_plan(str(self.root), "t3")
        self.assertEqual([task.status for task in plan.tasks],
                         ["complete", "complete", "pending"])
        self.assertEqual(plan.states()["T3"], "READY")     # 节点验收后下游可派发
        self.assertIn("T3", [item["id"] for item in self.cli("next", "t3")["ready"]])
        self.cli("slice", "t3", "T3")

        records = self.node_review_events("t3")
        self.assertEqual(len(records), 1)
        data = records[0]["data"]
        self.assertEqual(data["节点"], "N1")
        self.assertEqual(data["谱系"], result["lineage"])
        self.assertEqual(data["审查阶段"], 1)
        self.assertEqual(data["verdict"], "pass")
        self.assertEqual(data["commits"], span)
        self.assertEqual(data["premises"], [])
        self.assertEqual(data["open_issues"], [])
        self.assertEqual(data["operation_id"], "rv-N1-1")
        self.assertEqual(data["entry"], "review")
        self.assertEqual([row["task"] for row in data["lines"]], ["T1", "T2"])
        self.assertTrue(all(row["conclusion"] for row in data["lines"]))
        self.assertEqual(data["节点版本"], workflow.node_version(plan, plan.nodes[0]))
        self.assertRegex(data["节点版本"], r"^[a-f0-9]{16}$")
        self.assertEqual(data["receipt"]["result"]["event"], records[0]["id"])
        self.assertEqual(workflow.round_count(self.events("t3"), data["谱系"]), 0)
        # 审查不新增账本行（事件即记录；账本正文不变）
        self.assertEqual(self.ledger_body("t3"), body)

    def test_three_review_fail_keeps_implemented_and_does_not_map_complete(self):
        self.node_review_plan(slug="t3f")
        self.record_v4("T1", slug="t3f", operation_id="rec-t1")
        self.record_v4("T2", slug="t3f", operation_id="rec-t2")
        result = self.review_v4(
            "N1", slug="t3f", verdict="fail", operation_id="rv-N1-1",
            lines=self.review_lines(("T1", "依据 record 证据，符合规格"),
                                    ("T2", "缺边界用例：输入为空时行为未验证")))
        self.assertEqual(result["verdict"], "fail")
        self.assertEqual(result["mapped_status"], workflow.STATUS_IMPLEMENTED)
        plan = workflow.load_plan(str(self.root), "t3f")
        self.assertEqual([task.status for task in plan.tasks],
                         ["implemented", "implemented", "pending"])
        self.assertEqual(plan.states()["T3"], "BLOCKED")   # 节点未通过：不释放跨节点依赖
        records = self.node_review_events("t3f")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["data"]["verdict"], "fail")
        derived = workflow.derived_states(plan, workflow.read_events(str(self.root), "t3f"))
        self.assertEqual(derived, {"T1": "implemented", "T2": "implemented", "T3": "pending"})

    def test_three_review_lines_must_cover_owners_exactly(self):
        self.node_review_plan(slug="t3l")
        self.record_v4("T1", slug="t3l", operation_id="rec-t1")
        self.record_v4("T2", slug="t3l", operation_id="rec-t2")
        cases = [
            ("T1: 只写了 T1", "缺行：T2"),
            ("T1: a；T2: b；T3: c", "多行：T3"),
            ("T1: a；T1: b；T2: c", "重复行：T1"),
            ("T1: ；T2: b", "缺结论＋依据：T1"),
            ("", "没有解析出任何"),
            ("   \n  ", "没有解析出任何"),
        ]
        for lines, needle in cases:
            with self.subTest(lines=lines):
                message = self.review_v4("N1", slug="t3l", lines=lines, expected=1)["error"]
                self.assertIn(needle, message)
                self.assertIn("T1", message)
        self.assertEqual(self.node_review_events("t3l"), [])
        self.assertEqual([task.status for task in workflow.load_plan(str(self.root), "t3l").tasks],
                         ["implemented", "implemented", "pending"])
        # 宽松解析（正向）：换行分隔、半角冒号、结论里的标点都不误判成新行
        self.review_v4("N1", slug="t3l", operation_id="rv-N1-1",
                       lines="T1: 结论一，含；分号与逗号\nT2: 结论二; 补充说明")
        records = self.node_review_events("t3l")
        self.assertEqual(len(records), 1)
        self.assertEqual([row["task"] for row in records[0]["data"]["lines"]], ["T1", "T2"])
        self.assertEqual(records[0]["data"]["lines"][0]["conclusion"], "结论一，含；分号与逗号")
        self.assertEqual(records[0]["data"]["lines"][1]["conclusion"], "结论二; 补充说明")

    def test_three_review_requires_all_members_implemented(self):
        self.node_review_plan(slug="t3r")
        self.record_v4("T1", slug="t3r", operation_id="rec-t1")
        message = self.review_v4("N1", slug="t3r", operation_id="rv-N1-1", expected=1)["error"]
        self.assertIn("尚未全部实现", message)
        self.assertIn("T2", message)
        self.assertEqual(self.node_review_events("t3r"), [])

    def test_three_review_requires_operation_id_and_known_node(self):
        self.node_review_plan(slug="t3o")
        self.record_v4("T1", slug="t3o", operation_id="rec-t1")
        self.record_v4("T2", slug="t3o", operation_id="rec-t2")
        for operation_id, needle in (("", "--operation-id"), ("rv N1 1", "空白")):
            with self.subTest(operation_id=operation_id):
                message = self.review_v4("N1", slug="t3o", operation_id=operation_id,
                                         expected=1)["error"]
                self.assertIn(needle, message)
        message = self.review_v4("N9", slug="t3o", operation_id="rv-N9-1", expected=1)["error"]
        self.assertIn("没有审查节点 N9", message)
        self.assertIn("N1", message)
        self.assertEqual(self.node_review_events("t3o"), [])
        self.assertEqual([task.status for task in workflow.load_plan(str(self.root), "t3o").tasks],
                         ["implemented", "implemented", "pending"])

    def test_three_review_idempotent_replay_and_conflict_rejected(self):
        self.node_review_plan(slug="t3i")
        self.record_v4("T1", slug="t3i", operation_id="rec-t1")
        self.record_v4("T2", slug="t3i", operation_id="rec-t2")
        first = self.review_v4("N1", slug="t3i", operation_id="rv-N1-1")
        events, plan_text, body = (self.events("t3i"), self.plan("t3i").read_text(),
                                   self.ledger_body("t3i"))
        # 同 ID＋相同请求（逐任务行书写顺序无关）→ 幂等重放：返回原结果、零写入、轮次不双计
        replay = self.review_v4(
            "N1", slug="t3i", operation_id="rv-N1-1",
            lines=self.review_lines(("T2", "同 T1；组内集成关系已查，无新问题"),
                                    ("T1", "依据 record 证据（跑 `true` 退出码 0），实现符合规格")))
        self.assert_replay_matches(replay, first)
        self.assertEqual(self.events("t3i"), events)
        self.assertEqual(self.plan("t3i").read_text(), plan_text)
        self.assertEqual(self.ledger_body("t3i"), body)
        self.assertEqual(len(self.node_review_events("t3i")), 1)
        self.assertEqual(workflow.round_count(events, first["lineage"]), 0)
        # 同 ID＋不同请求 → 拒绝（结论、逐任务行、已审范围任一不同）
        span = self.commit_range()
        for extra in ({"verdict": "fail"}, {"lines": self.review_lines(("T1", "另一份结论"), ("T2", "另一份结论"))},
                      {"commits": span}):
            with self.subTest(extra=extra):
                message = self.review_v4("N1", slug="t3i", operation_id="rv-N1-1",
                                         expected=1, **extra)["error"]
                self.assertIn("请求摘要不符", message)
        self.assertEqual(len(self.node_review_events("t3i")), 1)
        self.assertEqual(workflow.round_count(self.events("t3i"), first["lineage"]), 0)

    def test_three_review_reuses_lineage_and_counts_rounds(self):
        self.node_review_plan(slug="t3n")
        self.record_v4("T1", slug="t3n", operation_id="rec-t1")
        self.record_v4("T2", slug="t3n", operation_id="rec-t2")
        first = self.review_v4("N1", slug="t3n", operation_id="rv-N1-1")
        lineage = first["lineage"]
        self.assertEqual(first["rounds"], 0)
        self.assertEqual(workflow.round_count(self.events("t3n"), lineage), 0)
        second = self.review_v4("N1", slug="t3n", verdict="fail", operation_id="rv-N1-2",
                                lines=self.review_lines(("T1", "仍符合规格"),
                                                        ("T2", "修复未到位：缺失败信号自查")))
        self.assertEqual(second["lineage"], lineage)   # 同节点第二次送审复用谱系
        self.assertEqual(second["rounds"], 1)
        self.assertEqual(workflow.round_count(self.events("t3n"), lineage), 1)
        third = self.review_v4("N1", slug="t3n", operation_id="rv-N1-3",
                               lines=self.review_lines(("T1", "复核通过"),
                                                       ("T2", "修复已到位，复核通过")))
        self.assertEqual(third["lineage"], lineage)
        self.assertEqual(third["rounds"], 2)
        self.assertEqual(workflow.round_count(self.events("t3n"), lineage), 2)
        records = self.node_review_events("t3n")
        self.assertEqual([event["data"]["谱系"] for event in records], [lineage] * 3)
        self.assertEqual([task.status for task in workflow.load_plan(str(self.root), "t3n").tasks],
                         ["complete", "complete", "pending"])
        # 同请求重试仍不双计：事件数、轮次都不变
        self.assert_replay_matches(
            self.review_v4("N1", slug="t3n", operation_id="rv-N1-3",
                           lines=self.review_lines(("T1", "复核通过"),
                                                   ("T2", "修复已到位，复核通过"))), third)
        self.assertEqual(len(self.node_review_events("t3n")), 3)
        self.assertEqual(workflow.round_count(self.events("t3n"), lineage), 2)

    def test_three_node_version_follows_declared_fields_only(self):
        self.node_review_plan(slug="t3v")
        plan = workflow.load_plan(str(self.root), "t3v")
        before = workflow.node_version(plan, plan.nodes[0])
        self.assertRegex(before, r"^[a-f0-9]{16}$")
        # 只改运行字段（状态）→ 版本不变
        self.plan("t3v").write_text(
            self.plan("t3v").read_text().replace("- **状态**：pending", "- **状态**：complete", 1))
        changed = workflow.load_plan(str(self.root), "t3v")
        self.assertEqual(workflow.node_version(changed, changed.nodes[0]), before)
        # 改某任务的验收要求（声明字段）→ 版本变化：旧结论不得据此沿用（D-18）
        self.plan("t3v").write_text(
            self.plan("t3v").read_text().replace("- **验收**：结果正确", "- **验收**：结果正确且边界明确", 1))
        edited = workflow.load_plan(str(self.root), "t3v")
        self.assertNotEqual(workflow.node_version(edited, edited.nodes[0]), before)

    def test_three_review_rejected_on_legacy_plan_and_no_stubs(self):
        self.make_v4_plan(slug="t3legacy", version=3)
        self.approve_v4("t3legacy")
        message = self.review_v4("N1", slug="t3legacy", expected=1)["error"]
        self.assertIn("格式 3", message)
        self.assertIn("review", message)
        self.assertFalse((self.root / ".workflow/t3legacy/events.jsonl").exists())
        # `--new-phase` 已由 T6 实现：与普通 review 同一入口，格式 ≤3 在同一道格式检查上
        # 被拒（不为旧格式补空壳）；`--recheck` 同理（见上一条断言）。
        args = ["review", "t3legacy", "N1", "--new-phase", "--basis", "fixture 实质变化",
                "--confirmation", "rv-N1-1", "--confirmed-commit", "HEAD..HEAD",
                "--operation-id", "np-N1-1"]
        message = self.cli(*args, expected=1)["error"]
        self.assertIn("格式 3", message)
        self.assertIn("review", message)
        self.assertFalse((self.root / ".workflow/t3legacy/events.jsonl").exists())

    def test_three_review_interrupt_after_event_replays_and_repairs_projection(self):
        """崩溃窗口（pass 事件已写、状态未写）→ 入口修复投影，重放返回原结果。"""
        self.node_review_plan(slug="t3c")
        self.record_v4("T1", slug="t3c", operation_id="rec-t1")
        self.record_v4("T2", slug="t3c", operation_id="rec-t2")
        shown = self.review_v4("N1", slug="t3c", operation_id="rv-N1-1", text=True)
        self.assertIn("映射 complete", shown)
        self.rollback_complete("t3c")   # 事件在、状态未回写
        self.assertEqual([task.status for task in workflow.load_plan(str(self.root), "t3c").tasks],
                         ["implemented", "implemented", "pending"])
        replay_text = self.review_v4("N1", slug="t3c", operation_id="rv-N1-1", text=True)
        self.assertTrue(replay_text.startswith(shown), replay_text)
        self.assertIn("幂等重放", replay_text)
        self.assertEqual([task.status for task in workflow.load_plan(str(self.root), "t3c").tasks],
                         ["complete", "complete", "pending"])
        self.assertEqual(len(self.node_review_events("t3c")), 1)
        repairs = self.repair_events("t3c")
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0]["data"]["entry"], "review")
        self.assertEqual(repairs[0]["data"]["repairs"],
                         [{"task": "T1", "from": "implemented", "to": "complete"},
                          {"task": "T2", "from": "implemented", "to": "complete"}])

    def rollback_complete(self, slug="v4", status="implemented"):
        """把已验收任务的计划状态手工回退（构造审查通过后的中断残留态）。"""
        self.plan(slug).write_text(
            self.plan(slug).read_text().replace("- **状态**：complete", f"- **状态**：{status}"))

    def test_three_projection_repairs_down_after_fail_crash_window(self):
        """`fail` 事件已写、状态仍是 `complete`（中断残留）→ 入口修复下。

        T4 起 `slice` 还叠了跨节点就绪门：N1 最近结论是 `fail`（未验收），N2 的 T3
        必须被拒——修复照旧先在入口完成，随后才因未验收被拦（两条断言都要成立）。
        """
        self.node_review_plan(slug="t3d")
        self.record_v4("T1", slug="t3d", operation_id="rec-t1")
        self.record_v4("T2", slug="t3d", operation_id="rec-t2")
        self.review_v4("N1", slug="t3d", operation_id="rv-N1-1")
        self.review_v4("N1", slug="t3d", verdict="fail", operation_id="rv-N1-2",
                       lines=self.review_lines(("T1", "仍符合规格"), ("T2", "发现必修问题")))
        self.assertEqual([task.status for task in workflow.load_plan(str(self.root), "t3d").tasks],
                         ["implemented", "implemented", "pending"])
        self.plan("t3d").write_text(
            self.plan("t3d").read_text().replace("- **状态**：implemented", "- **状态**：complete"))
        message = self.cli("slice", "t3d", "T3", expected=1)["error"]
        self.assertIn("N1 未验收", message)   # T4：上游节点未验收 → 跨节点下游拒绝派发
        self.assertEqual([task.status for task in workflow.load_plan(str(self.root), "t3d").tasks],
                         ["implemented", "implemented", "pending"])
        repairs = self.repair_events("t3d")
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0]["data"]["repairs"],
                         [{"task": "T1", "from": "complete", "to": "implemented"},
                          {"task": "T2", "from": "complete", "to": "implemented"}])

    def test_three_projection_refuses_progress_without_implementation_evidence(self):
        """无 `implemented` 事件却声称有进度（implemented/complete）→ 拒绝，零写入。"""
        self.node_review_plan(slug="t3p")
        for claimed in ("complete", "implemented"):
            with self.subTest(claimed=claimed):
                self.plan("t3p").write_text(
                    self.plan("t3p").read_text().replace("- **状态**：pending",
                                                         f"- **状态**：{claimed}", 1))
                message = self.cli("slice", "t3p", "T1", expected=1)["error"]
                self.assertIn("领先于事件重放推导", message)
                self.assertIn("T1", message)
                self.assertNotIn("无法由事件重放推导", message)
                self.plan("t3p").write_text(
                    self.plan("t3p").read_text().replace(f"- **状态**：{claimed}",
                                                         "- **状态**：pending", 1))
        self.assertFalse((self.root / ".workflow/t3p/events.jsonl").exists())

    # ------------------------------------------------ 三态调度与格式 4 入口门（T4）

    def test_four_cross_node_gate_rejects_until_upstream_reviewed(self):
        """上游节点未验收（有 implemented 未 review）→ 跨节点下游 slice 拒绝并给节点与状态。"""
        self.node_review_plan(slug="t4a")
        self.record_v4("T1", slug="t4a", operation_id="rec-t1")
        plan = workflow.load_plan(str(self.root), "t4a")
        facts = workflow.task_states(plan)
        self.assertEqual(facts["T1"], {"implemented": True, "node_valid": False, "blocked": False})
        self.assertEqual(facts["T3"], {"implemented": False, "node_valid": False, "blocked": True})
        self.assertEqual(plan.states(), {"T1": "IMPLEMENTED", "T2": "READY", "T3": "BLOCKED"})
        self.assertEqual(workflow.node_state(plan, plan.events, plan.nodes[0])["state"],
                         workflow.NODE_STATE_INVALID)

        message = self.cli("slice", "t4a", "T3", expected=1)["error"]
        self.assertIn("N1 未验收", message)          # 节点 ID ＋ 状态
        self.assertIn("跨节点依赖", message)

        shown = self.cli("next", "t4a")
        self.assertNotIn("T3", [item["id"] for item in shown["ready"]])
        self.assertEqual(shown["unaccepted_nodes"], ["N1"])
        self.assertEqual(shown["review_debt"], {"tasks": ["T1"], "unopened": ["N1"]})
        next_text = self.cli_text("next", "t4a")
        self.assertIn("未验收节点", next_text)
        self.assertIn("审查债务", next_text)

        status = self.cli("status", "t4a")
        self.assertEqual(status["unaccepted_nodes"], ["N1"])
        self.assertEqual(status["review_debt"], {"tasks": ["T1"], "unopened": ["N1"]})
        status_text = self.cli_text("status", "t4a")
        self.assertIn("未验收节点", status_text)
        self.assertIn("审查债务", status_text)
        self.assertIn("已实现待审查：T1", status_text)

        # 派发片段也带节点状态（控制器核对用）
        self.assertIn("审查节点状态", self.cli("slice", "t4a", "T2")["brief"])

        self.record_v4("T2", slug="t4a", operation_id="rec-t2")
        span = self.commit_range()
        self.review_v4("N1", slug="t4a", commits=span, operation_id="rv-N1-1")
        self.cli("slice", "t4a", "T3")               # 上游验收后跨节点放行
        self.assertIn("T3", [item["id"] for item in self.cli("next", "t4a")["ready"]])
        self.assertEqual(self.cli("status", "t4a")["unaccepted_nodes"], [])
        self.assertEqual(self.cli("status", "t4a")["review_debt"], {"tasks": [], "unopened": []})

    def test_four_declared_only_edge_blocks_without_task_dependency(self):
        """仅声明节点依赖（无任务级依赖）同样拦：等待图一张，声明即约束（D-21）。"""
        nodes = (self.node_block("N1", "T1")
                 + self.node_block("N2", "T2", deps="N1", final="是"))
        self.make_v4_plan(slug="t4b", nodes=nodes,
                          tasks=self.v4_tasks((("T1", "无"), ("T2", "无"))))
        self.approve_v4("t4b")
        plan = workflow.load_plan(str(self.root), "t4b")
        self.assertEqual(workflow.wait_graph(plan), {"N1": set(), "N2": {"N1"}})
        self.record_v4("T1", slug="t4b", operation_id="rec-t1")
        plan = workflow.load_plan(str(self.root), "t4b")
        self.assertTrue(workflow.task_states(plan)["T2"]["blocked"])
        message = self.cli("slice", "t4b", "T2", expected=1)["error"]
        self.assertIn("N1 未验收", message)
        span = self.commit_range()
        self.review_v4("N1", slug="t4b", commits=span, operation_id="rv-N1-1",
                       lines=self.review_lines(("T1", "依据 record 证据，符合规格")))
        self.cli("slice", "t4b", "T2")
        self.assertFalse(workflow.task_states(
            workflow.load_plan(str(self.root), "t4b"))["T2"]["blocked"])

    def test_four_inner_dependency_chain_dispatches_before_review(self):
        """组内依赖按「已实现」放行：节点能凑齐送审条件（不被跨节点规则自锁）。"""
        nodes = (self.node_block("N1", "T1, T2")
                 + self.node_block("N2", "T3", deps="N1", final="是"))
        self.make_v4_plan(slug="t4c", nodes=nodes,
                          tasks=self.v4_tasks((("T1", "无"), ("T2", "T1"), ("T3", "无"))))
        self.approve_v4("t4c")
        message = self.cli("slice", "t4c", "T2", expected=1)["error"]
        self.assertIn("组内上游 T1 尚未实现", message)
        self.record_v4("T1", slug="t4c", operation_id="rec-t1")
        self.cli("slice", "t4c", "T2")               # 不等 N1 审查通过
        self.record_v4("T2", slug="t4c", operation_id="rec-t2")
        plan = workflow.load_plan(str(self.root), "t4c")
        self.assertFalse(workflow.node_valid_state(plan, plan.events, plan.nodes[0]))
        span = self.commit_range()
        result = self.review_v4("N1", slug="t4c", commits=span, operation_id="rv-N1-1")
        self.assertEqual(result["mapped_status"], workflow.STATUS_COMPLETE)
        self.assertEqual([task.status for task in workflow.load_plan(str(self.root), "t4c").tasks],
                         ["complete", "complete", "pending"])
        self.cli("slice", "t4c", "T3")               # 上游节点验收后放行
        self.assertIn("T3", [item["id"] for item in self.cli("next", "t4c")["ready"]])

    def test_four_batch_requires_same_node_and_same_node_batch_passes(self):
        """合并派发是「一次审查」的粒度：跨节点批次拒绝，同节点批次放行。"""
        nodes = (self.node_block("N1", "T1, T2")
                 + self.node_block("N2", "T3, T4", deps="N1", final="是"))
        self.make_v4_plan(slug="t4d", nodes=nodes,
                          tasks=self.v4_tasks((("T1", "无"), ("T2", "无"),
                                               ("T3", "无"), ("T4", "无"))))
        self.approve_v4("t4d")
        message = self.cli("slice", "t4d", "T1", "T3", expected=1)["error"]
        self.assertIn("同属一个节点", message)
        self.assertIn("N2", message)
        result = self.cli("slice", "t4d", "T1", "T2")
        self.assertTrue(result["batch"])
        self.assertEqual(result["tasks"], ["T1", "T2"])
        # 三态语义的旧守卫仍在：已验收（complete）不得再次入批
        self.record_v4("T1", "T2", slug="t4d", operation_id="rec-batch")
        span = self.commit_range()
        self.review_v4("N1", slug="t4d", commits=span, operation_id="rv-N1-1")
        message = self.cli("record", "t4d", "T1", "T2", "--commits", span,
                           "--evidence", "证据", "--operation-id", "rec-batch-2",
                           expected=1)["error"]
        self.assertIn("已完成，不能再次纳入批次", message)

    def test_four_review_debt_lists_follow_pass_and_fail(self):
        """审查债务：已实现待审查任务 ＋ 尚未开启审查的节点；fail 后仍无 pass 记录即仍在债上。"""
        self.node_review_plan(slug="t4e")
        self.record_v4("T1", slug="t4e", operation_id="rec-t1")
        self.record_v4("T2", slug="t4e", operation_id="rec-t2")
        self.assertEqual(self.cli("next", "t4e")["review_debt"],
                         {"tasks": ["T1", "T2"], "unopened": ["N1"]})
        self.assertEqual(self.cli("status", "t4e")["review_debt"],
                         {"tasks": ["T1", "T2"], "unopened": ["N1"]})
        self.review_v4("N1", slug="t4e", verdict="fail", commits="HEAD..HEAD",
                       operation_id="rv-N1-1")
        debt = self.cli("next", "t4e")["review_debt"]
        self.assertEqual(debt, {"tasks": ["T1", "T2"], "unopened": []})   # 已开启审查、仍无 pass
        self.assertEqual(self.cli("status", "t4e")["unaccepted_nodes"], ["N1"])
        self.assertIn("已实现待审查：T1、T2", self.cli_text("status", "t4e"))

    def test_four_close_and_verify_gate_on_unaccepted_nodes(self):
        """close/verify 就绪门：未验收节点拒绝（列出节点与状态），节点通过后放行。"""
        tasks = self.v4_tasks((("T1", "无"), ("T2", "无")))
        self.make_v4_plan(slug="t4f", nodes=self.node_block("N1", "T1, T2", final="是"),
                          tasks=tasks)
        self.approve_v4("t4f")
        self.record_v4("T1", slug="t4f", operation_id="rec-t1")
        self.record_v4("T2", slug="t4f", operation_id="rec-t2")
        for command in ("close", "verify"):
            with self.subTest(entry=command):
                message = self.cli(command, "t4f", expected=1)["error"]
                self.assertIn("未验收", message)
                self.assertIn("N1", message)
                self.assertIn("已实现成员：T1、T2", message)
        span = self.commit_range()
        self.review_v4("N1", slug="t4f", commits=span, operation_id="rv-N1-1")
        result = self.cli("verify", "t4f")
        self.assertTrue(result["passed"], result["blockers"])
        self.assertTrue(self.cli("close", "t4f")["closed"])

    def test_four_three_states_never_roll_back_implemented(self):
        """三态分别计算：节点结论无效/依赖阻塞都不回退已实现的任务状态行（D-09）。"""
        self.node_review_plan(slug="t4g")
        self.record_v4("T1", slug="t4g", operation_id="rec-t1")
        self.record_v4("T2", slug="t4g", operation_id="rec-t2")
        self.review_v4("N1", slug="t4g", verdict="fail", commits="HEAD..HEAD",
                       operation_id="rv-N1-1")
        plan = workflow.load_plan(str(self.root), "t4g")
        facts = workflow.task_states(plan)
        self.assertTrue(facts["T1"]["implemented"] and facts["T2"]["implemented"])
        self.assertFalse(facts["T1"]["node_valid"])
        self.assertTrue(facts["T3"]["blocked"])
        self.assertEqual(plan.states(),
                         {"T1": "IMPLEMENTED", "T2": "IMPLEMENTED", "T3": "BLOCKED"})
        self.assertEqual(workflow.derived_states(plan, plan.events),
                         {"T1": "implemented", "T2": "implemented", "T3": "pending"})
        before = self.plan("t4g").read_text()
        self.cli("slice", "t4g", "T3", expected=1)
        self.cli("next", "t4g")
        self.cli("status", "t4g")
        self.assertEqual(self.plan("t4g").read_text(), before)   # 展示/拒绝路径零改写

    def test_four_legacy_format3_entrypoints_unchanged(self):
        """格式 ≤3：三态门、批量同节点守卫与债务清单都不生效，旧行为逐字保留。"""
        fields = ("- **文件**：source.py\n- **并行**：否\n- **做法**：fixture 做法\n"
                  "- **接口**：无\n- **预期**：fixture 预期\n- **验收**：结果正确\n"
                  "- **失败信号**：结果错误\n- **决策**：D-01\n")
        self.plan("probe").write_text(
            "**Goal**: fixture\n**格式**: 3\n"
            "**设计文档**: 无 — 独立临时回归测试不需要单独设计文档\n"
            "## 方案\n### 背景与目标\nfixture scheme\n## 验证命令\n```sh\ntrue\n```\n"
            "## 决策\n| ID | 决策 | 来源 | 理由 |\n|---|---|---|---|\n"
            "| D-01 | fixture decision | 用户 | fixture rationale |\n"
            "## 验证覆盖\n| 对象 | 验证手段 | 类型 | 必需性 | 证据 |\n|---|---|---|---|---|\n"
            "| A1 | `source.py::test_example` | 自动化 | 必需 | |\n"
            "| D-01 | `source.py::test_example` | 自动化 | 必需 | |\n"
            "### 不验证的部分\n- 无\n"
            "## 阶段\n### Phase 1: fixture\n"
            "#### T1 fixture\n- **依赖**：无\n" + fields + "- **状态**：complete\n"
            "#### T2 fixture\n- **依赖**：无\n" + fields + "- **状态**：complete\n")
        self.cli("approve", "probe", "方案", "--by", "fixture 方案确认")
        self.cli("approve", "probe", "计划", "--by", "fixture 计划确认")
        # 单个已完成任务仍可再派发（旧路径没有就绪门）
        result = self.cli("slice", "probe", "T2")
        self.assertNotIn("node_states", result)
        self.assertNotIn("审查节点状态", result["brief"])
        message = self.cli("slice", "probe", "T1", "T2", expected=1)["error"]
        self.assertEqual(message, "T1 已完成，不能再次纳入批次。")
        self.assertNotIn("unaccepted_nodes", self.cli("status", "probe"))
        self.assertNotIn("awaiting_review", self.cli("next", "probe"))
        self.assertNotIn("审查债务", self.cli_text("status", "probe"))
        self.assertEqual(workflow.task_states(workflow.load_plan(str(self.root), "probe")), {})

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


    # ------------------------------------------------ 失效、前提与去重（T5）

    def t5_plan(self, slug="t5", nodes=None, tasks=None):
        """N1（T1、T2）＋ N2（T3，依赖 N1，兼任终审）：跨节点下游当放行观察位。"""
        if nodes is None:
            nodes = (self.node_block("N1", "T1, T2")
                     + self.node_block("N2", "T3", deps="N1", final="是"))
        if tasks is None:
            tasks = self.v4_tasks((("T1", "无"), ("T2", "无"), ("T3", "T1")))
        self.make_v4_plan(slug=slug, nodes=nodes, tasks=tasks)
        self.approve_v4(slug)

    def write_file(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def commit_files(self, message, *paths):
        for path in paths:
            self.git("add", path)
        self.git("-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", message)
        return self.git("rev-parse", "--short", "HEAD")

    def t5_review_n1(self, slug="t5", operation_id="rv-N1-1", **extra):
        """造一个真实提交当已审范围；record T1/T2 后 review N1（默认 pass）。"""
        base = self.git("rev-parse", "--short", "HEAD")
        self.write_file("source.py", "def test_example():\n    return False\n")
        head = self.commit_files("T1/T2: 实现改动", "source.py")
        self.record_v4("T1", slug=slug, operation_id="rec-%s-1" % slug)
        self.record_v4("T2", slug=slug, operation_id="rec-%s-2" % slug)
        return self.review_v4("N1", slug=slug, commits="%s..%s" % (base, head),
                              operation_id=operation_id, **extra)

    def impact_v4(self, slug, node="N1", verdict="irrelevant", basis="fixture 依据",
                  expect_review="rv-N1-1", expect_changes="", operation_id="imp-1",
                  expected=0):
        return self.cli("impact", slug, node, "--verdict", verdict, "--basis", basis,
                        "--expect-review", expect_review, "--expect-changes", expect_changes,
                        "--operation-id", operation_id, expected=expected)

    def invalidated_events(self, slug="t5"):
        return [event for event in self.events(slug) if event["type"] == "node_invalidated"]

    def impact_events(self, slug="t5"):
        return [event for event in self.events(slug) if event["type"] == "impact_assessed"]

    def pending_of(self, slug, node="N1"):
        return self.cli("status", slug)["pending_changes"].get(node)

    def test_five_self_change_invalidates_then_recheck_restores(self):
        """已审范围上出新提交 → 待重新确认、跨节点下游被拒；`--recheck` 通过 → 恢复。"""
        self.t5_plan(slug="t5a")
        first = self.t5_review_n1(slug="t5a")
        self.cli("slice", "t5a", "T3")                 # 上游验收后跨节点放行
        self.write_file("source.py", "def test_example():\n    return 'changed'\n")
        self.commit_files("T1: 又改一处", "source.py")
        message = self.cli("slice", "t5a", "T3", expected=1)["error"]
        self.assertIn("N1 待重新确认", message)
        self.assertIn("已审范围", message)              # 原因随状态给出
        self.assertIn("跨节点依赖", message)
        status = self.cli("status", "t5a")
        self.assertEqual(status["node_states"]["N1"], workflow.NODE_STATE_RECHECK)
        self.assertIn("N1", status["unaccepted_nodes"])
        self.assertIn("待重新确认", self.cli_text("status", "t5a"))
        # 调度入口把失效观察落盘（审计痕迹；展示入口只派生、不写事件）
        records = self.invalidated_events("t5a")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["data"]["原因"], workflow.INVALIDATION_SELF)
        self.assertEqual(records[0]["data"]["谱系"], first["lineage"])
        self.assertEqual(records[0]["data"]["所否定结论"], "rv-N1-1")
        self.assertTrue(any(item["path"] == "source.py"
                            for item in records[0]["data"]["触发证据"]))
        # 同范围没有新提交时不再重复写失效记录（幂等）
        self.cli("slice", "t5a", "T3", expected=1)
        self.assertEqual(len(self.invalidated_events("t5a")), 1)
        # 定向复核通过 → 回到有效（新记录为准，阶段与轮次不变）
        second = self.review_v4("N1", slug="t5a", operation_id="rv-N1-2",
                                recheck="rv-N1-1")
        self.assertEqual(second["phase"], 1)
        self.assertEqual(second["rounds"], 1)
        self.assertEqual(second["recheck_of"], "rv-N1-1")
        self.assertEqual(len(self.node_review_events("t5a")), 2)
        self.assertEqual(self.cli("status", "t5a")["node_states"]["N1"],
                         workflow.NODE_STATE_VALID)
        self.cli("slice", "t5a", "T3")

    def test_five_pass_fail_pass_regression_blocks_until_recheck(self):
        """pass → fail（不放行）→ recheck pass 恢复：不回看更早的 pass。"""
        self.t5_plan(slug="t5f2")
        self.t5_review_n1(slug="t5f2")
        self.cli("slice", "t5f2", "T3")
        self.review_v4("N1", slug="t5f2", verdict="fail", operation_id="rv-N1-2",
                       lines=self.review_lines(("T1", "缺边界用例"), ("T2", "同 T1")))
        message = self.cli("slice", "t5f2", "T3", expected=1)["error"]
        self.assertIn("N1 未验收", message)
        self.assertEqual(self.cli("status", "t5f2")["node_states"]["N1"],
                         workflow.NODE_STATE_INVALID)
        # fail 的失效记录拦阻：即便早先有 pass 也不放行；复核 pass 才恢复
        self.review_v4("N1", slug="t5f2", operation_id="rv-N1-3", recheck="rv-N1-1")
        self.assertEqual(self.cli("status", "t5f2")["node_states"]["N1"],
                         workflow.NODE_STATE_VALID)
        self.cli("slice", "t5f2", "T3")
        self.assertEqual([task.status for task in
                          workflow.load_plan(str(self.root), "t5f2").tasks],
                         ["complete", "complete", "pending"])

    def test_five_worktree_change_without_commit_invalidates(self):
        """不新增提交、只改已审接口（工作树变化）→ 待重新确认、依赖节点派发被拒。"""
        self.t5_plan(slug="t5w")
        self.t5_review_n1(slug="t5w")
        self.cli("slice", "t5w", "T3")
        self.write_file("source.py", "def test_example():\n    return 'worktree'\n")
        message = self.cli("slice", "t5w", "T3", expected=1)["error"]
        self.assertIn("N1 待重新确认", message)
        self.assertIn("工作树变化", message)
        records = self.invalidated_events("t5w")
        self.assertEqual(records[-1]["data"]["原因"], workflow.INVALIDATION_SELF)
        self.assertIn("source.py", [item["path"] for item in records[-1]["data"]["触发证据"]])

    def test_five_out_of_scope_change_pauses_until_judged_and_reuses_across_commit(self):
        """范围外变化（提交与工作树同一口径）：先暂停放行，判「无关」后按内容复用。"""
        self.t5_plan(slug="t5c")
        self.t5_review_n1(slug="t5c")
        self.cli("slice", "t5c", "T3")
        # 范围外的新文件（未提交）→ 暂停放行，展示 impact 的预期值
        self.write_file("notes.txt", "note-1\n")
        status = self.cli("status", "t5c")
        self.assertEqual(status["node_states"]["N1"], workflow.NODE_STATE_PAUSED)
        self.assertIn("N1", status["unaccepted_nodes"])
        pending = self.pending_of("t5c")
        self.assertEqual(pending["review"], "rv-N1-1")
        self.assertEqual([item["path"] for item in pending["changes"]], ["notes.txt"])
        digest = pending["digest"]
        self.assertRegex(digest, r"^[a-f0-9]{16}$")
        shown = self.cli_text("status", "t5c")
        self.assertIn("待影响判断", shown)
        self.assertIn("notes.txt", shown)
        self.assertIn(digest, shown)              # 逐项 path＋内容摘要＋变化集摘要
        message = self.cli("slice", "t5c", "T3", expected=1)["error"]
        self.assertIn("暂停放行", message)
        self.assertIn("notes.txt", message)
        message = self.cli("verify", "t5c", expected=1)["error"]
        self.assertIn("暂停放行", message)
        self.assertIn("impact", message)
        # 同一内容提交 → 摘要不变：判定可复用（不以未提交豁免）
        self.commit_files("chore: notes", "notes.txt")
        self.assertEqual(self.pending_of("t5c")["digest"], digest)
        hmm = self.impact_v4("t5c", expect_changes=digest, expected=0)
        self.assertEqual(hmm["state_after"], workflow.NODE_STATE_VALID)
        self.assertIsNone(hmm["invalidated"])
        self.assertEqual(hmm["changes"], [{"path": "notes.txt", "摘要": pending["changes"][0]["摘要"]}])
        self.cli("slice", "t5c", "T3")
        # 范围外提交判「无关」不触发 node_invalidated；同 ID 重试返回原结果、不重新绑定
        self.assertEqual(self.invalidated_events("t5c"), [])
        replay = self.impact_v4("t5c", expect_changes=digest)
        self.assert_replay_matches(replay, hmm)
        self.assertEqual(len(self.impact_events("t5c")), 1)
        self.assertEqual(self.cli("status", "t5c")["node_states"]["N1"],
                         workflow.NODE_STATE_VALID)
        # 重启（重放事件重算）后相同绑定直接复用，不重复阻塞
        self.assertEqual(len([event for event in self.events("t5c")
                              if event["type"] == "impact_assessed"]), 1)

    def test_five_same_path_content_change_expires_binding(self):
        """同路径内容变化使绑定过期；观察 H1 后内容变 H2 再提交针对 H1 的判断必被拒。"""
        self.t5_plan(slug="t5d")
        self.t5_review_n1(slug="t5d")
        self.write_file("conf.py", "SWITCH = 0  # 仅注释\n")
        first = self.pending_of("t5d")
        self.impact_v4("t5d", basis="只加了注释，不影响任何结论", expect_changes=first["digest"])
        self.assertEqual(self.cli("status", "t5d")["node_states"]["N1"],
                         workflow.NODE_STATE_VALID)
        # 同路径内容变化（开关真改了）→ 旧判定失效、重新阻塞
        self.write_file("conf.py", "SWITCH = 1  # 改开关\n")
        status = self.cli("status", "t5d")
        self.assertEqual(status["node_states"]["N1"], workflow.NODE_STATE_PAUSED)
        second = self.pending_of("t5d")
        self.assertNotEqual(second["digest"], first["digest"])
        self.assertEqual(second["changes"][0]["path"], "conf.py")
        # 针对旧快照 H1 的判断 → 被拒、返回新快照、保持阻塞
        message = self.impact_v4("t5d", basis="按旧快照", expect_changes=first["digest"],
                                 operation_id="imp-2", expected=1)["error"]
        self.assertIn("不符", message)
        self.assertIn(second["digest"], message)
        self.assertIn("conf.py", message)
        self.assertEqual(self.cli("status", "t5d")["node_states"]["N1"],
                         workflow.NODE_STATE_PAUSED)
        self.assertEqual(len(self.impact_events("t5d")), 1)   # 被拒的提交没有写入任何事件
        # 按新快照判「相关」→ 转待重新确认（写 node_invalidated，原因 impact:related）
        result = self.impact_v4("t5d", verdict="related", basis="开关默认值被改，结论需重判",
                                expect_changes=second["digest"], operation_id="imp-3")
        self.assertEqual(result["state_after"], workflow.NODE_STATE_RECHECK)
        self.assertIsNotNone(result["invalidated"])
        self.assertEqual(self.invalidated_events("t5d")[-1]["data"]["原因"],
                         workflow.INVALIDATION_IMPACT["related"])
        message = self.cli("slice", "t5d", "T3", expected=1)["error"]
        self.assertIn("待重新确认", message)

    def test_five_record_change_after_conclusion_makes_it_stale(self):
        """审查记录更替后旧绑定过期；未知节点、无待判断变化与缺操作 ID 都被拒。"""
        self.t5_plan(slug="t5n")
        self.t5_review_n1(slug="t5n")
        # 无待判断变化时 impact 被拒（「无关」不是常规推进步骤）
        message = self.impact_v4("t5n", expect_changes="x", expected=1)["error"]
        self.assertIn("没有待判断的范围外变化", message)
        self.assertEqual(self.impact_events("t5n"), [])
        # 缺 --operation-id 被拒（impact 与 --recheck 同一协议）
        args = ["impact", "t5n", "N1", "--verdict", "irrelevant", "--basis", "b",
                "--expect-review", "rv-N1-1", "--expect-changes", "x"]
        self.assertIn("--operation-id", self.cli(*args, expected=1)["error"])
        self.assertIn("--operation-id",
                      self.review_v4("N1", slug="t5n", recheck="rv-N1-1", operation_id="",
                                     expected=1)["error"])
        message = self.cli("impact", "t5n", "N9", "--verdict", "irrelevant", "--basis", "b",
                           "--expect-review", "x", "--expect-changes", "y",
                           "--operation-id", "imp-9", expected=1)["error"]
        self.assertIn("没有审查节点 N9", message)
        # 范围外变化出现 → 暂停；随后审查记录更替（新 pass 记录）→ 旧预期值失效
        self.write_file("notes.txt", "h1\n")
        stale = self.pending_of("t5n")
        self.review_v4("N1", slug="t5n", operation_id="rv-N1-2")
        message = self.impact_v4("t5n", expect_review="rv-N1-1",
                                 expect_changes=stale["digest"], operation_id="imp-1",
                                 expected=1)["error"]
        self.assertIn("--expect-review", message)
        self.assertIn("rv-N1-2", message)      # 返回新快照（新结论操作 ID）
        self.assertEqual(self.cli("status", "t5n")["node_states"]["N1"],
                         workflow.NODE_STATE_PAUSED)

    def test_five_premises_recorded_and_change_requires_recheck(self):
        """前提清单随结论保存；前提被触及（提交或工作树）→ 待重新确认；recheck 后新记录保留。"""
        self.t5_plan(slug="t5p")
        self.write_file("conf/app.toml", "SWITCH = 0\n")
        self.write_file("lib/shared.py", "def shared():\n    return 1\n")
        base = self.git("rev-parse", "--short", "HEAD")
        self.write_file("source.py", "def test_example():\n    return False\n")
        head = self.commit_files("T1/T2: 实现", "source.py")
        self.record_v4("T1", slug="t5p", operation_id="rec-t5p-1")
        self.record_v4("T2", slug="t5p", operation_id="rec-t5p-2")
        result = self.review_v4("N1", slug="t5p", commits="%s..%s" % (base, head),
                                operation_id="rv-N1-1",
                                premises="配置: conf/app.toml; 共享实现: lib/shared.py")
        entries = result["premises"]
        self.assertEqual([entry["类型"] for entry in entries], ["配置", "共享实现"])
        self.assertEqual(entries[0]["引用"], ["conf/app.toml"])
        self.assertRegex(entries[0]["摘要"], r"^[a-f0-9]{16}$")
        self.assertEqual(entries[0]["基线提交"], self.git("rev-parse", "HEAD"))
        self.assertEqual(self.node_review_events("t5p")[0]["data"]["premises"], entries)
        # 声明前提本身不暂停：未动过的前提不触发失效
        self.assertEqual(self.pending_of("t5p"), None)
        self.assertEqual(self.cli("status", "t5p")["node_states"]["N1"],
                         workflow.NODE_STATE_VALID)
        self.cli("slice", "t5p", "T3")
        # 前提（配置）在未提交的工作树上被改 → 待重新确认、下游被拒
        self.write_file("conf/app.toml", "SWITCH = 1\n")
        message = self.cli("slice", "t5p", "T3", expected=1)["error"]
        self.assertIn("N1 待重新确认", message)
        self.assertIn("前提", message)
        records = self.invalidated_events("t5p")
        self.assertEqual(records[-1]["data"]["原因"], workflow.INVALIDATION_PREMISE)
        self.assertIn("conf/app.toml",
                      [item["path"] for item in records[-1]["data"]["触发证据"]])
        # 前提变化后 recheck 通过 → 生成新记录（旧记录保留）、轮次沿谱系 +1
        self.commit_files("conf: 开关改到 1", "conf/app.toml")
        second = self.review_v4("N1", slug="t5p", operation_id="rv-N1-2", recheck="rv-N1-1",
                                premises="配置: conf/app.toml; 共享实现: lib/shared.py")
        self.assertEqual(second["rounds"], 1)
        records = self.node_review_events("t5p")
        self.assertEqual([event["data"]["operation_id"] for event in records],
                         ["rv-N1-1", "rv-N1-2"])
        self.assertEqual(records[1]["data"]["recheck_of"], "rv-N1-1")
        self.assertEqual(self.cli("status", "t5p")["node_states"]["N1"],
                         workflow.NODE_STATE_VALID)
        self.cli("slice", "t5p", "T3")

    def test_five_premises_shape_rejected_on_bad_input(self):
        """前提清单校验：路径不存在、类型不支持、写法不是 `<类型>: <引用>` 都直接拒绝。"""
        self.t5_plan(slug="t5q")
        self.record_v4("T1", slug="t5q", operation_id="rec-t5q-1")
        self.record_v4("T2", slug="t5q", operation_id="rec-t5q-2")
        cases = [
            ("契约锚点: missing.txt", "路径不存在"),
            ("契约锚点", "不是 `<类型>: <路径"),
            ("未知类型: source.py", "不支持"),
            ("契约锚点: ", "没有列出引用路径"),
        ]
        for raw, needle in cases:
            with self.subTest(premises=raw):
                message = self.review_v4("N1", slug="t5q", premises=raw, expected=1)["error"]
                self.assertIn(needle, message)
                self.assertIn("--premises", message)
        self.assertEqual(self.node_review_events("t5q"), [])
        # 目录递归展开成文件列表（按相对路径排序）——条目即引用集合，摘要覆盖全部文件
        self.write_file("conf/b.toml", "B = 1\n")
        self.write_file("conf/a.toml", "A = 1\n")
        result = self.review_v4("N1", slug="t5q", operation_id="rv-N1-1",
                                premises="配置: conf")
        self.assertEqual(result["premises"][0]["引用"], ["conf/a.toml", "conf/b.toml"])
        digest = result["premises"][0]["摘要"]
        self.assertEqual(workflow.change_set_digest([
            ("conf/a.toml", workflow._file_content_digest(str(self.root), "conf/a.toml")),
            ("conf/b.toml", workflow._file_content_digest(str(self.root), "conf/b.toml")),
        ]), digest)

    def test_five_declared_requirement_change_stales_without_commit(self):
        """只改某任务验收要求（节点块与代码不变）并重批计划 → 该节点转待重新确认。"""
        self.t5_plan(slug="t5r")
        self.t5_review_n1(slug="t5r")
        self.cli("slice", "t5r", "T3")
        before = workflow.load_plan(str(self.root), "t5r")
        version = workflow.node_version(before, before.nodes[0])
        self.plan("t5r").write_text(self.plan("t5r").read_text()
                                    .replace("- **验收**：结果正确",
                                             "- **验收**：结果正确，且空输入也要有明确行为", 1))
        self.cli("approve", "t5r", "计划", "--by", "fixture 重新确认新验收要求")
        message = self.cli("slice", "t5r", "T3", expected=1)["error"]
        self.assertIn("N1 待重新确认", message)
        self.assertIn("节点版本", message)
        after = workflow.load_plan(str(self.root), "t5r")
        self.assertNotEqual(workflow.node_version(after, after.nodes[0]), version)
        self.assertEqual(self.cli("status", "t5r")["node_states"]["N1"],
                         workflow.NODE_STATE_RECHECK)

    def test_five_split_children_inherit_lineage_and_keep_rounds(self):
        """拆分（前身来自历史记录）：子节点各自继承同一谱系根，轮次沿根累计不重置。"""
        tasks = self.v4_tasks((("T1", "无"), ("T2", "无")))
        self.make_v4_plan(slug="t5s", nodes=self.node_block("N1", "T1, T2", final="是"),
                          tasks=tasks)
        self.approve_v4("t5s")
        base = self.git("rev-parse", "--short", "HEAD")
        self.write_file("source.py", "def test_example():\n    return False\n")
        head = self.commit_files("T1/T2: 实现", "source.py")
        self.record_v4("T1", slug="t5s", operation_id="rec-t5s-1")
        self.record_v4("T2", slug="t5s", operation_id="rec-t5s-2")
        first = self.review_v4("N1", slug="t5s", commits="%s..%s" % (base, head),
                               operation_id="rv-N1-1")
        # 拆分：N1 从计划里移除，N3（T1）与 N4（T2）各自以 N1 为唯一前身
        nodes = (self.node_block("N3", "T1", pred="N1")
                 + self.node_block("N4", "T2", pred="N1", final="是"))
        self.make_v4_plan(slug="t5s", nodes=nodes, tasks=tasks)
        self.approve_v4("t5s")
        self.assertEqual(self.cli("check", "t5s")["errors"], [])   # 合法拆分（前身来自历史记录）
        # 继承同一谱系根；旧结论版本与子节点不符 → 待重新确认（不依赖提交）
        self.assertEqual(self.cli("status", "t5s")["node_states"]["N3"],
                         workflow.NODE_STATE_RECHECK)
        second = self.review_v4("N3", slug="t5s", operation_id="rv-N3-1",
                                lines=self.review_lines(("T1", "拆分后仅覆盖 T1，依据同前")))
        self.assertEqual(second["lineage"], first["lineage"])
        self.assertEqual(second["rounds"], 1)                      # 轮次沿谱系根累计
        self.assertEqual(second["phase"], 1)
        third = self.review_v4("N4", slug="t5s", operation_id="rv-N4-1",
                               lines=self.review_lines(("T2", "拆分后仅覆盖 T2，依据同前")))
        self.assertEqual(third["lineage"], first["lineage"])       # 共享前身 → 同一根
        self.assertEqual(workflow.round_count(self.events("t5s"), first["lineage"]), 2)
        self.assertEqual(self.cli("status", "t5s")["node_states"]["N4"],
                         workflow.NODE_STATE_VALID)

    def test_five_undecidable_and_impact_binding_persisted(self):
        """判「无关」的依据与绑定随事件持久化；判「判不出」→ 转待重新确认。"""
        self.t5_plan(slug="t5u")
        self.t5_review_n1(slug="t5u")
        self.write_file("notes.txt", "h1\n")
        pending = self.pending_of("t5u")
        result = self.impact_v4("t5u", basis="看不出与任何交付物的关系",
                                expect_changes=pending["digest"])
        self.assertEqual(result["verdict"], "irrelevant")
        data = self.impact_events("t5u")[0]["data"]
        self.assertEqual(data["basis"], "看不出与任何交付物的关系")
        self.assertEqual(data["审查记录"], "rv-N1-1")
        self.assertEqual(data["变化集摘要"], pending["digest"])
        self.assertEqual(data["变化集"],
                         [{"path": "notes.txt", "摘要": pending["changes"][0]["摘要"]}])
        self.assertEqual(data["节点版本"], result["node_version"])
        self.assertEqual(data["审查阶段"], 1)
        self.assertEqual(self.cli("status", "t5u")["node_states"]["N1"],
                         workflow.NODE_STATE_VALID)
        # 同 ID ＋ 不同请求 → 拒绝（同一操作身份不得承担两次不同判断）
        message = self.impact_v4("t5u", basis="换了依据", expect_changes=pending["digest"],
                                 operation_id="imp-1", expected=1)["error"]
        self.assertIn("已用于另一次操作", message)
        self.assertEqual(len(self.impact_events("t5u")), 1)
        # 同一路径内容再变 → 旧判定不适用（重新暂停）；判「判不出」→ 转待重新确认
        self.write_file("notes.txt", "h2\n")
        second = self.pending_of("t5u")
        self.assertNotEqual(second["digest"], pending["digest"])
        result = self.impact_v4("t5u", verdict="undecidable", basis="影响面无法判定",
                                expect_changes=second["digest"], operation_id="imp-2")
        self.assertEqual(result["state_after"], workflow.NODE_STATE_RECHECK)
        self.assertEqual(self.invalidated_events("t5u")[-1]["data"]["原因"],
                         workflow.INVALIDATION_IMPACT["undecidable"])
        message = self.cli("slice", "t5u", "T3", expected=1)["error"]
        self.assertIn("待重新确认", message)

    def test_five_recheck_never_deduped_and_interrupt_replays(self):
        """同范围同结论的两次复核都保存；事件落盘后中断 → 携原 ID 重试恢复投影与原结果。"""
        self.t5_plan(slug="t5o")
        self.t5_review_n1(slug="t5o")
        # `--recheck` 指向不存在的操作 / 非审查记录 → 拒绝
        message = self.review_v4("N1", slug="t5o", recheck="rv-nope",
                                 operation_id="rv-N1-2", expected=1)["error"]
        self.assertIn("不存在", message)
        message = self.review_v4("N1", slug="t5o", recheck="rec-t5o-1",
                                 operation_id="rv-N1-2", expected=1)["error"]
        self.assertIn("不是节点审查记录", message)
        # 不同操作 ID 永不去重：同一范围与结论的复核各存一条（轮次照常累计）
        second = self.review_v4("N1", slug="t5o", recheck="rv-N1-1", operation_id="rv-N1-2")
        third_text = self.review_v4("N1", slug="t5o", recheck="rv-N1-1",
                                    operation_id="rv-N1-3", text=True)
        self.assertEqual(len(self.node_review_events("t5o")), 3)
        self.assertEqual(len([event for event in self.node_review_events("t5o")
                              if event["data"].get("recheck_of") == "rv-N1-1"]), 2)
        self.assertEqual(workflow.round_count(self.events("t5o"), second["lineage"]), 2)
        # 事件落盘后返回前中断：状态未回写 → 携原 ID 重试：恢复投影、返回原结果、轮次与阶段不变
        self.rollback_complete("t5o")
        replay_text = self.review_v4("N1", slug="t5o", recheck="rv-N1-1",
                                     operation_id="rv-N1-3", text=True)
        self.assertTrue(replay_text.startswith(third_text), replay_text)
        self.assertIn("幂等重放", replay_text)
        self.assertEqual(len(self.node_review_events("t5o")), 3)
        self.assertEqual([task.status for task in
                          workflow.load_plan(str(self.root), "t5o").tasks],
                         ["complete", "complete", "pending"])
        repairs = self.repair_events("t5o")
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0]["data"]["entry"], "review")
        self.assertEqual(workflow.round_count(self.events("t5o"), second["lineage"]), 2)


    # ------------------------------------------------ 封顶恢复与受影响审批（T6）

    def t6_plan(self, slug="t6", nodes=None, tasks=None):
        """N1（T1、T2）＋ N2（T3，依赖 N1，兼任终审）：与 T5 同一跨节点观察位。"""
        self.t5_plan(slug=slug, nodes=nodes, tasks=tasks)

    def t6_capped(self, slug="t6"):
        """首审 ＋ 两轮复核 → 两轮修复预算用尽；返回首审结果（含谱系）。"""
        first = self.t5_review_n1(slug=slug, operation_id="rv-N1-1")
        self.review_v4("N1", slug=slug, operation_id="rv-N1-2", recheck="rv-N1-1")
        self.review_v4("N1", slug=slug, operation_id="rv-N1-3", recheck="rv-N1-1")
        return first

    def new_phase_v4(self, slug="t6", node="N1",
                     basis="根因分析：验证方法改为先建空输入夹具再跑主路径",
                     confirmation="rv-N1-3", confirmed_commit="HEAD..HEAD",
                     operation_id="np-N1-1", expected=0, text=False, **extra):
        args = ["review", slug, node, "--new-phase", "--basis", basis,
                "--confirmation", confirmation, "--confirmed-commit", confirmed_commit,
                "--operation-id", operation_id]
        for key, value in extra.items():
            args.extend(["--" + key.replace("_", "-"), value])
        return (self.cli_text(*args, expected=expected) if text
                else self.cli(*args, expected=expected))

    def phase_events(self, slug="t6"):
        return [event for event in self.events(slug) if event["type"] == "review_phase"]

    def test_six_round_cap_rejects_third_round(self):
        """两轮预算用尽后，第 3 轮普通 review（含 `--recheck`）被拒并给出暂停提示。"""
        self.t6_plan(slug="t6cap")
        first = self.t6_capped(slug="t6cap")
        self.assertEqual(workflow.round_count(self.events("t6cap"), first["lineage"], 1), 2)
        for extra in ({}, {"recheck": "rv-N1-1"}):
            with self.subTest(extra=extra):
                message = self.review_v4("N1", slug="t6cap", operation_id="rv-N1-4",
                                         expected=1, **extra)["error"]
                self.assertIn("暂停相关部分及其依赖，进入根因/方案分析", message)
                self.assertIn("两轮", message)
                self.assertIn("--new-phase", message)
        self.assertEqual(len(self.node_review_events("t6cap")), 3)
        self.assertEqual(self.phase_events("t6cap"), [])

    def test_six_new_phase_opens_resets_rounds_and_keeps_total(self):
        """合规 `--new-phase`：新阶段从首审级计轮、总账累计可见、成员回到未验收。"""
        self.t6_plan(slug="t6new")
        first = self.t6_capped(slug="t6new")
        lineage = first["lineage"]
        body = self.ledger_body("t6new")
        basis = "根因分析：验证方法改为先建空输入夹具再跑主路径；原问题 1–3 接续追踪"
        result = self.new_phase_v4(slug="t6new", basis=basis, confirmation="rv-N1-3",
                                   operation_id="np-N1-1")
        self.assertEqual(result["node"], "N1")
        self.assertEqual(result["lineage"], lineage)
        self.assertEqual(result["previous_phase"], 1)
        self.assertEqual(result["phase"], 2)
        self.assertEqual(result["rounds"], 0)                       # 新阶段从首审级
        self.assertEqual(result["total_rounds"], 2)                 # 总账保留
        self.assertEqual([item["rounds"] for item in result["ledger"]], [2, 0])

        events = self.events("t6new")
        self.assertEqual(workflow.round_count(events, lineage, 2), 0)
        self.assertEqual(workflow.round_count(events, lineage, 1), 2)
        records = self.phase_events("t6new")
        self.assertEqual(len(records), 1)
        data = records[0]["data"]
        self.assertEqual(data["节点"], "N1")
        self.assertEqual(data["谱系"], lineage)
        self.assertEqual((data["前阶段"], data["新阶段"]), (1, 2))
        self.assertEqual(data["basis"], basis)
        self.assertEqual(data["确认"], {"形态": "记录", "值": "rv-N1-3"})
        self.assertEqual(data["已确认版本"]["commits"], "HEAD..HEAD")
        self.assertEqual(data["已确认版本"]["head"], self.git("rev-parse", "HEAD"))
        self.assertEqual(data["operation_id"], "np-N1-1")
        self.assertEqual(data["entry"], "review --new-phase")
        self.assertEqual(data["receipt"]["result"]["phase"], 2)
        self.assertEqual(data["receipt"]["result"]["event"], records[0]["id"])
        self.assertEqual(self.ledger_body("t6new"), body)          # 不开账本行

        # 新阶段＝未验收：成员回到「已实现」（不退回待实现），下游不释放
        self.assertEqual([task.status for task in
                          workflow.load_plan(str(self.root), "t6new").tasks],
                         ["implemented", "implemented", "pending"])
        status = self.cli("status", "t6new")
        self.assertEqual(status["node_states"]["N1"], workflow.NODE_STATE_INVALID)
        self.assertIn("N1", status["unaccepted_nodes"])
        rounds = status["node_rounds"]["N1"]
        self.assertEqual(rounds["phase"], 2)
        self.assertEqual(rounds["rounds"], 0)
        self.assertEqual(rounds["total"], 2)
        self.assertEqual(rounds["phases"], [{"phase": 1, "rounds": 2}, {"phase": 2, "rounds": 0}])
        shown = self.cli_text("status", "t6new")
        self.assertIn("总账", shown)
        self.assertIn("合计 2 轮", shown)
        message = self.cli("slice", "t6new", "T3", expected=1)["error"]
        self.assertIn("N1 未验收", message)

        # 新阶段内重新送审：阶段 2、轮次从 0 计；pass 后成员重新映射 complete
        again = self.review_v4("N1", slug="t6new", operation_id="rv-N1-5")
        self.assertEqual(again["phase"], 2)
        self.assertEqual(again["rounds"], 0)
        self.assertEqual(self.node_review_events("t6new")[-1]["data"]["审查阶段"], 2)
        self.assertEqual(self.cli("status", "t6new")["node_states"]["N1"],
                         workflow.NODE_STATE_VALID)
        self.assertEqual(self.cli("status", "t6new")["node_rounds"]["N1"]["total"], 2)

    def test_six_new_phase_rejects_missing_stale_and_mixed_bindings(self):
        """缺确认/缺依据/缺操作 ID、引用不存在、白名单外类型、混用参数、版本不存在。"""
        self.t6_plan(slug="t6bad")
        self.t6_capped(slug="t6bad")
        message = self.new_phase_v4(slug="t6bad", confirmation="", operation_id="np-b1",
                                    expected=1)["error"]
        self.assertIn("--confirmation", message)
        message = self.new_phase_v4(slug="t6bad", basis="   ", operation_id="np-b2",
                                    expected=1)["error"]
        self.assertIn("--basis", message)
        args = ["review", "t6bad", "N1", "--new-phase", "--basis", "实质变化",
                "--confirmation", "rv-N1-3", "--confirmed-commit", "HEAD..HEAD"]
        self.assertIn("--operation-id", self.cli(*args, expected=1)["error"])
        message = self.new_phase_v4(slug="t6bad", confirmation="rv-nope",
                                    operation_id="np-b3", expected=1)["error"]
        self.assertIn("记录/操作 ID 引用不存在", message)
        message = self.new_phase_v4(slug="t6bad", confirmation="rec-t6bad-1",
                                    operation_id="np-b4", expected=1)["error"]
        self.assertIn("白名单", message)
        message = self.new_phase_v4(slug="t6bad", operation_id="np-b5", expected=1,
                                    verdict="pass")["error"]
        self.assertIn("互斥", message)
        message = self.review_v4("N1", slug="t6bad", operation_id="rv-N1-9", expected=1,
                                 basis="实质变化")["error"]
        self.assertIn("--new-phase", message)
        for bad in ("deadbeef..HEAD", "HEAD", "HEAD..deadbeef"):
            with self.subTest(confirmed_commit=bad):
                message = self.new_phase_v4(slug="t6bad", confirmation="rv-N1-3",
                                            confirmed_commit=bad, operation_id="np-b6",
                                            expected=1)["error"]
                self.assertIn("所确认版本", message)
        # 从未送审的节点没有谱系可承接：不得凭空开阶段
        message = self.new_phase_v4(slug="t6bad", node="N2", confirmation="rv-N1-3",
                                    operation_id="np-b7", expected=1)["error"]
        self.assertIn("谱系", message)
        self.assertEqual(self.phase_events("t6bad"), [])
        self.assertEqual(len(self.node_review_events("t6bad")), 3)

    def test_six_new_phase_requires_round_cap(self):
        """未封顶（round_count 0/1）不得开新阶段；用尽两轮后合规开启通过。"""
        self.t6_plan(slug="t6gate0")
        first = self.t5_review_n1(slug="t6gate0", operation_id="rv-N1-1")   # 首审：0 轮用尽
        lineage = first["lineage"]
        self.assertEqual(workflow.round_count(self.events("t6gate0"), lineage, 1), 0)
        message = self.new_phase_v4(slug="t6gate0", confirmation="rv-N1-1",
                                    operation_id="np-N1-1", expected=1)["error"]
        self.assertIn("未到封顶", message)
        self.assertIn("继续常规修复轮次", message)
        self.assertEqual(self.phase_events("t6gate0"), [])
        # 第 1 轮已用（round_count 1）仍不得开新阶段
        second = self.review_v4("N1", slug="t6gate0", operation_id="rv-N1-2", recheck="rv-N1-1")
        self.assertEqual(workflow.round_count(self.events("t6gate0"), lineage, 1), 1)
        message = self.new_phase_v4(slug="t6gate0", confirmation="rv-N1-2",
                                    operation_id="np-N1-2", expected=1)["error"]
        self.assertIn("未到封顶", message)
        self.assertIn("只用了 1 轮", message)
        self.assertEqual(self.phase_events("t6gate0"), [])
        self.assertEqual(second["rounds"], 1)
        # 第 2 轮用尽（round_count 2）→ 门槛通过，合规开启
        self.review_v4("N1", slug="t6gate0", operation_id="rv-N1-3", recheck="rv-N1-1")
        opened = self.new_phase_v4(slug="t6gate0", confirmation="rv-N1-3",
                                   operation_id="np-N1-3")
        self.assertEqual((opened["previous_phase"], opened["phase"]), (1, 2))
        self.assertEqual(len(self.phase_events("t6gate0")), 1)

    def test_six_new_phase_phase_linkage_reuse_and_sequence(self):
        """阶段衔接：确认所载阶段≠当前、同一确认重复使用、重放序列不连续都拒绝。"""
        self.t6_plan(slug="t6link")
        self.t6_capped(slug="t6link")
        opened = self.new_phase_v4(slug="t6link", confirmation="rv-N1-3", operation_id="np-N1-1")
        self.assertEqual((opened["previous_phase"], opened["phase"]), (1, 2))
        # 阶段 2 内重新送审并再次用尽两轮（新阶段从首审级重计）
        self.review_v4("N1", slug="t6link", operation_id="rv-N1-5")
        self.review_v4("N1", slug="t6link", operation_id="rv-N1-6", recheck="rv-N1-5")
        self.review_v4("N1", slug="t6link", operation_id="rv-N1-7", recheck="rv-N1-5")
        self.assertEqual(workflow.round_count(self.events("t6link"), opened["lineage"], 2), 2)
        # 同一确认记录换新操作 ID 再用 → 拒绝（一次性，不得重复重置预算）
        message = self.new_phase_v4(slug="t6link", confirmation="rv-N1-3", operation_id="np-N1-2",
                                    expected=1)["error"]
        self.assertIn("一次性", message)
        self.assertIn("rv-N1-3", message)
        # 确认所载阶段（阶段 1）≠ 当前阶段（阶段 2）→ 拒绝
        message = self.new_phase_v4(slug="t6link", confirmation="rv-N1-1", operation_id="np-N1-3",
                                    expected=1)["error"]
        self.assertIn("阶段", message)
        # 阶段 2 内的新记录可作下一次新阶段的确认（阶段 2 → 3）；总账逐段累计
        third = self.new_phase_v4(slug="t6link", confirmation="rv-N1-5", operation_id="np-N1-4")
        self.assertEqual((third["previous_phase"], third["phase"]), (2, 3))
        self.assertEqual([item["rounds"] for item in third["ledger"]], [2, 2, 0])
        self.assertEqual(third["total_rounds"], 4)
        self.assertEqual(len(self.phase_events("t6link")), 2)
        # 事件重放的阶段序列必须连续：打断序列（1→2 改记 3→4）后拒绝
        path = self.root / ".workflow/t6link/events.jsonl"
        events = self.events("t6link")
        for event in events:
            if event["type"] == "review_phase":
                event["data"]["前阶段"], event["data"]["新阶段"] = 3, 4
                break
        path.write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events))
        message = self.new_phase_v4(slug="t6link", confirmation="rv-N1-3", operation_id="np-N1-5",
                                    expected=1)["error"]
        self.assertIn("连续", message)
        self.assertEqual(len(self.phase_events("t6link")), 2)

    def test_six_confirmed_version_window_binding(self):
        """旧版本确认不得放行其后该谱系范围内的新变更；纳入确认后通过。"""
        self.t6_plan(slug="t6ver")
        self.t6_capped(slug="t6ver")
        old = self.git("rev-parse", "--short", "HEAD")
        self.write_file("source.py", "def test_example():\n    return 'later'\n")
        self.commit_files("T1/T2: 确认之后的又一处改动", "source.py")
        message = self.new_phase_v4(slug="t6ver", confirmed_commit="%s..%s" % (old, old),
                                    operation_id="np-N1-1", expected=1)["error"]
        self.assertIn("所确认版本", message)
        self.assertIn("未纳入确认", message)
        self.assertIn("source.py", message)
        self.assertEqual(self.phase_events("t6ver"), [])
        # 把该变更纳入所确认版本（B 推到当前 HEAD）→ 通过
        head = self.git("rev-parse", "--short", "HEAD")
        result = self.new_phase_v4(slug="t6ver", confirmed_commit="%s..%s" % (old, head),
                                   operation_id="np-N1-2")
        self.assertEqual(result["phase"], 2)
        self.assertEqual(result["confirmed_version"]["head"], self.git("rev-parse", "HEAD"))

    def test_six_new_phase_reapproval_gates_scheme_and_plan(self):
        """影响面重评：方案正文变化 → 方案门失效；只改计划 → 计划门失效（不新增机制）。"""
        self.t6_plan(slug="t6gate")
        self.t6_capped(slug="t6gate")
        self.new_phase_v4(slug="t6gate", operation_id="np-N1-1")
        # 方案正文（本计划未声明设计文档 → `## 方案` 一节）变化 → 方案审批失效
        self.plan("t6gate").write_text(
            self.plan("t6gate").read_text().replace(
                "fixture 为什么做、做完是什么样",
                "fixture 为什么做、做完是什么样（影响面重评后改写）"))
        message = self.cli("slice", "t6gate", "T3", expected=1)["error"]
        self.assertIn("『方案』在审批之后被修改过", message)
        self.cli("approve", "t6gate", "方案", "--by", "fixture 影响面重评：方案正文再确认")
        self.cli("approve", "t6gate", "计划", "--by", "fixture 影响面重评：计划再确认")
        self.cli("slice", "t6gate", "T3", expected=1)   # 门过了，但 N1 仍未验收
        # 只改计划（方案正文不动）→ 计划门失效，不是方案门
        self.plan("t6gate").write_text(
            self.plan("t6gate").read_text().replace(
                "- **预期**：fixture 预期结果", "- **预期**：fixture 预期结果（重评后补一条）", 1))
        message = self.cli("slice", "t6gate", "T3", expected=1)["error"]
        self.assertIn("『计划』在审批之后被修改过", message)
        self.assertNotIn("『方案』在审批之后被修改过", message)
        self.cli("approve", "t6gate", "计划", "--by", "fixture 计划门重过")
        message = self.cli("slice", "t6gate", "T3", expected=1)["error"]
        self.assertIn("N1 未验收", message)             # 只差节点验收：重过计划门即到此

    def test_six_new_phase_idempotent_replay_and_conflict(self):
        """同操作 ID＋同请求重试返回原结果、不重复开启；同 ID＋不同请求拒绝。"""
        self.t6_plan(slug="t6idem")
        self.t6_capped(slug="t6idem")
        self.new_phase_v4(slug="t6idem", operation_id="np-N1-1")
        receipt = self.phase_events("t6idem")[0]["data"]["receipt"]   # 原结果随事件持久化
        first, shown = receipt["result"], receipt["text"]
        counts = len(self.events("t6idem"))
        replay = self.new_phase_v4(slug="t6idem", operation_id="np-N1-1")
        self.assert_replay_matches(replay, first)
        self.assertEqual(len(self.events("t6idem")), counts)
        self.assertEqual(len(self.phase_events("t6idem")), 1)
        self.assertEqual(workflow.round_count(self.events("t6idem"), first["lineage"], 2), 0)
        message = self.new_phase_v4(slug="t6idem", basis="换一份实质变化说明",
                                    operation_id="np-N1-1", expected=1)["error"]
        self.assertIn("请求摘要不符", message)
        self.assertEqual(len(self.phase_events("t6idem")), 1)
        # 事件落盘后、状态回写前中断（计划仍是 complete）→ 携原 ID 重试：修复投影、
        # 返回原结果（文案以原 receipt 开头）、不重复开启新阶段。
        self.plan("t6idem").write_text(self.plan("t6idem").read_text().replace(
            "- **状态**：implemented", "- **状态**：complete"))
        replay_text = self.new_phase_v4(slug="t6idem", operation_id="np-N1-1", text=True)
        self.assertTrue(replay_text.startswith(shown), replay_text)
        self.assertIn("幂等重放", replay_text)
        self.assertEqual(len(self.phase_events("t6idem")), 1)
        self.assertEqual([task.status for task in
                          workflow.load_plan(str(self.root), "t6idem").tasks],
                         ["implemented", "implemented", "pending"])
        repairs = self.repair_events("t6idem")
        self.assertEqual([event["data"]["entry"] for event in repairs], ["review"])
        self.assertEqual(len(workflow.read_events(str(self.root), "t6idem")), counts + 1)

    def test_six_recheck_mode_and_round_attribution_recorded(self):
        """复核方式与轮次归属写入事件：普通首审 round=0/mode 空；主控核对可选。"""
        self.t6_plan(slug="t6mode")
        self.t5_review_n1(slug="t6mode", operation_id="rv-N1-1")
        data = self.node_review_events("t6mode")[0]["data"]
        self.assertEqual(data["round"], 0)
        self.assertEqual(data.get("recheck_mode", ""), "")
        second = self.review_v4("N1", slug="t6mode", operation_id="rv-N1-2", recheck="rv-N1-1")
        self.assertEqual((second["round"], second["recheck_mode"]), (1, "定向复核"))
        third = self.review_v4("N1", slug="t6mode", operation_id="rv-N1-3", recheck="rv-N1-1",
                               recheck_mode="主控核对")
        self.assertEqual((third["round"], third["recheck_mode"]), (2, "主控核对"))
        records = self.node_review_events("t6mode")
        self.assertEqual([event["data"]["round"] for event in records], [0, 1, 2])
        self.assertEqual([event["data"].get("recheck_mode", "") for event in records],
                         ["", "定向复核", "主控核对"])
        message = self.review_v4("N1", slug="t6mode", operation_id="rv-N1-4",
                                 recheck="rv-N1-1", recheck_mode="随便看看",
                                 expected=1)["error"]
        self.assertIn("主控核对", message)
        self.assertIn("定向复核", message)
        message = self.review_v4("N1", slug="t6mode", operation_id="rv-N1-5",
                                 recheck_mode="主控核对", expected=1)["error"]
        self.assertIn("--recheck", message)
        self.assertEqual(len(self.node_review_events("t6mode")), 3)

    def test_six_report_confirmation_form_records_path_and_digest(self):
        """报告形态：真实存在的报告记录路径＋摘要；同一报告（路径＋摘要）只能用一次。"""
        self.t6_plan(slug="t6rep")
        self.t6_capped(slug="t6rep")
        message = self.new_phase_v4(slug="t6rep", confirmation="reports/missing.md",
                                    operation_id="np-N1-1", expected=1)["error"]
        self.assertIn("记录/操作 ID 引用不存在", message)
        report = self.write_file(".workflow/t6rep/reports/confirm.md",
                                 "# 独立确认\n\n根因与验证方法已改，原问题 1–3 接续。\n")
        result = self.new_phase_v4(slug="t6rep", confirmation="reports/confirm.md",
                                   operation_id="np-N1-2")
        self.assertEqual(result["phase"], 2)
        payload = self.phase_events("t6rep")[0]["data"]["确认"]
        self.assertEqual(payload["形态"], "报告")
        self.assertEqual(payload["路径"], ".workflow/t6rep/reports/confirm.md")
        self.assertEqual(payload["摘要"], hashlib.sha256(report.read_bytes()).hexdigest()[:16])
        self.assertEqual(result["confirmation"], payload)
        # 阶段 2 内重新送审并把新阶段的两轮也用尽（开新阶段须已封顶）
        self.review_v4("N1", slug="t6rep", operation_id="rv-N1-5")
        self.review_v4("N1", slug="t6rep", operation_id="rv-N1-6", recheck="rv-N1-5")
        self.review_v4("N1", slug="t6rep", operation_id="rv-N1-7", recheck="rv-N1-5")
        # 同一报告（路径＋摘要）换新操作 ID 再用 → 拒绝（一次性；全路径与简写归一后同身份）
        message = self.new_phase_v4(slug="t6rep",
                                    confirmation=".workflow/t6rep/reports/confirm.md",
                                    operation_id="np-N1-3", expected=1)["error"]
        self.assertIn("一次性", message)
        self.assertEqual(len(self.phase_events("t6rep")), 1)
        # 同一路径内容变了＝另一份凭据（摘要口径，按路径沿用旧状态不成立）
        report.write_text("# 独立确认（修订）\n\n补一条影响面重评结论。\n")
        again = self.new_phase_v4(slug="t6rep", confirmation="reports/confirm.md",
                                  operation_id="np-N1-4")
        self.assertEqual((again["previous_phase"], again["phase"]), (2, 3))
        payloads = [event["data"]["确认"] for event in self.phase_events("t6rep")]
        self.assertEqual(payloads[0]["路径"], payloads[1]["路径"])
        self.assertNotEqual(payloads[0]["摘要"], payloads[1]["摘要"])


if __name__ == "__main__":
    unittest.main()
