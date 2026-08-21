#!/usr/bin/env bash
set -euo pipefail

COMMON_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$COMMON_SCRIPT_DIR/.." && pwd)"
cd -- "$PROJECT_ROOT"

# 将 uv 缓存放在项目内，避免不同机器的全局缓存权限和锁文件影响脚本。
export UV_CACHE_DIR="${UV_CACHE_DIR:-$PROJECT_ROOT/.uv-cache}"
