#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$(cd -- "$SCRIPT_DIR/.." && pwd)"

uv run uvicorn backend.main:app --host "${APP_HOST:-127.0.0.1}" --port "${APP_PORT:-8000}"
