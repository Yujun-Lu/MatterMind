#!/usr/bin/env bash
set -euo pipefail

MATTERGEN_VENV_PATH="${MATTERGEN_VENV_PATH:-/root/autodl-tmp/venvs/mattergen-310}"
VASP_VENV_PATH="${VASP_VENV_PATH:-/root/autodl-tmp/venvs/vasp-310}"
API_VENV_PATH="${API_VENV_PATH:-}"

if [ -z "$API_VENV_PATH" ]; then
  if [ -d "$VASP_VENV_PATH" ]; then
    API_VENV_PATH="$VASP_VENV_PATH"
  else
    API_VENV_PATH="$MATTERGEN_VENV_PATH"
  fi
fi

if [ ! -f "$API_VENV_PATH/bin/activate" ]; then
  echo "API virtualenv not found: $API_VENV_PATH" >&2
  exit 1
fi

source "$API_VENV_PATH/bin/activate"

ENV_FILE="${ENV_FILE:-/root/autodl-tmp/MM-v2-2/backend/.env.local}"
if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

export TMPDIR=/root/autodl-tmp/tmp
export PIP_CACHE_DIR=/root/autodl-tmp/pip-cache
export XDG_CACHE_HOME=/root/autodl-tmp/.cache
export HF_ENDPOINT="https://hf-mirror.com"

export MATTERGEN_REPO=/root/autodl-tmp/MatterGen/mattergen
export RESULTS_BASE_DIR=/root/autodl-tmp/mattergen-results
export REDIS_URL=redis://localhost:6379/0
export MATTERGEN_QUEUE="${MATTERGEN_QUEUE:-mattergen}"
export VASP_QUEUE="${VASP_QUEUE:-vasp}"

cd /root/autodl-tmp/MM-v2-2/backend

uvicorn app.main:app --host 0.0.0.0 --port 8000
