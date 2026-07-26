#!/usr/bin/env bash
set -euo pipefail

# skill 快速安装脚本
# 用法: ./install-skill.sh <skill 目录路径>
# 作用: 将指定 skill 以软链接方式安装到 Claude Code / Codex / OpenCode 三个客户端

usage() {
  echo "用法: $0 <skill 目录路径>"
  exit 1
}

# ---------- 参数校验 ----------
[ $# -eq 1 ] || usage

src="$1"

if [ ! -d "$src" ]; then
  echo "✗ 错误: 路径不存在或不是目录: $src"
  exit 1
fi

if [ ! -f "$src/SKILL.md" ]; then
  echo "✗ 错误: 目录中未找到 SKILL.md，不是有效的 skill: $src"
  exit 1
fi

# 转为绝对路径（软链接目标必须是绝对路径，否则会成为断链）
src_dir=$(cd "$src" && pwd)
name=$(basename "$src_dir")

# ---------- 三个客户端的 skill 目录 ----------
targets=(
  "$HOME/.claude/skills"
  "$HOME/.codex/skills"
  "$HOME/.config/opencode/skills"
)

for dir in "${targets[@]}"; do
  mkdir -p "$dir"
  link="$dir/$name"

  # 覆盖策略: 已存在（旧链接/真实目录/文件/断链）先删除再建链接
  # 不用 ln -sfn：目标是真实目录时链接会被错误地创建到目录里面
  if [ -e "$link" ] || [ -L "$link" ]; then
    rm -rf "$link"
    ln -s "$src_dir" "$link"
    echo "✓ 已覆盖: $link -> $src_dir"
  else
    ln -s "$src_dir" "$link"
    echo "✓ 新装: $link -> $src_dir"
  fi
done

echo "完成: $name 已安装到 ${#targets[@]} 个客户端"
