#!/usr/bin/env bash
# 用途：扫描/生成 CLAUDE.md 完成后，写入缓存标记，供下次 check_cache.sh 判断是否命中
# 用法：bash write_cache.sh [项目根目录，默认当前目录]

set -euo pipefail

PROJECT_DIR="${1:-.}"
cd "$PROJECT_DIR"

if ! git rev-parse --git-dir > /dev/null 2>&1; then
  echo "NOT_A_GIT_REPO — 跳过缓存写入（缓存机制依赖 git，非 git 项目无法使用）"
  exit 0
fi

GIT_COMMON_DIR=$(git rev-parse --git-common-dir)
CACHE_FILE="${GIT_COMMON_DIR}/claude-onboard.md"

CURRENT_SHA=$(git rev-parse HEAD)
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

cat > "$CACHE_FILE" <<EOF
# Claude Code 项目认知缓存标记
# 本文件由 codebase-onboarding skill 自动生成，用于判断项目认知是否需要刷新
# 不要手动编辑；如需强制刷新认知，删除本文件或直接要求 Claude 重新 onboard

sha: ${CURRENT_SHA}
branch: ${CURRENT_BRANCH}
generated_at: ${TIMESTAMP}
EOF

echo "缓存已写入：${CACHE_FILE}"
echo "  sha: ${CURRENT_SHA}"
echo "  branch: ${CURRENT_BRANCH}"
echo "  generated_at: ${TIMESTAMP}"
