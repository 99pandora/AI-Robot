#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$(cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/_pnpm.sh"

# Vite 开发服务器通过 proxy 将 /api 请求转发到 FastAPI 主服务。
pnpm_exec --filter xiaosu-admin dev --host "${FRONTEND_HOST:-127.0.0.1}" --port "${FRONTEND_PORT:-5173}"
