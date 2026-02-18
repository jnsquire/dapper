#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${WSL_DISTRO_NAME:-}" ]] && ! grep -qi microsoft /proc/version 2>/dev/null; then
  echo "This script must be run from WSL." >&2
  exit 1
fi

if ! command -v powershell.exe >/dev/null 2>&1; then
  echo "powershell.exe not found. Ensure WSL interop is enabled." >&2
  exit 1
fi

if ! command -v wslpath >/dev/null 2>&1; then
  echo "wslpath not found." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WIN_REPO_ROOT="$(wslpath -w "$REPO_ROOT")"
WIN_SCRIPT="$(wslpath -w "$SCRIPT_DIR/run-windows-tests-host.ps1")"

args_file=""
if [[ "$#" -gt 0 ]]; then
  args_file="$(mktemp)"
  trap '[[ -n "$args_file" ]] && rm -f "$args_file"' EXIT
  printf '%s\n' "$@" > "$args_file"
  WIN_ARGS_FILE="$(wslpath -w "$args_file")"
fi

ps_args=(
  -NoProfile
  -ExecutionPolicy Bypass
  -File "$WIN_SCRIPT"
  -RepoPath "$WIN_REPO_ROOT"
)
if [[ -n "$args_file" ]]; then
  ps_args+=( -PytestArgsFile "$WIN_ARGS_FILE" )
fi

powershell.exe "${ps_args[@]}"
exit $?
