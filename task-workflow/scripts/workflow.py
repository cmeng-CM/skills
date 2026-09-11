#!/usr/bin/env python3
"""task-workflow 引擎。

确定性地操作 <project>/.workflow/<slug>/ 下的状态文件：解析计划的依赖图、
计算可执行任务、切分派发片段、记录账本、检查计划质量、执行验证并留证。

用法：
    workflow.py init    <slug> --goal "..."
    workflow.py status  [slug]
    workflow.py next    [slug]
    workflow.py slice   [slug] <task-id>
    workflow.py record  [slug] <task-id> --commits <range> --verdict <clean|issues>
    workflow.py check   [slug]
    workflow.py approve [slug] <方案|计划> --by "<用户的原话>"
    workflow.py verify  [slug] [--label <name>]
    workflow.py close   [slug] --handoff <去向> --next-step "<建议>"

所有子命令都支持 --json 输出机器可读结果。
引擎只做确定性操作；语义判断（需求是否清楚、代码是否合格）留给 skill。
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime

# ---------------------------------------------------------------- 解析规则

TASK_HEADER = re.compile(r"^####\s+(T\d+)\b\s*(.*)$")
PHASE_HEADER = re.compile(r"^###\s+Phase\s+(\d+)\s*[:：]?\s*(.*)$")
SECTION_HEADER = re.compile(r"^##\s+(.+?)\s*$")
META_FIELD = re.compile(r"^\*\*(?P<key>[^*]+?)\*\*\s*[:：]\s*(?P<value>.*)$")
TASK_FIELD = re.compile(r"^-\s+\*\*(?P<key>[^*]+?)\*\*\s*[:：]\s*(?P<value>.*)$")
DECISION_ROW = re.compile(r"^\|\s*(D-\d+)\s*\|(.+)\|\s*$")
TABLE_ROW = re.compile(r"^\|(.+)\|\s*$")
TASK_REF = re.compile(r"\bT\d+\b")
DECISION_REF = re.compile(r"\bD-\d+\b")
FENCE = re.compile(r"^```")

PLACEHOLDERS = [
    "TBD",
    "TODO",
    "FIXME",
    "待补",
    "待定",
    "待填",
    "???",
    "<placeholder>",
    "xxx",
]

TASK_FIELD_KEYS = ["文件", "依赖", "并行", "接口", "验收", "失败信号", "决策", "状态"]
VALID_STATUS = ["pending", "in_progress", "complete", "blocked"]

MAX_TASKS = 8          # 超过则建议拆分
MAX_FILES_PER_TASK = 5  # 单任务文件数上限
MAX_BATCH_TASKS = 4     # 同批合并的任务数上限（一个 subagent 一次能高质量做完的量）
UNTRACKED_HASH_LIMIT = 1 << 20  # 超大未跟踪文件只记大小，不读内容


class WorkflowError(Exception):
    """用户可见的错误，直接打印不打栈。"""


# ---------------------------------------------------------------- 仓库定位

def _git(root, *args):
    """跑一条 git 命令，失败返回空串（非 git 项目是合法场景）。"""
    try:
        out = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, timeout=30
        )
        return out.stdout if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def find_project_root(start=None):
    """向上找到含 .git 的目录；没有就返回起始目录。"""
    cur = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isdir(os.path.join(cur, ".git")) or os.path.isfile(
            os.path.join(cur, ".git")
        ):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return os.path.abspath(start or os.getcwd())
        cur = parent


def workflow_root(root):
    return os.path.join(root, ".workflow")


def plan_path(root, slug):
    return os.path.join(workflow_root(root), slug, "plan.md")


def ledger_path(root, slug):
    return os.path.join(workflow_root(root), slug, "ledger.md")


def reports_dir(root, slug):
    return os.path.join(workflow_root(root), slug, "reports")


def list_slugs(root):
    base = workflow_root(root)
    if not os.path.isdir(base):
        return []
    return sorted(
        d
        for d in os.listdir(base)
        if os.path.isfile(os.path.join(base, d, "plan.md"))
    )


def resolve_slug(root, slug):
    """slug 缺省时要求当前只有一个活跃工作流，避免猜错对象。"""
    slugs = list_slugs(root)
    if slug:
        if slug not in slugs:
            raise WorkflowError(
                f"未找到工作流 '{slug}'。现有：{', '.join(slugs) or '（无）'}"
            )
        return slug
    if not slugs:
        raise WorkflowError("当前项目没有工作流。先运行 init，或由 skill 的 P 轮创建计划。")
    if len(slugs) > 1:
        raise WorkflowError(
            f"有多个活跃工作流（{', '.join(slugs)}），请显式指定 slug。"
        )
    return slugs[0]


# ---------------------------------------------------------------- 计划解析

class Task:
    def __init__(self, tid, title, line_start):
        self.id = tid
        self.title = title.strip()
        self.line_start = line_start
        self.line_end = line_start
        self.fields = {}
        self.field_lines = {}
        self.phase = None

    def get(self, key):
        return self.fields.get(key, "").strip()

    @property
    def status(self):
        return self.get("状态").lower() or "pending"

    @property
    def deps(self):
        raw = self.get("依赖")
        if not raw or raw in ("无", "none", "-", "None"):
            return []
        return sorted(set(TASK_REF.findall(raw)))

    @property
    def decision_refs(self):
        raw = self.get("决策")
        if not raw or raw in ("无", "none", "-"):
            return []
        return sorted(set(DECISION_REF.findall(raw)))

    @property
    def is_parallel(self):
        return self.get("并行").lower() in ("是", "yes", "true", "y")

    @property
    def files(self):
        """从『文件』字段抽出出现的路径片段数量。"""
        raw = self.get("文件")
        if not raw:
            return []
        return re.findall(r"[`'\"]?([\w./\-]+\.[A-Za-z0-9]+)", raw)


class Plan:
    def __init__(self, path, text):
        self.path = path
        self.text = text
        self.lines = text.splitlines()
        self.meta = {}
        self.decisions = []   # [{id, decision, source, rationale}]
        self.phases = []      # [(num, name, checkpoint)]
        self.tasks = []
        self.coverage = []    # [{target, means, type}]
        self.exclusions_present = False   # 是否有「不验证的部分」
        self.sections = {}    # 各段的正文行，供 bug 类型检查用
        self.verify_command = ""
        self._parse()

    @property
    def kind(self):
        """工作流类型：bug 走免门路径，其余为 feature。"""
        return (self.meta.get("类型") or "feature").strip().lower()

    @property
    def is_bug(self):
        return self.kind == "bug"

    def _parse(self):
        section = None
        current_task = None
        current_phase = None
        in_fence = False
        verify_buf = []
        collecting_verify = False

        for idx, line in enumerate(self.lines):
            if FENCE.match(line):
                in_fence = not in_fence
                if collecting_verify and not in_fence:
                    collecting_verify = False
                continue

            if collecting_verify:
                verify_buf.append(line)
                continue

            sec = SECTION_HEADER.match(line)
            if sec and not in_fence:
                section = sec.group(1).strip()
                current_task = None
                continue

            phase = PHASE_HEADER.match(line)
            if phase and not in_fence:
                current_phase = (int(phase.group(1)), phase.group(2).strip(), "")
                self.phases.append(list(current_phase))
                current_task = None
                continue

            task = TASK_HEADER.match(line)
            if task and not in_fence:
                current_task = Task(task.group(1), task.group(2), idx)
                current_task.phase = self.phases[-1][0] if self.phases else None
                self.tasks.append(current_task)
                continue

            if current_task is not None:
                current_task.line_end = idx
                fld = TASK_FIELD.match(line)
                if fld:
                    key = fld.group("key").strip()
                    current_task.fields[key] = fld.group("value").strip()
                    current_task.field_lines[key] = idx
                continue

            fld = META_FIELD.match(line)
            if fld:
                self.meta[fld.group("key").strip()] = fld.group("value").strip()
                continue

            if section:
                body = self.sections.setdefault(section, [])
                if line.strip():
                    body.append(line.strip())

                if section.startswith("决策"):
                    row = DECISION_ROW.match(line)
                    if row:
                        cells = [c.strip() for c in row.group(2).split("|")]
                        if cells and cells[0] and "---" not in cells[0]:
                            # 三列：| ID | 决策 | 理由 |
                            # 四列：| ID | 决策 | 来源 | 理由 |
                            if len(cells) >= 3:
                                source, rationale = cells[1], cells[2]
                            else:
                                source, rationale = "", (cells[1] if len(cells) > 1 else "")
                            self.decisions.append(
                                {
                                    "id": row.group(1),
                                    "decision": cells[0],
                                    "source": source,
                                    "rationale": rationale,
                                }
                            )
                elif section.startswith("验证覆盖"):
                    if line.strip().startswith("###") and "不验证" in line:
                        self.exclusions_present = True
                    row = TABLE_ROW.match(line)
                    if row and not line.strip().startswith("|--"):
                        cells = [c.strip() for c in row.group(1).split("|")]
                        if len(cells) >= 3 and cells[0] not in ("对象", "") and not cells[0].startswith("--"):
                            self.coverage.append(
                                {"target": cells[0], "means": cells[1], "type": cells[2]}
                            )
                elif section.startswith("验证命令"):
                    if FENCE.match(line) and not in_fence:
                        collecting_verify = True
                    elif line.strip() and not line.strip().startswith("```"):
                        verify_buf.append(line.strip())

            if current_phase and current_task is None:
                cp = META_FIELD.match(line)
                if cp and "heckpoint" in cp.group("key"):
                    self.phases[-1][2] = cp.group("value").strip()

        self.verify_command = "\n".join(l for l in verify_buf if l.strip()).strip()
        if self.verify_command in ("未声明", "-", "无"):
            self.verify_command = ""

    # ---- 状态计算（依赖图）

    def states(self):
        """返回 {task_id: STATE}，STATE ∈ DONE/BLOCKED/READY/RUNNING。"""
        by_id = {t.id: t for t in self.tasks}
        done = {t.id for t in self.tasks if t.status == "complete"}
        out = {}
        for t in self.tasks:
            if t.id in done:
                out[t.id] = "DONE"
            elif t.status == "blocked":
                out[t.id] = "BLOCKED"
            elif any(d not in done for d in t.deps if d in by_id):
                out[t.id] = "BLOCKED"
            elif t.status == "in_progress":
                out[t.id] = "RUNNING"
            else:
                out[t.id] = "READY"
        return out

    def ready(self):
        st = self.states()
        return [t for t in self.tasks if st[t.id] in ("READY", "RUNNING")]

    def current_phase(self):
        """第一个还有未完成任务（或尚有阶段未开启）的阶段号。"""
        if not self.phases:
            return None
        for num, _name, _cp in self.phases:
            if any(
                t.phase == num and self.states()[t.id] != "DONE" for t in self.tasks
            ):
                return num
        return None

    def phase_name(self, num):
        for n, name, _cp in self.phases:
            if n == num:
                return name
        return ""


def load_plan(root, slug):
    path = plan_path(root, slug)
    if not os.path.isfile(path):
        raise WorkflowError(f"计划文件不存在：{path}")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    return Plan(path, text)


# ---------------------------------------------------------------- 计划检查

def check_plan(plan):
    """返回 [{level, task, message}]，level ∈ ERROR/WARNING/INFO。"""
    out = []
    by_id = {t.id: t for t in plan.tasks}

    def add(level, message, task=None):
        out.append({"level": level, "task": task, "message": message})

    if not plan.tasks:
        add("ERROR", "计划里没有任何任务（缺少 `#### T1 <名称>` 任务块）。")
        return out

    if not plan.phases:
        add("ERROR", "计划里没有任何阶段（缺少 `### Phase 1: <名称>`）。")

    # 1. 依赖引用存在性 + 循环依赖
    for t in plan.tasks:
        for dep in t.deps:
            if dep not in by_id:
                add("ERROR", f"依赖的任务 {dep} 不存在。", t.id)
        if t.id in t.deps:
            add("ERROR", "任务依赖了自己。", t.id)

    graph = {t.id: [d for d in t.deps if d in by_id] for t in plan.tasks}
    state = {}
    reported = set()

    def visit(node, stack):
        if state.get(node) == "done":
            return False
        if state.get(node) == "visiting":
            # 同一轮递归里回边 = 环；跨轮残留的 visiting 已在别处报告过，跳过
            if node in stack and stack[stack.index(node):]:
                cycle = " → ".join(stack[stack.index(node):] + [node])
                if cycle not in reported:
                    reported.add(cycle)
                    add("ERROR", f"循环依赖：{cycle}")
                return True
            return False
        state[node] = "visiting"
        found = False
        for nxt in graph[node]:
            if visit(nxt, stack + [node]):
                found = True
        # 无条件落 done：环上的节点也要出栈，否则外层循环会再次进入并误判
        state[node] = "done"
        return found

    for t in plan.tasks:
        visit(t.id, [])

    # 2. 必填字段
    for t in plan.tasks:
        if not t.get("验收"):
            add("ERROR", "缺少『验收』字段——没有可判定的验收标准。", t.id)
        if not t.get("失败信号"):
            add(
                "ERROR",
                "缺少『失败信号』字段——没有失败信号的验收标准无法判定，等于没写。",
                t.id,
            )
        if t.status not in VALID_STATUS:
            add(
                "ERROR",
                f"状态 '{t.status}' 非法，只能是 {'/'.join(VALID_STATUS)}。",
                t.id,
            )
        if not t.get("文件"):
            add("WARNING", "缺少『文件』字段——派发时执行者不知道要碰哪些文件。", t.id)
        elif len(t.files) > MAX_FILES_PER_TASK:
            add(
                "WARNING",
                f"单任务涉及 {len(t.files)} 个文件（上限 {MAX_FILES_PER_TASK}），建议拆分。",
                t.id,
            )

    # 3. 决策覆盖（双向）
    declared = {d["id"] for d in plan.decisions}
    referenced = set()
    for t in plan.tasks:
        for ref in t.decision_refs:
            if ref not in declared:
                add("ERROR", f"引用了不存在的决策 {ref}。", t.id)
            referenced.add(ref)
        if not t.decision_refs:
            add(
                "WARNING",
                "没有关联任何决策——确认它不是无来源的遗留任务。",
                t.id,
            )
    for dec in sorted(declared - referenced):
        add(
            "ERROR",
            f"决策 {dec} 没有任何任务承载（范围缩减检测）——讨论里定了的事在计划中丢了。",
        )

    # 3b. 决策来源：未经用户确认的决策必须在门槛处被看见
    unconfirmed = [d["id"] for d in plan.decisions if d["source"] != "用户"]
    if unconfirmed:
        add(
            "WARNING",
            f"以下决策未经用户确认（来源列不是『用户』）：{', '.join(unconfirmed)}。"
            "若其中任何一条属于「输入容错 / 输出格式取值 / 范围边界 / 兼容性影响」"
            "这四类，必须停下来问用户一次，不能自行决定后只记进表里。",
        )

    if not plan.decisions:
        add("WARNING", "计划里没有『决策』表——需求与任务之间缺少可追溯的锚点。")

    # 4. 占位符扫描（标题、表格行同样检查——计划里任何位置都不许留占位符）
    for idx, line in enumerate(plan.lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        for token in PLACEHOLDERS:
            if token in line:
                tid = None
                for t in plan.tasks:
                    if t.line_start < idx - 1 <= max(t.line_end, t.line_start + 40):
                        tid = t.id
                        break
                add("ERROR", f"L{idx} 含占位符 '{token}'：{stripped[:60]}", tid)
                break

    # 5. 规模
    if len(plan.tasks) > MAX_TASKS:
        add(
            "WARNING",
            f"计划有 {len(plan.tasks)} 个任务（上限 {MAX_TASKS}），考虑拆成多个工作流。",
        )

    # 6. 验证命令
    if not plan.verify_command:
        add(
            "WARNING",
            "未声明验证命令——V 轮会要求补上（写进 plan 的『验证命令』代码块）。",
        )

    # 7. 验证覆盖：每条决策都必须说明"用什么证明它对"
    if not plan.coverage and plan.decisions:
        add(
            "ERROR",
            "有决策表但缺少『验证覆盖』一节——没有东西声明验证覆盖了什么范围。"
            "每条决策都要说明用什么手段证明，并显式列出不验证的部分。",
        )
    else:
        covered = set()
        for entry in plan.coverage:
            refs = DECISION_REF.findall(entry["target"])
            for ref in refs:
                if ref not in {d["id"] for d in plan.decisions}:
                    add("ERROR", f"验证覆盖引用了不存在的决策 {ref}。")
                covered.add(ref)
            if not entry["means"].strip():
                add("ERROR", f"验证覆盖里『{entry['target']}』没写验证手段。")
            if entry["type"] not in ("自动化", "人工"):
                add(
                    "ERROR",
                    f"验证覆盖里『{entry['target']}』的类型是 '{entry['type']}'，"
                    "只能是『自动化』或『人工』。",
                )
            if entry["type"] == "人工" and len(entry["means"]) < 8:
                add(
                    "WARNING",
                    f"验证覆盖里『{entry['target']}』标为人工验证，但没写清怎么做。"
                    "人工验证要写具体的命令或步骤，否则没法复核。",
                )
        for dec in sorted({d["id"] for d in plan.decisions} - covered):
            add(
                "ERROR",
                f"决策 {dec} 没有出现在验证覆盖里——它不会被任何手段验证。",
            )
        seen_targets = {}
        for entry in plan.coverage:
            key = entry["target"]
            seen_targets[key] = seen_targets.get(key, 0) + 1
        for target, n in sorted(seen_targets.items()):
            if n > 1:
                add("WARNING", f"验证覆盖里『{target}』出现了 {n} 次（重复行会虚增覆盖数）。")

    if plan.coverage and not plan.exclusions_present:
        add(
            "ERROR",
            "『验证覆盖』一节缺少『### 不验证的部分』——不写明哪些不验证，"
            "覆盖范围就是隐式的。真的没有就写『无』。",
        )

    # 8. bug 类型：复现、根因、回归测试三样缺一不可
    if plan.is_bug:
        for sec_name, why in [
            ("复现", "没有可复现的失败，就无法证明修好了"),
            ("根因", "说不清为什么错，就只是让症状消失了"),
        ]:
            body = [l for l in plan.sections.get(sec_name, []) if not l.startswith("<!--")]
            if not body or all("TODO" in l for l in body):
                add("ERROR", f"bug 工作流缺少『{sec_name}』——{why}。")
        has_regression = any(
            "回归" in e["target"] or "回归" in e["means"] for e in plan.coverage
        )
        if not has_regression:
            add(
                "ERROR",
                "bug 工作流必须在验证覆盖里明确列出『回归测试』一项——"
                "修复不带回归测试，同一个 bug 会回来。",
            )
        if plan.verify_command == "":
            add("ERROR", "bug 工作流的验证命令必须声明：修复后要能一键重跑复现与全量测试。")

    return out


# ---------------------------------------------------------------- 账本

def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def ledger_init(root, slug, plan_rel):
    path = ledger_path(root, slug)
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            f"""# Ledger: {slug}

Plan: {plan_rel}
Created: {datetime.now().strftime('%Y-%m-%d')}

> 账本是压缩/清空上下文后唯一可信的恢复点。**不相信对话回忆，只相信账本与 git log。**
> 首行的 `Plan:` 用于防止多个工作流串账——首行指向别的计划时，这份账本属于那个计划。

## 审批

| 时间 | 阶段 | 依据指纹 | 依据 |
|------|------|---------|------|

## 完成记录

| 任务 | 提交范围 | 审查 | 时间 |
|------|---------|------|------|

## 裁决

| 时间 | 决定 | 理由 | 错的代价 |
|------|------|------|---------|

## 错误

| 时间 | 错误 | 尝试 | 处理 |
|------|------|------|------|

## 验证记录

| 时间 | 标签 | 提交 | 命令 | 退出码 | 指纹 | 结果 |
|------|------|------|------|-------|------|------|

## 收尾

| 时间 | 完成度 | 指纹 | 交接 | 下一步 |
|------|-------|------|------|--------|
"""
        )
    return path


STATUS_LINE = re.compile(r"^- \*\*状态\*\*[:：].*$", re.M)


def plan_content_hash(plan_path):
    """审批依据指纹：计划内容的哈希，**剥离任务状态字段**。

    剥离状态是必须的——`record` 每次完成任务都要改状态，若不剥离，正常的
    执行流程会让自己刚获得的审批立刻失效。其余任何改动（改需求、改任务、
    改验收标准）都会让指纹变化，从而让旧审批失效。
    """
    with open(plan_path, encoding="utf-8") as fh:
        text = fh.read()
    stripped = STATUS_LINE.sub("- **状态**：<忽略>", text)
    return hashlib.sha256(stripped.encode()).hexdigest()[:16]


def section_hash(plan_path, section_name):
    """某一段（如『方案』）的内容指纹。段落被改写即失效。"""
    with open(plan_path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    body = _section_lines(lines, section_name)
    return hashlib.sha256("\n".join(body).encode()).hexdigest()[:16]


def _read_approvals(root, slug):
    """读出审批记录：{阶段: {"time","fingerprint","basis"}}，同一阶段取最后一条。"""
    path = ledger_path(root, slug)
    if not os.path.isfile(path):
        return {}
    out, inside = {}, False
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if s.startswith("## "):
                inside = s.startswith("## 审批")
                continue
            if inside and s.startswith("|"):
                cells = [c.strip() for c in s.strip("|").split("|")]
                if len(cells) >= 4 and cells[0] != "时间" and not cells[0].startswith("--"):
                    out[cells[1]] = {
                        "time": cells[0],
                        "fingerprint": cells[2],
                        "basis": cells[3],
                    }
    return out


def require_plan_approval(root, slug, plan_path):
    """执行前的门：方案与计划都须经用户审批，且内容未在审批后被改动。

    bug 工作流是例外：它的"需求"是一个症状而不是规格，没有可审的方案。
    补偿控制是 bug 类型强制的『复现 / 根因 / 回归测试』三项（见 check_plan），
    以及 V 轮对回归测试是否真实存在的校验。
    """
    plan_text = open(plan_path, encoding="utf-8").read()
    if (re.search(r"^\*\*类型\*\*\s*[:：]\s*bug\s*$", plan_text, re.M)):
        return {"_skipped": {"time": _now(), "fingerprint": "—", "basis": "bug 工作流免门"}}

    approvals = _read_approvals(root, slug)

    if "方案" not in approvals:
        raise WorkflowError(
            "『方案』尚未经用户审批，不得进入执行轮。"
            "先把方案呈现给用户审阅，得到明确答复后运行："
            f" workflow.py approve {slug} 方案 --by '<用户的原话或说明>'"
        )
    got = section_hash(plan_path, "方案")
    if approvals["方案"]["fingerprint"] != got:
        raise WorkflowError(
            f"『方案』在审批之后被修改过（审批时 {approvals['方案']['fingerprint']}，"
            f"当前 {got}），该审批已失效。请把改动呈现给用户，重新审批。"
        )

    if "计划" not in approvals:
        raise WorkflowError(
            "『计划』尚未经用户审批，不得进入执行轮。"
            "先把计划呈现给用户审阅，得到明确答复后运行："
            f" workflow.py approve {slug} 计划 --by '<用户的原话或说明>'"
        )
    want = plan_content_hash(plan_path)
    if approvals["计划"]["fingerprint"] != want:
        raise WorkflowError(
            f"『计划』在审批之后被修改过（审批时 {approvals['计划']['fingerprint']}，"
            f"当前 {want}），该审批已失效。请把改动呈现给用户，重新审批。"
        )
    return approvals


def _read_verify_records(root, slug):
    """读出验证记录表的全部行（按文件顺序）。"""
    path = ledger_path(root, slug)
    if not os.path.isfile(path):
        return []
    rows, inside = [], False
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if s.startswith("## "):
                inside = s.startswith("## 验证记录")
                continue
            if inside and s.startswith("|"):
                cells = [c.strip() for c in s.strip("|").split("|")]
                if len(cells) >= 7 and cells[0] != "时间" and not cells[0].startswith("--"):
                    rows.append(
                        {
                            "time": cells[0],
                            "label": cells[1],
                            "commit": cells[2],
                            "command": cells[3],
                            "exit_code": cells[4],
                            "fingerprint": cells[5],
                            "result": cells[6],
                        }
                    )
    return rows


def ledger_append(root, slug, section, row):
    path = ledger_path(root, slug)
    if not os.path.isfile(path):
        raise WorkflowError(f"账本不存在：{path}")
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    header = f"## {section}"
    try:
        start = lines.index(header)
    except ValueError:
        raise WorkflowError(f"账本缺少章节：{header}")

    # 表头两行之后的连续表格行，插到表格末尾
    idx = start + 1
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    idx += 2  # 跳过 | 表头 | 与 |---|
    while idx < len(lines) and lines[idx].strip().startswith("|"):
        idx += 1
    lines.insert(idx, row)

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def ledger_check_owner(root, slug):
    """账本首行必须命名本计划的路径，防止多工作流串账。"""
    path = ledger_path(root, slug)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("Plan:"):
                owner = line.split(":", 1)[1].strip()
                if slug not in owner:
                    raise WorkflowError(
                        f"账本首行指向的是别的计划（{owner}），拒绝在其上记账。"
                        f"请检查 .workflow/{slug}/ 是否被误用。"
                    )
                return owner
    return None


# ---------------------------------------------------------------- 内容指纹

def fingerprint(root):
    """工作树内容指纹：内容变了指纹就变，与是否已提交无关。

    **必须包含 HEAD**：只哈希 diff + status 的话，一棵干净的提交树两者都为空，
    指纹会坍缩成空串的哈希——那样"提交了新代码"不会改变指纹，旧验证就被错误地
    当成对新内容有效。加上 HEAD 之后，提交或换分支都会让指纹变化。

    tracked 的改动走 git diff；未跟踪文件额外读内容（超大文件只记大小）。
    """
    h = hashlib.sha256()
    h.update(_git(root, "rev-parse", "HEAD").encode())
    h.update(_git(root, "diff", "HEAD").encode())
    status = _git(root, "status", "--porcelain")
    h.update(status.encode())

    for line in status.splitlines():
        if not line.startswith("??"):
            continue
        rel = line[3:].strip().strip('"')
        full = os.path.join(root, rel)
        if os.path.isdir(full):
            for dirpath, _dirs, names in os.walk(full):
                for name in sorted(names):
                    p = os.path.join(dirpath, name)
                    h.update(os.path.relpath(p, root).encode())
                    _hash_file(h, p)
        else:
            h.update(rel.encode())
            _hash_file(h, full)
    return h.hexdigest()[:16]


def _hash_file(h, path):
    try:
        size = os.path.getsize(path)
    except OSError:
        return
    h.update(str(size).encode())
    if size > UNTRACKED_HASH_LIMIT:
        return
    try:
        with open(path, "rb") as fh:
            h.update(fh.read())
    except OSError:
        pass


# ---------------------------------------------------------------- 子命令

def cmd_init(args):
    root = find_project_root()
    slug = args.slug
    wf = workflow_root(root)
    target = os.path.join(wf, slug)

    if os.path.exists(os.path.join(target, "plan.md")):
        raise WorkflowError(f"工作流 '{slug}' 已存在：{target}")

    os.makedirs(reports_dir(root, slug), exist_ok=True)

    # 自忽略：不去改项目的 .gitignore，目录自己忽略自己
    gitignore = os.path.join(wf, ".gitignore")
    if not os.path.exists(gitignore):
        with open(gitignore, "w", encoding="utf-8") as fh:
            fh.write("*\n")

    plan_rel = os.path.relpath(plan_path(root, slug), root)
    kind = "bug" if args.bug else "feature"
    bug_sections = (
        """
## 复现

TODO（可复现的最小步骤或命令。**修之前先确认它确实失败**——没有可复现的失败，就无法证明修好了）

## 根因

TODO（为什么错。说不清根因就只是在让症状消失，不是在修复）
"""
        if args.bug
        else ""
    )
    regression_row = (
        "| 回归测试（捕获本 bug） | TODO | 自动化 |\n" if args.bug else ""
    )

    with open(plan_path(root, slug), "w", encoding="utf-8") as fh:
        fh.write(
            f"""# {args.goal or slug}

**Goal**: {args.goal or 'TODO'}
**Slug**: {slug}
**类型**: {kind}
**Created**: {datetime.now().strftime('%Y-%m-%d')}

## 验证命令

```
未声明
```

## 全局约束

- TODO（每条一行，逐字写清确切取值；每个任务的隐含需求都包括本节）
{bug_sections}
## 方案

### 做法

TODO（2-3 句到一节，随任务规模伸缩。写清怎么实现，不写文件清单）

### 备选与取舍

TODO（考虑过的其他做法，以及为什么没选。只有一种做法时写"无备选"并给理由）

### 明确不做

TODO（这次范围外的事。范围边界是四类敏感决策之一，用户要在这里看到它）

## 决策

| ID | 决策 | 来源 | 理由 |
|----|------|------|------|
| D-01 | TODO | TODO | TODO |

## 验证覆盖

> 每条决策都要说明"用什么证明它对"。**验证范围必须写出来**，否则覆盖到哪里是隐式的、无法审查。
> 类型只能是『自动化』或『人工』；标自动化的会在 V 轮核对产物是否真实存在。

| 对象 | 验证手段 | 类型 |
|------|---------|------|
{regression_row}| D-01 | TODO | 自动化 |

### 不验证的部分

- TODO（这次明确不验证什么、为什么。真的没有就写"无"——但必须显式写出来）

## 阶段

### Phase 1: 实现

**Checkpoint**: TODO（本阶段全部任务完成后可判定的检查点）

#### T1 TODO

- **文件**：TODO
- **依赖**：无
- **并行**：否
- **接口**：consumes 无 / produces 无
- **验收**：TODO
- **失败信号**：TODO
- **决策**：D-01
- **状态**：pending
"""
        )

    ledger_init(root, slug, plan_rel)

    result = {
        "root": root,
        "slug": slug,
        "kind": kind,
        "plan": plan_path(root, slug),
        "ledger": ledger_path(root, slug),
        "reports": reports_dir(root, slug),
    }
    note = (
        "  bug 路径：免两道审批门，但强制『复现 / 根因 / 回归测试』三项\n" if args.bug else ""
    )
    return result, (
        f"✓ 已创建 .workflow/{slug}/（类型 {kind}）\n"
        f"  计划：{result['plan']}\n  账本：{result['ledger']}\n{note}"
    )


def cmd_status(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    plan = load_plan(root, slug)
    st = plan.states()
    counts = {}
    for state in st.values():
        counts[state] = counts.get(state, 0) + 1

    phase = plan.current_phase()
    if not plan.tasks:
        stage = "P（计划未成形）"
    elif counts.get("DONE", 0) == len(plan.tasks):
        stage = "V（执行完毕，待验证）"
    else:
        stage = "E（执行中）"

    result = {
        "root": root,
        "slug": slug,
        "stage": stage,
        "goal": plan.meta.get("Goal", ""),
        "phase": phase,
        "phase_name": plan.phase_name(phase) if phase else "",
        "counts": counts,
        "total": len(plan.tasks),
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "state": st[t.id],
                "status": t.status,
                "deps": t.deps,
                "phase": t.phase,
            }
            for t in plan.tasks
        ],
        "verify_command": plan.verify_command,
    }

    lines = [
        f"工作流 {slug} — {stage}",
        f"目标：{result['goal']}",
        f"进度：{counts.get('DONE', 0)}/{len(plan.tasks)} 完成"
        + (f"，{counts.get('READY', 0)} 可执行" if counts.get("READY") else "")
        + (f"，{counts.get('BLOCKED', 0)} 被阻塞" if counts.get("BLOCKED") else ""),
    ]
    if phase:
        lines.append(f"当前阶段：Phase {phase} — {result['phase_name']}")
    lines.append("")
    for t in result["tasks"]:
        mark = {
            "DONE": "[x]",
            "READY": "[ ]",
            "RUNNING": "[~]",
            "BLOCKED": "[-]",
        }[t["state"]]
        dep = f"  ← {', '.join(t['deps'])}" if t["deps"] else ""
        lines.append(f"  {mark} {t['id']} {t['title']}  ({t['state']}){dep}")
    if not plan.verify_command:
        lines.append("")
        lines.append("⚠ 未声明验证命令")
    return result, "\n".join(lines)


def cmd_next(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    plan = load_plan(root, slug)
    st = plan.states()
    ready = [t for t in plan.tasks if st[t.id] in ("READY", "RUNNING")]
    blocked = [t for t in plan.tasks if st[t.id] == "BLOCKED"]

    # 可合并提示：互不依赖 + 文件不重叠的 READY 任务。是否"同型"机器判不了，
    # 所以只提示候选，判断留给控制器。
    batchable = []
    if len(ready) > 1:
        group = []
        for t in ready:
            if len(group) >= MAX_BATCH_TASKS:
                break
            ids = {x.id for x in group}
            if ids & set(t.deps):
                continue
            paths = {_norm_path(f) for f in t.files} - {""}
            taken = {_norm_path(f) for x in group for f in x.files} - {""}
            if paths and paths & taken:
                continue
            group.append(t)
        if len(group) > 1:
            batchable = [t.id for t in group]

    result = {
        "slug": slug,
        "ready": [{"id": t.id, "title": t.title, "parallel": t.is_parallel} for t in ready],
        "blocked": [{"id": t.id, "title": t.title, "deps": t.deps} for t in blocked],
        "batchable": batchable,
    }
    if not ready:
        msg = "没有可执行的任务。"
        if blocked:
            msg += f" 剩余 {len(blocked)} 个任务被阻塞。"
        elif plan.tasks:
            msg += " 全部任务已完成，进入 V 轮验证。"
        else:
            msg += " 计划里没有任务。"
        return result, msg
    lines = ["可执行任务："]
    for t in result["ready"]:
        tag = "  [可并行]" if t["parallel"] else ""
        lines.append(f"  {t['id']} {t['title']}{tag}")
    if len(batchable) > 1:
        lines += [
            "",
            f"可合并为一批：{', '.join(batchable)}"
            "（互不依赖、文件不重叠）",
            f"  ——若它们是同型机械改动，用 `slice <slug> {' '.join(batchable)}`"
            " 一次派发、一次审查；否则逐个派。",
        ]
    if blocked:
        lines.append("")
        lines.append("被阻塞：")
        for t in result["blocked"]:
            lines.append(f"  {t['id']} {t['title']}  ← 等 {', '.join(t['deps'])}")
    return result, "\n".join(lines)


def cmd_approve(args):
    """记录用户对某个阶段的审批。审批绑定内容指纹，改了就失效。"""
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    plan = load_plan(root, slug)
    ledger_check_owner(root, slug)

    stage = args.stage
    if stage not in ("方案", "计划"):
        raise WorkflowError(f"未知阶段 '{stage}'，只能是『方案』或『计划』。")

    basis = (args.by or "").strip()
    if not basis:
        raise WorkflowError(
            "必须用 --by 说明审批依据（用户的原话，或你如何得到答复的）。"
            "没有依据的审批等于自己给自己盖章。"
        )

    if stage == "方案":
        body = _section_lines(plan.lines, "方案")
        if not body or any("TODO" in l for l in body):
            raise WorkflowError("『方案』一节还是空的（或含 TODO），无可审批内容。")
        fp = section_hash(plan.path, "方案")
    else:
        findings = [f for f in check_plan(plan) if f["level"] == "ERROR"]
        if findings:
            raise WorkflowError(
                f"计划还有 {len(findings)} 个 ERROR，不能审批。先跑 `check` 修掉。"
            )
        fp = plan_content_hash(plan.path)

    stamp = _now()
    ledger_append(root, slug, "审批", f"| {stamp} | {stage} | {fp} | {basis} |")

    result = {
        "slug": slug,
        "stage": stage,
        "fingerprint": fp,
        "basis": basis,
        "approved_at": stamp,
    }
    return result, f"✓ 已记录『{stage}』审批（指纹 {fp}）\n  依据：{basis}"


def _norm_path(token):
    """把『文件』字段里的一项归一成可比较的路径（去掉行号区间）。"""
    return token.split(":")[0].strip().lstrip("./")


def validate_batch(plan, tasks):
    """合并派发的机械守卫。

    注意：同批由**一个** subagent 顺序完成，所以文件重叠不是并发冲突问题——
    它是"这批不像同型机械改动"的气味，只报警告。真正会挡的是后面几条。

    返回警告列表；不满足硬条件时抛 WorkflowError。
    """
    if len(tasks) > MAX_BATCH_TASKS:
        raise WorkflowError(
            f"一批最多 {MAX_BATCH_TASKS} 个任务（当前 {len(tasks)} 个）。"
            "一个 subagent 一次能高质量做完的量有限——超了就拆成两批，"
            "或者干脆逐个派发。"
        )

    st = plan.states()
    ids = {t.id for t in tasks}

    # 依赖检查放在状态检查之前：有内部依赖时该任务必然处于 BLOCKED，
    # 若先查状态，"批次内含依赖"这条更精确的提示就永远出不来。
    for t in tasks:
        inner = ids & set(t.deps)
        if inner:
            raise WorkflowError(
                f"{t.id} 依赖批次内的 {', '.join(sorted(inner))}。"
                "批次是给互不依赖的同型改动用的——有依赖说明它们是顺序工作，"
                "该逐个派发（后一个的审查要看前一个的结果）。"
            )

    for t in tasks:
        state = st[t.id]
        if state == "DONE":
            raise WorkflowError(f"{t.id} 已完成，不能再次纳入批次。")
        if state == "BLOCKED":
            raise WorkflowError(f"{t.id} 当前被阻塞（依赖未完成），不能纳入批次。")

    warnings = []
    seen = {}
    for t in tasks:
        files = [_norm_path(f) for f in t.files]
        if not files:
            warnings.append(
                f"{t.id} 的『文件』字段里析不出路径，文件重叠检查对它无效——"
                "确认它不会和同批其他任务改同一处。"
            )
        for path in files:
            if path in seen and seen[path] != t.id:
                warnings.append(
                    f"{t.id} 与 {seen[path]} 都涉及 {path}——同批改同一文件通常"
                    "说明它们不是同型机械改动，确认一下是否该分开派。"
                )
            seen[path] = t.id
    return warnings


def _task_body(plan, task):
    """抽出一个任务块的原文（到下一个标题为止）。"""
    end = task.line_start + 1
    while end < len(plan.lines) and not re.match(r"^#{2,4}\s", plan.lines[end]):
        end += 1
    return "\n".join(plan.lines[task.line_start:end]).rstrip()


def cmd_slice(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    plan = load_plan(root, slug)
    require_plan_approval(root, slug, plan.path)   # 执行门：方案与计划都须已审批

    ids = list(args.task_id)
    tasks = []
    for tid in ids:
        t = next((x for x in plan.tasks if x.id == tid), None)
        if t is None:
            raise WorkflowError(
                f"计划里没有 {tid}。现有：{', '.join(x.id for x in plan.tasks)}"
            )
        tasks.append(t)

    warnings = validate_batch(plan, tasks) if len(tasks) > 1 else []
    batch = len(tasks) > 1
    label = " + ".join(t.id for t in tasks)

    header = [
        f"# 派发片段：{'批次 ' if batch else ''}{label}",
        "",
        f"**Goal（本工作流）**: {plan.meta.get('Goal', '')}",
    ]
    if batch:
        header += [
            "",
            f"**这是一批 {len(tasks)} 个同型任务，一次做完、一次提交、一次审查。**",
            "按顺序做，每个任务完成后自己先跑一遍它的验收命令再进入下一个。",
        ]
    header += ["", "## 全局约束（逐字遵守）", ""]
    constraints = _section_lines(plan.lines, "全局约束")
    header += constraints or ["- （无）"]

    if batch:
        header += ["", f"## 批次任务（{len(tasks)} 个）"]
        for t in tasks:
            header += ["", _task_body(plan, t)]
    else:
        header += ["", f"## 本任务（{tasks[0].id}）", "", _task_body(plan, tasks[0])]

    deps_ctx = []
    for t in tasks:
        for dep in t.deps:
            if dep in {x.id for x in tasks}:
                continue   # 批次内部依赖已被守卫挡掉
            dt = next((x for x in plan.tasks if x.id == dep), None)
            if dt:
                deps_ctx.append(f"- {dt.id} {dt.title}：{dt.get('接口') or '（未声明接口）'}")
    if deps_ctx:
        header += ["", "## 依赖任务的接口（已完成的上下文）", ""] + deps_ctx

    report_name = f"batch-{'-'.join(t.id for t in tasks)}" if batch else tasks[0].id
    header += [
        "",
        "## 报告契约",
        "",
        f"正文写入 `.workflow/{slug}/reports/{report_name}.md`（详细内容都放这里）。",
        "回话只给 ≤15 行，必须包含：状态（DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED）、",
        "改了哪些文件、跑了什么命令、结果、遗留问题。",
    ]
    if batch:
        header.append(
            f"批次里每个任务（{label}）的完成情况都要说清——哪个 DONE、哪个有保留。"
        )
    header.append("**不要复述本片段内容，不要粘贴大段代码。**")

    result = {
        "slug": slug,
        "tasks": [t.id for t in tasks],
        "batch": batch,
        "warnings": warnings,
        "brief": "\n".join(header),
    }
    text = result["brief"]
    if warnings:
        text = "⚠ " + "\n⚠ ".join(warnings) + "\n\n" + text
    return result, text


def _section_lines(lines, name):
    out, inside, in_fence = [], False, False
    for line in lines:
        if FENCE.match(line):
            in_fence = not in_fence
            if inside:
                continue
        sec = SECTION_HEADER.match(line)
        if sec and not in_fence:
            inside = sec.group(1).strip().startswith(name)
            continue
        if inside:
            if line.strip() and not line.strip().startswith("#"):
                out.append(line)
    return out


def cmd_record(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    plan = load_plan(root, slug)
    require_plan_approval(root, slug, plan.path)   # 与 slice 同一道门，防绕过
    ledger_check_owner(root, slug)

    tasks = []
    for tid in args.task_id:
        t = next((x for x in plan.tasks if x.id == tid), None)
        if t is None:
            raise WorkflowError(f"计划里没有 {tid}。")
        tasks.append(t)

    warnings = validate_batch(plan, tasks) if len(tasks) > 1 else []
    batch = len(tasks) > 1
    status = "complete" if args.verdict == "clean" else "in_progress"

    for t in tasks:
        line_idx = t.field_lines.get("状态")
        if line_idx is None:
            raise WorkflowError(f"{t.id} 缺少『状态』字段行，无法回写。")
        plan.lines[line_idx] = f"- **状态**：{status}"
    with open(plan.path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(plan.lines) + "\n")

    stamp = _now()
    commits = args.commits or "—"
    label = " + ".join(t.id for t in tasks)
    review_note = f"{args.verdict}（批次 {label}）" if batch else args.verdict
    for t in tasks:
        ledger_append(
            root, slug, "完成记录",
            f"| {t.id} | {commits} | {review_note} | {stamp} |",
        )
    if args.note:
        ledger_append(
            root, slug, "裁决", f"| {stamp} | {label} | {args.note} | — |"
        )

    result = {
        "slug": slug,
        "tasks": [t.id for t in tasks],
        "batch": batch,
        "warnings": warnings,
        "status": status,
        "verdict": args.verdict,
        "ledger": ledger_path(root, slug),
    }
    text = (
        f"✓ {label} → {status}（{review_note}），已记账本"
        if batch
        else f"✓ {label} → {status}（{args.verdict}），已记账本"
    )
    if warnings:
        text = "⚠ " + "\n⚠ ".join(warnings) + "\n" + text
    return result, text


def cmd_check(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    plan = load_plan(root, slug)
    findings = check_plan(plan)

    errors = [f for f in findings if f["level"] == "ERROR"]
    warnings = [f for f in findings if f["level"] == "WARNING"]

    result = {
        "slug": slug,
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
    }
    if not findings:
        return result, "✓ 计划检查通过，无发现。"
    lines = []
    for f in errors:
        tag = f"[{f['task']}]" if f["task"] else ""
        lines.append(f"✗ ERROR {tag} {f['message']}")
    for f in warnings:
        tag = f"[{f['task']}]" if f["task"] else ""
        lines.append(f"! WARN  {tag} {f['message']}")
    lines.append("")
    lines.append(f"共 {len(errors)} 个错误、{len(warnings)} 个警告。")
    if errors:
        lines.append("有 ERROR 时不得进入执行轮。")
    return result, "\n".join(lines)


ARTIFACT_TOKEN = re.compile(r"`([^`]+)`")


def audit_coverage(root, plan):
    """核对验证覆盖表：自动化条目声称的产物是否真的存在。

    这一步在 V 轮做而不是 check 做——按 TDD，测试是在执行轮才写出来的，
    P 轮检查时它们还不存在。

    返回 [{target, means, type, status, note}]，status ∈ ok/missing/manual/unknown。
    """
    out = []
    for entry in plan.coverage:
        target, means, typ = entry["target"], entry["means"], entry["type"]
        if typ != "自动化":
            out.append({"target": target, "means": means, "type": typ,
                        "status": "manual", "note": "需人工执行"})
            continue

        tokens = [t for t in ARTIFACT_TOKEN.findall(means)] or [means.strip()]
        checked, missing = [], []
        for tok in tokens:
            parts = tok.split("::")
            path = parts[0].strip()
            symbols = [s.strip() for s in parts[1:] if s.strip()]
            if not path or " " in path:
                continue
            full = os.path.join(root, path)
            if not os.path.exists(full):
                missing.append(f"{path}（文件不存在）")
                continue
            if symbols:
                try:
                    with open(full, encoding="utf-8", errors="ignore") as fh:
                        content = fh.read()
                except OSError:
                    missing.append(f"{tok}（读不到）")
                    continue
                # 支持 file::Class::method 与 file::test_name 两种写法：
                # 逐段核对，任一段找不到才算缺口
                absent = [s for s in symbols if s not in content]
                if absent:
                    missing.append(f"{tok}（文件里没有 {'、'.join(absent)}）")
                    continue
            checked.append(tok)

        if not checked and not missing:
            out.append({"target": target, "means": means, "type": typ,
                        "status": "unknown", "note": "没能从手段里解析出可核对的产物路径"})
        elif missing:
            out.append({"target": target, "means": means, "type": typ,
                        "status": "missing", "note": "；".join(missing)})
        else:
            out.append({"target": target, "means": means, "type": typ,
                        "status": "ok", "note": "、".join(checked)})
    return out


def cmd_verify(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    plan = load_plan(root, slug)
    command = args.command or plan.verify_command

    if not command:
        raise WorkflowError(
            "未声明验证命令。请把命令写进 plan.md 的『验证命令』代码块，"
            "或用 --command 指定。没有可执行的验证命令时不判通过。"
        )

    print(f"$ {command}", file=sys.stderr)
    proc = subprocess.run(
        command, shell=True, cwd=root, capture_output=True, text=True
    )
    code = proc.returncode
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-20:]
    fp = fingerprint(root)
    head = _git(root, "rev-parse", "--short", "HEAD").strip() or "—"
    stamp = _now()
    label = args.label or "verify"

    coverage = audit_coverage(root, plan)
    gaps = [c for c in coverage if c["status"] in ("missing",)]
    manual = [c for c in coverage if c["status"] == "manual"]

    ledger_check_owner(root, slug)
    ledger_append(
        root,
        slug,
        "验证记录",
        f"| {stamp} | {label} | {head} | `{command}` | {code} | {fp} | "
        f"{'PASS' if code == 0 else 'FAIL'} |",
    )

    result = {
        "slug": slug,
        "command": command,
        "exit_code": code,
        "passed": code == 0 and not gaps,
        "commit": head,
        "fingerprint": fp,
        "coverage": coverage,
        "gaps": gaps,
        "manual": manual,
        "output_tail": tail,
        "recorded_at": stamp,
    }
    lines = [
        f"{'✓ PASS' if code == 0 else '✗ FAIL'} (exit {code})  提交 {head}  指纹 {fp}"
    ]
    if tail:
        lines.append("")
        lines += [f"  {l}" for l in tail]

    if coverage:
        auto = [c for c in coverage if c["type"] == "自动化"]
        lines += [
            "",
            f"验证覆盖：{len(auto)} 项自动化 / {len(manual)} 项人工",
        ]
        mark = {"ok": "✓", "missing": "✗", "manual": "·", "unknown": "?"}
        for c in coverage:
            note = f"  （{c['note']}）" if c["note"] else ""
            lines.append(f"  {mark[c['status']]} {c['target']}：{c['means']}{note}")
        if gaps:
            lines += [
                "",
                f"⚠ 有 {len(gaps)} 项自动化覆盖声称的产物不存在——这些决策实际上没有被验证。",
            ]
        if manual:
            lines += [
                "",
                f"其中 {len(manual)} 项需人工执行，逐项确认后才算通过（不给一次性打包确认）。",
            ]
        if plan.exclusions_present:
            excluded = [
                l for l in plan.sections.get("验证覆盖", [])
                if l.startswith("-")
            ]
            if excluded:
                lines += ["", "不验证的部分（见 plan.md）："]
                lines += [f"  {l}" for l in excluded[:6]]

    if code != 0:
        lines += ["", "验证红灯：不得声称完成。"]
    elif gaps:
        lines += ["", "存在覆盖缺口：不得收尾（close 会拒绝）。"]

    return result, "\n".join(lines)


# ---------------------------------------------------------------- 入口

def cmd_close(args):
    """收尾记账。把「没有验证不得声称完成」机械化到收尾这个边界上。"""
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    plan = load_plan(root, slug)
    ledger_check_owner(root, slug)

    st = plan.states()
    incomplete = [t.id for t in plan.tasks if st[t.id] != "DONE"]
    if incomplete:
        raise WorkflowError(
            f"还有未完成的任务（{', '.join(incomplete)}），不得收尾。"
        )

    fp = fingerprint(root)
    manual = (args.manual_confirmed or "").strip()

    if manual:
        evidence = f"人工确认：{manual}"
        verify_fp = "—"
    else:
        records = _read_verify_records(root, slug)
        if not records:
            raise WorkflowError(
                "账本里没有验证记录。先跑 `verify`（或用 --manual-confirmed 记录人工确认），再收尾。"
            )
        last = records[-1]
        if last["result"] != "PASS":
            raise WorkflowError(
                f"最近一次验证是 {last['result']}（{last['time']}），不得收尾。"
                "修好之后重跑 `verify`。"
            )
        if last["fingerprint"] != fp:
            raise WorkflowError(
                f"工作树内容与最近一次验证时不一致"
                f"（验证时 {last['fingerprint']}，当前 {fp}），该验证已失效。"
                "先重跑 `verify` 绑定当前内容，再收尾。"
            )
        coverage = audit_coverage(root, plan)
        gaps = [c for c in coverage if c["status"] == "missing"]
        if gaps:
            detail = "\n".join(f"  - {c['target']}：{c['note']}" for c in gaps)
            raise WorkflowError(
                f"有 {len(gaps)} 项验证覆盖声称的产物不存在，这些决策实际上没有被验证：\n"
                f"{detail}\n补上它们，或把它们移到『不验证的部分』并说明理由，再收尾。"
            )
        evidence = f"验证 {last['fingerprint']}"
        verify_fp = last["fingerprint"]

    stamp = _now()
    ledger_append(
        root,
        slug,
        "收尾",
        f"| {stamp} | {len(plan.tasks)}/{len(plan.tasks)} | {verify_fp} | "
        f"{args.handoff or '—'} | {args.next_step or '—'} |",
    )

    result = {
        "slug": slug,
        "tasks": len(plan.tasks),
        "evidence": evidence,
        "fingerprint": fp,
        "handoff": args.handoff or "",
        "next_step": args.next_step or "",
        "closed_at": stamp,
    }
    lines = [
        f"✓ 已收尾并记账本：{len(plan.tasks)}/{len(plan.tasks)} 任务完成，{evidence}",
    ]
    if args.handoff:
        lines.append(f"  交接：{args.handoff}")
    if args.next_step:
        lines.append(f"  下一步：{args.next_step}")
    return result, "\n".join(lines)


def _add_json(sp):
    """让 --json 在子命令前后都能用；用 SUPPRESS 避免子解析器把顶层的值覆盖回 False。"""
    sp.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS, help="输出 JSON"
    )


def build_parser():
    p = argparse.ArgumentParser(
        prog="workflow.py", description="task-workflow 引擎（确定性操作工作流状态）"
    )
    p.add_argument("--json", action="store_true", help="输出 JSON")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="创建新工作流")
    s.add_argument("slug")
    s.add_argument("--goal", default="")
    s.add_argument("--bug", action="store_true",
                   help="bug 修复工作流：免两道审批门，强制复现/根因/回归测试")
    _add_json(s)
    s.set_defaults(func=cmd_init)

    for name, fn, helptext in [
        ("status", cmd_status, "报告当前阶段与任务状态"),
        ("next", cmd_next, "列出当前可执行的任务（依赖图拓扑）"),
        ("check", cmd_check, "检查计划质量（依赖/覆盖/占位符/规模）"),
        ("verify", cmd_verify, "执行验证命令并留证"),
    ]:
        s = sub.add_parser(name, help=helptext)
        s.add_argument("slug", nargs="?")
        if name == "verify":
            s.add_argument("--command")
            s.add_argument("--label")
        _add_json(s)
        s.set_defaults(func=fn)

    s = sub.add_parser("slice", help="抽出派发片段（可给多个任务合并成一批）")
    s.add_argument("slug", nargs="?")
    s.add_argument("task_id", nargs="+", help="一个或多个任务 ID；多个即为合并批次")
    _add_json(s)
    s.set_defaults(func=cmd_slice)

    s = sub.add_parser("approve", help="记录用户对『方案』或『计划』的审批")
    s.add_argument("slug", nargs="?")
    s.add_argument("stage", choices=["方案", "计划"])
    s.add_argument("--by", required=True, help="审批依据：用户的原话或你如何得到答复")
    _add_json(s)
    s.set_defaults(func=cmd_approve)

    s = sub.add_parser("record", help="记录任务完成并更新状态（可一次记一批）")
    s.add_argument("slug", nargs="?")
    s.add_argument("task_id", nargs="+", help="一个或多个任务 ID")
    s.add_argument("--commits", default="")
    s.add_argument("--verdict", default="clean", choices=["clean", "issues"])
    s.add_argument("--note", default="")
    _add_json(s)
    s.set_defaults(func=cmd_record)

    s = sub.add_parser("close", help="收尾记账（有未验证内容时拒绝）")
    s.add_argument("slug", nargs="?")
    s.add_argument("--handoff", default="", help="交接去向，如 work-closeout / session-handoff")
    s.add_argument("--next-step", default="", help="给用户的下一步建议")
    s.add_argument(
        "--manual-confirmed",
        default="",
        help="无法自动化验证时，记录谁确认了什么（例如「用户逐项确认了 T1/T2 的手工检查项」）",
    )
    _add_json(s)
    s.set_defaults(func=cmd_close)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result, text = args.func(args)
    except WorkflowError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"✗ {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(text)
    if args.cmd == "check" and not result.get("ok", True):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
