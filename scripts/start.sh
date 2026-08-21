#!/usr/bin/env bash
set -euo pipefail

source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"
uv run uvicorn backend.main:app --host "${APP_HOST:-127.0.0.1}" --port "${APP_PORT:-8000}"
