#!/usr/bin/env bash
set -euo pipefail

# Git Bash 有时不会把 Windows 的 pnpm.cmd 加入 PATH；此函数兼容三种安装方式。
pnpm_exec() {
  if command -v pnpm >/dev/null 2>&1; then
    pnpm "$@"
    return
  fi
  if command -v pnpm.cmd >/dev/null 2>&1; then
    pnpm.cmd "$@"
    return
  fi
  # MSYS 会把 cmd.exe 的 /c 参数误转换成磁盘路径，必须关闭路径转换。
  if command -v cmd.exe >/dev/null 2>&1 \
    && MSYS_NO_PATHCONV=1 cmd.exe /d /s /c "where pnpm >nul 2>&1"; then
    MSYS_NO_PATHCONV=1 cmd.exe /d /s /c pnpm "$@"
    return
  fi
  echo "pnpm 未找到，请先安装 pnpm，或将 pnpm.cmd 所在目录加入 Git Bash PATH。" >&2
  return 127
}
