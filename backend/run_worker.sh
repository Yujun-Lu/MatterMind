#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-both}"

case "$MODE" in
  mattergen)
    exec "$SCRIPT_DIR/run_worker_mattergen.sh"
    ;;
  vasp)
    exec "$SCRIPT_DIR/run_worker_vasp.sh"
    ;;
  both)
    trap 'kill 0 2>/dev/null || true' INT TERM EXIT
    "$SCRIPT_DIR/run_worker_mattergen.sh" &
    MATTERGEN_PID=$!
    "$SCRIPT_DIR/run_worker_vasp.sh" &
    VASP_PID=$!
    wait -n "$MATTERGEN_PID" "$VASP_PID"
    STATUS=$?
    kill "$MATTERGEN_PID" "$VASP_PID" 2>/dev/null || true
    wait "$MATTERGEN_PID" "$VASP_PID" 2>/dev/null || true
    exit "$STATUS"
    ;;
  *)
    echo "Usage: $0 [mattergen|vasp|both]" >&2
    exit 1
    ;;
esac
