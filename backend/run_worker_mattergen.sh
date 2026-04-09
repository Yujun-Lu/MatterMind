#!/usr/bin/env bash
set -euo pipefail

MATTERGEN_VENV_PATH="${MATTERGEN_VENV_PATH:-/root/autodl-tmp/venvs/mattergen-310}"
if [ ! -f "$MATTERGEN_VENV_PATH/bin/activate" ]; then
  echo "MatterGen virtualenv not found: $MATTERGEN_VENV_PATH" >&2
  exit 1
fi
source "$MATTERGEN_VENV_PATH/bin/activate"

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

celery -A app.celery_app.celery_app worker -l info -c 1 --prefetch-multiplier=1 -Q "$MATTERGEN_QUEUE" -n mattergen@%h
