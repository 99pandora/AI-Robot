#!/usr/bin/env bash
set -euo pipefail

source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"
uv run uvicorn backend.mock_api.main:app --host "${MOCK_API_HOST:-127.0.0.1}" --port "${MOCK_API_PORT:-8001}"
