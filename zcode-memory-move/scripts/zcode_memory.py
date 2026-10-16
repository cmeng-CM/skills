#!/usr/bin/env python3
"""zcode_memory.py — ZCode 项目记忆定位与迁移（纯标准库，Python 3.8+）。

记忆键算法（与 ZCode 运行时实现一致，已实测验证）：
    slug   = basename(resolve(工作区路径))，小写化 → 非 [a-z0-9._-] 字符替换为 "-"
             → 去首尾 "-" → 截前 48 字符；为空则 "project"
    hash16 = sha256(resolve(工作区路径)) 的前 16 位十六进制（Windows 上路径先小写）
    记忆目录 = <cliStorageRoot>/memories/projects/<slug>-<hash16>/memory/
    （本机 cliStorageRoot 实测为 ~/.zcode/cli；可用环境变量 ZCODE_CLI_ROOT 覆盖，便于测试）

子命令：
    key <路径>                  正向：目录路径 → 记忆键与记忆目录
    find <键 或 路径>            反查：键归属哪个目录（扫描候选根逐个重算 sha256 核对）
    inventory [--roots R ...]   盘点全部记忆键：归属目录 + 文件数
    move <源> <目标> [--keep-source] [--dry-run] [--skip-conflicts]
                                迁移/合并：复制 → 逐文件校验 → 合并 MEMORY.md → 删源
"""
from __future__ import annotations

import argparse
import filecmp
import hashlib
import os
import re
import shutil
import sys
from pathlib import Path

CLI_ROOT = Path(os.environ.get("ZCODE_CLI_ROOT", Path.home() / ".zcode" / "cli"))
MEM_ROOT = CLI_ROOT / "memories" / "projects"
KEY_RE = re.compile(r"^[a-z0-9._-]+-[0-9a-f]{16}$")
DEFAULT_ROOTS = [Path.home() / "workspace"]
SKIP_NAMES = {".DS_Store"}


def slugify(name: str) -> str:
    t = name.lower()
    t = re.sub(r"[^a-z0-9._-]+", "-", t)
    t = re.sub(r"^-+|-+$", "", t)
    return t[:48] or "project"


def key_for(path: str) -> tuple[str, str]:
    """目录路径 → (记忆键, 规范化绝对路径)。对应 Node path.resolve：不解析软链。"""
    resolved = os.path.abspath(os.path.expanduser(str(path)))
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]
    base = os.path.basename(resolved.rstrip(os.sep)) or "project"
    return f"{slugify(base)}-{digest}", resolved


def mem_dir(key: str) -> Path:
    return MEM_ROOT / key / "memory"


def list_files(d: Path) -> list[Path]:
    if not d.is_dir():
        return []
    return [p for p in sorted(d.iterdir()) if p.is_file() and p.name not in SKIP_NAMES]


def resolve_arg(arg: str) -> tuple[str, Path]:
    """参数 → (键, 记忆目录)。接受：记忆键 / 工作区目录路径 / 记忆目录路径。"""
    s = str(Path(os.path.expanduser(arg)))
    marker = "/memories/projects/"
    if marker in s:
        key = s.split(marker, 1)[1].split("/", 1)[0]
        return key, mem_dir(key)
    if KEY_RE.match(arg) and not Path(os.path.expanduser(arg)).exists():
        return arg, mem_dir(arg)
    key, _ = key_for(arg)
    return key, mem_dir(key)


def scan_map(roots: list[Path], max_depth: int, follow: bool) -> dict[str, list[str]]:
    """扫候选根目录：{记忆键: [路径, ...]}。"""
    found: dict[str, list[str]] = {}
    for root in roots:
        root = Path(os.path.expanduser(str(root)))
        if not root.is_dir():
            continue
        base_parts = len(root.parts)
        for dirpath, dirnames, _ in os.walk(root, followlinks=follow):
            depth = len(Path(dirpath).parts) - base_parts
            if depth >= max_depth:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules"}]
            key, _ = key_for(dirpath)
            found.setdefault(key, []).append(dirpath)
    return found


def show_memory(key: str) -> None:
    d = mem_dir(key)
    print(f"记忆键:   {key}")
    print(f"记忆目录: {d}")
    files = list_files(d)
    if d.is_dir():
        print(f"状态:     存在，{len(files)} 个文件")
        for p in files:
            print(f"  - {p.name}")
    else:
        print("状态:     不存在（该目录从未作为工作区开过会话，或记忆已迁移走）")


def cmd_key(args: argparse.Namespace) -> int:
    key, resolved = key_for(args.path)
    print(f"路径:     {resolved}")
    show_memory(key)
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    target = args.target
    is_key = bool(KEY_RE.match(target)) and not Path(os.path.expanduser(target)).exists()
    if not is_key:
        key, resolved = key_for(target)
        print(f"路径:     {resolved}")
        show_memory(key)
        return 0
    show_memory(target)
    roots = [Path(r) for r in (args.roots or [])] or DEFAULT_ROOTS
    found = scan_map(roots, args.max_depth, args.follow_symlinks)
    paths = found.get(target, [])
    if paths:
        for p in paths:
            print(f"归属目录: {p}")
    else:
        print("归属目录: 未在扫描根内找到匹配路径。")
        print(" 可能原因：workspaceIdentity 键 / 目录已改名或删除 / 曾经经软链路径打开（resolve 不解析软链）。")
        print(" 可用 --roots <目录> 追加扫描根（如软链所在根），或读记忆内容人工判断。")
    return 0


def cmd_inventory(args: argparse.Namespace) -> int:
    if not MEM_ROOT.is_dir():
        print(f"记忆根目录不存在: {MEM_ROOT}", file=sys.stderr)
        return 1
    roots = [Path(r) for r in (args.roots or [])] or DEFAULT_ROOTS
    found = scan_map(roots, args.max_depth, args.follow_symlinks)
    keys = [p for p in sorted(MEM_ROOT.iterdir()) if p.is_dir()]
    if not keys:
        print("（没有任何记忆键）")
        return 0
    for keydir in keys:
        key = keydir.name
        files = list_files(keydir / "memory")
        print(f"{key}  （{len(files)} 个文件）")
        owners = found.get(key, [])
        if owners:
            for o in owners:
                print(f"  → {o}")
        else:
            print("  → （未匹配到路径：workspaceIdentity 键 / 目录已改名或删除 / 软链路径）")
    return 0


def files_equal(a: Path, b: Path) -> bool:
    return a.is_file() and b.is_file() and filecmp.cmp(a, b, shallow=False)


def merge_index(src_md: Path, dst_md: Path) -> str:
    src_lines = [l for l in src_md.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not dst_md.exists():
        shutil.copy2(src_md, dst_md)
        return f"目标无索引，直接采用源的 {len(src_lines)} 行"
    dst_lines = [l for l in dst_md.read_text(encoding="utf-8").splitlines() if l.strip()]
    seen = set(dst_lines)
    added = [l for l in src_lines if l not in seen]
    if added:
        dst_md.write_text("\n".join(dst_lines + added) + "\n", encoding="utf-8")
    return f"并入 {len(added)} 行（源 {len(src_lines)} 行，重复跳过 {len(src_lines) - len(added)} 行）"


def cmd_move(args: argparse.Namespace) -> int:
    src_key, src_dir = resolve_arg(args.src)
    dst_key, dst_dir = resolve_arg(args.dst)
    if src_key == dst_key:
        print(f"源与目标是同一个键 {src_key}，无需迁移。")
        return 0
    if not src_dir.is_dir():
        print(f"源记忆目录不存在: {src_dir}", file=sys.stderr)
        return 1
    src_files = list_files(src_dir)
    if not src_files:
        print(f"源记忆目录为空: {src_dir}（无文件可迁）")
        return 0

    dst_dir.mkdir(parents=True, exist_ok=True)
    index_src = src_dir / "MEMORY.md"
    to_copy, same, conflicts = [], [], []
    for p in src_files:
        if p.name == "MEMORY.md":
            continue  # 索引不参与冲突判定，单独按行合并去重
        q = dst_dir / p.name
        if not q.exists():
            to_copy.append(p)
        elif files_equal(p, q):
            same.append(p.name)
        else:
            conflicts.append(p.name)

    print(f"源:   {src_key}  →  {src_dir}")
    print(f"目标: {dst_key}  →  {dst_dir}")
    print(f"计划复制 {len(to_copy)} 个；内容一致跳过 {len(same)} 个；同名冲突 {len(conflicts)} 个")
    if index_src.is_file():
        print("MEMORY.md: 将并入目标索引（按行去重）")
    if conflicts:
        print("同名冲突（内容不同）:")
        for name in conflicts:
            print(f"  - {name}")
    if args.dry_run:
        print("（--dry-run：未执行任何写入）")
        return 0
    if conflicts and not args.skip_conflicts:
        print("已中止：请人工裁决冲突文件（保留哪份 / 改名并存 / 跳过），或加 --skip-conflicts 跳过它们。")
        print("源未做任何修改。")
        return 1

    copied: list[str] = []
    for p in to_copy:
        shutil.copy2(p, dst_dir / p.name)
        copied.append(p.name)
    failed = [n for n in copied if not files_equal(src_dir / n, dst_dir / n)]
    if failed:
        for n in failed:
            (dst_dir / n).unlink()
        print(f"校验失败：已回滚目标侧本次复制 {failed}；源未动。")
        return 1
    print(f"复制并校验通过: {len(copied)} 个文件")

    if (src_dir / "MEMORY.md").is_file():
        print("MEMORY.md: " + merge_index(src_dir / "MEMORY.md", dst_dir / "MEMORY.md"))

    if args.keep_source:
        print(f"--keep-source：源保留在 {src_dir}")
    else:
        keep = set(conflicts) if args.skip_conflicts else set()
        for p in src_files:
            if p.name in keep:
                continue
            p.unlink()
        left = [p.name for p in list_files(src_dir)]
        print(f"源已清理，剩余文件: {left or '无'}")
    print(f"完成：目标现在共 {len(list_files(dst_dir))} 个文件")
    return 0


def add_scan_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument("--roots", action="append", help="追加扫描根目录（可多次）")
    p.add_argument("--max-depth", type=int, default=5, help="扫描深度（默认 5）")
    p.add_argument("--follow-symlinks", action="store_true", help="让扫描进入软链目录")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ZCode 项目记忆定位与迁移")
    sub = parser.add_subparsers(dest="command", required=True)

    p_key = sub.add_parser("key", help="目录路径 → 记忆键与记忆目录")
    p_key.add_argument("path")
    p_key.set_defaults(func=cmd_key)

    p_find = sub.add_parser("find", help="记忆键或目录路径 → 归属（哈希核对）")
    p_find.add_argument("target")
    add_scan_opts(p_find)
    p_find.set_defaults(func=cmd_find)

    p_inv = sub.add_parser("inventory", help="盘点全部记忆键")
    add_scan_opts(p_inv)
    p_inv.set_defaults(func=cmd_inventory)

    p_mv = sub.add_parser("move", help="迁移/合并记忆并删源（默认）；--keep-source 只复制")
    p_mv.add_argument("src", help="源：记忆键 / 工作区目录 / 记忆目录")
    p_mv.add_argument("dst", help="目标：工作区目录 / 记忆目录")
    p_mv.add_argument("--keep-source", action="store_true", help="只复制，不删源")
    p_mv.add_argument("--dry-run", action="store_true", help="只输出计划，不写任何文件")
    p_mv.add_argument("--skip-conflicts", action="store_true", help="跳过同名冲突文件（留在源），不中止")
    p_mv.set_defaults(func=cmd_move)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
