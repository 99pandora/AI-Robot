#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$(cd -- "$SCRIPT_DIR/.." && pwd)"

# 使用项目内缓存，避免系统 uv 缓存权限或锁文件影响启动。
export UV_CACHE_DIR="${UV_CACHE_DIR:-$PWD/.uv-cache}"
uv run uvicorn backend.main:app --host "${APP_HOST:-127.0.0.1}" --port "${APP_PORT:-8000}"
