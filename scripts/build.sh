#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$(cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/_pnpm.sh"

pnpm_exec --filter xiaosu-admin build
