"""真实 CLI 回归与解析输入矩阵；所有仓库、命令及旧账本均为隔离 fixture。"""
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


if __name__ == "__main__":
    unittest.main()
