#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$(cd -- "$SCRIPT_DIR/.." && pwd)"

echo "前端将在后续步骤初始化；当前无需构建产物。"
