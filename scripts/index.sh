#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$(cd -- "$SCRIPT_DIR/.." && pwd)"

# 使用项目根目录作为种子文档和运行时 storage 的相对路径基准。
uv run python -c "from pathlib import Path; from backend.knowledge.seed import index_seed_documents; indexed = index_seed_documents(Path.cwd()); print('已索引种子文档：'); print(*indexed, sep='\\n') if indexed else print('没有新增文档。')"
