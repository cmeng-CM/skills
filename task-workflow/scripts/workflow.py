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
    workflow.py gate    [slug] --reason "<升级原因>"
    workflow.py verify  [slug] [--label <name>]
    workflow.py close   [slug] --next-step "<建议>"

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
import tempfile
import uuid
from datetime import datetime

# ---------------------------------------------------------------- 解析规则

TASK_HEADER = re.compile(r"^####\s+(T\d+)\b\s*(.*)$")
PHASE_HEADER = re.compile(r"^###\s+Phase\s+(\d+)\s*[:：]?\s*(.*)$")
SECTION_HEADER = re.compile(r"^##\s+(.+?)\s*$")
H2_ANYWHERE = re.compile(r"^##\s+(.+?)\s*$", re.M)  # 在整份文本里找二级标题
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

TASK_FIELD_KEYS = ["文件", "依赖", "并行", "做法", "接口", "预期", "验收", "失败信号", "决策", "状态"]
VALID_STATUS = ["pending", "in_progress", "complete", "blocked"]

# 计划格式版本。逐档只加不删，老档按老规则跑完：
#   2 起：任务新增『做法』『预期』两个字段；方案新增『背景与目标』节。
#   3 起：方案只写一遍——声明了设计文档时，`## 方案` 退化为承接 + 增量 + 指针，
#          方案审批的指纹绑设计文档的「一句话方案 / 背景与目标 / 做法 /
#          备选与取舍 / 明确不做」五节（同一份内容写两遍，改一处忘一处）。
# 不写 `**格式**` 的计划按 1 处理——升级前建的、正在进行中的工作流不该被新校验打断。
PLAN_FORMAT_KEY = "格式"
APPROVAL_MODE_KEY = "审批模式"
APPROVAL_MODE_GATED = "gated"
APPROVAL_MODE_EXECUTION = "execution"
PLAN_FORMAT_V2 = 2
PLAN_FORMAT_V3 = 3
PLAN_FORMAT_CURRENT = PLAN_FORMAT_V3

# 设计文档：与状态控制分开的独立产物，必须落在项目仓库里（.workflow/ 自忽略）
DESIGN_DOC_KEY = "设计文档"
DESIGN_DOC_SECTIONS = [
    "一句话方案",
    "背景与目标",
    "做法",
    "备选与取舍",
    "接口与数据形状",
    "明确不做",
    "实际交付",
    "已知限制",
    "验收标准",
    "决策摘要",
]
# 格式 1 的设计文档骨架（本次升级前）：不带「背景与目标」「实际交付」。
# 老文档按这一份校验，避免升级动作把进行中的工作流卡住。
DESIGN_DOC_SECTIONS_V1 = [
    "一句话方案",
    "做法",
    "备选与取舍",
    "接口与数据形状",
    "明确不做",
    "已知限制",
    "验收标准",
    "决策摘要",
]
DESIGN_DOC_MIN_REASON = 10  # 声明「无」时理由的最短长度（挡掉「无 — 不需要」这类凑数）
DESIGN_DOC_NONE_MARKERS = ("无", "不适用", "n/a", "N/A")

# 格式 3：方案的唯一真源。声明了设计文档时，方案审批绑的是文档里这五节，
# 计划只留承接、增量与指针——同一份内容不写两遍。
DESIGN_DOC_PLAN_SECTIONS = [
    "一句话方案",
    "背景与目标",
    "做法",
    "备选与取舍",
    "明确不做",
]

MAX_TASKS = 8          # 超过则建议拆分
MAX_FILES_PER_TASK = 5  # 单任务文件数上限
MAX_BATCH_TASKS = 4     # 同批合并的任务数上限（一个 subagent 一次能高质量做完的量）


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


def _git_ok(root, *args):
    """只关心退出码的 git 命令（如 merge-base --is-ancestor，成功时 stdout 是空的）。"""
    try:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, timeout=30
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


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
    slugs = [s for s in slugs if not lifecycle(root, s)["closed"]]
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
    def approval_mode(self):
        """审批模式：老计划和显式 gated 计划走两道审批门。"""
        mode = (self.meta.get(APPROVAL_MODE_KEY) or APPROVAL_MODE_GATED).strip().lower()
        return mode if mode in (APPROVAL_MODE_GATED, APPROVAL_MODE_EXECUTION) else mode

    @property
    def is_execution(self):
        return self.approval_mode == APPROVAL_MODE_EXECUTION

    @property
    def is_gated(self):
        return self.approval_mode == APPROVAL_MODE_GATED

    @property
    def kind(self):
        """工作流类型：bug 走 bug 补偿路径，其余为 feature。"""
        return (self.meta.get("类型") or "feature").strip().lower()

    @property
    def is_bug(self):
        return self.kind == "bug"

    @property
    def format_version(self):
        """计划格式版本。头部没写 `**格式**` 的项目按 1 处理（升级前建的计划）。"""
        m = re.match(r"(\d+)", (self.meta.get(PLAN_FORMAT_KEY) or "").strip())
        return int(m.group(1)) if m else 1

    @property
    def is_v2(self):
        return self.format_version >= PLAN_FORMAT_V2

    @property
    def is_v3(self):
        return self.format_version >= PLAN_FORMAT_V3

    @property
    def design_doc_sections(self):
        """本计划该按哪份骨架核对设计文档。"""
        return DESIGN_DOC_SECTIONS if self.is_v2 else DESIGN_DOC_SECTIONS_V1

    def _parse(self):
        section = None
        current_task = None
        current_phase = None
        in_fence = False
        verify_buf = []
        collecting_verify = False
        coverage_headers = []

        for idx, line in enumerate(self.lines):
            if FENCE.match(line):
                if section and section.startswith("验证命令"):
                    collecting_verify = not in_fence
                in_fence = not in_fence
                if collecting_verify and not in_fence:
                    collecting_verify = False
                continue

            if collecting_verify:
                verify_buf.append(line)
                continue
            if in_fence:
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

            # 头部字段只在第一个二级标题之前认。进入小节之后，`**承接**：…`
            # 这类行是小节正文，不是头部字段——吞掉它会让 `check` 误报「该节是空的」。
            fld = META_FIELD.match(line)
            if fld and section is None:
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
                        if "对象" in cells and "类型" in cells:
                            coverage_headers = cells
                            continue
                        if len(cells) >= 3 and cells[0] and not cells[0].startswith("--"):
                            mapped = dict(zip(coverage_headers, cells))
                            requirement = mapped.get("必需性", mapped.get("必需", cells[3] if not coverage_headers and len(cells) > 3 else "必需"))
                            required = requirement.lower() not in ("可选", "optional", "否", "false", "no")
                            self.coverage.append(
                                {"id": mapped.get("ID", mapped.get("对象", cells[0])),
                                 "target": mapped.get("对象", cells[0]),
                                 "means": mapped.get("验证手段", cells[1]),
                                 "type": mapped.get("类型", cells[2]),
                                 "required": required,
                                 "evidence": mapped.get("证据", "")}
                            )

            if current_phase and current_task is None:
                cp = META_FIELD.match(line)
                if cp and "heckpoint" in cp.group("key"):
                    self.phases[-1][2] = cp.group("value").strip()

        self.verify_command = "\n".join(verify_buf).strip()
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


# ---------------------------------------------------------------- 设计文档

def _md_section(text, name):
    """取 `## <name>` 一节的正文（到下一个二级标题为止）。找不到返回空串。"""
    buf, collecting = [], False
    for line in text.splitlines():
        m = SECTION_HEADER.match(line)
        if m:
            if collecting:
                break
            collecting = m.group(1).strip() == name
            continue
        if collecting:
            buf.append(line)
    return "\n".join(buf)


def design_doc_decl(plan):
    """解析计划头部的 `**设计文档**` 声明。

    返回 (path, reason)：
      - path 是路径：设计文档落在这里
      - path == ""：声明为「无」，reason 是理由
      - path is None：根本没声明
    """
    raw = (plan.meta.get(DESIGN_DOC_KEY) or "").strip()
    if not raw:
        return None, ""
    for marker in DESIGN_DOC_NONE_MARKERS:
        if raw.startswith(marker):
            reason = raw[len(marker):].lstrip(" \t—-—:：,，.。()（）【】[]").strip()
            return "", reason
    return raw.split()[0].strip("`"), ""


def design_doc_problems(root, plan, stage="plan"):
    """设计文档的问题清单，返回 (errors, warnings)。

    为什么必须落在项目仓库里：`.workflow/` 是自忽略的状态目录，收尾后仍保留，
    但状态控制（计划/账本/报告）不进入版本库。长期设计记录须独立入库，
    半年后仍可通过仓库查阅。

    stage="close" 时额外要求「实际交付」已回写：起草阶段它只能是「无（尚未实现…）」，
    收尾时还那样就等于这次改动到底交付了什么没有记录。
    """
    errors, warnings = [], []
    declared, reason = design_doc_decl(plan)
    sections = plan.design_doc_sections

    if declared is None:
        errors.append(
            "计划头部缺少 `**设计文档**` 声明——设计记录没有归属产物。"
            "写一份（十节骨架见 references/design-doc.md），或写 `无 — <理由>`。"
        )
        return errors, warnings

    if declared == "":
        if len(reason) < DESIGN_DOC_MIN_REASON:
            errors.append(
                "『设计文档』声明为『无』但没给理由（或理由太短）——"
                "写成 `无 — <为什么这次不需要设计文档>`。"
            )
        else:
            warnings.append(f"本次不产出设计文档，理由：{reason}")
        return errors, warnings

    norm = declared.replace("\\", "/").lstrip("/")
    if norm.startswith(".workflow/") or "/.workflow/" in norm:
        errors.append(
            f"设计文档不能放在 `{declared}`——`.workflow/` 是自忽略的状态目录，"
            "记录会保留，但不进入版本库，不能代替长期设计记录。"
            "放到项目仓库里（如 `docs/<模块>方案.md`）。"
        )
        return errors, warnings

    full = os.path.join(root, norm)
    if not os.path.isfile(full):
        errors.append(
            f"声明的设计文档不存在：{declared}——P 轮就要起草（基于已批准的方案），"
            "不是执行完再补。"
        )
        return errors, warnings

    try:
        with open(full, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        errors.append(f"读不到设计文档 {declared}。")
        return errors, warnings

    headings = {m.group(1).strip() for m in H2_ANYWHERE.finditer(text)}
    missing = [s for s in sections if s not in headings]
    if missing:
        errors.append(
            f"设计文档 {declared} 缺必填小节（二级标题）：{'、'.join(missing)}。"
        )
    else:
        # 有标题但正文是空的，等于没写。不适用的小节写「无（<理由>）」——
        # 给诚实的省略留出口，否则会逼出凑数的空话。
        empty = []
        for s in sections:
            body = [
                l for l in _md_section(text, s).splitlines()
                if l.strip() and not l.strip().startswith("<!--")
            ]
            if not body:
                empty.append(s)
        if empty:
            errors.append(
                f"设计文档 {declared} 有 {len(empty)} 个必填小节是空的：{'、'.join(empty)}。"
                "不适用的小节写「无（<理由>）」，不要留空。"
            )

    for idx, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        for token in PLACEHOLDERS:
            if token in line:
                errors.append(
                    f"设计文档 {declared}:L{idx} 含占位符 '{token}'：{stripped[:60]}"
                )
                break

    summary = _md_section(text, "决策摘要")
    refs = set(DECISION_REF.findall(summary))
    gap = sorted({d["id"] for d in plan.decisions} - refs)
    if gap:
        errors.append(
            f"设计文档的『决策摘要』没有引用 {', '.join(gap)}——"
            "决策不许只留在任务报告或账本里，设计文档必须给出合并视图。"
        )

    # 收尾时「实际交付」必须已回写：起草阶段写「无（尚未实现…）」是合法的，
    # 但带着它收尾就等于这次改动交付了什么没有留下记录。
    if stage == "close" and plan.is_v2:
        body = "\n".join(
            l for l in _md_section(text, "实际交付").splitlines()
            if l.strip() and not l.strip().startswith("<!--")
        ).strip()
        if body.startswith(DESIGN_DOC_NONE_MARKERS):
            errors.append(
                f"设计文档 {declared} 的『实际交付』还是未回写状态——"
                "收尾前把它补成：交付物清单（文件/接口/表/脚本）、与计划的偏离及原因、遗留项。"
                "三个月后读到这份文档的人，只能靠这一节知道当时到底改了什么。"
            )
    return errors, warnings


# ---------------------------------------------------------------- 计划检查

def _plan_subsection(plan, section, sub):
    """取 `## <section>` 里 `### <sub>` 的正文行。

    返回 (是否存在, 正文行列表)。计划解析器已经把各二级节的正文行收集在
    plan.sections 里，这里再按三级标题切一刀。
    """
    found, collecting, body = False, False, []
    for line in plan.sections.get(section, []):
        m = re.match(r"^###\s+(.+?)\s*$", line)
        if m:
            if collecting:
                break
            if m.group(1).strip() == sub:
                found, collecting = True, True
            continue
        if collecting:
            body.append(line)
    return found, body


def check_plan(plan, root=None):
    """返回 [{level, task, message}]，level ∈ ERROR/WARNING/INFO。"""
    out = []
    by_id = {t.id: t for t in plan.tasks}

    def add(level, message, task=None):
        out.append({"level": level, "task": task, "message": message})

    if plan.approval_mode not in (APPROVAL_MODE_GATED, APPROVAL_MODE_EXECUTION):
        add(
            "ERROR",
            f"审批模式必须是 gated 或 execution，当前是『{plan.approval_mode}』。",
        )

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
        if plan.is_v2:
            if not t.get("做法"):
                add(
                    "ERROR",
                    "缺少『做法』字段——执行者只知道改哪些文件，不知道这一步具体做什么；"
                    "它会自己去补设计决策。写清动作、关键取值、边界。",
                    t.id,
                )
            if not t.get("预期"):
                add(
                    "ERROR",
                    "缺少『预期』字段——没有可观察的预期结果，"
                    "做完也无法判断结果是否符合预期（只能判断命令跑没跑过）。",
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

    # 2b. 格式 1 的计划：新字段缺失只提示，不打断进行中的工作流（见 PLAN_FORMAT_KEY）
    if not plan.is_v2:
        legacy = [t.id for t in plan.tasks if not t.get("做法") or not t.get("预期")]
        if legacy:
            add(
                "WARNING",
                f"本计划是格式 1：{', '.join(legacy)} 缺『做法』/『预期』。"
                "这两个字段是升级新增的（执行者需要知道每步做什么、预期看到什么）。"
                "把头部 `**格式**` 改成 2 或更高并补齐，check 就会强制它们；"
                "老计划不补也能继续跑完。",
            )

    # 2c. 方案的「背景与目标」：为什么做 + 预期结果 + 承接关系
    # bug 路径例外：它的"为什么"已经在 `## 复现` + `## 根因` 两节里，不重复要求。
    found, body = _plan_subsection(plan, "方案", "背景与目标")
    lvl = "ERROR" if plan.is_v2 else "WARNING"
    if not found and not plan.is_bug:
        add(
            lvl,
            "『方案』缺少 `### 背景与目标` 小节——没有它，"
            "读者（和三个月后的你）不知道这个改动为什么做、要做成什么样。"
            "已有设计来源时，这一节还要写明承接关系（源路径 + 继承什么 + 本次增量）。",
        )
    elif found and not body:
        add(lvl, "『方案』的 `### 背景与目标` 是空的——把问题现状与预期结果写上去。")

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
            f"计划有 {len(plan.tasks)} 个任务（上限 {MAX_TASKS}）。"
            "规模直接决定两道门的成败：任务越多，计划越长，人在门上越审不动，"
            "审批就越容易退化成走过场。**首选拆成多个工作流**；确实不拆时，"
            "请在决策表里记一条「接受超限，因为 <理由>——代价是两道门的审阅有效性下降」，"
            "让这个取舍被看见而不是留到事后才发现。",
        )

    # 6. 验证命令
    if not plan.verify_command:
        add(
            "WARNING",
            "未声明验证命令——V 轮需核对非空人工/豁免验收；必验自动化仍须命令，bug 不允许未声明。",
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

    # 9. 设计文档：独立产物，落在项目仓库里（root 缺失时只查声明）
    if root is not None:
        doc_errors, doc_warnings = design_doc_problems(root, plan)
        for msg in doc_errors:
            add("ERROR", msg)
        for msg in doc_warnings:
            add("WARNING", msg)

    return out


# ---------------------------------------------------------------- 账本

def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def ledger_init(root, slug, plan_rel, approval_mode=APPROVAL_MODE_GATED, mode_reason=""):
    path = ledger_path(root, slug)
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode_note = mode_reason.replace("|", "／").replace("\n", " ").strip() or "（未提供）"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            f"""# Ledger: {slug}

Plan: {plan_rel}
Created: {datetime.now().strftime('%Y-%m-%d')}
Approval-mode: {approval_mode}
Approval-basis: {mode_note}

> 恢复时读取计划、旧账本与 git log；新验证、人工结论和生命周期以 events.jsonl 为准，本账本同步呈现。
> 首行的 `Plan:` 用于防止多个工作流串账——首行指向别的计划时，这份账本属于那个计划。
> `Approval-mode` 记录的是审批路径，不是质量豁免：execution 仍须 check、审查、verify 和 close。

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

| 时间 | 完成度 | 指纹 | 下一步 |
|------|-------|------|--------|
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


def design_doc_plan_hash(path, sections):
    """设计文档里承载方案的那几节的联合指纹（格式 3）。"""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    parts = [_md_section(text, name) for name in sections]
    return hashlib.sha256("\n\n".join(parts).encode()).hexdigest()[:16]


def plan_section_target(root, plan):
    """『方案』的载体在哪。

    返回 (kind, path, sections)：
      - ("design", 设计文档绝对路径, 五节名单)：格式 3+ 且声明了设计文档——
        方案的真源在项目仓库的设计文档里，它比计划命长。
      - ("plan", 计划路径, None)：其余情形（格式 ≤2，或设计文档声明为「无」）——
        方案就是计划的 `## 方案` 一节。
    """
    declared, _reason = design_doc_decl(plan)
    if plan.is_v3 and declared:
        return "design", os.path.join(root, declared), DESIGN_DOC_PLAN_SECTIONS
    return "plan", plan.path, None


def plan_section_hash(root, plan):
    """『方案』当前的内容指纹（绑定对象见 plan_section_target）。"""
    kind, path, sections = plan_section_target(root, plan)
    if kind != "design":
        return section_hash(plan.path, "方案")
    if not os.path.isfile(path):
        raise WorkflowError(
            "本计划把『方案』的真源放在设计文档里，但 "
            f"{os.path.relpath(path, root)} 不存在。先起草它的这五节——"
            + " / ".join(sections)
            + "——再走方案门。"
        )
    return design_doc_plan_hash(path, sections)


def _read_ledger_meta(root, slug):
    """读取账本中持久化的路径模式，区分无审批与漏审批。"""
    path = ledger_path(root, slug)
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("Approval-mode:"):
                out["approval_mode"] = line.split(":", 1)[1].strip()
            elif line.startswith("Approval-basis:"):
                out["approval_basis"] = line.split(":", 1)[1].strip()
    return out


def _append_ledger_decision(root, slug, decision, reason):
    stamp = _now()
    ledger_append(root, slug, "裁决", f"| {stamp} | {decision} | {reason} | — |")


def _set_approval_mode(root, slug, plan, mode, reason):
    """切换审批模式并同步计划/账本；不允许静默改模式。"""
    if mode not in (APPROVAL_MODE_GATED, APPROVAL_MODE_EXECUTION):
        raise WorkflowError(f"未知审批模式 '{mode}'。只能是 gated 或 execution。")
    reason = (reason or "").replace("|", "／").replace("\n", " ").strip()
    if not reason:
        raise WorkflowError("切换审批模式必须提供原因。")

    lines = plan.lines[:]
    found = False
    for i, line in enumerate(lines):
        if re.match(r"^\*\*审批模式\*\*\s*[:：]", line):
            lines[i] = f"**审批模式**: {mode}"
            found = True
            break
    if not found:
        insert_at = 0
        while insert_at < len(lines) and (
            not lines[insert_at].strip() or lines[insert_at].startswith("#")
        ):
            insert_at += 1
        lines.insert(insert_at, f"**审批模式**: {mode}")
    with open(plan.path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    plan.lines = lines
    plan.text = "\n".join(lines)
    plan.meta[APPROVAL_MODE_KEY] = mode
    for i, line in enumerate(plan.lines):
        if re.match(r"^\*\*审批模式依据\*\*\s*[:：]", line):
            plan.lines[i] = f"**审批模式依据**: {reason}"
            plan.meta["审批模式依据"] = reason
            break
    with open(plan.path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(plan.lines) + "\n")

    ledger_pathname = ledger_path(root, slug)
    if os.path.isfile(ledger_pathname):
        with open(ledger_pathname, encoding="utf-8") as fh:
            ledger_lines = fh.read().splitlines()
        mode_found = False
        basis_found = False
        for i, line in enumerate(ledger_lines):
            if line.startswith("Approval-mode:"):
                ledger_lines[i] = f"Approval-mode: {mode}"
                mode_found = True
            elif line.startswith("Approval-basis:"):
                ledger_lines[i] = f"Approval-basis: {reason}"
                basis_found = True
        if not mode_found:
            # 老账本没有该元数据时，在 Created 后补上，不破坏既有表格。
            insert_at = next(
                (i + 1 for i, line in enumerate(ledger_lines) if line.startswith("Created:")),
                3,
            )
            ledger_lines.insert(insert_at, f"Approval-mode: {mode}")
        if not basis_found:
            insert_at = next(
                (i + 1 for i, line in enumerate(ledger_lines) if line.startswith("Approval-mode:")),
                4,
            )
            ledger_lines.insert(insert_at, f"Approval-basis: {reason}")
        with open(ledger_pathname, "w", encoding="utf-8") as fh:
            fh.write("\n".join(ledger_lines) + "\n")

    _append_ledger_decision(
        root,
        slug,
        "升级为 gated 审批路径" if mode == APPROVAL_MODE_GATED else "切换为 execution 路径",
        reason,
    )
    return mode


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


def _require_plan_check(plan, root):
    """execution/bug 免审批，但不能免计划结构检查。"""
    errors = [f for f in check_plan(plan, root) if f["level"] == "ERROR"]
    if errors:
        detail = "\n".join(f"  - {f['message']}" for f in errors[:8])
        suffix = "" if len(errors) <= 8 else f"\n  …另有 {len(errors) - 8} 个 ERROR"
        raise WorkflowError(
            f"计划检查未通过（{len(errors)} 个 ERROR），不得执行：\n{detail}{suffix}\n"
            "先运行 `workflow.py check` 修正计划。"
        )


def _effective_approval_mode(root, slug, plan):
    """以账本为准确认审批模式，防止手改计划字段偷偷绕门。"""
    persisted = _read_ledger_meta(root, slug).get("approval_mode")
    declared = plan.approval_mode
    if persisted:
        if persisted not in (APPROVAL_MODE_GATED, APPROVAL_MODE_EXECUTION):
            raise WorkflowError(f"账本里的审批模式无效：{persisted}")
        if declared != persisted:
            raise WorkflowError(
                f"计划声明的审批模式 {declared} 与账本记录的 {persisted} 不一致。"
                "不要手改审批模式；需要升级时运行 `gate <slug> --reason \"...\"`。"
            )
        return persisted
    # 老账本没有模式元数据，兼容规则是 gated；不能靠手加字段获得 execution。
    if declared == APPROVAL_MODE_EXECUTION:
        raise WorkflowError(
            "老账本没有审批模式记录，按 gated 处理；不能手改计划字段切到 execution。"
        )
    return APPROVAL_MODE_GATED


def require_plan_approval(root, slug, plan):
    """执行前的门：gated 校验审批；bug/execution 保留质量控制但不等用户审批。"""
    mode = _effective_approval_mode(root, slug, plan)
    if plan.is_bug or mode == APPROVAL_MODE_EXECUTION:
        _require_plan_check(plan, root)
    if plan.is_bug:
        return {"_skipped": {"time": _now(), "fingerprint": "—", "basis": "bug 工作流免门"}}
    if mode == APPROVAL_MODE_EXECUTION:
        return {
            "_skipped": {
                "time": _now(),
                "fingerprint": "—",
                "basis": "execution 工作流无审批门（仍须 check、审查、verify、close）",
            }
        }

    approvals = _read_approvals(root, slug)

    if "方案" not in approvals:
        raise WorkflowError(
            "『方案』尚未经用户审批，不得进入执行轮。"
            "先把方案呈现给用户审阅，得到明确答复后运行："
            f" workflow.py approve {slug} 方案 --by '<用户的原话或说明>'"
        )
    got = plan_section_hash(root, plan)
    if approvals["方案"]["fingerprint"] != got:
        kind, path, _sections = plan_section_target(root, plan)
        where = (
            f"设计文档 `{os.path.relpath(path, root)}`"
            if kind == "design"
            else "计划的 `## 方案` 一节"
        )
        raise WorkflowError(
            f"『方案』在审批之后被修改过（审批时 {approvals['方案']['fingerprint']}，"
            f"当前 {got}），该审批已失效。方案的正文在{where}，"
            "请把改动呈现给用户，重新审批。"
        )

    if "计划" not in approvals:
        raise WorkflowError(
            "『计划』尚未经用户审批，不得进入执行轮。"
            "先把计划呈现给用户审阅，得到明确答复后运行："
            f" workflow.py approve {slug} 计划 --by '<用户的原话或说明>'"
        )
    want = plan_content_hash(plan.path)
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
                if (len(cells) == 7 and re.fullmatch(r"-?\d+", cells[4])
                        and cells[6] in ("PASS", "FAIL")
                        and re.fullmatch(r"[a-f0-9]{16,64}", cells[5])):
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
    """保守绑定 HEAD、索引/工作树和未跟踪完整内容，排除工作流记账。"""
    h = hashlib.sha256()
    is_git = _git_ok(root, "rev-parse", "--git-dir")
    if os.path.exists(os.path.join(root, ".git")) and not is_git:
        raise WorkflowError("项目含 .git，但无法读取 Git 状态；不能降级为无版本指纹")
    if is_git:
        def git_bytes(*args):
            p = subprocess.run(["git", *args], cwd=root, capture_output=True)
            if p.returncode:
                raise WorkflowError(f"读取工作树失败：git {' '.join(args)}")
            return p.stdout
        head = _git(root, "rev-parse", "--verify", "HEAD").strip()
        h.update(head.encode())
        paths = ["--", ".", ":(exclude).workflow"]
        if head:
            h.update(git_bytes("diff", "--binary", "HEAD", *paths))
        else:
            h.update(git_bytes("diff", "--binary", "--cached", *paths))
            h.update(git_bytes("diff", "--binary", *paths))
        h.update(git_bytes("status", "--porcelain=v1", "-z", "--untracked-files=all", *paths))
        names = git_bytes("ls-files", "--others", "--exclude-standard", "-z", *paths)
        for name in sorted(n for n in names.split(b"\0") if n):
            h.update(name + b"\0")
            _hash_file(h, os.path.join(root, os.fsdecode(name)))
    else:
        for directory, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in (".workflow", ".git"))
            for name in sorted(files):
                path = os.path.join(directory, name)
                h.update(os.path.relpath(path, root).encode() + b"\0")
                _hash_file(h, path)
    return h.hexdigest()


def _hash_file(h, path):
    try:
        if os.path.islink(path):
            h.update(b"symlink\0" + os.fsencode(os.readlink(path)))
            return
        h.update(str(os.path.getsize(path)).encode() + b"\0")
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError as exc:
        raise WorkflowError(f"无法读取证据/工作树文件 {path}：{exc}") from exc


# ---------------------------------------------------------------- 结构化证据（旧账本只读兼容）

EVENT_TYPES = {"start", "verify", "manual", "waiver", "evidence", "close", "reopen"}
VIEW_MARKER = "<!-- workflow-events-view -->"


def events_path(root, slug):
    return os.path.join(workflow_root(root), slug, "events.jsonl")


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def acceptance_fingerprint(plan):
    """保守绑定完整计划语义；只排除任务状态和显式独立证据列。

    不枚举少数验收字段，避免漏掉 Checkpoint、围栏约束或附加验收说明。
    表格规范化只为允许独立引用修正；引用本身另由验证/补证摘要约束。
    """
    canonical, section, evidence_column = [], "", None
    in_fence = False
    for line in plan.lines:
        if FENCE.match(line):
            in_fence = not in_fence
        heading = SECTION_HEADER.match(line) if not in_fence else None
        if heading:
            section = heading.group(1).strip()
            evidence_column = None
        if STATUS_LINE.match(line) and not in_fence:
            continue
        row = TABLE_ROW.match(line) if section.startswith("验证覆盖") and not in_fence else None
        if row:
            cells = [cell.strip() for cell in row.group(1).split("|")]
            if "对象" in cells and "类型" in cells:
                evidence_column = cells.index("证据") if "证据" in cells else None
            if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
                continue
            canonical.append([cell for index, cell in enumerate(cells) if index != evidence_column])
        else:
            canonical.append(line.rstrip())
    return _digest(canonical)


def _legacy_lifecycle(root, slug):
    """只承认可完整识别且无后续执行的旧 close，不给旧 PASS 补造绑定。"""
    path = ledger_path(root, slug)
    plan = load_plan(root, slug)
    result = {"closed": False, "cycle": 1, "legacy": True, "close": None}
    if not os.path.isfile(path):
        return result
    with open(path, encoding="utf-8") as fh:
        text = fh.read().split(VIEW_MARKER)[0]
    section, closes, activities = "", [], []
    time_re = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?")
    for line in text.splitlines():
        heading = SECTION_HEADER.match(line)
        if heading:
            section = heading.group(1)
            continue
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        # 旧表的时间列固定；命令、下一步或备注中的日期绝不能充当事件时间。
        time_index = 3 if section == "完成记录" else 0
        if len(cells) <= time_index or not time_re.fullmatch(cells[time_index]):
            continue
        stamp = cells[time_index].replace("T", " ")
        if section == "收尾":
            if len(cells) == 4 and re.fullmatch(r"\d+/\d+", cells[1]):
                done, total = map(int, cells[1].split("/"))
                if done == total:
                    closes.append({"closed_at": stamp, "tasks": total,
                                   "fingerprint": cells[2], "next_step": cells[3]})
        elif section in ("完成记录", "验证记录", "审批", "审批记录"):
            activities.append(stamp)
    if closes:
        last = max(closes, key=lambda c: c["closed_at"])
        if (last["tasks"] == len(plan.tasks) and plan.tasks
                and all(t.status == "complete" for t in plan.tasks)
                and not any(stamp > last["closed_at"] for stamp in activities)):
            result.update(closed=True, close=last)
    return result


def read_events(root, slug):
    path = events_path(root, slug)
    if not os.path.exists(path):
        return []
    events, seen, cycle, closed = [], set(), 1, False
    try:
        with open(path, encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, 1):
                if not line.endswith("\n"):
                    raise ValueError("事件尾行不完整")
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError("事件必须是对象")
                for key in ("id", "type", "time", "workflow"):
                    if not isinstance(event.get(key), str) or not event[key]:
                        raise ValueError(f"缺少 {key}")
                datetime.fromisoformat(event["time"])
                if (event.get("schema") != 1 or type(event.get("cycle")) is not int
                        or event["type"] not in EVENT_TYPES or event["workflow"] != slug
                        or event["id"] in seen or not isinstance(event.get("data"), dict)):
                    raise ValueError("事件身份或结构无效")
                kind, data = event["type"], event["data"]
                if not events:
                    if kind != "start" or event["cycle"] != 1 or type(data.get("legacy_closed")) is not bool:
                        raise ValueError("缺少有效 start 事件")
                    closed = data["legacy_closed"]
                    if closed:
                        snapshot = data.get("legacy_close")
                        if (not isinstance(snapshot, dict) or not snapshot.get("closed_at")
                                or type(snapshot.get("tasks")) is not int or snapshot["tasks"] <= 0):
                            raise ValueError("旧 close 快照不完整")
                elif kind == "start":
                    raise ValueError("重复 start")
                elif kind == "reopen":
                    if not closed or event["cycle"] != cycle + 1:
                        raise ValueError("重开周期不连续或原周期未关闭")
                    cycle += 1
                    closed = False
                    for key in ("reason", "by", "work", "task"):
                        if not isinstance(data.get(key), str) or not data[key].strip():
                            raise ValueError(f"reopen 缺少 {key}")
                else:
                    if event["cycle"] != cycle or closed:
                        raise ValueError("关闭周期仍写入证据或周期不符")
                    if kind in ("verify", "manual", "waiver", "evidence"):
                        for key in ("fingerprint", "acceptance"):
                            if not isinstance(data.get(key), str) or not re.fullmatch(r"[a-f0-9]{64}", data[key]):
                                raise ValueError(f"缺少有效 {key}")
                    if kind == "verify":
                        if (type(data.get("exit_code")) is not int or not isinstance(data.get("command"), str)
                                or not data["command"].strip() or type(data.get("stable")) is not bool
                                or not isinstance(data.get("receipt"), str)
                                or not isinstance(data.get("receipt_hash"), str)):
                            raise ValueError("验证事件不完整")
                        after = data.get("after")
                        if (not isinstance(after, dict) or set(after) != {"fingerprint", "acceptance"}
                                or any(not isinstance(v, str) or not re.fullmatch(r"[a-f0-9]{64}", v) for v in after.values())
                                or data["stable"] != all(after[k] == data[k] for k in after)
                                or not re.fullmatch(r"[a-f0-9]{64}", data["receipt_hash"])):
                            raise ValueError("验证前后绑定无效")
                        artifacts = data.get("artifacts")
                        if not isinstance(artifacts, dict) or any(not isinstance(refs, list) for refs in artifacts.values()):
                            raise ValueError("验证缺少逐项证据摘要")
                        for refs in artifacts.values():
                            for ref in refs:
                                if (not isinstance(ref, dict) or not isinstance(ref.get("path"), str)
                                        or not isinstance(ref.get("hash"), str)
                                        or not re.fullmatch(r"[a-f0-9]{64}", ref["hash"])):
                                    raise ValueError("验证证据摘要无效")
                    if kind in ("manual", "waiver", "evidence"):
                        for key in ("item", "source"):
                            if not isinstance(data.get(key), str) or not data[key].strip():
                                raise ValueError(f"逐项记录缺少 {key}")
                    if kind == "manual" and (data.get("status") not in ("passed", "rejected") or not isinstance(data.get("by"), str) or not data["by"].strip()):
                        raise ValueError("人工结论无效")
                    if kind == "waiver" and any(not isinstance(data.get(k), str) or not data[k].strip() for k in ("reason", "by")):
                        raise ValueError("豁免缺少依据")
                    if kind == "evidence":
                        if (data.get("verification") not in seen or not isinstance(data.get("references"), list)
                                or not data["references"]):
                            raise ValueError("补证缺少既有验证或引用")
                        for ref in data["references"]:
                            if (not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not ref["path"]
                                    or not isinstance(ref.get("hash"), str) or not re.fullmatch(r"[a-f0-9]{64}", ref["hash"])):
                                raise ValueError("补证引用无效")
                        source = next(e for e in events if e["id"] == data["verification"])
                        if (source["type"] != "verify" or source["cycle"] != cycle
                                or source["data"]["exit_code"] != 0 or not source["data"]["stable"]
                                or any(source["data"][key] != data[key] for key in ("fingerprint", "acceptance"))
                                or any(e["type"] == "verify" for e in events[events.index(source) + 1:])):
                            raise ValueError("补证越过失败/不同版本或绑定了非验证记录")
                    if kind == "close":
                        snapshot = data.get("snapshot")
                        if (not isinstance(snapshot, dict) or not data.get("closed_at")
                                or snapshot.get("passed") is not True or snapshot.get("command_passed") is not True
                                or snapshot.get("cycle") != cycle or type(data.get("tasks")) is not int
                                or data["tasks"] <= 0 or not isinstance(data.get("next_step"), str)
                                or any(snapshot.get(k) != [] for k in ("blockers", "pending", "gaps", "unknown"))
                                or not isinstance(snapshot.get("coverage"), list)
                                or any(not isinstance(snapshot.get(k), str) or not re.fullmatch(r"[a-f0-9]{64}", snapshot[k]) for k in ("fingerprint", "acceptance"))):
                            raise ValueError("close 缺少结论快照")
                        closed = True
                seen.add(event["id"])
                events.append(event)
        if not events:
            raise ValueError("events.jsonl 为空")
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise WorkflowError(f"结构化证据损坏，无法确认，禁止回退旧 PASS：{path}（{exc}）") from exc
    return events


def lifecycle(root, slug, events=None):
    events = read_events(root, slug) if events is None else events
    if not events:
        return _legacy_lifecycle(root, slug)
    start = events[0]
    state = {"closed": start["data"]["legacy_closed"], "cycle": 1,
             "legacy": False, "close": start["data"].get("legacy_close")}
    for event in events[1:]:
        if event["type"] == "close":
            state.update(closed=True, close=event["data"])
        elif event["type"] == "reopen":
            state.update(closed=False, cycle=event["cycle"], close=None)
    return state


def require_active(root, slug):
    state = lifecycle(root, slug)
    if state["closed"]:
        raise WorkflowError("工作流已经 closed。原目标修补先显式 reopen；新目标请 init --from。")
    ledger_check_owner(root, slug)
    return state


def _event(slug, cycle, kind, data):
    return {"schema": 1, "id": uuid.uuid4().hex, "type": kind,
            "time": datetime.now().astimezone().isoformat(timespec="microseconds"),
            "workflow": slug, "cycle": cycle, "data": data}


def _atomic_text(path, text):
    directory = os.path.dirname(path)
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=".workflow-write-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sync_event_view(root, slug, events=None):
    events = read_events(root, slug) if events is None else events
    path = ledger_path(root, slug)
    if not os.path.isfile(path):
        raise WorkflowError(f"账本不存在：{path}")
    with open(path, encoding="utf-8") as fh:
        original = fh.read().split(VIEW_MARKER)[0]
    def cell(value):
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace("|", "&#124;").replace("\n", "<br>").replace("\r", "")
    rows = [VIEW_MARKER, "## 结构化事件（events.jsonl 的只读呈现）", "",
            "| 时间 | 周期 | 类型 | ID | 详情 |", "|---|---|---|---|---|"]
    for event in events:
        data = event["data"]
        if event["type"] == "verify":
            detail = (f"命令：{data['command']}\n退出码：{data['exit_code']}；稳定：{data['stable']}"
                      f"\n工作树：{data['fingerprint']}；验收：{data['acceptance']}\n输出：{data['receipt']}")
        elif event["type"] in ("manual", "waiver"):
            detail = (f"{data['item']}：{data.get('status', 'waived')}；{data.get('reason', '')}"
                      f"\n用户答复：{data['by']}\n来源：{data['source']}")
        elif event["type"] == "close":
            detail = f"{data['tasks']} 项任务；验收通过；下一步：{data['next_step']}"
        else:
            detail = json.dumps(data, ensure_ascii=False, sort_keys=True)
        rows.append("| " + " | ".join(cell(x) for x in [event["time"], event["cycle"], event["type"], event["id"], detail]) + " |")
    _atomic_text(path, original + ("" if original.endswith("\n\n") else "\n") + "\n".join(rows) + "\n")


def append_events(root, slug, new):
    old = read_events(root, slug)
    if not old:
        legacy = _legacy_lifecycle(root, slug)
        start = _event(slug, 1, "start", {"legacy_closed": legacy["closed"], "legacy_close": legacy["close"]})
        new = [start] + new
    # 单控制器写入；一批逐项确认在同一次 append 中保存，读者拒绝任何残缺尾行。
    with open(events_path(root, slug), "a", encoding="utf-8") as fh:
        fh.write("".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in new))
        fh.flush()
        os.fsync(fh.fileno())
    sync_event_view(root, slug)


def _coverage_items(plan):
    items = {}
    for entry in plan.coverage:
        identity = entry["id"]
        if not identity or identity in items:
            raise WorkflowError("验证覆盖的 ID/对象名不唯一；请给每项稳定、唯一的 ID。")
        if entry["type"] not in ("自动化", "人工"):
            raise WorkflowError(f"验收项 {identity} 类型不明；必须为 自动化 或 人工。")
        items[identity] = entry
    return items


def _binding(root, plan):
    return {"fingerprint": fingerprint(root), "acceptance": acceptance_fingerprint(plan)}


def _bound(event, state, binding):
    return (event["cycle"] == state["cycle"]
            and all(event["data"].get(k) == v for k, v in binding.items()))


def _file_digest(path):
    h = hashlib.sha256()
    try:
        if not os.path.isfile(path):
            raise OSError("不是可读取的文件")
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError as exc:
        raise WorkflowError(f"无法读取证据文件 {path}：{exc}") from exc
    return h.hexdigest()


def _receipt(root, slug, event):
    data = event["data"]
    expected = os.path.join(".workflow", slug, "evidence", event["id"] + ".json")
    if data["receipt"] != expected:
        raise WorkflowError("验证输出引用不属于该次验证")
    path = os.path.join(root, expected)
    if _file_digest(path) != data["receipt_hash"]:
        raise WorkflowError("验证输出缺失或损坏，不能补证或收尾")
    try:
        with open(path, encoding="utf-8") as fh:
            receipt = json.load(fh)
        for key in ("command", "exit_code", "fingerprint", "acceptance", "stable", "artifacts"):
            if receipt.get(key) != data[key]:
                raise ValueError(f"{key} 不符")
        if receipt.get("id") != event["id"] or receipt.get("cycle") != event["cycle"]:
            raise ValueError("验证身份不符")
        return receipt
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise WorkflowError(f"验证输出绑定无法确认：{exc}") from exc


def _adopted_references(root, events, verification, item):
    """检查该项完整采纳链，不允许最新引用覆盖历史损坏事实。"""
    references = list(verification["data"]["artifacts"].get(item, []))
    for event in events:
        if (event["type"] == "evidence" and event["cycle"] == verification["cycle"]
                and event["data"]["verification"] == verification["id"]
                and event["data"]["item"] == item):
            references.extend(event["data"]["references"])
    for reference in references:
        try:
            current = _file_digest(os.path.join(root, reference["path"]))
        except WorkflowError as exc:
            raise WorkflowError(f"已采纳证据链存在缺失/损坏产物，不能替换或重复登记放行：{reference['path']}") from exc
        if current != reference["hash"]:
            raise WorkflowError(f"已采纳证据链产物已变化，不能替换或重复登记放行：{reference['path']}")
    return references


def acceptance_state(root, slug, plan, binding=None):
    events = read_events(root, slug)
    state = lifecycle(root, slug, events)
    binding = binding or _binding(root, plan)
    items = _coverage_items(plan)
    current = [e for e in events if e["cycle"] == state["cycle"]]
    valid = [e for e in current if _bound(e, state, binding)]
    verifications = [e for e in current if e["type"] == "verify"]
    latest = verifications[-1] if verifications else None
    blockers, pending, unknown, gaps = [], [], [], []
    if not items:
        blockers.append("验收清单为空，不能静默通过")
    verdicts, waivers, supplements = {}, {}, {}
    for event in valid:
        kind, data = event["type"], event["data"]
        if kind == "manual":
            verdicts[data["item"]] = event
            waivers.pop(data["item"], None)
        elif kind == "waiver":
            waivers[data["item"]] = event
        elif kind == "evidence" and latest and data["verification"] == latest["id"]:
            supplements[data["item"]] = event
    coverage = audit_coverage(root, plan)
    for entry in coverage:
        identity = entry["id"]
        chain_error = None
        if latest and entry["type"] == "自动化" and identity not in waivers:
            try:
                _adopted_references(root, current, latest, identity)
            except WorkflowError as exc:
                chain_error = str(exc)
        if identity in waivers:
            entry.update(status="waived", note=waivers[identity]["data"]["reason"])
        elif chain_error:
            entry.update(status="unknown", note=chain_error)
        elif entry["type"] == "人工":
            verdict = verdicts.get(identity)
            entry["status"] = verdict["data"]["status"] if verdict else "pending"
            if entry["required"] and entry["status"] != "passed":
                pending.append(entry)
        elif identity in supplements:
            refs = supplements[identity]["data"]["references"]
            try:
                for ref in refs:
                    if _file_digest(os.path.join(root, ref["path"])) != ref["hash"]:
                        raise WorkflowError("补证引用内容已变化")
                entry.update(status="ok", note="已关联既有验证：" + latest["id"])
                entry["references"] = refs
            except WorkflowError as exc:
                entry.update(status="unknown", note=str(exc))
        elif entry["status"] == "ok":
            recorded = latest["data"]["artifacts"].get(identity, []) if latest else []
            if not recorded or recorded != entry.get("references", []):
                entry.update(status="unknown", note="引用无原验证内容摘要或内容已变化；先用 evidence 核对关联，不能只凭存在放行")
        if entry["required"] and entry["status"] == "unknown":
            unknown.append(entry)
        if entry["required"] and entry["status"] == "missing":
            gaps.append(entry)
    required_auto = [c for c in coverage if c["required"] and c["type"] == "自动化" and c["status"] != "waived"]
    command_needed = bool(plan.verify_command or required_auto or latest)
    command_ok = not command_needed
    if command_needed:
        if not latest:
            blockers.append("没有绑定当前验收要求的结构化验证；旧 PASS 不能事后补造验收绑定，先核实既有证据")
        elif not _bound(latest, state, binding):
            blockers.append("最近验证的工作树/验收要求已失效；保留原记录，需取得当前版本证据")
        elif latest["data"]["exit_code"] != 0:
            blockers.append("最近验证命令失败，人工确认或逐项豁免不能覆盖命令失败")
        elif latest["data"]["command"].strip() != plan.verify_command.strip():
            blockers.append("实际命令与计划验收命令不符；--command 诊断结果不能替代计划必验命令")
        elif not latest["data"]["stable"]:
            blockers.append("验证期间工作树或验收要求发生变化，结果不能用于收尾")
        else:
            try:
                _receipt(root, slug, latest)
                command_ok = True
            except WorkflowError as exc:
                blockers.append(str(exc))
    elif not items or not (verdicts or waivers):
        blockers.append("无验证命令时，必须有明确验收项和逐项人工结论/用户豁免依据；空验收不通过")
    if pending:
        blockers.append("实现完成，等待人工验收：" + "、".join(c["id"] for c in pending))
    if unknown:
        blockers.append("必验证据待核实：" + "、".join(c["id"] for c in unknown))
    if gaps:
        blockers.append("必验覆盖缺少产物：" + "、".join(c["id"] for c in gaps))
    return {"passed": not blockers, "command_passed": command_ok,
            "command_exit_code": latest["data"]["exit_code"] if latest else None,
            "verification": latest["id"] if latest else None,
            "pending": pending, "manual": [c for c in coverage if c["type"] == "人工"],
            "unknown": unknown, "gaps": gaps, "coverage": coverage, "blockers": blockers,
            **binding, "cycle": state["cycle"]}


def cmd_acceptance(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    plan = load_plan(root, slug)
    items = _coverage_items(plan)
    binding = _binding(root, plan)
    result = {"slug": slug, **binding, "checklist": _digest(binding), "items": list(items.values())}
    lines = ["请依据以下逐项手段/步骤及预期核对；可一次答复明确清单中的多项。",
             f"清单绑定：{result['checklist']}"]
    lines += [f"{c['id']} [{c['type']}, {'必需' if c['required'] else '可选'}] {c['target']}：{c['means']}"
              for c in items.values()]
    return result, "\n".join(lines)


def cmd_confirmation(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    state = require_active(root, slug)
    plan = load_plan(root, slug)
    items = _coverage_items(plan)
    binding = _binding(root, plan)
    if args.checklist != _digest(binding):
        raise WorkflowError("清单已失效或未提供正确绑定；先用 acceptance 展示当前具体清单。")
    if not args.by.strip() or not args.source.strip():
        raise WorkflowError("必须提供用户原答复 --by 和可追溯来源 --source")
    selected = list(dict.fromkeys(args.item))
    events = []
    for identity in selected:
        if identity not in items:
            raise WorkflowError(f"未知验收项 {identity}；用 acceptance 查看唯一 ID/对象名。")
        if args.cmd == "confirm" and items[identity]["type"] != "人工":
            raise WorkflowError(f"{identity} 是自动化项，不能用人工确认替代自动验证。")
        data = {**binding, "item": identity, "by": args.by, "source": args.source,
                "checklist": args.checklist}
        if args.cmd == "confirm":
            data["status"] = args.status
            kind = "manual"
        else:
            if not args.reason.strip():
                raise WorkflowError("豁免必须说明具体理由")
            data["reason"] = args.reason
            kind = "waiver"
        events.append(_event(slug, state["cycle"], kind, data))
    append_events(root, slug, events)
    return {"slug": slug, "items": selected, "events": [e["id"] for e in events]}, "✓ 已逐项记录：" + "、".join(selected)


def cmd_evidence(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    state = require_active(root, slug)
    plan = load_plan(root, slug)
    binding = _binding(root, plan)
    item = _coverage_items(plan).get(args.item)
    if not item or item["type"] != "自动化":
        raise WorkflowError("补证必须指向唯一的自动化验收项")
    events = read_events(root, slug)
    verifications = [e for e in events if e["type"] == "verify" and e["cycle"] == state["cycle"]]
    if not verifications or verifications[-1]["id"] != args.verify:
        raise WorkflowError("补证只能关联当前周期最近一次结构化验证；旧 PASS 缺历史验收绑定，且不得越过后续验证失败")
    latest = verifications[-1]
    if not _bound(latest, state, binding) or latest["data"]["exit_code"] != 0 or not latest["data"]["stable"]:
        raise WorkflowError("该验证失败、期间漂移或工作树/验收要求已改变，不能补证放行")
    _receipt(root, slug, latest)
    _adopted_references(root, events, latest, args.item)
    if not args.source.strip():
        raise WorkflowError("补证必须给出与原验证的关联依据 --source")
    refs = []
    for reference in args.ref:
        path = os.path.abspath(os.path.join(root, reference))
        if os.path.commonpath([os.path.realpath(root), os.path.realpath(path)]) != os.path.realpath(root):
            raise WorkflowError("补证引用须在项目内；不支持无历史绑定的外部结果导入")
        digest = _file_digest(path)
        refs.append({"path": os.path.relpath(path, root), "hash": digest})
    event = _event(slug, state["cycle"], "evidence", {**binding, "item": args.item,
                   "verification": latest["id"], "references": refs, "source": args.source})
    append_events(root, slug, [event])
    return {"slug": slug, "event": event["id"], "verification": latest["id"], "executed": False}, "✓ 已关联既有验证证据；未执行验证命令"


def cmd_reopen(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    state = lifecycle(root, slug)
    if not state["closed"]:
        raise WorkflowError("工作流尚未 closed，无需 reopen")
    if not all(v.strip() for v in (args.reason, args.by, args.work)):
        raise WorkflowError("reopen 必须有原因、用户修补授权和新增工作说明")
    plan = load_plan(root, slug)
    cycle = state["cycle"] + 1
    task_id = "T" + str(max([int(t.id[1:]) for t in plan.tasks] or [0]) + 1)
    event = _event(slug, cycle, "reopen", {"reason": args.reason, "by": args.by,
                   "work": args.work, "task": task_id, "previous_close": state["close"]})
    # 先保存重开事实，即使写计划失败仍保持 open，绝不残留可误收尾的 closed。
    append_events(root, slug, [event])
    text = plan.text.rstrip() + f"\n\n## 阶段（重开周期 {cycle}）\n\n#### {task_id} {args.work.strip()}\n\n"
    values = {"依赖": "无", "并行": "否", "做法": args.work.strip(), "决策": "无", "状态": "pending"}
    for key in TASK_FIELD_KEYS:
        text += f"- **{key}**：{values.get(key, 'TODO（按原目标修补范围补充）')}\n"
    _atomic_text(plan.path, text)
    return {"slug": slug, "cycle": cycle, "task": task_id, "event": event["id"], "closed": False}, f"✓ 已重开周期 {cycle}，保留历史 close；新增 {task_id}，补充计划后执行并重新验收"


def cmd_sync(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    sync_event_view(root, slug)
    return {"slug": slug, "synced": True}, "✓ 已从结构化事件同步账本呈现，旧账本保留"


# ---------------------------------------------------------------- 子命令

def cmd_init(args):
    root = find_project_root()
    slug = args.slug
    if not re.fullmatch(r"[\w][\w.-]*", slug) or slug in (".", ".."):
        raise WorkflowError("slug 必须是单个目录名，不能包含路径或空白")
    if args.from_slug:
        resolve_slug(root, args.from_slug)
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
    approval_mode = APPROVAL_MODE_EXECUTION if args.execution else APPROVAL_MODE_GATED
    if args.bug and args.execution:
        raise WorkflowError("--bug 与 --execution 不能同时使用；bug 使用自身的免门补偿路径。")
    if args.execution and not (args.execution_reason or "").strip():
        raise WorkflowError("--execution 必须同时提供 --execution-reason，说明为何没有新增用户判断。")
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
    # bug 路径不要求 `### 背景与目标`：为什么做已在 `## 复现` + `## 根因` 里
    goal_section = (
        """<!-- bug 路径不写 `### 背景与目标`：为什么做已在 `## 复现` + `## 根因` 两节里 -->

"""
        if args.bug
        else """### 背景与目标

TODO（为什么做 + 做成什么样 + 承接关系。问题现状（现在是什么样、不改会怎样）、
预期结果（做完后谁看到什么不同）、关键约束。**已有设计来源时在这里写明**：
承接哪份文档、继承它的哪些结论、本次增量/修正了什么——有来源就不要从零重写，
缺什么补什么。这一节不写实现细节，做法节不重复动机）

"""
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
**审批模式**: {approval_mode}
**审批模式依据**: {args.execution_reason.strip() if args.execution_reason.strip() else '进入 gated 路径，待方案与计划审阅'}
**Created**: {datetime.now().strftime('%Y-%m-%d')}
**格式**: {PLAN_FORMAT_CURRENT}
**设计文档**: TODO
{('**来源工作流**: ' + args.from_slug) if args.from_slug else ''}
<!-- 项目仓库内的路径（如 docs/<模块>方案.md），十节骨架见 references/design-doc.md。
     不需要设计文档就写「无 — <理由>」。四类情形必须写一份：跨模块改动 /
     新外部依赖或数据模型变化 / 安全·性能·迁移 / 需要先定技术决策才能开工。
     不要放在 .workflow/ 下——那是自忽略的状态目录，记录保留但不代替入库的长期设计文档。

     声明了路径时（格式 3）：方案的正文归这份文档——它的「一句话方案 / 背景与目标 /
     做法 / 备选与取舍 / 明确不做」五节就是方案门的审阅对象，方案审批的指纹也绑在这五节上；
     下面的 `## 方案` 只写承接、增量与指针。声明「无」时，方案四段写在这里。 -->

## 验证命令

```
未声明
```

## 全局约束

- TODO（每条一行，逐字写清确切取值；每个任务的隐含需求都包括本节）
{bug_sections}
## 方案

<!-- 方案只写一遍。声明了设计文档：正文在文档的对应五节里，这一节写承接关系、
     本次增量、以及指向文档的指针；「做法 / 备选与取舍 / 明确不做」各留一行指针即可。
     声明「无」：四段都写在这里。写两遍的代价是改一处忘一处，读者不知道信哪个。 -->

{goal_section}### 做法

TODO（有设计文档：一行指针 + 本次特有的实现机制。无设计文档：2-3 句到一节，
随任务规模伸缩。写清怎么实现，不写文件清单。见 references/plan-format.md）

### 备选与取舍

TODO（有设计文档：一行指针。无设计文档：考虑过的其他做法，以及为什么没选。
只有一种做法时写"无备选"并给理由）

### 明确不做

TODO（有设计文档：一行指针。无设计文档：这次范围外的事。
范围边界是四类敏感决策之一，用户要在这里看到它）

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
- **做法**：TODO（这一步具体做什么：动作 + 关键取值 + 边界/禁止项。判据是「换一个执行者，不追问就能做完」）
- **接口**：consumes 无 / produces 无
- **预期**：TODO（做完后应观察到什么——可观察的行为/产物，不是「实现完成」这类实现细节）
- **验收**：TODO（用什么证明：命令/检查，可判定）
- **失败信号**：TODO（什么现象说明它没做对）
- **决策**：D-01
- **状态**：pending
"""
        )

    ledger_init(root, slug, plan_rel, approval_mode, args.execution_reason.strip())

    result = {
        "root": root,
        "slug": slug,
        "kind": kind,
        "approval_mode": approval_mode,
        "approval_basis": args.execution_reason.strip(),
        "plan": plan_path(root, slug),
        "ledger": ledger_path(root, slug),
        "reports": reports_dir(root, slug),
        "source_workflow": args.from_slug or None,
    }
    note = ""
    if args.bug:
        note = "  bug 路径：免两道审批门，但强制『复现 / 根因 / 回归测试』三项\n"
    elif args.execution:
        note = "  execution 路径：不暂停审批门，但仍强制 check、审查、verify、close\n"
    return result, (
        f"✓ 已创建 .workflow/{slug}/（类型 {kind}，审批模式 {approval_mode}）\n"
        f"  计划：{result['plan']}\n  账本：{result['ledger']}\n{note}"
    )


def cmd_status(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    plan = load_plan(root, slug)
    ledger_check_owner(root, slug)
    approval_mode = _effective_approval_mode(root, slug, plan)
    st = plan.states()
    counts = {}
    for state in st.values():
        counts[state] = counts.get(state, 0) + 1

    phase = plan.current_phase()
    life = lifecycle(root, slug)
    acceptance = None
    if life["closed"]:
        stage = "closed（已收尾）"
    elif not plan.tasks:
        stage = "P（计划未成形）"
    elif counts.get("DONE", 0) == len(plan.tasks):
        stage = "V（执行完毕，待验证）"
        acceptance = acceptance_state(root, slug, plan)
        if acceptance["passed"]:
            stage = "V（验收通过，待收尾）"
        elif acceptance["unknown"]:
            stage = "V（证据待核实）"
        elif acceptance["command_exit_code"] not in (None, 0):
            stage = "V（自动验证失败）"
        elif acceptance["pending"] and acceptance["command_passed"]:
            stage = "V（实现完成，等待人工验收）"
    else:
        stage = "E（执行中）"

    result = {
        "root": root,
        "slug": slug,
        "stage": stage,
        "closed": life["closed"],
        "cycle": life["cycle"],
        "close": life["close"],
        "acceptance": acceptance,
        "kind": plan.kind,
        "approval_mode": approval_mode,
        "approval_path": (
            "bug（免审批，受复现/根因/回归测试约束）"
            if plan.is_bug
            else ("execution（无审批门，保留全部质量控制）" if approval_mode == APPROVAL_MODE_EXECUTION else "gated（方案门 + 计划门）")
        ),
        "approval_basis": plan.meta.get("审批模式依据", ""),
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
        f"类型：{plan.kind}；路径：{result['approval_path']}",
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


def cmd_gate(args):
    """把 execution 工作流升级为 gated，记录原因后恢复两道审批门。"""
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    require_active(root, slug)
    plan = load_plan(root, slug)
    ledger_check_owner(root, slug)
    reason = (args.reason or "").strip()
    if not reason:
        raise WorkflowError("升级为 gated 必须用 --reason 说明触发了什么新的判断。")
    if plan.is_bug:
        raise WorkflowError(
            "bug 工作流不能用 gate 切换；命中升级条件时，应按完整路径新建或承接 feature 工作流。"
        )
    current_mode = _effective_approval_mode(root, slug, plan)
    if current_mode == APPROVAL_MODE_GATED:
        raise WorkflowError("该工作流已经是 gated 审批路径，无需重复升级。")
    _set_approval_mode(root, slug, plan, APPROVAL_MODE_GATED, reason)
    return (
        {"slug": slug, "approval_mode": APPROVAL_MODE_GATED, "reason": reason},
        f"✓ 工作流 {slug} 已升级为 gated；原因：{reason}\n"
        "  后续 slice/record 前须分别完成方案门与计划门。",
    )


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
    require_active(root, slug)
    plan = load_plan(root, slug)
    ledger_check_owner(root, slug)

    approval_mode = _effective_approval_mode(root, slug, plan)
    if approval_mode == APPROVAL_MODE_EXECUTION:
        raise WorkflowError(
            "execution 工作流按设计不走方案/计划审批，不能伪造 approve 记录。"
            "若执行中出现新的范围、设计或取舍判断，先运行 `gate <slug> --reason \"...\"` 升级。"
        )

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
        kind, path, sections = plan_section_target(root, plan)
        if kind == "design":
            if not os.path.isfile(path):
                raise WorkflowError(
                    f"『方案』的载体是设计文档（{os.path.relpath(path, root)}）的五节："
                    + " / ".join(sections)
                    + "。文件还不存在，无可审批内容——先起草它，再走方案门。"
                )
            with open(path, encoding="utf-8") as fh:
                doc = fh.read()
            body = "\n".join(_md_section(doc, name) for name in sections)
            if not body.strip() or "TODO" in body:
                raise WorkflowError(
                    "设计文档里承载方案的五节还是空的（或含 TODO），无可审批内容。"
                    "方案门审的就是这五节：一句话方案 / 背景与目标 / 做法 / 备选与取舍 / 明确不做。"
                )
            fp = design_doc_plan_hash(path, sections)
        else:
            body = _section_lines(plan.lines, "方案")
            if not body or any("TODO" in l for l in body):
                raise WorkflowError("『方案』一节还是空的（或含 TODO），无可审批内容。")
            fp = section_hash(plan.path, "方案")
    else:
        findings = [f for f in check_plan(plan, root) if f["level"] == "ERROR"]
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
        "kind": plan.kind,
        "approval_mode": approval_mode,
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
    require_active(root, slug)
    plan = load_plan(root, slug)
    require_plan_approval(root, slug, plan)   # 执行门：方案与计划都须已审批

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

    header += [
        "",
        "## 提交契约（完成的一部分）",
        "",
        "- 做完**自己提交**：只 stage 你改过的文件（逐个写明路径，"
        "**不要 `git add -A` / `git add .`**——那会把工作树里别人的改动一起带走）",
        "- 提交信息用 `T<N>: <任务名>`（批次写 `T3+T4: <批次名>`），正文一两句说清改了什么",
        "- **不要攒到最后**：单任务至少一次提交；批次一次提交即可，但批次内部也要按顺序做",
        "- **不要 push / merge / rebase / 改历史**——远端动作由用户在确认后单独做",
        f"- 报告里给出提交范围 `<base7>..<head7>`（本任务的 base 是 `{_git(root, 'rev-parse', '--short', 'HEAD').strip() or 'HEAD'}`）",
    ]

    doc_decl, _doc_reason = design_doc_decl(plan)
    if doc_decl:
        header += [
            "",
            "## 设计文档（设计以它为准）",
            "",
            f"`{doc_decl}`",
            "动手前读它的「接口与数据形状」一节——那是权威签名，不要自己另定"
            "（参考型小节，可能排在文档末尾）。",
            "顺手扫一眼「背景与目标」：知道为什么做这个改动，遇到本任务没覆盖的边界时，",
            "按它写的目标判断，而不是自己发明。",
            "**不要修改该文档**（回写由控制器在末尾统一做）；发现它和代码不符，",
            "在报告里记一条「文档与实现不符：<文档第几节> → <实际是什么>」。",
        ]

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
        "",
        "**报告只装证据，不装判断**：命令与退出码、产物路径、实测结果、与计划的偏离、",
        "阻塞、待人工验收的部分。技术选择与边界裁定必须显式交出来，写成",
        "`候选决策：<选择> — <理由> — <代价>`，由控制器归位到设计文档或计划；",
        "**工作流记录收尾后保留，但不进入版本库；长期设计判断必须另行归位。**",
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


def _check_commit_range(root, raw, plan, has_note):
    """校验 record 的 `--commits <base>..<head>`，返回 [(level, message)]。

    为什么值得校验：提交范围是账本里「这个任务改了什么」的唯一记录，终审也按它取
    diff。空范围（base == head）或写错的 sha 会让这两件事同时失效，而账本本身看不出来。

    **阶段性提交**是硬要求：每个任务完成即提交，别把几个任务攒成一次。
    格式 2 的计划按 ERROR 拦；老计划降为 WARNING——那批计划可能是按「不提交」的
    约定跑起来的（有的项目全局约束就写着"提交只在用户明确要求时做"），不该被升级打断。
    """
    out = []

    def add(level, message):
        if level == "ERROR" and not plan.is_v2:
            level = "WARNING"
        out.append((level, message))

    if not _git_ok(root, "rev-parse", "--git-dir"):
        add("WARNING", "当前目录不是 git 仓库，提交范围没有校验。")
        return out

    raw = (raw or "").strip()
    if not raw or raw in ("—", "-"):
        add(
            "ERROR",
            "record 必须给 `--commits <base>..<head>`："
            "阶段性提交是硬要求（任务完成即提交，不攒到最后）。",
        )
        return out

    if ".." not in raw:
        add("ERROR", f"--commits 期望 `<base>..<head>` 形式，收到 '{raw}'。")
        return out

    base, _, head = raw.partition("..")
    base, head = base.strip(), head.strip()

    for label, rev in (("base", base), ("head", head)):
        if not rev:
            add("ERROR", f"--commits 的 {label} 是空的。")
            return out
        if not _git(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").strip():
            add("ERROR", f"--commits 里的 {label} '{rev}' 在这个仓库里查不到。")
            return out

    if _git(root, "rev-parse", f"{base}^{{commit}}") == _git(
        root, "rev-parse", f"{head}^{{commit}}"
    ):
        if has_note:
            add(
                "WARNING",
                "本任务没有产生提交（base 与 head 指向同一个提交）——"
                "已按 `--note` 记下理由。",
            )
        else:
            add(
                "ERROR",
                "本任务没有产生提交（base 与 head 指向同一个提交）。"
                "确实无需改动时，把理由写进 `--note \"<为什么这个任务没有产生提交>\"` 即可放行。",
            )
        return out

    if not _git_ok(root, "merge-base", "--is-ancestor", base, head):
        add("ERROR", f"base '{base}' 不是 head '{head}' 的祖先——范围写反了或跨了分支。")

    if not _git_ok(root, "merge-base", "--is-ancestor", head, "HEAD"):
        add(
            "WARNING",
            f"head '{head}' 不在当前 HEAD 的历史里（可能 rebase 过，或提交在别的分支）"
            "——确认这个范围确实属于本任务。",
        )
    return out


def cmd_record(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    require_active(root, slug)
    plan = load_plan(root, slug)
    require_plan_approval(root, slug, plan)   # 与 slice 同一道门，防绕过
    ledger_check_owner(root, slug)

    tasks = []
    for tid in args.task_id:
        t = next((x for x in plan.tasks if x.id == tid), None)
        if t is None:
            raise WorkflowError(f"计划里没有 {tid}。")
        tasks.append(t)

    commit_problems = _check_commit_range(root, args.commits, plan, bool(args.note))
    blockers = [m for lvl, m in commit_problems if lvl == "ERROR"]
    if blockers:
        detail = "\n".join(f"  - {m}" for m in blockers)
        raise WorkflowError(
            f"提交范围不合法，先修正再记账：\n{detail}\n"
            "（提交范围是账本里「这个任务改了什么」的唯一记录，"
            "终审也按它取 diff——空范围或写错的 sha 会让这两件事同时失效。）"
        )

    warnings = validate_batch(plan, tasks) if len(tasks) > 1 else []
    warnings += [m for lvl, m in commit_problems if lvl == "WARNING"]
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

    # 阶段末提醒：本次记录让某个阶段的任务全部完成了 → 把该阶段的 Checkpoint 摆出来。
    # 只提醒、不校验——"检查点成立没成立"要人判，引擎查不了；给它假的强制力比不验更坏。
    done_ids = {t.id for t in tasks}
    finished = None
    for num, name, cp in plan.phases:
        ptasks = [t for t in plan.tasks if t.phase == num]
        if ptasks and any(t.id in done_ids for t in ptasks) and all(
            plan.states()[t.id] == "DONE" for t in ptasks
        ):
            finished = (num, name, cp)

    result = {
        "slug": slug,
        "tasks": [t.id for t in tasks],
        "batch": batch,
        "warnings": warnings,
        "status": status,
        "verdict": args.verdict,
        "ledger": ledger_path(root, slug),
        "phase_completed": (
            {"num": finished[0], "name": finished[1], "checkpoint": finished[2]}
            if finished
            else None
        ),
    }
    text = (
        f"✓ {label} → {status}（{review_note}），已记账本"
        if batch
        else f"✓ {label} → {status}（{args.verdict}），已记账本"
    )
    if warnings:
        text = "⚠ " + "\n⚠ ".join(warnings) + "\n" + text
    if finished:
        num, name, cp = finished
        text += (
            f"\n\n▸ Phase {num}「{name}」的任务已全部完成——**推进下一阶段前逐条核对检查点**："
            f"\n  {cp if cp else '（本阶段没写 Checkpoint，补上：本阶段做完该看到什么）'}"
            f"\n  核对结论记进账本「裁决」区。引擎只提醒，不替你判它成立不成立。"
        )
    return result, text


def cmd_check(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    plan = load_plan(root, slug)
    findings = check_plan(plan, root)

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
    """检查自动化引用的存在性；语义覆盖仍由独立审查判断。"""
    out = []
    for entry in plan.coverage:
        current = dict(entry)
        if entry["type"] == "人工":
            current.update(status="manual", note="需人工执行")
            out.append(current)
            continue
        means = entry["means"]
        reference = entry.get("evidence", "") or means
        tokens = ARTIFACT_TOKEN.findall(reference) or [reference.strip()]
        checked, missing, references = [], [], []
        for token in tokens:
            parts = token.split("::")
            path = parts[0].strip()
            symbols = [s.strip() for s in parts[1:] if s.strip()]
            if not path or " " in path or "\n" in path:
                continue
            full = os.path.join(root, path)
            if not os.path.exists(full):
                missing.append(f"{path}（文件不存在）")
                continue
            if symbols:
                try:
                    with open(full, encoding="utf-8") as fh:
                        content = fh.read()
                    absent = [symbol for symbol in symbols if symbol not in content]
                    if absent:
                        missing.append(f"{token}（文件里没有 {'、'.join(absent)}）")
                        continue
                except (OSError, UnicodeError):
                    missing.append(f"{token}（读不到）")
                    continue
            try:
                references.append({"path": os.path.relpath(os.path.abspath(full), root),
                                   "hash": _file_digest(full)})
            except WorkflowError as exc:
                missing.append(str(exc))
                continue
            checked.append(token)
        current["references"] = references
        if missing:
            current.update(status="missing", note="；".join(missing))
        elif checked:
            current.update(status="ok", note="、".join(checked))
        else:
            current.update(status="unknown", note="没有可核对的产物引用，优先关联既有验证证据")
        out.append(current)
    return out


def cmd_verify(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    state = require_active(root, slug)
    plan = load_plan(root, slug)
    _coverage_items(plan)
    command = args.command if args.command is not None else plan.verify_command
    before = _binding(root, plan)
    if not command.strip():
        result = acceptance_state(root, slug, plan, before)
        result.update(slug=slug, command="", exit_code=None, executed=False)
        return result, "无验证命令；" + ("逐项验收通过" if result["passed"] else "；".join(result["blockers"]))
    print(f"$ {command}", file=sys.stderr)
    proc = subprocess.run(command, shell=True, cwd=root, capture_output=True, text=True, errors="replace")
    after = _binding(root, load_plan(root, slug))
    coverage = audit_coverage(root, load_plan(root, slug))
    event = _event(slug, state["cycle"], "verify", {**before,
                   "command": command, "exit_code": proc.returncode,
                   "stable": before == after, "after": after,
                   "label": args.label or "verify",
                   "artifacts": {c["id"]: c.get("references", []) for c in coverage if c["type"] == "自动化"},
                   "commit": _git(root, "rev-parse", "HEAD").strip() or "—"})
    directory = os.path.join(workflow_root(root), slug, "evidence")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, event["id"] + ".json")
    receipt = {**event["data"], "id": event["id"], "cycle": state["cycle"],
               "workflow": slug, "stdout": proc.stdout, "stderr": proc.stderr}
    _atomic_text(path, json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
    event["data"].update(receipt=os.path.relpath(path, root), receipt_hash=_file_digest(path))
    append_events(root, slug, [event])
    result = acceptance_state(root, slug, load_plan(root, slug), after)
    result.update(slug=slug, event=event["id"], command=command, exit_code=proc.returncode,
                  commit=event["data"]["commit"], executed=True,
                  output_tail=(proc.stdout + proc.stderr).splitlines()[-20:], recorded_at=event["time"])
    lines = [f"命令退出 {proc.returncode}；整体验收 {'PASS' if result['passed'] else '待处理'}；验证 {event['id']}"]
    lines += result["blockers"]
    lines += result["output_tail"]
    return result, "\n".join(lines)


def cmd_close(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    plan = load_plan(root, slug)
    ledger_check_owner(root, slug)
    state = lifecycle(root, slug)
    if state["closed"]:
        return {"slug": slug, "closed": True, "already_closed": True,
                "cycle": state["cycle"], "close": state["close"]}, "✓ 已收尾；保留原结论，未重复记账"
    if args.manual_confirmed.strip():
        raise WorkflowError("--manual-confirmed 不再作为泛确认旁路；先 acceptance 展示清单，再 confirm --item 逐项登记既有用户答复")
    incomplete = [t.id for t in plan.tasks if t.status != "complete"]
    if not plan.tasks or incomplete:
        raise WorkflowError("没有完整任务或仍有未完成任务：" + "、".join(incomplete))
    doc_errors, _warnings = design_doc_problems(root, plan, stage="close")
    if doc_errors:
        raise WorkflowError("设计文档未就绪：" + "；".join(doc_errors))
    result = acceptance_state(root, slug, plan)
    if not result["passed"]:
        raise WorkflowError("不得收尾：" + "；".join(result["blockers"]))
    stamp = datetime.now().astimezone().isoformat(timespec="microseconds")
    data = {"snapshot": result, "closed_at": stamp, "tasks": len(plan.tasks),
            "next_step": args.next_step, "goal": plan.meta.get("Goal", "")}
    event = _event(slug, state["cycle"], "close", data)
    append_events(root, slug, [event])
    return {"slug": slug, "closed": True, "cycle": state["cycle"], "event": event["id"], **data}, "✓ 全部必验项已通过/明确豁免，已保存收尾快照"


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
    s.add_argument("--from", dest="from_slug", help="新目标关联来源工作流，不改变原工作流")
    s.add_argument("--bug", action="store_true",
                   help="bug 修复工作流：免两道审批门，强制复现/根因/回归测试")
    s.add_argument(
        "--execution",
        action="store_true",
        help="执行型工作流：不暂停审批门，但仍执行 check、审查、验证和收尾",
    )
    s.add_argument(
        "--execution-reason",
        default="",
        help="execution 模式的依据：说明范围/规则已明确且没有新增用户判断",
    )
    _add_json(s)
    s.set_defaults(func=cmd_init)

    for name, fn, helptext in [
        ("status", cmd_status, "报告当前阶段与任务状态"),
        ("next", cmd_next, "列出当前可执行的任务（依赖图拓扑）"),
        ("check", cmd_check, "检查计划质量（依赖/覆盖/占位符/规模）"),
        ("verify", cmd_verify, "执行验证命令并留证"),
        ("acceptance", cmd_acceptance, "展示验收清单及工作树/要求绑定"),
        ("sync", cmd_sync, "从 events.jsonl 重建账本呈现"),
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

    s = sub.add_parser("gate", help="把 execution 工作流升级为 gated 审批路径")
    s.add_argument("slug", nargs="?")
    s.add_argument("--reason", required=True, help="升级原因：新增的范围、设计或取舍判断")
    _add_json(s)
    s.set_defaults(func=cmd_gate)

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
    s.add_argument("--next-step", default="", help="给用户的下一步建议")
    s.add_argument(
        "--manual-confirmed",
        default="",
        help="兼容参数；活跃工作流须改用 acceptance + confirm 逐项登记，不能绕过自动失败",
    )
    _add_json(s)
    s.set_defaults(func=cmd_close)

    for name in ("confirm", "waive"):
        s = sub.add_parser(name, help="逐项记录人工结论" if name == "confirm" else "逐项记录用户明确豁免")
        s.add_argument("slug", nargs="?")
        s.add_argument("--item", action="append", required=True, help="唯一验收 ID/对象名；可重复指定")
        s.add_argument("--checklist", required=True, help="acceptance 返回的当前清单绑定")
        s.add_argument("--by", required=True, help="用户的具体答复")
        s.add_argument("--source", required=True, help="可追溯的答复来源；允许引用已有授权")
        if name == "confirm":
            s.add_argument("--status", choices=["passed", "rejected"], default="passed")
        else:
            s.add_argument("--reason", required=True)
        _add_json(s)
        s.set_defaults(func=cmd_confirmation)

    s = sub.add_parser("evidence", help="关联最近一次验证的证据引用，不执行命令")
    s.add_argument("slug", nargs="?")
    s.add_argument("--verify", required=True, help="当前周期最近一次结构化验证 ID")
    s.add_argument("--item", required=True)
    s.add_argument("--ref", action="append", required=True, help="项目内的既有证据路径，可多次指定")
    s.add_argument("--source", required=True, help="该引用和原验证的关联依据")
    _add_json(s)
    s.set_defaults(func=cmd_evidence)

    s = sub.add_parser("reopen", help="原目标修补重开新周期，保留历史 close")
    s.add_argument("slug", nargs="?")
    s.add_argument("--reason", required=True)
    s.add_argument("--by", required=True, help="用户明确请求修补的原话/依据")
    s.add_argument("--work", required=True, help="原目标内新增工作，生成待完善的任务条目")
    _add_json(s)
    s.set_defaults(func=cmd_reopen)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result, text = args.func(args)
    except (WorkflowError, OSError, UnicodeError) as exc:
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
    if args.cmd == "verify" and not result.get("passed", False):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
