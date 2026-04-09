#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION_NAME="${1:-mattergen}"

if command -v tmux >/dev/null 2>&1; then
  if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "tmux session already running: $SESSION_NAME"
    echo "Attach with: tmux attach -t $SESSION_NAME"
    exit 0
  fi

  tmux new-session -d -s "$SESSION_NAME" -n main -c "$BASE_DIR/backend" \
    "/bin/bash -lc '$BASE_DIR/backend/run_api.sh'"

  tmux split-window -h -t "$SESSION_NAME":0 -c "$BASE_DIR/backend" \
    "/bin/bash -lc '$BASE_DIR/backend/run_worker.sh'"

  tmux split-window -v -t "$SESSION_NAME":0.1 -c "$BASE_DIR/frontend" \
    "/bin/bash -lc 'npm run dev'"

  tmux select-layout -t "$SESSION_NAME":0 tiled
  tmux attach -t "$SESSION_NAME"
  exit 0
fi

LOG_DIR="$BASE_DIR/logs"
mkdir -p "$LOG_DIR"

echo "tmux not found. Starting in background with nohup logs in $LOG_DIR"
nohup /bin/bash -lc "$BASE_DIR/backend/run_api.sh" >"$LOG_DIR/api.log" 2>&1 &
echo $! >"$LOG_DIR/api.pid"

nohup /bin/bash -lc "$BASE_DIR/backend/run_worker.sh" >"$LOG_DIR/worker.log" 2>&1 &
echo $! >"$LOG_DIR/worker.pid"

nohup /bin/bash -lc "cd '$BASE_DIR/frontend' && npm run dev" >"$LOG_DIR/frontend.log" 2>&1 &
echo $! >"$LOG_DIR/frontend.pid"

echo "Started. PID files saved to $LOG_DIR"
