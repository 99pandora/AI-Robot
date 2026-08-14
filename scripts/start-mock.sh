#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$(cd -- "$SCRIPT_DIR/.." && pwd)"

uv run uvicorn backend.mock_api.main:app --host "${MOCK_API_HOST:-127.0.0.1}" --port "${MOCK_API_PORT:-8001}"
