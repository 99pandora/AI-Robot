#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$(cd -- "$SCRIPT_DIR/.." && pwd)"

# 使用项目内缓存和临时目录，避免受机器全局权限影响。
export UV_CACHE_DIR="${UV_CACHE_DIR:-$PWD/.uv-cache}"
PYTEST_BASETEMP="$PWD/.tmp/pytest-$(date +%Y%m%d%H%M%S)-$$"
uv run pytest -p no:cacheprovider --basetemp "$PYTEST_BASETEMP"
