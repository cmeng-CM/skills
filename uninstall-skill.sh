#!/usr/bin/env bash
set -euo pipefail

# skill 卸载脚本
# 用法: ./uninstall-skill.sh <skill 名称或路径>
# 作用: 从 Claude Code / Codex / OpenCode 以及跨工具标准路径 ~/.agents/skills 移除指定 skill
#       目标是软链接 → 仅移除链接（不影响源目录）
#       目标是实际文件/目录 → 直接删除

usage() {
  echo "用法: $0 <skill 名称或路径>"
  exit 1
}

# ---------- 参数处理 ----------
[ $# -eq 1 ] || usage

# 传路径也可以，统一取最后一段作为 skill 名
name=$(basename "$1")

# ---------- 各客户端的 skill 目录 ----------
targets=(
  "$HOME/.claude/skills"
  "$HOME/.agents/skills"
)

for dir in "${targets[@]}"; do
  link="$dir/$name"

  if [ -L "$link" ]; then
    # 软链接（含断链）: 只移除链接本身
    rm "$link"
    echo "✓ 已移除链接: $link"
  elif [ -e "$link" ]; then
    # 实际文件或目录: 直接删除
    rm -rf "$link"
    echo "✓ 已删除实际内容: $link"
  else
    echo "- 未安装，跳过: $link"
  fi
done

echo "完成: $name 已从 ${#targets[@]} 个客户端目录卸载"
