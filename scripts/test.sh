#!/usr/bin/env bash
set -euo pipefail

source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"

TEST_TARGET="${1:-all}"
PYTEST_BASETEMP="$PROJECT_ROOT/.tmp/pytest-${TEST_TARGET}-$(date +%Y%m%d%H%M%S)-$$"

case "$TEST_TARGET" in
  all)
    TEST_PATHS=()
    ;;
  feishu)
    TEST_PATHS=(backend/tests/test_feishu.py)
    ;;
  *)
    echo "用法：bash ./scripts/test.sh [all|feishu]" >&2
    exit 2
    ;;
esac

uv run pytest -p no:cacheprovider --basetemp "$PYTEST_BASETEMP" "${TEST_PATHS[@]}"
