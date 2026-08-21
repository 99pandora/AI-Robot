#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$(cd -- "$SCRIPT_DIR/.." && pwd)"

# 该脚本是无凭据环境下可重复执行的 IM 适配器验收；真实消息验收见 README。
export UV_CACHE_DIR="${UV_CACHE_DIR:-$PWD/.uv-cache}"
PYTEST_BASETEMP="$PWD/.tmp/pytest-feishu-$(date +%Y%m%d%H%M%S)-$$"
uv run pytest -p no:cacheprovider --basetemp "$PYTEST_BASETEMP" backend/tests/test_feishu.py
