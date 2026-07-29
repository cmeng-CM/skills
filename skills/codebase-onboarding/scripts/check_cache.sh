#!/usr/bin/env bash
# 用途：判断项目认知缓存是否仍然有效
# 用法：bash check_cache.sh [项目根目录，默认当前目录]
# 输出：
#   CACHE_VALID   — 缓存存在且 SHA 匹配当前 HEAD，可以跳过扫描
#   CACHE_STALE   — 缓存存在但 SHA 不匹配，代码已变化，需要重新扫描
#   CACHE_MISSING — 没有缓存文件，需要首次扫描
#   NOT_A_GIT_REPO — 当前目录不是 git 仓库，缓存机制不适用，直接走扫描

set -euo pipefail

PROJECT_DIR="${1:-.}"
cd "$PROJECT_DIR"

if ! git rev-parse --git-dir > /dev/null 2>&1; then
  echo "NOT_A_GIT_REPO"
  exit 0
fi

GIT_COMMON_DIR=$(git rev-parse --git-common-dir)
CACHE_FILE="${GIT_COMMON_DIR}/claude-onboard.md"

if [ ! -f "$CACHE_FILE" ]; then
  echo "CACHE_MISSING"
  exit 0
fi

CURRENT_SHA=$(git rev-parse HEAD)
CACHED_SHA=$(grep -m1 '^sha:' "$CACHE_FILE" | awk '{print $2}' || echo "")

if [ "$CURRENT_SHA" = "$CACHED_SHA" ]; then
  echo "CACHE_VALID"
else
  echo "CACHE_STALE"
fi
