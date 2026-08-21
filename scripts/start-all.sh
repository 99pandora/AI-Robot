#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_common.sh"
source "$SCRIPT_DIR/_pnpm.sh"

RUN_DIR="${XIAOSU_RUN_DIR:-$PROJECT_ROOT/.tmp/xiaosu}"
mkdir -p "$RUN_DIR"

PIDS=()
NAMES=()

stop_pid() {
  local pid="$1"
  if command -v taskkill.exe >/dev/null 2>&1; then
    # Git Bash 下 uv/pnpm 可能再派生 Windows 子进程，需要按进程树停止。
    MSYS_NO_PATHCONV=1 taskkill.exe /PID "$pid" /T /F >/dev/null 2>&1 || true
  else
    kill "$pid" 2>/dev/null || true
  fi
}

stop_services() {
  local exit_code=$?
  trap - EXIT INT TERM

  for pid in "${PIDS[@]}"; do
    stop_pid "$pid"
  done
  for pid in "${PIDS[@]}"; do
    wait "$pid" 2>/dev/null || true
  done

  echo "已停止小苏服务。日志目录：$RUN_DIR"
  exit "$exit_code"
}

trap stop_services EXIT INT TERM

start_uvicorn() {
  local name="$1"
  shift
  "$@" >"$RUN_DIR/$name.log" 2>&1 &
  PIDS+=("$!")
  NAMES+=("$name")
}

start_uvicorn mock uv run uvicorn backend.mock_api.main:app \
  --host "${MOCK_API_HOST:-127.0.0.1}" --port "${MOCK_API_PORT:-8001}"
start_uvicorn backend uv run uvicorn backend.main:app \
  --host "${APP_HOST:-127.0.0.1}" --port "${APP_PORT:-8000}"

pnpm_exec --filter xiaosu-admin dev \
  --host "${FRONTEND_HOST:-127.0.0.1}" --port "${FRONTEND_PORT:-5173}" \
  >"$RUN_DIR/frontend.log" 2>&1 &
PIDS+=("$!")
NAMES+=("frontend")

echo "小苏项目已启动："
echo "  管理后台: http://${FRONTEND_HOST:-127.0.0.1}:${FRONTEND_PORT:-5173}"
echo "  主服务:   http://${APP_HOST:-127.0.0.1}:${APP_PORT:-8000}"
echo "  Mock API: http://${MOCK_API_HOST:-127.0.0.1}:${MOCK_API_PORT:-8001}"
echo "按 Ctrl+C 停止全部服务；日志：$RUN_DIR"

while true; do
  for index in "${!PIDS[@]}"; do
    if ! kill -0 "${PIDS[$index]}" 2>/dev/null; then
      echo "${NAMES[$index]} 已退出，请检查 $RUN_DIR/${NAMES[$index]}.log" >&2
      exit 1
    fi
  done
  sleep 1
done
