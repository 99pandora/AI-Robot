#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_common.sh"
source "$SCRIPT_DIR/_pnpm.sh"

pnpm_exec --filter xiaosu-admin build
