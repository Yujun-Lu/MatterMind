from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .config import JOB_META_FILENAME, LOG_FILENAME, VASP_RESULTS_BASE_DIR


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_base_dir() -> None:
    VASP_RESULTS_BASE_DIR.mkdir(parents=True, exist_ok=True)


def job_dir(job_id: str) -> Path:
    return VASP_RESULTS_BASE_DIR / job_id


def create_job_dir(job_id: str) -> Path:
    ensure_base_dir()
    path = job_dir(job_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path(job_id: str) -> Path:
    return job_dir(job_id) / LOG_FILENAME


def meta_path(job_id: str) -> Path:
    return job_dir(job_id) / JOB_META_FILENAME


def write_meta(job_id: str, data: Dict[str, Any]) -> None:
    path = meta_path(job_id)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_meta(job_id: str) -> Dict[str, Any]:
    path = meta_path(job_id)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def iter_job_ids() -> Iterable[str]:
    if not VASP_RESULTS_BASE_DIR.exists():
        return []
    return [p.name for p in VASP_RESULTS_BASE_DIR.iterdir() if p.is_dir()]


def list_jobs() -> List[str]:
    return list(iter_job_ids())
