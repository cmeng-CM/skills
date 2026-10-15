#!/usr/bin/env python3
"""task-workflow 引擎。

确定性地操作 <project>/.workflow/<slug>/ 下的状态文件：解析计划的依赖图、
计算可执行任务、切分派发片段、记录账本、检查计划质量、执行验证并留证。

用法：
    workflow.py init    <slug> --goal "..."
    workflow.py status  [slug]
    workflow.py next    [slug]
    workflow.py slice   [slug] <task-id>
    workflow.py record  [slug] <task-id> --commits <range> --verdict <clean|issues>   （格式 ≤3）
    workflow.py record  [slug] <task-id> --commits <range> --evidence "<验收与结果>" --operation-id <id>  （格式 ≥4，两态记账）
    workflow.py review  [slug] <N1> --verdict <pass|fail> --commits <range> --lines "<T1: 结论＋依据；…>" --evidence "<引用>" --operation-id <id>  （格式 ≥4，节点审查）
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
COVERAGE_COLUMNS = {"对象", "验证手段", "类型", "ID", "必需性", "必需", "证据"}
COVERAGE_REQUIRED_COLUMNS = {"对象", "验证手段", "类型"}


def _table_separator(cells):
    return bool(cells) and all(re.fullmatch(r":?-+:?", cell) for cell in cells)


def _coverage_header_problems(cells):
    problems = []
    if len(set(cells)) != len(cells):
        problems.append("列名重复")
    missing = COVERAGE_REQUIRED_COLUMNS - set(cells)
    if missing:
        problems.append("缺少表头：" + "、".join(sorted(missing)))
    unsupported = set(cells) - COVERAGE_COLUMNS
    if unsupported:
        problems.append("不支持/无法解释的列：" + "、".join(sorted(unsupported)))
    if "必需" in cells and "必需性" in cells:
        problems.append("必需与必需性是同一语义，不能同时声明")
    return problems

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
# 格式 ≥4：两态记账（D-03/D-04）。`record` 记「已实现」，节点 `review` 通过后成员
# 任务才映射 `complete`；`in_progress`/`blocked` 在格式 ≥4 下没有写入口——留着只会
# 掩盖投影不一致，一律判非法。格式 ≤3 沿用原集合与原行为（逐字不变）。
VALID_STATUS_V4 = ["pending", "implemented", "complete"]
STATUS_PENDING = "pending"
STATUS_IMPLEMENTED = "implemented"
STATUS_COMPLETE = "complete"

# 计划格式版本。逐档只加不删，老档按老规则跑完：
#   2 起：任务新增『做法』『预期』两个字段；方案新增『背景与目标』节。
#   3 起：方案只写一遍——声明了设计文档时，`## 方案` 退化为承接 + 增量 + 指针，
#          方案审批的指纹绑设计文档的「一句话方案 / 背景与目标 / 做法 /
#          备选与取舍 / 明确不做」五节（同一份内容写两遍，改一处忘一处）。
#   4 起：计划新增 `## 审查节点` 段——审查单位从任务改为节点（节点是验收单位、
#          任务是执行单位）。该段只在格式 ≥4 解析与校验；`init` 默认仍写 3
#          （首版 opt-in，见 D-13），旧计划不解析此段、不新增校验。
# 不写 `**格式**` 的计划按 1 处理——升级前建的、正在进行中的工作流不该被新校验打断。
PLAN_FORMAT_KEY = "格式"
APPROVAL_MODE_KEY = "审批模式"
APPROVAL_MODE_GATED = "gated"
APPROVAL_MODE_EXECUTION = "execution"
PLAN_FORMAT_V2 = 2
PLAN_FORMAT_V3 = 3
PLAN_FORMAT_V4 = 4
PLAN_FORMAT_CURRENT = PLAN_FORMAT_V3

# 审查节点（格式 ≥4）：节点块＝`### N<n> <名称>`（块标题即节点 ID）
# ＋ 六项必填字段（归属任务 / 分组理由 / 审查职责 / 依赖节点 / 送审条件 / 兼任终审）
# ＋ 一个可选字段（前身）。块内未知字段忽略（前向兼容）。
NODE_SECTION = "审查节点"
NODE_HEADER = re.compile(r"^###\s+(N\d+)\s*(.*)$")
NODE_FIELD = re.compile(r"^(?:-\s+)?\*\*(?P<key>[^*]+?)\*\*\s*[:：]\s*(?P<value>.*)$")
NODE_REQUIRED_FIELDS = ("归属任务", "分组理由", "审查职责", "依赖节点", "送审条件", "兼任终审")
NODE_FINAL_VALUES = ("是", "否")
# 三个列表字段（归属任务 / 依赖节点 / 前身）共用的严格值解析：
# 先剥离一个尾部括号注解（`无（原 N3 已并入）` → `无`、`N0（原谱系 L1）` → `N0`，
# 注解里的 ID 不参与声明——否则一句说明会被读成真依赖或多前身），再按
# 「无 | 分隔符分隔的 ID 列表」逐项全匹配；残余无法解析的值报 ERROR，
# 不静默降级为空集（依赖缺失比多一条报错更难查）。
NODE_LIST_SEPARATOR = re.compile(r"\s*[,，、;；]\s*")
NODE_ANNOTATION = re.compile(r"[（(][^（()）]*[）)]\s*$")
NODE_NONE = "无"
TASK_ID_PATTERN = r"T\d+"
NODE_ID_PATTERN = r"N\d+"
PREDECESSOR_PATTERN = r"[A-Za-z][A-Za-z0-9_-]*"
NODE_LIST_FIELDS = (
    ("归属任务", TASK_ID_PATTERN),
    ("依赖节点", NODE_ID_PATTERN),
    ("前身", PREDECESSOR_PATTERN),
)
REF_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
HISTORY_NODE_KEYS = ("节点", "node")
HISTORY_LINEAGE_KEYS = ("谱系", "lineage")
HISTORY_PREDECESSOR_KEYS = ("前身", "predecessor")

# 节点审查（T3：D-01/D-03/D-15/D-18）。审查阶段首版恒为 1（阶段递增属 T6，
# 此处只带默认值，不发明推进语义）；节点版本只由声明字段决定——剔除运行字段
# 之后，改 `状态` 不动版本，改任务验收要求等声明即换版本。
NODE_PHASE_FIRST = 1
NODE_RUN_FIELDS = ("状态",)
NODE_REVIEW_VERDICTS = ("pass", "fail")
# 节点结论状态（T4 接线口径）：`valid`＝已验收（结论有效）、`invalid`＝未验收；
# `recheck`（待重新确认）由 T5 的失效与恢复规则产生——T4 只预留状态与措辞、
# 不发明触发。判据只在 `node_state()` 一处实现（T5 只换该函数）。
NODE_STATE_VALID = "valid"
NODE_STATE_INVALID = "invalid"
NODE_STATE_RECHECK = "recheck"
NODE_STATE_TEXT = {NODE_STATE_VALID: "已验收", NODE_STATE_INVALID: "未验收",
                   NODE_STATE_RECHECK: "待重新确认"}

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


def parse_id_list(raw, pattern):
    """列表字段的值解析：剥离一个尾部括号注解后，只接受 `无` 或分隔符分隔的 ID 列表。

    返回 (values, problem)：problem 为 None 表示通过；否则是一句可读的原因。
    严格解析是有意为之——无法识别的值必须报错，不得静默降级为空集；
    值非法时该字段不产生任何列表项（check 已 ERROR，计划不得执行）。
    """
    given = raw.strip()
    text = _strip_annotation(given)
    if not text:
        if given:
            return [], "剥离尾部括号注解后没有可解析内容"
        return [], None
    if text == NODE_NONE:
        return [], None
    tokens = NODE_LIST_SEPARATOR.split(text)
    if any(not token for token in tokens):
        return [], "存在空的列表项（分隔符重复）"
    bad = [token for token in tokens if not re.fullmatch(pattern, token)]
    if bad:
        return [], "无法解析的列表项：" + "、".join(bad)
    return tokens, None


def _strip_annotation(text):
    """剥离一个尾部括号注解：`无（原 N3 已并入）` → `无`。"""
    return NODE_ANNOTATION.sub("", text).strip()


class Node:
    """审查节点块（格式 ≥4）：`### N<n> <名称>` ＋ 六项必填字段 ＋ 可选「前身」。

    节点是验收单位、任务是执行单位；节点 ID 就是块标题里的 `N<n>`。
    """

    def __init__(self, nid, title, line_start):
        self.id = nid
        self.title = title.strip()
        self.line_start = line_start
        self.fields = {}
        self.field_lines = {}

    def get(self, key):
        return self.fields.get(key, "").strip()

    def parse_list(self, key, pattern):
        """解析列表字段（三个字段共用），返回 (values, problem)。"""
        return parse_id_list(self.get(key), pattern)

    @property
    def tasks(self):
        """『归属任务』里列出的任务 ID（值非法时为空，由 check 报「字段值非法」）。"""
        return sorted(set(self.parse_list("归属任务", TASK_ID_PATTERN)[0]))

    @property
    def deps(self):
        """『依赖节点』声明的节点 ID（`无` 表示不声明）。声明即约束（D-21）。"""
        return sorted(set(self.parse_list("依赖节点", NODE_ID_PATTERN)[0]))

    @property
    def is_final(self):
        """兼任终审：恰一个节点为『是』。"""
        return self.get("兼任终审") == "是"

    @property
    def predecessors(self):
        """『前身』声明的引用（合法时最多一个；`无` 表示没有）。"""
        return self.parse_list("前身", PREDECESSOR_PATTERN)[0]


class Plan:
    def __init__(self, path, text):
        self.path = path
        self.text = text
        self.lines = text.splitlines()
        self.meta = {}
        self.decisions = []   # [{id, decision, source, rationale}]
        self.phases = []      # [(num, name, checkpoint)]
        self.tasks = []
        self.nodes = []       # 格式 ≥4 的审查节点块；格式 ≤3 恒为空（不解析）
        self.has_node_section = False   # 计划文本里是否有 `## 审查节点` 段（仅格式 ≥4 判定）
        self.node_headings = []         # 段内的三级标题 (行号, 原文)，含写错的标题
        self.coverage = []    # [{target, means, type}]
        self.coverage_errors = []  # 结构诊断留在计划中，不阻断历史 closed 的只读解析。
        self.coverage_rows = {}  # 实际覆盖行及独立证据列身份；指纹复用，不再推断范围。
        self.exclusions_present = False   # 是否有「不验证的部分」
        self.sections = {}    # 各段的正文行，供 bug 类型检查用
        self.verify_command = ""
        self._events = None         # 格式 ≥4：事件流的惰性缓存（见 `events`）
        self._event_loader = None   # 由 load_plan 注入；check 只做容错的历史读取
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
    def is_v4(self):
        """格式 ≥4：审查节点制（节点为验收单位）。新解析与新校验一律挂在这里。"""
        return self.format_version >= PLAN_FORMAT_V4

    @property
    def valid_statuses(self):
        """合法任务状态按格式分流：格式 ≥4 只认两态记账 + 已验收。"""
        return VALID_STATUS_V4 if self.is_v4 else VALID_STATUS

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
        exclusion_depth = None

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
                coverage_headers = []
                exclusion_depth = None
                current_task = None
                continue

            if section and section.startswith("验证覆盖"):
                heading = re.match(r"^(#{3,6})\s+(.+)$", line.strip())
                if heading:
                    depth = len(heading.group(1))
                    if exclusion_depth is not None and depth <= exclusion_depth:
                        exclusion_depth = None
                        coverage_headers = []
                    if "不验证" in heading.group(2):
                        self.exclusions_present = True
                        if exclusion_depth is None:
                            exclusion_depth = depth
                    self.sections.setdefault(section, []).append(line.strip())
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
                    if exclusion_depth is None:
                        coverage_headers = self._coverage_row(line, idx, coverage_headers)

            if current_phase and current_task is None:
                cp = META_FIELD.match(line)
                if cp and "heckpoint" in cp.group("key"):
                    self.phases[-1][2] = cp.group("value").strip()

        self.verify_command = "\n".join(verify_buf).strip()
        if self.verify_command in ("未声明", "-", "无"):
            self.verify_command = ""
        if self.is_v4:
            self._parse_nodes()

    def _parse_nodes(self):
        """解析 `## 审查节点` 段（只在格式 ≥4 调用）。

        段内每个三级标题都是节点块，块标题里的 `N<n>` 即节点 ID；块内
        `- **字段**：值` 逐条收进 fields，未知字段忽略（前向兼容）。
        格式 ≤3 的计划完全不走这条路径（含写坏的节点块——旧计划不该被新校验打断）。
        """
        inside, in_fence, current = False, False, None
        for idx, line in enumerate(self.lines):
            if FENCE.match(line):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            sec = SECTION_HEADER.match(line)
            if sec:
                # 段名精确匹配：`## 审查节点与边界` 这类近似标题不是节点段。
                inside = sec.group(1).strip() == NODE_SECTION
                if inside:
                    self.has_node_section = True
                current = None
                continue
            if not inside:
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith("<!--"):
                continue
            head = NODE_HEADER.match(stripped)
            if head:
                current = Node(head.group(1), head.group(2), idx)
                self.nodes.append(current)
                self.node_headings.append((idx, stripped))
                continue
            if re.match(r"^###\s", stripped):
                # 段内三级标题都必须能读出节点 ID，否则节点会被静默漏掉。
                self.node_headings.append((idx, stripped))
                current = None
                continue
            if re.match(r"^#{1,6}\s", stripped):
                current = None
                continue
            if current is not None:
                fld = NODE_FIELD.match(stripped)
                if fld:
                    key = fld.group("key").strip()
                    if key not in current.fields:
                        current.fields[key] = fld.group("value").strip()
                        current.field_lines[key] = idx

    def _coverage_row(self, line, idx, headers):
        if "|" not in line:
            return headers

        def error(message):
            self.coverage_errors.append({"line": idx + 1, "message": message, "text": line})

        def remember(names, separator=False):
            self.coverage_rows[idx] = {"cells": cells, "separator": separator,
                                       "evidence_column": names.index("证据") if "证据" in names else None}

        row = TABLE_ROW.fullmatch(line.strip())
        if not row:
            error("覆盖表行必须完整包围在 | ... | 中；不支持单元格内的管道字符")
            return headers
        cells = [cell.strip() for cell in row.group(1).split("|")]
        if _table_separator(cells):
            if (headers and len(cells) != len(headers)) or (not headers and len(cells) not in (3, 4)):
                error("完整分隔行的列数与覆盖表不符")
            elif not headers or not _coverage_header_problems(headers):
                remember(headers, separator=True)
            return headers
        next_row = TABLE_ROW.fullmatch(self.lines[idx + 1].strip()) if idx + 1 < len(self.lines) else None
        followed_by_separator = next_row and _table_separator([c.strip() for c in next_row.group(1).split("|")])
        is_header = (followed_by_separator or COVERAGE_REQUIRED_COLUMNS.issubset(cells)
                     or (not {"自动化", "人工"}.intersection(cells) and COVERAGE_COLUMNS.intersection(cells)))
        if is_header:
            problems = _coverage_header_problems(cells)
            for problem in problems:
                error(problem)
            if not problems:
                remember(cells)
            return cells
        if headers:
            if _coverage_header_problems(headers):
                return headers  # 保留表头原文诊断；不猜各数据单元格的含义。
            if len(cells) != len(headers):
                error(f"数据行有 {len(cells)} 列，表头为 {len(headers)} 列；不得截断或补猜")
                return headers
        elif len(cells) not in (3, 4):
            error("无表头旧覆盖表只支持三列或四列")
            return headers
        names = headers or ["对象", "验证手段", "类型", "必需性"][:len(cells)]
        remember(names)
        mapped = dict(zip(names, cells))  # 列数已完整校验。
        requirement = mapped.get("必需性", mapped.get("必需", "必需"))
        self.coverage.append({"id": mapped.get("ID", mapped["对象"]),
                              "target": mapped["对象"], "means": mapped["验证手段"],
                              "type": mapped["类型"], "line": idx + 1,
                              "required": requirement.lower() not in ("可选", "optional", "否", "false", "no"),
                              "evidence": mapped.get("证据", "")})
        return headers

    @property
    def events(self):
        """本工作流的事件流（格式 ≥4 三态调度的输入；格式 ≤3 恒为空列表）。

        惰性加载：`load_plan` 注入加载器，首次访问才读 `events.jsonl`——读法用严格
        解析的 `read_events`（事件是权威记录，坏事件不得静默降级为「没有事件」）。
        惰性是为了 `check`：计划校验只读计划文本与**容错**的历史记录（前身解析用
        `_events_for_plan`），不因事件文件损坏而打断计划诊断；执行入口
        （slice/record/review/close/verify）本来就会先读事件，拦在那里。
        """
        if self._events is None:
            self._events = [] if self._event_loader is None else self._event_loader()
        return self._events

    # ---- 状态计算（依赖图）

    def states(self):
        """返回 {task_id: STATE}，STATE ∈ DONE/BLOCKED/READY/RUNNING/IMPLEMENTED。

        格式 ≥4 改走 `task_states()` 三态派生（D-09/T4）——`complete`→DONE；
        所属节点的直接跨节点上游未验收→BLOCKED；有实现证据（待节点审查）→
        IMPLEMENTED；其余（含 `pending`）→READY。组内依赖按「已实现」放行、
        不等待审查。格式 ≤3 逐字走旧路径（四态、旧判据，行为不变）。
        """
        if not self.is_v4:
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
        facts = task_states(self)
        out = {}
        for t in self.tasks:
            if t.status == STATUS_COMPLETE:
                out[t.id] = "DONE"          # 已验收（节点通过后映射，T3）
            elif facts[t.id]["blocked"]:
                out[t.id] = "BLOCKED"
            elif facts[t.id]["implemented"]:
                out[t.id] = "IMPLEMENTED"   # 已实现、等待节点审查（不派发）
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
    plan = Plan(path, text)
    if plan.is_v4:
        # 格式 ≥4：三态调度的输入是事件流（D-04 事件是权威记录）——加载器随计划
        # 注入，首次访问才读（见 `Plan.events`），各入口共用同一份读法。
        plan._event_loader = lambda: read_events(root, slug)
    return plan


# ------------------------------------------------------- 审查节点（格式 ≥4）

def node_owner_map(plan):
    """任务 → 归属审查节点 ID（格式 ≥4）。

    「每个任务恰属一个节点」由 `check` 保证；同一任务被两个节点声明的坏计划在
    解析阶段就被拒（`_node_findings`），这里只取第一个出现者（不放大坏计划的影响）。
    """
    owner = {}
    for node in plan.nodes:
        for tid in node.tasks:
            owner.setdefault(tid, node.id)
    return owner


def wait_graph(plan):
    """节点等待图：{等待者: {被等待者, …}}（格式 ≥4；旧格式返回空图）。

    方向统一为「等待者 → 被等待者」（D-10）：B 依赖 A → B 等待 A → 边 B → A。
    三条来源合并为同一张图，**声明即约束**（D-21）：
      ① 任务依赖导出的跨节点边（任务 A 依赖任务 B、两者分属不同节点）；
      ② 显式声明的节点依赖边（`依赖节点` 字段）；
      ③ 终审边——恰有一个终审节点时：终审 → 每个其它节点（终审等待全部验收）。
    判环、派发与就绪检查共用这一张图；格式 ≤3 的节点集为空，返回空图。
    """
    graph = {node.id: set() for node in plan.nodes}
    owner = node_owner_map(plan)
    task_ids = {task.id for task in plan.tasks}
    for task in plan.tasks:
        waiter = owner.get(task.id)
        if waiter is None:
            continue
        for dep in task.deps:
            if dep not in task_ids:
                continue
            waited = owner.get(dep)
            if waited and waited != waiter:
                graph[waiter].add(waited)
    for node in plan.nodes:
        for dep in node.deps:
            if dep in graph:
                graph[node.id].add(dep)
    finals = [node.id for node in plan.nodes if node.is_final]
    if len(finals) == 1:
        for nid in graph:
            if nid != finals[0]:
                graph[finals[0]].add(nid)
    return graph


def wait_cycles(graph):
    """等待图里的环，逐个返回（形如 ['N1', 'N2', 'N1']，方向即等待者 → 被等待者）。"""
    state, cycles = {}, []

    def visit(node, stack):
        if state.get(node) == "done":
            return
        if state.get(node) == "visiting":
            if node in stack:
                cycles.append(stack[stack.index(node):] + [node])
            return
        state[node] = "visiting"
        for nxt in sorted(graph.get(node, ())):
            visit(nxt, stack + [node])
        state[node] = "done"

    for node in sorted(graph):
        visit(node, [])
    return cycles


def _id_tokens(value):
    """从字段值里回收 ID 字符串（中文字符不参与匹配，说明文字不会混进引用）。"""
    if isinstance(value, list):
        return [token for item in value for token in _id_tokens(item)]
    if not isinstance(value, str):
        return []
    return REF_TOKEN.findall(value)


def _events_for_plan(plan):
    """计划同目录下 events.jsonl 的原始事件行（坏行跳过；只服务前身解析）。"""
    path = os.path.join(os.path.dirname(plan.path), "events.jsonl")
    events = []
    if not os.path.isfile(path):
        return events
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return events


def _event_scope(event, known, roots_of):
    """把单个事件里的节点/谱系/前身 ID 并入前身解析范围（递归进 data 等嵌套结构）。"""
    if isinstance(event, dict):
        node_refs, lineage_refs = [], []
        for key, value in event.items():
            if key in HISTORY_NODE_KEYS or key in HISTORY_PREDECESSOR_KEYS:
                node_refs.extend(_id_tokens(value))
            if key in HISTORY_LINEAGE_KEYS:
                lineage_refs.extend(_id_tokens(value))
        known.update(node_refs)
        known.update(lineage_refs)
        for ref in set(node_refs):
            for root in set(lineage_refs):
                roots_of.setdefault(ref, set()).add(root)
        for value in event.values():
            _event_scope(value, known, roots_of)
    elif isinstance(event, list):
        for item in event:
            _event_scope(item, known, roots_of)


def lineage_history(plan):
    """本工作流历史记录里的 ID 集合与谱系映射：(ids, roots_of)。

    ids ＝ events.jsonl 中各事件的节点/谱系/前身字段回收到的 ID 字符串；
    roots_of ＝ 引用 → 映射到的谱系根集合（>1 即解析歧义）。
    """
    ids, roots_of = set(), {}
    for event in _events_for_plan(plan):
        _event_scope(event, ids, roots_of)
    return ids, roots_of


def predecessor_scope(plan, exclude=None, history=None):
    """审查节点 {exclude 之外的} 解析『前身』的已知 ID 集合（格式 ≥4）。

    known ＝ 当前计划节点 ID ∪ **其它节点**声明的前身值 ∪ 本工作流历史记录
    （审查记录与事件中的谱系/节点 ID），并对已解析引用做链式展开。
    `exclude` 传声明节点自己的 ID：自己的声明不为自己背书——自声明若能自证，
    「引用不存在」永远报不出来、检查形同虚设。合法拆分不受影响：被替换节点
    存在于历史记录，或同一前身由多个子节点分别承接时，另有一处来源。
    history 可复用 `lineage_history(plan)` 的结果，避免逐节点重扫事件。
    """
    history_ids, roots_of = lineage_history(plan) if history is None else history
    known = {node.id for node in plan.nodes}
    for node in plan.nodes:
        if node.id != exclude:
            known.update(node.predecessors)
    known.update(history_ids)
    frontier = list(known)
    while frontier:
        ref = frontier.pop()
        for root in roots_of.get(ref, ()):
            if root not in known:
                known.add(root)
                frontier.append(root)
    return known


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


def _node_findings(plan, by_id):
    """格式 ≥4 的审查节点校验（D-01/D-05/D-10/D-21/D-09/D-11）。

    判据：每个任务恰属一个节点；节点块六项必填字段齐全、值合法；依赖节点与
    前身引用可解析（前身最多一个、不得引用在用节点、不得歧义——合并即拒绝）；
    恰有一个终审节点且它不被任何节点等待；等待图（任务依赖导出 ∪ 显式声明 ∪
    终审边）合并为同一张图后无环。校验只在格式 ≥4 生效（调用方负责分流）。
    """
    out = []

    def add(level, message, task=None):
        out.append({"level": level, "task": task, "message": message})

    for idx, heading in plan.node_headings:
        if not NODE_HEADER.match(heading):
            add(
                "ERROR",
                f"L{idx + 1} 『{NODE_SECTION}』段内的三级标题必须是节点块"
                f"（形如 `### N1 <名称>`，块标题即节点 ID）：{heading[:60]}",
            )

    if not plan.has_node_section:
        add(
            "ERROR",
            f"格式 4 计划缺少 `## {NODE_SECTION}` 段——节点是格式 4 的验收单位，"
            "每个任务必须恰属一个节点。",
        )
        return out
    if not plan.nodes:
        add("ERROR", f"『{NODE_SECTION}』段里没有任何节点块（形如 `### N1 <名称>`）。")
        return out

    node_id_list = [node.id for node in plan.nodes]
    node_ids = set(node_id_list)
    for nid in sorted({nid for nid in node_id_list if node_id_list.count(nid) > 1}):
        add(
            "ERROR",
            f"审查节点 ID 重复：{nid}——两个以上的节点块共用一个 ID，"
            "归属、终审与等待图都会塌缩到同一节点上（节点 ID 是稳定身份）。",
        )
    history = lineage_history(plan)
    finals = []
    for node in plan.nodes:
        problems = {}
        for key, pattern in NODE_LIST_FIELDS:
            values, problem = node.parse_list(key, pattern)
            problems[key] = problem
            if problem and node.get(key):
                add(
                    "ERROR",
                    f"审查节点 {node.id} 的『{key}』字段值非法（{problem}）——"
                    "只接受『无』或逗号分隔的 ID 列表。",
                )
        for key in NODE_REQUIRED_FIELDS:
            if not node.get(key):
                add("ERROR", f"审查节点 {node.id} 缺少『{key}』字段（六项必填，缺一不可）。")
        verdict = node.get("兼任终审")
        if verdict and verdict not in NODE_FINAL_VALUES:
            add(
                "ERROR",
                f"审查节点 {node.id} 的『兼任终审』只能是『是』或『否』，"
                f"当前是『{verdict}』。",
            )
        if verdict == "是" and node.id not in finals:
            finals.append(node.id)   # 重复 ID 已被「节点 ID 重复」报过，不再放大
        listed = node.tasks
        if not node.get("归属任务"):
            pass   # 空值/缺字段已按「缺项」报过，不再重复
        elif not listed and not problems["归属任务"]:
            # 值为「无」或剥注解后为空：没列出真实任务 ID；
            # 值非法时上面已报「字段值非法」，不再叠加。
            add("ERROR", f"审查节点 {node.id} 的『归属任务』没有列出真实任务 ID。")
        for tid in listed:
            if tid not in by_id:
                add("ERROR", f"审查节点 {node.id} 的归属任务 {tid} 不存在。")
        for dep in node.deps:
            if dep not in node_ids:
                add("ERROR", f"审查节点 {node.id} 依赖的节点 {dep} 不存在。")
        refs = node.predecessors
        if len(refs) > 1:
            add(
                "ERROR",
                f"审查节点 {node.id} 声明了多个前身（{'、'.join(refs)}）——"
                "首版不支持已送审节点合并，每个新节点最多承接一个前身。",
            )
        elif refs:
            ref = refs[0]
            roots_of = history[1]
            if ref in node_ids:
                add(
                    "ERROR",
                    f"审查节点 {node.id} 的前身 {ref} 仍是本计划中在用的节点——"
                    "调整应替换或移除原节点，而不是并列引用。",
                )
            elif ref not in predecessor_scope(plan, node.id, history):
                add(
                    "ERROR",
                    f"审查节点 {node.id} 的前身 {ref} 解析不到——"
                    "前身须存在于当前计划文本或本工作流的历史记录（审查记录与事件）中。",
                )
            elif len(roots_of.get(ref, ())) > 1:
                add(
                    "ERROR",
                    f"审查节点 {node.id} 的前身 {ref} 在历史记录里映射到多个谱系根"
                    f"（{'、'.join(sorted(roots_of[ref]))}）——解析歧义，须人工裁定后重写。",
                )

    owners = {}
    for node in plan.nodes:
        for tid in node.tasks:
            if tid in by_id and node.id not in owners.get(tid, ()):
                owners.setdefault(tid, []).append(node.id)
    for task in plan.tasks:
        held = owners.get(task.id, [])
        if not held:
            add(
                "ERROR",
                f"任务 {task.id} 不属于任何审查节点——格式 4 下每个任务恰属一个节点。",
                task.id,
            )
        elif len(held) > 1:
            add(
                "ERROR",
                f"任务 {task.id} 同时归属审查节点 {'、'.join(held)}——每个任务恰属一个节点。",
                task.id,
            )

    if len(finals) != 1:
        detail = f"{len(finals)} 个" + (f"（{'、'.join(finals)}）" if finals else "")
        add(
            "ERROR",
            f"格式 4 计划必须恰有一个『兼任终审：是』的审查节点，当前是 {detail}。",
        )

    graph = wait_graph(plan)
    for cycle in wait_cycles(graph):
        add(
            "ERROR",
            "节点等待图存在环（等待者 → 被等待者）：" + " → ".join(cycle)
            + "——两条来源（任务依赖导出的跨节点边 ∪ 显式声明的节点依赖边）合并后判环。",
        )
    if len(finals) == 1:
        waited_by = sorted(
            src for src, targets in graph.items() if finals[0] in targets and src != finals[0]
        )
        if waited_by:
            add(
                "ERROR",
                f"终审节点 {finals[0]} 不得为其它节点的上游，但 {'、'.join(waited_by)} 在等它——"
                "终审等待全部验收，不能反过来被别人等待。",
            )
    return out


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

    # 1b. 审查节点（仅格式 ≥4）：归属、终审约束与等待图；旧格式不解析、不校验
    if plan.is_v4:
        out.extend(_node_findings(plan, by_id))

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
        if t.status not in plan.valid_statuses:
            add(
                "ERROR",
                f"状态 '{t.status}' 非法，只能是 {'/'.join(plan.valid_statuses)}。",
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
    for problem in plan.coverage_errors:
        add("ERROR", f"覆盖表 L{problem['line']}：{problem['message']}；原文：{problem['text']}")
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
            if entry["type"] == "自动化":
                declaration = reference_declaration(entry)
                if declaration["state"] == "invalid":
                    add("WARNING", f"覆盖项 {entry['id']} 的引用声明无法核实：{declaration['error']}；"
                        "必验项未获明确豁免时会阻止收尾，可选项仅反馈。")
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
    """审批依据指纹：只占位真实任务状态，其余原文保持绑定。

    保留标准旧占位形状与默认换行读取，使有效旧审批继续可用。
    旧正则曾忽略非任务正文时使用内部域，不能让字面占位文本复用旧授权。
    """
    with open(plan_path, encoding="utf-8") as fh:
        text = fh.read()
    plan = Plan(plan_path, text)
    status_lines = {task.field_lines["状态"] for task in plan.tasks if "状态" in task.field_lines}
    parts, status_spans, offset = [], set(), 0
    for idx, line in enumerate(text.splitlines(keepends=True)):
        if idx in status_lines:
            body_length = len(plan.lines[idx])
            status_spans.add((offset, offset + body_length))
            parts.append("- **状态**：<忽略>" + line[body_length:])
        else:
            parts.append(line)
        offset += len(line)
    stripped = "".join(parts)
    if any(match.span() not in status_spans for match in STATUS_LINE.finditer(text)):
        stripped = "workflow-plan-approval:task-status-v1\0" + stripped
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

# 格式 ≥4 新增的事件类型（D-04）：`implemented` 承载两态记账与操作 ID 协议，
# `node_review` 承载节点审查结论（T3），`projection_repair` 记录投影自动修复。
# 事件名字面量一律走这三个常量。
EVENT_IMPLEMENTED = "implemented"
EVENT_NODE_REVIEW = "node_review"
PROJECTION_REPAIR = "projection_repair"
EVENT_TYPES = {"start", "verify", "manual", "waiver", "evidence", "command_retired", "close", "reopen",
               EVENT_IMPLEMENTED, EVENT_NODE_REVIEW, PROJECTION_REPAIR}
VIEW_MARKER = "<!-- workflow-events-view -->"


def events_path(root, slug):
    return os.path.join(workflow_root(root), slug, "events.jsonl")


def serialize_events(events):
    """事件列表 → JSONL 文本（写入与写入前自校验共用同一序列化）。"""
    return "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
                   for event in events)


def event_lines(text):
    """事件文本 → 行列表：**只按 `\\n` 切**——与读侧（逐文件行）同一套行切分。

    `str.splitlines()` 还会在 U+2028/U+2029 等 Unicode 行边界断开，用它做写入前
    自校验会把读侧能正常读回的事件（如 evidence 里含 U+2028）误判为「尾行不完整」；
    写侧接受的必须被读侧接受，所以两侧共用这一个切分。保留行尾换行，末尾无换行的
    残行交由 `parse_events` 按「事件尾行不完整」拒绝。
    """
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def validate_event_batch(existing, new, slug):
    """写入前自校验：已有事件＋待写事件必须能通过 `read_events` 的同一套结构校验。

    事件是权威记录：写坏它没有自救入口（只能手工编辑文件，且所有入口都会拒绝继续）。
    因此在落盘前先按读者的判据跑一遍——写后会被自己读校验拒绝的形态不得落盘。
    """
    try:
        parse_events(event_lines(serialize_events(list(existing) + list(new))), slug)
    except (ValueError, TypeError) as exc:
        raise WorkflowError(
            f"本次要写入的事件未通过结构自校验，已中止（未落盘）：{exc}。"
            "这是引擎缺陷（写出的形态自己读不了），请报告；不要手工编辑 events.jsonl。"
        ) from exc


# --------------------------------------------- 记账操作的身份协议（格式 ≥4；D-08）

def operation_id_problem(operation_id):
    """操作 ID 校验：非空、不含空白即通过；返回可读原因或 None。

    `rv-<谱系>-<seq>` 形状是调用方约定，引擎首版不强制前缀——只保证身份可用：
    空值承担不了重试身份，内含空白会在命令行与日志里被拆分。
    """
    if not isinstance(operation_id, str) or not operation_id.strip():
        return ("缺少 `--operation-id <id>`：格式 ≥4 的记账操作在首次执行前生成并保存"
                "稳定操作 ID，重试必须复用（首版不提供自动生成）")
    if any(char.isspace() for char in operation_id):
        return (f"操作 ID '{operation_id}' 含空白字符——它会被命令行与日志拆分，"
                "无法用作重试身份")
    return None


def operation_request_digest(payload):
    """请求摘要：相同请求判据（tasks 集合 + commits + evidence）的规范化摘要。

    规范化方式与既有 `_digest` 同一实现（`hashlib` 域内唯一的规范化序列化），
    这里只把它命名成协议里的概念，便于 T3/T5/T6 复用同一判据。
    """
    return _digest(payload)


def find_operation(events, operation_id):
    """按稳定操作 ID 找已记账事件；同一 ID 出现在多条事件里即身份不唯一，抛错。"""
    found = [event for event in events
             if isinstance(event.get("data"), dict)
             and event["data"].get("operation_id") == operation_id]
    if len(found) > 1:
        raise WorkflowError(
            f"操作 ID {operation_id} 出现在 {len(found)} 条事件里——"
            "记账身份必须唯一对应一次操作，拒绝继续（先修复事件文件里的重复条目）。"
        )
    return found[0] if found else None


def resolve_operation(root, slug, operation_id, request, entry):
    """记账操作的统一入口协议：查重 → 幂等重放 / 冲突拒绝 / 新操作放行。

    返回 (action, event)：action == "replay" 时 event 是原记账事件，调用方直接返回
    其 receipt（不写事件、不改计划、不重新计数）；action == "new" 时 event 为 None。
    - 相同 ID + 相同请求 → 幂等重放（返回原结果、恢复投影、不新增事件）
    - 相同 ID + 不同请求 → 拒绝（同一 ID 不得承担两次不同操作）
    - 未提供或形状非法 → 拒绝（首版无自动生成分支）
    """
    problem = operation_id_problem(operation_id)
    if problem:
        raise WorkflowError(f"{entry} 未携带可用的操作 ID：{problem}。")
    existing = find_operation(read_events(root, slug), operation_id)
    if existing is None:
        return "new", None
    if existing["data"].get("request") != request:
        raise WorkflowError(
            f"操作 ID {operation_id} 已用于另一次操作（请求摘要不符）——"
            "同 ID＋不同请求必须拒绝：确认要重试原操作就用原请求（tasks/commits/evidence "
            "一致）；确是新操作请另取新 ID。"
        )
    return "replay", existing


def operation_receipt(event):
    """幂等重放返回的原结果：随事件持久化的 receipt（中断后重建仍据此返回）。"""
    receipt = event["data"].get("receipt")
    if (not isinstance(receipt, dict) or not isinstance(receipt.get("result"), dict)
            or not isinstance(receipt.get("text"), str)):
        raise WorkflowError(
            f"记账事件 {event['id']} 的 receipt 不完整，无法幂等重放原结果。"
        )
    return receipt["result"], receipt["text"]


def replay_result(event, operation_id):
    """幂等重放的返回：原 receipt ＋ 一条「历史回放」提示。

    同一份成功文案会掩盖「这次只是历史回放、当前计划可能已重新审批」；提示进
    `warnings` 与显示文案，原 result 的其余字段逐字保留（不写事件、不改计划）。
    """
    result, text = operation_receipt(event)
    hint = (f"本次为幂等重放（原操作 {operation_id}，事件 {event['id']}）："
            "返回原结果，未写事件、未改计划、未改账本")
    return {**result, "warnings": list(result.get("warnings", [])) + [hint]}, text + "\n↺ " + hint


def ledger_lines(text):
    """账本文本 → 行列表：**只按 `\\n` 切**——与账本写入侧（`"\\n".join(lines)`）同源。

    `str.splitlines()` 还会在 U+2028/U+2029 等 Unicode 行边界断开：行内一旦含这些字符
    （例如 `--note` 原文），行身份判定就会失配（把已存在的行判成不存在，重放重复追加）。
    """
    return text.split("\n")


def restore_ledger_rows(root, slug, event):
    """幂等重放的账本补齐：事件里持久化了本操作将写入的账本行，缺则补、有则跳过。

    真实中断（事件已落盘、计划状态与账本行未回写）后携原 ID 重试时，账本行必须补回，
    否则账本与权威记录（事件）不一致。行文本（含时间戳）取自事件，重建不依赖当前
    时间与参数，因此重复重放不会重复追加。计划状态的恢复由入口的投影检查负责。
    行切分与账本写入同源（`ledger_lines`）：行内出现 U+2028/U+2029 也不会误判成「缺」。
    """
    rows = event["data"].get("ledger") or []
    if not rows:
        return
    path = ledger_path(root, slug)
    if not os.path.isfile(path):
        raise WorkflowError(f"账本不存在：{path}")
    with open(path, encoding="utf-8") as fh:
        present = set(ledger_lines(fh.read()))
    for item in rows:
        if item["row"] in present:
            continue
        ledger_append(root, slug, item["section"], item["row"])
        present.add(item["row"])


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


# --------------------------------------------- 节点审查（格式 ≥4；T3：D-01/D-03/D-15/D-18）

def node_version(plan, node):
    """节点版本：{节点块 ＋ 各归属任务块}声明字段规范化文本的 sha256 前 16 位（D-18）。

    剔除 `状态` 等运行字段：只改运行状态不换版本；节点声明或任务要求（含验收定义）
    变化即版本变化——旧结论属于旧版本，`review` 记录同时保存版本，供后续判定沿用
    （比较与失效规则属 T5，这里只负责稳定计算并随审查记录保存）。
    """
    def declared(fields):
        return {key: value for key, value in sorted(fields.items())
                if key not in NODE_RUN_FIELDS}

    by_id = {task.id: task for task in plan.tasks}
    payload = {
        "node": {"id": node.id, "fields": declared(node.fields)},
        "tasks": [{"id": tid, "fields": declared(by_id[tid].fields) if tid in by_id else {}}
                  for tid in node.tasks],
    }
    return _digest(payload)[:16]


def node_lineage(events, node_id):
    """该节点已有的审查谱系根（从 `node_review` 事件解析）；没有即 None。

    谱系根在首次送审时生成并随事件持久化，此后一律复用：重放/重试不会重新生成，
    只改节点声明也不换谱系（结论版本用 `节点版本` 另记）。同一节点出现多个不同谱系
    → 身份不唯一，拒绝继续。
    """
    found = []
    for event in events:
        if event["type"] != EVENT_NODE_REVIEW or event["data"].get("节点") != node_id:
            continue
        lineage = event["data"]["谱系"]
        if lineage not in found:
            found.append(lineage)
    if len(found) > 1:
        raise WorkflowError(
            f"节点 {node_id} 在事件里出现了多个谱系根（{'、'.join(found)}）——"
            "审查谱系是稳定身份，必须唯一，拒绝继续（先修复事件文件里的重复条目）。"
        )
    return found[0] if found else None


def new_node_lineage(slug, node):
    """首次送审生成谱系根 ID：`<节点ID>-<8 位摘要>`（含节点 ID 便于人读）。

    只在事件里解析不到谱系时调用一次，随后随事件持久化；摘要取工作流与节点 ID，
    与节点版本无关——声明变化不换谱系，只换结论版本。
    """
    return f"{node.id}-{_digest({'workflow': slug, 'node': node.id})[:8]}"


def node_review_count(events, lineage, phase=NODE_PHASE_FIRST):
    """同【谱系 × 审查阶段】的 `node_review` 记录条数——轮次谓词的**单一实现**。

    「送审前的条数」＝本次送审是第几轮（首审 0）；`round_count` 只是它的「减一」
    视图。T3 审查 Low ②：`review` 里的轮次读数与本函数曾是同谓词两处实现，
    现在两处都走这里。
    """
    return sum(1 for event in events
               if event["type"] == EVENT_NODE_REVIEW
               and event["data"].get("谱系") == lineage
               and event["data"].get("审查阶段") == phase)


def round_count(events, lineage, phase=NODE_PHASE_FIRST):
    """已用修复轮次：同【谱系 × 审查阶段】记录条数 − 1，下限 0。

    首审不计轮；「修复＋复核（含主控核对）」每多一条审查记录记一轮；同一操作 ID
    的重试是幂等重放（只有一条事件），因此不重复计数。上限 2 的拒绝与提示属 T6，
    本函数只提供读数；`phase` 默认首版恒 1 的阶段。
    """
    return max(0, node_review_count(events, lineage, phase) - 1)


def node_review_index(events):
    """`node_review` 事件的规范化索引——节点结论谓词的**单一取用点**。

    返回：
    - `lineage`：{节点 ID: 谱系}，同一节点按事件顺序取最后一次定义（读路径容错；
      写路径的 `node_lineage` 对同一节点出现多个谱系直接拒绝——两条路径的分工
      见 T3 报告候选 4，这里不改写路径的严格性）；
    - `nodes_with_records`：有任一 `node_review` 记录的节点 ID 集合（审查债务用）；
    - `latest`：{(谱系, 审查阶段): 结论}，同【谱系 × 阶段】取最近一条（后写覆盖
      先写）——「不得各自取最近一次 pass」的统一口径（D-18）。比较谓词只此一处
      实现（T3 审查 Low ②：`review` 的轮次计数与本派生不再各写一份）。
    """
    lineage, latest, recorded = {}, {}, set()
    for event in events:
        if event["type"] != EVENT_NODE_REVIEW:
            continue
        data = event["data"]
        lineage[data["节点"]] = data["谱系"]
        latest[(data["谱系"], data["审查阶段"])] = data["verdict"]
        recorded.add(data["节点"])
    return {"lineage": lineage, "latest": latest, "nodes_with_records": recorded}


def node_state(plan, events, node, index=None):
    """节点结论状态（T4 接线口径；T5 收口失效来源与恢复，只换本函数实现）。

    当前【谱系 × 当前审查阶段】下最近一条 `node_review` 结论为 `pass` →
    `NODE_STATE_VALID`；尚无谱系（从未送审）或最近一条不是 `pass` → `invalid`。
    节点版本坐标（声明变化即旧结论失放行资格）、前提与失效三条、范围外变化的
    兜底判断，以及「待重新确认」（`NODE_STATE_RECHECK`）的触发与恢复都属 T5——
    T4 只接线与调用、不自定义口径（`plan` 参数留给 T5 计算节点版本，签名不再变）。
    """
    index = node_review_index(events) if index is None else index
    lineage = index["lineage"].get(node.id)
    if lineage is None:
        return NODE_STATE_INVALID
    if index["latest"].get((lineage, NODE_PHASE_FIRST)) == "pass":
        return NODE_STATE_VALID
    return NODE_STATE_INVALID


def node_valid_state(plan, events, node, index=None):
    """节点结论是否有效（`node_state` 的布尔视图）——各入口只经这一个判据。"""
    return node_state(plan, events, node, index) == NODE_STATE_VALID


def node_state_line(plan, node, state, facts):
    """节点状态的展示行：节点 ID ＋ 状态 ＋ 已实现成员（派发/收尾消息带它）。"""
    members = [task.id for task in plan.tasks
               if task.id in node.tasks and facts.get(task.id, {}).get("implemented")]
    detail = f"（已实现成员：{'、'.join(members)}）" if members else ""
    return f"{node.id} {NODE_STATE_TEXT[state]}{detail}"


REVIEW_LINE_START = re.compile(r"(?:^|[\n；;])\s*(T\d+)\s*[:：]")


def parse_review_lines(raw, owners):
    """解析 `--lines`（宽松）：`T<n>:` 起一行，结论取到下一个行首。

    返回 (rows, problem)：rows ＝ [{task, conclusion}] 按书写顺序；problem 非空即
    拒绝。宽松点：`；`、`;`、换行都能分隔，行首空白与全/半角冒号都认，结论正文里
    出现别的标点不影响（只有下一个 `T<n>:` 才另起一行）。严格点：任务集合必须
    **恰好等于**归属任务集合（缺、多、重复行任一即拒绝，信息列明差异），且每行结论
    非空——行数只证明覆盖记录齐全，不证明检查充分。
    """
    matches = list(REVIEW_LINE_START.finditer(raw))
    if not matches:
        return [], "没有解析出任何 `<任务ID>: <结论＋依据>` 行"
    rows = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        rows.append({"task": match.group(1), "conclusion": raw[start:end].strip()})
    tasks = [row["task"] for row in rows]
    owner_set = set(owners)
    duplicates = sorted({tid for tid in tasks if tasks.count(tid) > 1})
    missing = [tid for tid in owners if tid not in set(tasks)]
    extra = sorted(set(tasks) - owner_set)
    blank = [row["task"] for row in rows if not row["conclusion"]]
    problems = []
    if duplicates:
        problems.append("重复行：" + "、".join(duplicates))
    if missing:
        problems.append("缺行：" + "、".join(missing))
    if extra:
        problems.append("多行：" + "、".join(extra))
    if blank:
        problems.append("缺结论＋依据：" + "、".join(blank))
    if problems:
        return rows, "；".join(problems) + f"——必须逐行覆盖归属任务 {'、'.join(owners)}"
    return rows, None


def acceptance_fingerprint(plan):
    """保守绑定完整计划语义；只排除任务状态和显式独立证据列。

    不枚举少数验收字段，避免漏掉 Checkpoint、围栏约束或附加验收说明。
    表格规范化只为允许独立引用修正；引用本身另由验证/补证摘要约束。
    """
    canonical = []
    task_status_lines = {task.field_lines["状态"] for task in plan.tasks if "状态" in task.field_lines}
    for idx, line in enumerate(plan.lines):
        if idx in task_status_lines:
            continue
        row = plan.coverage_rows.get(idx)
        if row is not None:
            if row["separator"]:
                continue
            canonical.append([cell for index, cell in enumerate(row["cells"]) if index != row["evidence_column"]])
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


def _verification_summary(event):
    return {"id": event["id"], **{key: event["data"][key] for key in
                                ("command", "exit_code", "fingerprint", "acceptance")}}


def read_events(root, slug):
    path = events_path(root, slug)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            return parse_events(event_lines(fh.read()), slug)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise WorkflowError(f"结构化证据损坏，无法确认，禁止回退旧 PASS：{path}（{exc}）") from exc


def parse_events(lines, slug):
    """对事件行跑结构校验；返回事件列表（坏行即抛 ValueError）。

    单独摘出来是为了让写入前自校验（`validate_event_batch`）复用同一套判据——
    append 之前先按读者的规则验一遍，避免引擎把自己的权威文件写出「读不了」的形态。
    行切分与读侧同源（`event_lines`），两侧对同一文本的接受集合一致。
    """
    events, seen, cycle, closed = [], set(), 1, False
    for line_no, line in enumerate(lines, 1):
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
            if kind in ("verify", "manual", "waiver", "evidence", "command_retired"):
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
            if kind == "command_retired":
                prior = [e for e in events if e["type"] == "verify" and e["cycle"] == cycle]
                if (not prior or data.get("verification") != prior[-1]["id"]
                        or data.get("previous") != _verification_summary(prior[-1])
                        or data.get("replacement_command") != ""
                        or data.get("checklist") != _digest({k: data[k] for k in ("fingerprint", "acceptance")})
                        or any(not isinstance(data.get(k), str) or not data[k].strip()
                               for k in ("by", "source", "reason"))):
                    raise ValueError("撤销旧命令要求缺少最新验证、新旧绑定或具体授权")
            if kind == EVENT_IMPLEMENTED:
                tasks = data.get("tasks")
                if (not isinstance(tasks, list) or not tasks
                        or any(not isinstance(tid, str) or not tid.strip() for tid in tasks)
                        or len(set(tasks)) != len(tasks)):
                    raise ValueError("已实现事件缺少任务清单")
                if (not isinstance(data.get("evidence"), str) or not data["evidence"].strip()
                        or not isinstance(data.get("entry"), str) or not data["entry"].strip()
                        or not isinstance(data.get("commits"), str)
                        or not isinstance(data.get("request"), str)
                        or not re.fullmatch(r"[a-f0-9]{64}", data["request"])):
                    raise ValueError("已实现事件缺少证据或请求摘要")
                if operation_id_problem(data.get("operation_id")) is not None:
                    raise ValueError("已实现事件的操作 ID 无效")
                receipt = data.get("receipt")
                if (not isinstance(receipt, dict) or not isinstance(receipt.get("result"), dict)
                        or not isinstance(receipt.get("text"), str)):
                    raise ValueError("已实现事件缺少结果 receipt")
                # 账本行随事件持久化：中断后重放据此补齐账本（缺则补、有则跳过）。
                ledger_rows = data.get("ledger")
                if (not isinstance(ledger_rows, list) or not ledger_rows
                        or any(not isinstance(item, dict)
                               or any(not isinstance(item.get(key), str) or not item[key].strip()
                                      for key in ("section", "row"))
                               for item in ledger_rows)):
                    raise ValueError("已实现事件缺少账本行")
            if kind == EVENT_NODE_REVIEW:
                # 节点审查记录：节点、谱系、阶段、节点版本、已审范围、逐任务行、结论、
                # 前提与未关闭问题占位（前提语义随 T5）、请求摘要与 receipt 缺一不可。
                if (not isinstance(data.get("节点"), str) or not data["节点"].strip()
                        or not isinstance(data.get("谱系"), str) or not data["谱系"].strip()
                        or type(data.get("审查阶段")) is not int or data["审查阶段"] < 1
                        or data.get("verdict") not in NODE_REVIEW_VERDICTS):
                    raise ValueError("节点审查事件缺少节点、谱系、审查阶段或结论")
                if not re.fullmatch(r"[a-f0-9]{16}", str(data.get("节点版本", ""))):
                    raise ValueError("节点审查事件缺少节点版本")
                if (not isinstance(data.get("commits"), str)
                        or not isinstance(data.get("evidence"), str) or not data["evidence"].strip()):
                    raise ValueError("节点审查事件缺少已审提交范围或审查依据")
                if (not isinstance(data.get("entry"), str) or not data["entry"].strip()
                        or not isinstance(data.get("request"), str)
                        or not re.fullmatch(r"[a-f0-9]{64}", data["request"])):
                    raise ValueError("节点审查事件缺少入口或请求摘要")
                if operation_id_problem(data.get("operation_id")) is not None:
                    raise ValueError("节点审查事件的操作 ID 无效")
                if (not isinstance(data.get("premises"), list) or not all(
                        isinstance(item, str) and item.strip() for item in data["premises"])):
                    raise ValueError("节点审查事件缺少前提占位")
                if (not isinstance(data.get("open_issues"), list) or not all(
                        isinstance(item, str) and item.strip() for item in data["open_issues"])):
                    raise ValueError("节点审查事件缺少未关闭问题占位")
                lines = data.get("lines")
                if not isinstance(lines, list) or not lines:
                    raise ValueError("节点审查事件缺少逐任务行")
                for row in lines:
                    if (not isinstance(row, dict)
                            or any(not isinstance(row.get(key), str) or not row[key].strip()
                                   for key in ("task", "conclusion"))):
                        raise ValueError("节点审查事件的逐任务行缺少任务或结论")
                if len({row["task"] for row in lines}) != len(lines):
                    raise ValueError("节点审查事件的逐任务行有重复任务")
                receipt = data.get("receipt")
                if (not isinstance(receipt, dict) or not isinstance(receipt.get("result"), dict)
                        or not isinstance(receipt.get("text"), str)):
                    raise ValueError("节点审查事件缺少结果 receipt")
            if kind == PROJECTION_REPAIR:
                repairs = data.get("repairs")
                if (not isinstance(data.get("entry"), str) or not data["entry"].strip()
                        or not isinstance(repairs, list) or not repairs):
                    raise ValueError("投影修复事件缺少触发入口或修复清单")
                for item in repairs:
                    if (not isinstance(item, dict)
                            or any(not isinstance(item.get(key), str) or not item[key].strip()
                                   for key in ("task", "from", "to"))):
                        raise ValueError("投影修复事件缺少逐任务 from→to")
            if kind == "close":
                snapshot = data.get("snapshot")
                if (not isinstance(snapshot, dict) or not data.get("closed_at")
                        or snapshot.get("passed") is not True
                        or snapshot.get("cycle") != cycle or type(data.get("tasks")) is not int
                        or data["tasks"] <= 0 or not isinstance(data.get("next_step"), str)
                        or any(snapshot.get(k) != [] for k in ("blockers", "pending", "gaps", "unknown"))
                        or not isinstance(snapshot.get("coverage"), list)
                        or any(not isinstance(snapshot.get(k), str) or not re.fullmatch(r"[a-f0-9]{64}", snapshot[k]) for k in ("fingerprint", "acceptance"))):
                    raise ValueError("close 缺少结论快照")
                if snapshot.get("command_status") == "retired":
                    retirement = next((e for e in events if e["id"] == snapshot.get("command_retirement")), None)
                    prior = [e for e in events if e["type"] == "verify" and e["cycle"] == cycle]
                    if (not retirement or retirement["type"] != "command_retired"
                            or retirement["cycle"] != cycle or not prior
                            or retirement["data"]["verification"] != prior[-1]["id"]
                            or snapshot.get("retired_verification") != retirement["data"]["previous"]
                            or any(snapshot[k] != retirement["data"][k] for k in ("fingerprint", "acceptance"))
                            or snapshot.get("command_passed") is not None
                            or snapshot.get("command_required") is not False
                            or snapshot.get("command_exit_code") is not None
                            or snapshot.get("verification") is not None):
                        raise ValueError("close 的旧命令撤销快照无效")
                elif snapshot.get("command_passed") is not True:
                    raise ValueError("close 缺少成功命令或显式撤销结论")
                closed = True
        seen.add(event["id"])
        events.append(event)
    if not events:
        raise ValueError("events.jsonl 为空")
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
        elif event["type"] == EVENT_NODE_REVIEW:
            detail = (f"节点 {data['节点']} → {data['verdict']}；谱系 {data['谱系']}，"
                      f"阶段 {data['审查阶段']}，版本 {data['节点版本']}\n"
                      f"已审范围：{data['commits'] or '—'}；依据：{data['evidence']}\n"
                      + "\n".join(f"{row['task']}：{row['conclusion']}" for row in data["lines"]))
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
    # 写入前自校验：事件是权威记录，写坏它没有自救入口——先按读者的规则验一遍。
    validate_event_batch(old, new, slug)
    # 单控制器写入；一批逐项确认在同一次 append 中保存，读者拒绝任何残缺尾行。
    with open(events_path(root, slug), "a", encoding="utf-8") as fh:
        fh.write(serialize_events(new))
        fh.flush()
        os.fsync(fh.fileno())
    sync_event_view(root, slug)


# --------------------------------------------- 状态投影（格式 ≥4；D-04）

# 任务状态的推导与投影修复方向（T3 裁决 2）：有实现证据时不一致一律按事件推导修复
# （落后修复上；`complete` 缺 `pass` 支撑修复下）；投影声称有进度却没有实现证据 →
# 拒绝，不按计划状态静默回退。


def implemented_tasks(plan, events):
    """有 `implemented` 事件的任务集合——「实现是否完成」的单一判据（三态之一）。

    事件引用了计划里不存在的任务 → 无法推导，抛错拒绝（不静默忽略）。
    """
    known = {task.id for task in plan.tasks}
    implemented = set()
    for event in events:
        if event["type"] != EVENT_IMPLEMENTED:
            continue
        for tid in event["data"]["tasks"]:
            if tid not in known:
                # T5：改名/拆分/调整是设计里的预期场景，届时须用谱系解析放宽这条
                # 拒绝（给出合法恢复路径）；在此之前它是唯一出路——不得静默忽略。
                raise WorkflowError(
                    f"事件 {event['id']}（implemented）引用了计划里没有的任务 {tid}——"
                    "事件与计划无法对应，无法推导状态，拒绝继续（不得按计划状态静默放行）。"
                )
            implemented.add(tid)
    return implemented


def derived_states(plan, events):
    """由事件重放推导各任务的期望状态（格式 ≥4）——三档派生的单一真源（D-09/D-18）。

    ① 无 `implemented` 事件 → 期望 `pending`；
    ② 有实现证据、所属节点在【该谱系 × 当前阶段（首版恒 1）】下的**最近一条**
       `node_review` 为 `pass` → 期望 `complete`（＝已验收，D-03）；
    ③ 有实现证据、最近一条不是 `pass`（含审后 `fail`）→ 期望 `implemented`
       （已实现不因节点未通过而退回「待实现」）。
    实现判据（`implemented_tasks`）与节点结论判据（`node_valid_state`）都取自
    同一处实现；`repair_projection` 与各入口共用这一条规则，不得各自取
    「最近一次 pass」。
    """
    known = {task.id for task in plan.tasks}
    implemented = implemented_tasks(plan, events)
    index = node_review_index(events)
    passed = set()
    for node in plan.nodes:
        if node_valid_state(plan, events, node, index):
            passed.update(tid for tid in node.tasks if tid in known)
    out = {}
    for task in plan.tasks:
        if task.id not in implemented:
            out[task.id] = STATUS_PENDING
        elif task.id in passed:
            out[task.id] = STATUS_COMPLETE
        else:
            out[task.id] = STATUS_IMPLEMENTED
    return out


def _write_plan(plan):
    """回写计划文本（行数组 → 文件）；与既有 record / _set_approval_mode 同一写法。"""
    with open(plan.path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(plan.lines) + "\n")


def repair_projection(root, slug, entry="（未标注）"):
    """格式 ≥4：核对计划状态投影与事件重放推导，按事件双向修复；无证据的领先即拒绝。

    写入顺序与记账一致（先事件、后状态）：不一致时先写 `projection_repair` 事件
    （含触发入口与逐任务 from→to），再回写计划状态；随后原操作照常继续。
    修复方向按事件推导，双向（T3 裁决 2）：有实现证据时一律修复到推导值——
    投影落后修复上（pending→implemented、implemented→complete，后者是审查通过后
    中断的常见残留态），投影 `complete` 但无 `pass` 支撑修复下（`fail` 后中断的
    合法残留态）。投影声称 `implemented`/`complete` 而**没有任何实现证据** → 抛错
    拒绝：events.jsonl 是权威记录，事件缺失不得静默回退，也不得只改计划不写事件。
    格式 ≤3 不参与（调用方按格式分流；这里再兜一道，保持函数可独立复用）。
    """
    plan = load_plan(root, slug)
    if not plan.is_v4:
        return
    derived = derived_states(plan, read_events(root, slug))
    repairs, ahead = [], []
    for task in plan.tasks:
        want, have = derived[task.id], task.status
        if have == want:
            continue
        if have not in plan.valid_statuses:
            raise WorkflowError(
                f"任务 {task.id} 的状态 '{have}' 在格式 4 下非法"
                f"（只能是 {'/'.join(plan.valid_statuses)}），且无法由事件重放推导——"
                "拒绝继续；先修正为合法状态或补齐对应事件。"
            )
        if want == STATUS_PENDING:
            # 无实现证据却声称已有进度：事件缺失或冲突，不得静默回退。
            ahead.append(f"{task.id}：计划 {have} → 事件推导 {want}")
        else:
            # 有实现证据：双向修复到推导值（含 `complete` 缺 `pass` 支撑的修复下）。
            repairs.append({"task": task.id, "from": have, "to": want})
    if ahead:
        raise WorkflowError(
            "计划状态领先于事件重放推导，事件缺失或相互冲突，拒绝继续：\n  - "
            + "\n  - ".join(ahead)
            + "\n（格式 4 下 events.jsonl 是权威记录，计划状态只是可重放投影；"
            "不得按计划状态静默回退，也不得只改计划不写事件。）"
        )
    if not repairs:
        return
    for item in repairs:
        task = next(task for task in plan.tasks if task.id == item["task"])
        if task.field_lines.get("状态") is None:
            raise WorkflowError(f"{task.id} 缺少『状态』字段行，无法回写投影。")
    append_events(root, slug, [_event(slug, lifecycle(root, slug)["cycle"], PROJECTION_REPAIR,
                                      {"entry": entry, "repairs": repairs})])
    for item in repairs:
        task = next(task for task in plan.tasks if task.id == item["task"])
        plan.lines[task.field_lines["状态"]] = f"- **状态**：{item['to']}"
    _write_plan(plan)


# --------------------------------------------- 三态调度（格式 ≥4；T4：D-03/D-09/D-21）

def task_states(plan, events=None):
    """三态单一真源（格式 ≥4；D-09/T4）：{task_id: {implemented, node_valid, blocked}}。

    三种判断分别计算、不得混同：
    - `implemented`：该任务有 `implemented` 事件（实现是否完成，证据在 `record`）；
    - `node_valid`：所属审查节点的结论是否有效（口径见 `node_state`；失效判定源、
      版本坐标与恢复由 T5 收口——本函数只接线与调用，不自定义）；
    - `blocked`：所属节点的**直接**跨节点上游（`wait_graph` 边上的被等待者，含
      任务依赖导出边与显式声明边，D-21）中存在 `node_valid` 为假的节点。
      **组内依赖不看 node_valid**——同节点内按「已实现」放行（D-03）。
    上游未验收/失效只影响后两者与可派发性，**不改写任务状态行**：已实现的任务
    不因上游失效退回「待实现」（三态不得互相回退）。格式 ≤3 返回空字典。
    `events` 缺省取 `plan.events`（`load_plan` 为格式 ≥4 计划注入的事件流）。
    """
    if not plan.is_v4:
        return {}
    events = plan.events if events is None else events
    index = node_review_index(events)
    implemented = implemented_tasks(plan, events)
    owner = node_owner_map(plan)
    graph = wait_graph(plan)
    valid = {node.id: node_valid_state(plan, events, node, index) for node in plan.nodes}
    blocked = {node.id: any(not valid.get(up, False) for up in graph.get(node.id, ()))
               for node in plan.nodes}
    return {task.id: {"implemented": task.id in implemented,
                      "node_valid": valid.get(owner.get(task.id), False),
                      "blocked": blocked.get(owner.get(task.id), False)}
            for task in plan.tasks}


def node_progress(plan, events=None, facts=None):
    """节点级就绪视图（格式 ≥4；next/slice/status/close/verify 共用一份计算）。

    返回：
    - `states`：{节点 ID: 节点结论状态}（口径见 `node_state`）；
    - `members`：{节点 ID: [已实现的成员任务 ID]}；
    - `unaccepted`：有已实现成员、结论不是「已验收」的节点（close/verify 的就绪门
      看它；「待重新确认」由 T5 经 `node_state` 进入同一集合与同一校验点）；
    - `debt_tasks`：审查债务之「已实现但未完成节点审查的任务」（T4 裁决 4）——
      T4 口径下等价于「所在节点没有 pass 记录」；
    - `unopened`：审查债务之「尚未开启审查的节点」——有已实现成员但尚无任何
      `node_review` 记录。
    """
    empty = {"states": {}, "members": {}, "unaccepted": [], "debt_tasks": [], "unopened": []}
    if not plan.is_v4:
        return empty
    events = plan.events if events is None else events
    facts = task_states(plan, events) if facts is None else facts
    index = node_review_index(events)
    owner = node_owner_map(plan)
    states = {node.id: node_state(plan, events, node, index) for node in plan.nodes}
    members = {node.id: [task.id for task in plan.tasks
                         if task.id in node.tasks and facts[task.id]["implemented"]]
               for node in plan.nodes}
    return {
        "states": states,
        "members": members,
        "unaccepted": [node.id for node in plan.nodes
                       if members[node.id] and states[node.id] != NODE_STATE_VALID],
        "debt_tasks": [task.id for task in plan.tasks
                       if facts[task.id]["implemented"]
                       and states.get(owner.get(task.id), NODE_STATE_INVALID) != NODE_STATE_VALID],
        "unopened": [node.id for node in plan.nodes
                     if members[node.id] and node.id not in index["nodes_with_records"]],
    }


def node_progress_lines(progress):
    """未验收节点与「审查债务」的展示行（无内容返回空列表；next/status/slice 共用）。"""
    lines = []
    if progress["unaccepted"]:
        lines.append("未验收节点（跨节点依赖等待它们）：")
        for nid in progress["unaccepted"]:
            members = "、".join(progress["members"][nid])
            lines.append(f"  {nid} {NODE_STATE_TEXT[progress['states'][nid]]}（已实现成员：{members}）")
    debt = []
    if progress["debt_tasks"]:
        debt.append("已实现待审查：" + "、".join(progress["debt_tasks"]))
    if progress["unopened"]:
        debt.append("尚未开启审查：" + "、".join(progress["unopened"]))
    if debt:
        lines.append("审查债务：")
        lines.extend("  " + item for item in debt)
    return lines


def readiness_problems(plan, events, task, facts=None):
    """格式 ≥4 的派发就绪判据（T4 裁决 2）逐条原因；空列表＝可派发。

    就绪＝任务 `pending` ＋ 组内上游（同节点的任务依赖）全部已实现 ＋ 所属节点的
    **直接**跨节点上游（`wait_graph` 边：任务依赖导出边 ∪ 显式声明的节点依赖边，
    D-21）全部「已验收」。组内依赖按「已实现」放行、不等待审查（D-03）——组内依赖
    链不被跨节点规则阻塞，含组内依赖的节点能凑齐送审条件、不死锁；跨节点依赖等待
    上游节点整体已验收。格式 ≤3 不调用本函数（旧路径逐字不变）。
    """
    facts = task_states(plan, events) if facts is None else facts
    by_id = {item.id: item for item in plan.tasks}
    node_by_id = {node.id: node for node in plan.nodes}
    owner = node_owner_map(plan)
    problems = []
    if task.status != STATUS_PENDING:
        detail = {STATUS_IMPLEMENTED: "已实现、等待节点审查",
                  STATUS_COMPLETE: "已验收"}.get(task.status, "非派发状态")
        problems.append(
            f"{task.id} 当前状态为「{task.status}」（{detail}）——只有 pending 的任务可派发"
        )
    node_id = owner.get(task.id)
    for dep in task.deps:
        if dep not in by_id or owner.get(dep) != node_id:
            continue   # 跨节点依赖走下面的节点级判据；不存在的依赖由 check 报
        if not facts[dep]["implemented"]:
            problems.append(
                f"{task.id} 的组内上游 {dep} 尚未实现（同节点内按「已实现」放行，不等待审查）"
            )
    if node_id is not None:
        for up_id in sorted(wait_graph(plan).get(node_id, ())):
            up = node_by_id.get(up_id)
            if up is None:
                continue
            state = node_state(plan, events, up)
            if state != NODE_STATE_VALID:
                problems.append(
                    f"{task.id} 所属节点 {node_id} 跨节点等待 {node_state_line(plan, up, state, facts)}"
                    "——跨节点依赖（含仅显式声明的节点依赖）须等待上游节点已验收"
                )
    return problems


def require_node_acceptance(plan, events=None, entry="收尾"):
    """格式 ≥4 的最终验证/收尾就绪门（T4 裁决 5）：存在未验收节点即不放行。

    只加校验：不改验收指纹、计划指纹与既有收尾要求。「待重新确认」（T5）经
    `node_state` 进入同一集合与同一校验点，不另开旁路。格式 ≤3 直接返回——旧路径
    逐字不变（调用方无需按格式分流，本函数自己判）。
    """
    if not plan.is_v4:
        return
    progress = node_progress(plan, events)
    if not progress["unaccepted"]:
        return
    detail = "\n".join(
        f"  - {nid} {NODE_STATE_TEXT[progress['states'][nid]]}"
        f"（已实现成员：{'、'.join(progress['members'][nid])}）"
        for nid in progress["unaccepted"])
    raise WorkflowError(
        f"{entry} 拒绝：存在未验收的审查节点——节点是格式 4 的验收单位，"
        "上游节点通过 `review` 之前不得进入最终验证与收尾：\n" + detail
        + "\n（成员任务在节点通过后才映射 complete；先送审、通过后重试本命令。）"
    )


def _coverage_items(plan):
    if plan.coverage_errors:
        raise WorkflowError("覆盖表结构不明：" + "；".join(
            f"L{e['line']} {e['message']}（{e['text']}）" for e in plan.coverage_errors))
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
        adopted = []
        if latest and entry["type"] == "自动化" and identity not in waivers:
            try:
                adopted = _adopted_references(root, current, latest, identity)
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
        elif entry["status"] == "ok":
            if not entry["references"] or any(ref not in adopted for ref in entry["references"]):
                entry.update(status="unknown", note="当前声明引用尚无原验证/补证内容摘要；先用 evidence 核对关联")
        elif (entry["status"] == "unknown" and entry.get("declaration") == "none"
              and identity in supplements):
            # 无声明引用的说明文字可补证；明确路径/符号缺口不能被旧补证遮蔽。
            refs = supplements[identity]["data"]["references"]
            entry.update(status="ok", note="已关联既有验证：" + latest["id"], references=refs)
        if entry["required"] and entry["status"] == "unknown":
            unknown.append(entry)
        if entry["required"] and entry["status"] == "missing":
            gaps.append(entry)
    required_auto = [c for c in coverage if c["required"] and c["type"] == "自动化" and c["status"] != "waived"]
    retirement_eligible = bool(not state["closed"] and latest and items and not plan.verify_command
                               and not required_auto and not plan.is_bug)
    retirement = next((e for e in reversed(valid) if e["type"] == "command_retired"
                       and retirement_eligible and e["data"]["verification"] == latest["id"]), None)
    command_needed = bool(plan.verify_command or required_auto or (latest and not retirement))
    command_ok = not command_needed
    if retirement:
        try:
            _receipt(root, slug, latest)
        except WorkflowError as exc:
            blockers.append(str(exc))
    elif command_needed:
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
    if not command_needed and (not items or not (verdicts or waivers)):
        blockers.append("无验证命令时，必须有明确验收项和逐项人工结论/用户豁免依据；空验收不通过")
    if pending:
        blockers.append("实现完成，等待人工验收：" + "、".join(c["id"] for c in pending))
    if unknown:
        blockers.append("必验证据待核实：" + "、".join(c["id"] for c in unknown))
    if gaps:
        blockers.append("必验覆盖缺少产物：" + "、".join(c["id"] for c in gaps))
    return {"passed": not blockers, "command_passed": None if retirement else command_ok,
            "command_required": command_needed,
            "command_status": "retired" if retirement else ("passed" if command_ok and command_needed
                                                            else "not_required" if not command_needed else "blocked"),
            "command_exit_code": latest["data"]["exit_code"] if latest and not retirement else None,
            "verification": latest["id"] if latest and not retirement else None,
            "command_retirement": retirement["id"] if retirement else None,
            "retired_verification": _verification_summary(latest) if retirement else None,
            "command_change": {"previous": _verification_summary(latest) if latest else None,
                               "current": {"command": plan.verify_command, **binding,
                                           "required_automatic": [c["id"] for c in required_auto]},
                               "retirement_eligible": retirement_eligible},
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
    result["command_change"] = acceptance_state(root, slug, plan, binding)["command_change"]
    lines = ["请依据以下逐项手段/步骤及预期核对；可一次答复明确清单中的多项。",
             f"清单绑定：{result['checklist']}"]
    lines += [f"{c['id']} [{c['type']}, {'必需' if c['required'] else '可选'}] {c['target']}：{c['means']}"
              for c in items.values()]
    change = result["command_change"]
    if change["previous"]:
        old = change["previous"]
        lines += [f"旧验证 {old['id']}：{old['command']}；退出码 {old['exit_code']}",
                  f"旧工作树/验收：{old['fingerprint']} / {old['acceptance']}",
                  f"当前命令：{plan.verify_command or '无'}；当前工作树/验收：{binding['fingerprint']} / {binding['acceptance']}",
                  "仅修改计划或确认人工项不撤销旧命令要求；具体撤销授权须用 retire-command 单独登记。"]
    return result, "\n".join(lines)


def cmd_retire_command(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    state = require_active(root, slug)
    plan = load_plan(root, slug)
    binding = _binding(root, plan)
    if args.checklist != _digest(binding):
        raise WorkflowError("当前清单绑定已失效；先 acceptance 核对新旧命令和要求")
    if any(not getattr(args, key).strip() for key in ("by", "source", "reason")):
        raise WorkflowError("撤销旧命令要求必须有具体用户答复、来源和理由")
    current = acceptance_state(root, slug, plan, binding)
    if not current["command_change"]["retirement_eligible"]:
        raise WorkflowError("仅可在当前清单非空、无命令、无未豁免必验自动化项且非 bug 时撤销旧命令要求")
    events = read_events(root, slug)
    latest = [e for e in events if e["cycle"] == state["cycle"] and e["type"] == "verify"][-1]
    if args.verify != latest["id"]:
        raise WorkflowError("必须明确指向当前周期最近一次验证，不能越过后来的结果")
    _receipt(root, slug, latest)
    event = _event(slug, state["cycle"], "command_retired", {
        **binding, "verification": latest["id"], "previous": _verification_summary(latest),
        "replacement_command": "", "checklist": args.checklist,
        "by": args.by, "source": args.source, "reason": args.reason})
    append_events(root, slug, [event])
    return {"slug": slug, "event": event["id"], "retired_verification": event["data"]["previous"],
            "executed": False}, "✓ 已记录旧命令要求的明确撤销；旧结果保留，当前清单仍须逐项验收"


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
    declaration = reference_declaration(item)
    if declaration["state"] == "invalid":
        raise WorkflowError("明确引用格式无效，不能用补证掩盖：" + declaration["error"])
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
        elif acceptance["pending"] and (acceptance["command_passed"] or not acceptance["command_required"]):
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
        "coverage_errors": plan.coverage_errors,
    }

    lines = [
        f"工作流 {slug} — {stage}",
        f"类型：{plan.kind}；路径：{result['approval_path']}",
        f"目标：{result['goal']}",
        f"进度：{counts.get('DONE', 0)}/{len(plan.tasks)} 完成"
        + (f"，{counts.get('READY', 0)} 可执行" if counts.get("READY") else "")
        + (f"，{counts.get('BLOCKED', 0)} 被阻塞" if counts.get("BLOCKED") else "")
        + (f"，{counts.get('IMPLEMENTED', 0)} 已实现待审查" if counts.get("IMPLEMENTED") else ""),
    ]
    if phase:
        lines.append(f"当前阶段：Phase {phase} — {result['phase_name']}")
    lines.append("")
    for t in result["tasks"]:
        mark = {
            "DONE": "[x]",
            "READY": "[ ]",
            "RUNNING": "[~]",
            "IMPLEMENTED": "[~]",
            "BLOCKED": "[-]",
        }[t["state"]]
        dep = f"  ← {', '.join(t['deps'])}" if t["deps"] else ""
        lines.append(f"  {mark} {t['id']} {t['title']}  ({t['state']}){dep}")
    if plan.is_v4:
        # 格式 ≥4：未验收节点 / 待重新确认 / 审查债务清单（T4 裁决 4）。
        progress = node_progress(plan, plan.events)
        result["node_states"] = progress["states"]
        result["unaccepted_nodes"] = progress["unaccepted"]
        result["review_debt"] = {"tasks": progress["debt_tasks"], "unopened": progress["unopened"]}
        debt_lines = node_progress_lines(progress)
        if debt_lines:
            lines.append("")
            lines.extend(debt_lines)
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


def next_v4(plan, slug):
    """格式 ≥4 的 `next`（T4 裁决 2/4）：就绪与展示都走三态，不另算一套。

    就绪＝`pending` ＋ 组内上游已实现 ＋ 所属节点的直接跨节点上游已验收（D-03/D-21）；
    已实现待审查的任务单独列出（不派发）；未验收节点与「审查债务」清单随展示给出。
    """
    events = plan.events
    facts = task_states(plan, events)
    progress = node_progress(plan, events, facts)
    owner = node_owner_map(plan)
    ready, awaiting, blocked = [], [], []
    for task in plan.tasks:
        if task.status == STATUS_COMPLETE:
            continue
        problems = readiness_problems(plan, events, task, facts)
        if not problems:
            ready.append(task)
        elif task.status == STATUS_IMPLEMENTED:
            awaiting.append({"id": task.id, "title": task.title})
        else:
            blocked.append({"id": task.id, "title": task.title, "deps": task.deps,
                            "reasons": problems})

    # 可合并提示（格式 ≥4 追加同节点约束）：同节点 + 互不依赖 + 文件不重叠才是合法批次。
    batchable = []
    if len(ready) > 1:
        groups = {}
        for task in ready:
            groups.setdefault(owner.get(task.id), []).append(task)
        for members in groups.values():
            group = []
            for task in members:
                if len(group) >= MAX_BATCH_TASKS:
                    break
                ids = {x.id for x in group}
                if ids & set(task.deps):
                    continue
                paths = {_norm_path(f) for f in task.files} - {""}
                taken = {_norm_path(f) for x in group for f in x.files} - {""}
                if paths and paths & taken:
                    continue
                group.append(task)
            if len(group) > 1:
                batchable = [t.id for t in group]
                break

    result = {
        "slug": slug,
        "ready": [{"id": t.id, "title": t.title, "parallel": t.is_parallel} for t in ready],
        "awaiting_review": awaiting,
        "blocked": blocked,
        "batchable": batchable,
        "node_states": progress["states"],
        "unaccepted_nodes": progress["unaccepted"],
        "review_debt": {"tasks": progress["debt_tasks"], "unopened": progress["unopened"]},
    }
    lines = []
    if not ready:
        if awaiting or blocked:
            msg = "没有可派发的任务。"
            if awaiting:
                msg += f" {len(awaiting)} 个任务已实现、等待节点审查。"
            if blocked:
                msg += f" 剩余 {len(blocked)} 个任务被阻塞。"
        elif plan.tasks:
            msg = "没有可派发的任务。 全部任务已验收，进入 V 轮验证。"
        else:
            msg = "没有可派发的任务。 计划里没有任务。"
        lines.append(msg)
    else:
        lines.append("可执行任务：")
        for item in result["ready"]:
            tag = "  [可并行]" if item["parallel"] else ""
            lines.append(f"  {item['id']} {item['title']}{tag}")
        if len(batchable) > 1:
            lines += [
                "",
                f"可合并为一批：{', '.join(batchable)}"
                "（同属一个审查节点、互不依赖、文件不重叠）",
                f"  ——若它们是同型机械改动，用 `slice {slug} {' '.join(batchable)}`"
                " 一次派发、一次审查；否则逐个派。",
            ]
    if awaiting:
        lines += ["", "已实现待节点审查（不派发）："]
        for item in awaiting:
            lines.append(f"  {item['id']} {item['title']}")
    if blocked:
        lines.append("")
        lines.append("被阻塞：")
        for item in blocked:
            lines.append(f"  {item['id']} {item['title']}")
            lines.extend("      - " + reason for reason in item["reasons"])
    debt_lines = node_progress_lines(progress)
    if debt_lines:
        lines += [""] + debt_lines
    return result, "\n".join(lines)


def cmd_next(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    plan = load_plan(root, slug)
    if plan.is_v4:
        return next_v4(plan, slug)
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

    if plan.is_v4:
        # 格式 ≥4（T4 裁决 3）：批次成员须同属一个审查节点（一次审查只覆盖一个
        # 节点的归属任务）；「已完成或被阻塞」按三态（complete / 跨节点上游未验收）。
        owner = node_owner_map(plan)
        node_ids = {owner.get(t.id) for t in tasks}
        if len(node_ids) > 1:
            detail = "、".join(
                f"{t.id}→{owner.get(t.id) or '未归属节点'}" for t in tasks)
            raise WorkflowError(
                f"批次跨越多个审查节点（{detail}）——合并派发是「一次审查」的粒度，"
                "成员须同属一个节点；跨节点请拆成两次派发（节点通过后下游才解除等待）。"
            )
        facts = task_states(plan)
        for t in tasks:
            if t.status == STATUS_COMPLETE:
                raise WorkflowError(f"{t.id} 已完成，不能再次纳入批次。")
            if facts[t.id]["blocked"]:
                raise WorkflowError(
                    f"{t.id} 当前被阻塞（所属节点的跨节点上游有未验收节点），不能纳入批次。"
                )
        warnings = _batch_file_warnings(tasks)
        return warnings

    st = plan.states()
    for t in tasks:
        state = st[t.id]
        if state == "DONE":
            raise WorkflowError(f"{t.id} 已完成，不能再次纳入批次。")
        if state == "BLOCKED":
            raise WorkflowError(f"{t.id} 当前被阻塞（依赖未完成），不能纳入批次。")

    return _batch_file_warnings(tasks)


def _batch_file_warnings(tasks):
    """文件重叠/析不出路径的警告（≤3 与格式 ≥4 两条路径共用同一份判据）。"""
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
    if plan.is_v4:
        # 入口统一在动作前做投影检查：落后先修复（留 projection_repair）、领先即拒绝。
        repair_projection(root, slug, "slice")
        plan = load_plan(root, slug)   # 修复可能已回写状态行，重新取计划
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
    if plan.is_v4:
        # 就绪校验（T4 裁决 2）：待办/块级守卫都过了仍可能未就绪——逐任务给出原因，
        # 消息含上游节点 ID 与状态（「待重新确认」按 T5 的措辞走同一处状态文本）。
        facts = task_states(plan)
        problems = []
        for t in tasks:
            problems += readiness_problems(plan, plan.events, t, facts)
        if problems:
            raise WorkflowError(
                "本次派发不满足格式 4 的就绪条件：\n  - " + "\n  - ".join(problems)
                + "\n（组内依赖按「已实现」放行、不等待审查；跨节点依赖等待上游节点"
                "整体已验收——先送审上游节点、通过后再重试本命令。）"
            )
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
    if plan.is_v4:
        # 未验收节点 / 待重新确认 / 审查债务随展示给出（T4 裁决 4）。
        progress = node_progress(plan, plan.events)
        result["node_states"] = progress["states"]
        result["unaccepted_nodes"] = progress["unaccepted"]
        result["review_debt"] = {"tasks": progress["debt_tasks"], "unopened": progress["unopened"]}
        debt_lines = node_progress_lines(progress)
        if debt_lines:
            result["brief"] += ("\n\n## 审查节点状态（控制器核对用；不影响本任务范围）\n\n"
                                + "\n".join(debt_lines))
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


def _check_commit_range(root, raw, plan, has_note, empty_hint=None):
    """校验 record / review 的 `--commits <base>..<head>`，返回 [(level, message)]。

    为什么值得校验：提交范围是账本里「这个任务改了什么」的唯一记录，终审也按它取
    diff。空范围（base == head）或写错的 sha 会让这两件事同时失效，而账本本身看不出来。

    **阶段性提交**是硬要求：每个任务完成即提交，别把几个任务攒成一次。
    格式 2 的计划按 ERROR 拦；老计划降为 WARNING——那批计划可能是按「不提交」的
    约定跑起来的（有的项目全局约束就写着"提交只在用户明确要求时做"），不该被升级打断。
    `empty_hint` 覆盖空范围时的提示文案（review 的已审范围用；默认文案逐字不变）。
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
                empty_hint or
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


def record_implemented(args, root, slug, plan):
    """格式 ≥4 的 `record`：记「已实现」——证据必填、操作 ID 必带、先事件后状态。

    一次操作（可含多任务）只写一条 `implemented` 事件：tasks、evidence、commits、
    operation_id、请求摘要与结果 receipt；随后回写计划状态「已实现」，最后记账本行。
    同 ID＋同请求重试 → 幂等重放原结果（不写事件、不改计划、不重复账本行）；
    同 ID＋不同请求 → 拒绝。任务完成（＝已验收）由节点 `review` 通过后映射，
    不由记录者宣告——格式 ≥4 不再接受 `--verdict`。
    """
    if args.verdict is not None:
        raise WorkflowError(
            "格式 ≥4 的 record 不再使用 `--verdict`：改用 "
            "`--evidence \"<验收怎么跑、结果、失败信号自查>\"` 记「已实现」；"
            "任务完成（＝已验收）由节点审查通过后映射，不由记录者宣告。"
        )
    evidence = (args.evidence or "").strip()
    if not evidence:
        raise WorkflowError(
            "格式 ≥4 的 record 必须给 `--evidence \"<验收怎么跑、结果、失败信号自查>\"`——"
            "实现证据随任务记账：实际修改、提交范围、验收方法与结果、相关失败信号、"
            "尚存疑问。缺它账本里就没有「这个任务凭什么算做完」的依据。"
        )
    duplicates = sorted({tid for tid in args.task_id if args.task_id.count(tid) > 1})
    if duplicates:
        raise WorkflowError(
            f"重复的任务 ID：{'、'.join(duplicates)}——格式 ≥4 的 record 一次操作按任务集合"
            "记账（一条事件、一个操作身份、一次账本行），重复 ID 不产生额外效果，直接拒绝。"
        )

    # 请求身份用去重集合（重试可换书写顺序）；事件里的 tasks 用计划顺序取，
    # 重复 ID 已在上面拒绝，两者是同一集合。
    request = operation_request_digest(
        {"tasks": sorted(set(args.task_id)), "commits": args.commits, "evidence": evidence})
    action, existing = resolve_operation(root, slug, args.operation_id, request, "record")
    if action == "replay":
        # 幂等重放：不写事件、不改计划、不新增账本行；补齐中断可能漏写的账本行后
        # 返回随事件持久化的原结果＋历史回放提示。
        restore_ledger_rows(root, slug, existing)
        return replay_result(existing, args.operation_id)

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
    stamp = _now()
    commits = args.commits or "—"
    label = " + ".join(t.id for t in tasks)
    # 账本行随事件持久化：中断（事件已落盘、账本未写）后重放据此补齐，缺则补、有则跳过。
    ledger_rows = [{"section": "完成记录",
                    "row": f"| {t.id} | {commits} | 已实现（操作 {args.operation_id}） | {stamp} |"}
                   for t in tasks]
    if args.note:
        ledger_rows.append({"section": "裁决", "row": f"| {stamp} | {label} | {args.note} | — |"})

    event = _event(slug, lifecycle(root, slug)["cycle"], EVENT_IMPLEMENTED, {
        "tasks": [t.id for t in tasks],
        "evidence": evidence,
        "commits": args.commits,
        "operation_id": args.operation_id,
        "request": request,
        "entry": "record",
        "ledger": ledger_rows,
    })
    result = {
        "slug": slug,
        "tasks": [t.id for t in tasks],
        "batch": batch,
        "operation_id": args.operation_id,
        "event": event["id"],
        "warnings": warnings,
        "status": STATUS_IMPLEMENTED,
        "evidence": evidence,
        "commits": args.commits,
        "ledger": ledger_path(root, slug),
        # 阶段末提醒沿用 ≤3 语义（任务 complete 才算该阶段完成）；格式 4 的
        # 阶段检查点随节点验收推进，重定义属 T4，本任务不引入第二套语义。
        "phase_completed": None,
    }
    text = f"✓ {label} → 已实现（evidence 已记，操作 {args.operation_id}），已记账本"
    if warnings:
        text = "⚠ " + "\n⚠ ".join(warnings) + "\n" + text
    event["data"]["receipt"] = {"result": result, "text": text}
    for t in tasks:
        if t.field_lines.get("状态") is None:
            raise WorkflowError(f"{t.id} 缺少『状态』字段行，无法回写。")

    # 写入顺序固定：先 append 事件、再回写计划状态、最后记账本行（D-04）。
    append_events(root, slug, [event])
    for t in tasks:
        plan.lines[t.field_lines["状态"]] = f"- **状态**：{STATUS_IMPLEMENTED}"
    _write_plan(plan)
    for item in ledger_rows:
        ledger_append(root, slug, item["section"], item["row"])
    return result, text


def review_node(args, root, slug, plan):
    """格式 ≥4 的 `review`：记节点审查结论——`pass` 后成员任务才映射 `complete`。

    一次操作只写一条 `node_review` 事件：操作 ID、节点、谱系、审查阶段、节点版本、
    已审提交范围、逐任务行、审查依据、结论、前提与未关闭问题占位（`premises`/`open_issues`
    首版恒空——前提语义留 T5，不在此发明）、请求摘要与结果 receipt。写序＝先事件、
    后状态：`pass` 把成员任务写 `complete`，`fail` 保持 `implemented`——不映射 `complete`、
    不释放跨节点依赖，也不把已实现退回待实现。账本不新增行（事件即记录，呈现由 sync 承担）。
    同 ID＋同请求重试 → 幂等重放原结果（不写事件、不改计划、不重复计轮）；
    同 ID＋不同请求 → 拒绝。
    """
    verdict = args.verdict
    evidence = (args.evidence or "").strip()
    if not evidence:
        raise WorkflowError(
            "review 必须给 `--evidence \"<引用>\"`：审查依据（读到的实际改动与必要上下文、"
            "复用的验证与证据引用、失败信号自查）随结论保存——缺它结论没有可核的来源。"
        )
    commits = (args.commits or "").strip()
    if not commits:
        raise WorkflowError(
            "review 必须给 `--commits <base7>..<head7>`：已审提交范围是结论绑定的一部分"
            "（它决定这条结论覆盖哪个版本），缺它无法判断结论对谁有效。"
        )
    node = next((item for item in plan.nodes if item.id == args.node_id), None)
    if node is None:
        raise WorkflowError(
            f"计划里没有审查节点 {args.node_id}。现有节点："
            + ("、".join(item.id for item in plan.nodes) or "（一个都没有）")
            + "——格式 ≥4 的审查单位是节点（任务是执行单位）。"
        )
    owners = node.tasks
    if not owners:
        raise WorkflowError(
            f"审查节点 {node.id} 没有列出归属任务，无法送审——先在计划里补『归属任务』字段。"
        )
    by_id = {task.id: task for task in plan.tasks}
    unknown = [tid for tid in owners if tid not in by_id]
    if unknown:
        raise WorkflowError(
            f"审查节点 {node.id} 的归属任务 {'、'.join(unknown)} 不在计划里——先修正计划。"
        )
    rows, problem = parse_review_lines(args.lines or "", owners)
    if problem:
        raise WorkflowError(
            f"`--lines` 不合格：{problem}。逐任务一行结论，每行都要写清依据："
            "`--lines \"T1: 验收依据/结论；T2: 验收依据/结论\"`。"
        )

    # 请求身份：节点 + 结论 + 已审范围 + 逐任务行（任务序不敏感）+ 证据。
    request = operation_request_digest({
        "entry": "review",
        "node": node.id,
        "verdict": verdict,
        "commits": args.commits,
        "evidence": evidence,
        "lines": sorted([row["task"], row["conclusion"]] for row in rows),
    })
    action, existing = resolve_operation(root, slug, args.operation_id, request, "review")
    if action == "replay":
        # 幂等重放：不写事件、不改计划；返回随事件持久化的原结果（含显示文案）。
        return replay_result(existing, args.operation_id)

    require_plan_approval(root, slug, plan)   # 与 record/slice 同一道门，防绕过
    ledger_check_owner(root, slug)

    events = read_events(root, slug)
    # 送审条件（机械部分）：归属任务全部已实现（按事件推导，不按计划投影）。
    derived = derived_states(plan, events)
    pending = [tid for tid in owners if derived.get(tid) == STATUS_PENDING]
    if pending:
        raise WorkflowError(
            f"审查节点 {node.id} 的归属任务尚未全部实现，不得送审：{'、'.join(pending)} 没有 "
            "`implemented` 事件——先 `record` 记实现与证据，再送审"
            "（必要验证与未解决事项的核对由审查者负责，引擎只闸这一条机械条件）。"
        )

    problems = _check_commit_range(
        root, args.commits, plan, True,
        "节点内任务都没有产生提交（base 与 head 指向同一个提交），已审范围为空——"
        "确认这与实际一致。",
    )
    blockers = [message for level, message in problems if level == "ERROR"]
    if blockers:
        raise WorkflowError(
            "已审提交范围不合法，先修正再记审查结论：\n"
            + "\n".join(f"  - {m}" for m in blockers)
        )
    warnings = [message for level, message in problems if level == "WARNING"]

    version = node_version(plan, node)
    lineage = node_lineage(events, node.id) or new_node_lineage(slug, node)
    phase = NODE_PHASE_FIRST
    # 轮次与派生同源（T3 审查 Low ②）：同谓词不再两处实现。
    # `rounds` ＝ 本条记入后该谱系的轮次（＝记入前的记录条数，T3 候选 5）。
    prior = node_review_count(events, lineage, phase)
    mapped = STATUS_COMPLETE if verdict == "pass" else STATUS_IMPLEMENTED
    items = owners
    event = _event(slug, lifecycle(root, slug)["cycle"], EVENT_NODE_REVIEW, {
        "节点": node.id,
        "谱系": lineage,
        "审查阶段": phase,
        "节点版本": version,
        "commits": args.commits,
        "lines": rows,
        "evidence": evidence,
        "verdict": verdict,
        "premises": [],
        "open_issues": [],
        "operation_id": args.operation_id,
        "request": request,
        "entry": "review",
    })
    result = {
        "slug": slug,
        "node": node.id,
        "lineage": lineage,
        "phase": phase,
        "rounds": prior,
        "verdict": verdict,
        "commits": args.commits,
        "evidence": evidence,
        "node_version": version,
        "tasks": items,
        "mapped_status": mapped,
        "operation_id": args.operation_id,
        "event": event["id"],
        "premises": [],
        "open_issues": [],
        "warnings": warnings,
    }
    label = "、".join(items)
    if verdict == "pass":
        text = (f"✓ 节点 {node.id} → pass：{label} 映射 {STATUS_COMPLETE}"
                f"（谱系 {lineage}，第 {prior} 轮）；审查记录已入事件流")
    else:
        text = (f"✗ 节点 {node.id} → fail：{label} 保持 {STATUS_IMPLEMENTED}"
                f"（谱系 {lineage}，第 {prior} 轮）；节点未通过，跨节点依赖不释放；"
                "修复后送复审")
    if warnings:
        text = "⚠ " + "\n⚠ ".join(warnings) + "\n" + text
    event["data"]["receipt"] = {"result": result, "text": text}
    for tid in items:
        if by_id[tid].field_lines.get("状态") is None:
            raise WorkflowError(f"{tid} 缺少『状态』字段行，无法回写。")

    # 写入顺序固定：先 append 事件、再回写计划状态（D-04）；审查不新增账本行。
    append_events(root, slug, [event])
    for tid in items:
        plan.lines[by_id[tid].field_lines["状态"]] = f"- **状态**：{mapped}"
    _write_plan(plan)
    return result, text


def cmd_review(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    require_active(root, slug)
    plan = load_plan(root, slug)
    if not plan.is_v4:
        raise WorkflowError(
            f"本计划是格式 {plan.format_version}——`review` 只在格式 ≥4（审查节点制）生效："
            "格式 ≤3 的审查单位是任务，没有节点审查形态（也不该为它补一个空壳）。"
            "要把该工作流升级为节点审查，先把计划头部 `**格式**` 升到 4 并补齐 "
            "`## 审查节点` 段；`--recheck`/`--new-phase` 属后续任务，尚未提供。"
        )
    # 入口统一在动作前做投影检查（already-closed / 归属检查之后、审批门之前）：
    # 落后先修复（留 projection_repair）、领先即拒绝——与 record/slice/close 同一协议。
    repair_projection(root, slug, "review")
    plan = load_plan(root, slug)   # 修复可能已回写状态行，重新取计划
    return review_node(args, root, slug, plan)


def cmd_record(args):
    root = find_project_root()
    slug = resolve_slug(root, args.slug)
    require_active(root, slug)
    plan = load_plan(root, slug)
    if plan.is_v4:
        # 入口统一在动作前做投影检查：落后先修复（留 projection_repair）、领先即拒绝。
        # `review` 按同一入口协议接入（见 cmd_review）——不得各入口各自判断状态。
        repair_projection(root, slug, "record")
        plan = load_plan(root, slug)   # 修复可能已回写状态行，重新取计划
        return record_implemented(args, root, slug, plan)
    if (args.evidence or "").strip() or (args.operation_id or "").strip():
        # 新参数只服务格式 ≥4 的两态记账：旧格式上静默忽略会让误用被放过
        # （控制器会以为走了两态记账）。拒绝即恢复旧输入空间的报错行为。
        raise WorkflowError(
            f"本计划是格式 {plan.format_version}，不支持 `--evidence`/`--operation-id`"
            "（仅格式 ≥4 的两态记账使用）：请改用 `--verdict <clean|issues>`；"
            "要把该工作流升级为两态记账，先把计划头部 `**格式**` 升到 4 并补齐 `## 审查节点` 段。"
        )
    if args.verdict is None:
        args.verdict = "clean"
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


def reference_declaration(entry):
    """完整解析有限文件引用语法；none 与 invalid 不能在补证时混同。"""
    explicit = bool(entry.get("evidence", "").strip())
    text = (entry.get("evidence", "") if explicit else entry["means"]).strip()

    def invalid(message):
        return {"state": "invalid", "tokens": [], "error": message}

    if any(char in text for char in ("\n", "\r", "\0", "|")):
        return invalid("引用不能含换行、NUL 或表格管道字符")
    if "`" in text:
        if explicit and not re.fullmatch(r"`[^`]*`(?:[\s,，、;；+]+`[^`]*`)*", text):
            return invalid("独立证据列须为完整反引号引用列表；存在未闭合标记、缺分隔符或残余文本")
        if text.count("`") % 2:
            return invalid("引用反引号未闭合")
        raw_tokens = re.findall(r"`([^`]*)`", text)
    elif explicit or (text and not re.search(r"\s", text)):
        raw_tokens = [text]
    else:
        return {"state": "none", "tokens": [], "error": ""}
    tokens = []
    for token in raw_tokens:
        parts = [part.strip() for part in token.split("::")]
        if not parts[0] or any(not symbol for symbol in parts[1:]):
            return invalid("空路径/空引用或空符号不能被丢弃")
        tokens.append({"path": parts[0], "symbols": parts[1:]})
    return {"state": "declared", "tokens": tokens, "error": ""}


def audit_coverage(root, plan):
    """检查自动化引用的存在性；语义覆盖仍由独立审查判断。"""
    _coverage_items(plan)
    out = []
    for entry in plan.coverage:
        current = dict(entry)
        if entry["type"] == "人工":
            current.update(status="manual", note="需人工执行")
            out.append(current)
            continue
        declaration = reference_declaration(entry)
        current.update(declaration=declaration["state"], references=[])
        if declaration["state"] != "declared":
            note = declaration["error"] or "没有明确产物引用，优先关联既有验证证据"
            current.update(status="unknown", note=note)
            out.append(current)
            continue
        checked, missing, references = [], [], []
        for token in declaration["tokens"]:
            path, symbols = token["path"], token["symbols"]
            label = "::".join([path] + symbols)
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
                        missing.append(f"{label}（文件里没有 {'、'.join(absent)}）")
                        continue
                except (OSError, UnicodeError):
                    missing.append(f"{label}（读不到）")
                    continue
            try:
                references.append({"path": os.path.relpath(os.path.abspath(full), root),
                                   "hash": _file_digest(full)})
            except WorkflowError as exc:
                missing.append(str(exc))
                continue
            checked.append(label)
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
    # 就绪校验（T4 裁决 5）：存在未验收节点/未处理待重新确认 → 拒绝——验证与收尾
    # 都不能绕过节点验收（格式 ≤3 时本函数直接返回，旧路径逐字不变）。
    require_node_acceptance(plan, plan.events, "验证（verify）")
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
    if plan.is_v4:
        # 入口统一在动作前做投影检查：落后先修复（留 projection_repair）、领先即拒绝。
        # 排在 already-closed 与账本归属检查之后：已关闭周期不追加修复事件（事件读校验
        # 会拒绝向关闭周期写事件，先写会污染权威文件）。
        repair_projection(root, slug, "close")
        plan = load_plan(root, slug)   # 修复可能已回写状态行，重新取计划
        # 就绪校验（T4 裁决 5）：未验收节点不放行——节点级理由比「未完成任务」更能指路。
        require_node_acceptance(plan, plan.events, "收尾（close）")
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
    s.add_argument(
        "--verdict",
        default=None,
        choices=["clean", "issues"],
        help="格式 ≤3 的判词（默认 clean）；格式 ≥4 不再使用——改用 --evidence",
    )
    s.add_argument(
        "--evidence",
        default="",
        help="格式 ≥4 必填：验收怎么跑、结果、失败信号自查（实现证据随任务记账）",
    )
    s.add_argument(
        "--operation-id",
        default="",
        help="格式 ≥4 必填：本次记账操作的稳定 ID；首次执行前生成并保存，重试复用",
    )
    s.add_argument("--note", default="")
    _add_json(s)
    s.set_defaults(func=cmd_record)

    s = sub.add_parser("review", help="记节点审查结论（格式 ≥4；pass 后成员任务映射 complete）")
    s.add_argument("slug", nargs="?")
    s.add_argument("node_id", help="审查节点 ID（形如 N1）")
    s.add_argument("--verdict", required=True, choices=["pass", "fail"],
                   help="节点整体结论：pass 映射成员任务 complete；fail 保持已实现")
    s.add_argument("--commits", default="", help="已审提交范围 <base7>..<head7>")
    s.add_argument("--lines", default="",
                   help="逐任务行：`T1: 结论＋依据；T2: …`（`；` 或换行分隔，须覆盖全部归属任务）")
    s.add_argument("--evidence", default="", help="审查依据：读到的改动与上下文、复用的验证/证据引用")
    s.add_argument(
        "--operation-id",
        default="",
        help="必填：本次记账操作的稳定 ID；首次执行前生成并保存，重试复用",
    )
    _add_json(s)
    s.set_defaults(func=cmd_review)

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

    s = sub.add_parser("retire-command", help="明确撤销旧命令要求并绑定新验收；保留旧成功/失败")
    s.add_argument("slug", nargs="?")
    s.add_argument("--verify", required=True, help="当前周期最近一次验证 ID")
    s.add_argument("--checklist", required=True, help="acceptance 返回的当前清单绑定")
    s.add_argument("--by", required=True, help="用户对撤销旧命令要求的具体答复")
    s.add_argument("--source", required=True, help="答复的可追溯来源")
    s.add_argument("--reason", required=True)
    _add_json(s)
    s.set_defaults(func=cmd_retire_command)

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
