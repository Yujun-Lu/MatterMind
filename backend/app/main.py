from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import uuid
from pathlib import Path
from urllib.parse import unquote
from typing import Any, Dict, List, Optional

from celery.result import AsyncResult
from fastapi import Body, FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from .ai_analysis import (
    CHAT_SYSTEM_PROMPT,
    HDF5_VASP_CHAT_SYSTEM_PROMPT,
    POSTW90_SHARED_CHAT_SYSTEM_PROMPT,
    VTST_CHAT_SYSTEM_PROMPT,
    WANNIER_CHAT_SYSTEM_PROMPT,
    run_ai_analysis,
    stream_hdf5_vasp_analysis,
    stream_ai_analysis,
    stream_chat_response,
    stream_postw90_analysis,
    stream_vtst_analysis,
    stream_wannier_analysis,
)
from .chat_store import ensure_chat, public_messages, save_chat
from .celery_app import celery_app
from .config import (
    ALLOWED_ARTIFACTS,
    ANALYSIS_FILENAME,
    DASHSCOPE_MODEL,
    HDF5_METRICS_FILENAME,
    MATTERGEN_QUEUE,
    METRICS_FILENAME,
    POSTW90_METRICS_FILENAME,
    VASP_QUEUE,
    VTST_METRICS_FILENAME,
    WANNIER_METRICS_FILENAME,
    VASP_EXECUTABLE,
    VASP_ALLOWED_EXECUTABLES,
    VASP_MAX_NPROC,
    VASP_OPTIONAL_INPUTS,
    VASP_OUTPUT_FILES,
    VASP_REQUIRED_INPUTS,
    VASP_RUN_MODES,
    VASP_STANDARD_OPTIONAL_INPUTS,
    VASP_STANDARD_OUTPUT_FILES,
    VASP_STANDARD_REQUIRED_INPUTS,
    VASP_VTST_DEFAULT_MODE,
    VASP_VTST_MODES,
    VASP_WANNIER_POST_OPTIONAL_INPUTS,
    VASP_WANNIER_POST_OUTPUT_FILES,
    VASP_WANNIER_POST_REQUIRED_INPUTS,
    VASP_WANNIER_POSTW90_OPTIONAL_INPUTS,
    VASP_WANNIER_POSTW90_OUTPUT_FILES,
    VASP_WANNIER_POSTW90_REQUIRED_INPUTS,
    VASP_WANNIER_SCF_OPTIONAL_INPUTS,
    VASP_WANNIER_SCF_OUTPUT_FILES,
    VASP_WANNIER_SCF_REQUIRED_INPUTS,
    VASP_VTST_OPTIONAL_INPUTS,
    VASP_VTST_OUTPUT_FILES,
    VASP_VTST_PRE_RELAXED_REQUIRED_INPUTS,
    VASP_VTST_RELAX_FIRST_REQUIRED_INPUTS,
    WANNIER_PLOT_FORMAT,
)
from .models import (
    AnalysisRequest,
    ChatHistoryResponse,
    ChatMessageRequest,
    JobStatusResponse,
    JobSubmitRequest,
    JobSubmitResponse,
    Postw90SubmitRequest,
)
from .storage import create_job_dir, job_dir, list_jobs, log_path, now_iso, read_meta, write_meta
from .vasp_storage import (
    create_job_dir as create_vasp_job_dir,
    job_dir as vasp_job_dir,
    list_jobs as list_vasp_jobs,
    log_path as vasp_log_path,
    read_meta as read_vasp_meta,
    write_meta as write_vasp_meta,
)

app = FastAPI(title="MatterGen Runner", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TERMINAL_TASK_STATES = frozenset({"SUCCESS", "FAILURE", "REVOKED"})
SUCCESSFUL_METRICS_STATES = frozenset({"ok", "degraded", "unsupported"})


def _normalize_task_state(value: Any) -> str:
    state = str(value or "").strip().upper()
    return state or "PENDING"


def _coerce_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pid_is_alive(value: Any) -> bool:
    pid = _coerce_int(value)
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _has_persisted_outputs(meta: Dict[str, Any], results_dir: Path) -> bool:
    metrics_path = meta.get("metrics_path")
    if metrics_path:
        candidate = Path(metrics_path)
        if candidate.exists():
            return True

    analysis_path = meta.get("analysis_path")
    if analysis_path:
        candidate = Path(analysis_path)
        if candidate.exists():
            return True

    for rel_path in meta.get("available_output_files") or []:
        try:
            if (results_dir / rel_path).exists():
                return True
        except Exception:
            continue
    return False


def infer_state_from_meta(meta: Dict[str, Any], results_dir: Path) -> Optional[str]:
    explicit_state = _normalize_task_state(meta.get("job_status"))
    if explicit_state in TERMINAL_TASK_STATES:
        return explicit_state

    if meta.get("stop_status") == "stopped" or meta.get("stopped_at"):
        return "REVOKED"

    finished_at = meta.get("finished_at")
    return_code = _coerce_int(meta.get("return_code"))
    metrics_status = str(meta.get("metrics_status") or "").strip().lower()
    if finished_at:
        if return_code == 0:
            return "SUCCESS"
        if return_code is not None:
            return "FAILURE"
        if metrics_status == "stopped":
            return "REVOKED"
        if metrics_status == "failed":
            return "FAILURE"
        if metrics_status in SUCCESSFUL_METRICS_STATES:
            return "SUCCESS"
        if _has_persisted_outputs(meta, results_dir):
            return "SUCCESS"

    if _pid_is_alive(meta.get("active_process_pid")):
        return "STARTED"

    return None


def resolve_task_state(job_id: str, meta: Dict[str, Any], results_dir: Path) -> str:
    try:
        celery_state = _normalize_task_state(AsyncResult(job_id, app=celery_app).state)
    except Exception:
        celery_state = "PENDING"
    if celery_state != "PENDING":
        return celery_state
    return infer_state_from_meta(meta, results_dir) or celery_state


def get_vasp_file_sets(
    run_mode: str, vtst_mode: str = VASP_VTST_DEFAULT_MODE
) -> Dict[str, tuple[str, ...]]:
    if run_mode == "vtst_neb":
        required_inputs = (
            VASP_VTST_RELAX_FIRST_REQUIRED_INPUTS
            if vtst_mode == "relax_first"
            else VASP_VTST_PRE_RELAXED_REQUIRED_INPUTS
        )
        return {
            "required": required_inputs,
            "optional": VASP_VTST_OPTIONAL_INPUTS,
            "outputs": VASP_VTST_OUTPUT_FILES,
        }
    if run_mode == "wannier":
        return {
            "required": VASP_WANNIER_POST_REQUIRED_INPUTS,
            "optional": VASP_WANNIER_POST_OPTIONAL_INPUTS,
            "outputs": VASP_WANNIER_POST_OUTPUT_FILES,
        }
    if run_mode == "wannier_scf":
        return {
            "required": VASP_WANNIER_SCF_REQUIRED_INPUTS,
            "optional": VASP_WANNIER_SCF_OPTIONAL_INPUTS,
            "outputs": VASP_WANNIER_SCF_OUTPUT_FILES,
        }
    if run_mode == "wannier_post":
        return {
            "required": VASP_WANNIER_POST_REQUIRED_INPUTS,
            "optional": VASP_WANNIER_POST_OPTIONAL_INPUTS,
            "outputs": VASP_WANNIER_POST_OUTPUT_FILES,
        }
    if run_mode == "wannier_postw90":
        return {
            "required": VASP_WANNIER_POSTW90_REQUIRED_INPUTS,
            "optional": VASP_WANNIER_POSTW90_OPTIONAL_INPUTS,
            "outputs": VASP_WANNIER_POSTW90_OUTPUT_FILES,
        }
    return {
        "required": VASP_STANDARD_REQUIRED_INPUTS,
        "optional": VASP_STANDARD_OPTIONAL_INPUTS,
        "outputs": VASP_STANDARD_OUTPUT_FILES,
    }


def build_wannier_visualization_options(
    run_mode: str,
    *,
    enable_lwrite_unk: bool,
    enable_wannier_plot: bool,
) -> Optional[Dict[str, Any]]:
    if run_mode not in {"wannier", "wannier_post"}:
        return None
    return {
        "enable_lwrite_unk": bool(enable_lwrite_unk),
        "enable_wannier_plot": bool(enable_wannier_plot),
        "wannier_plot_format": WANNIER_PLOT_FORMAT if enable_wannier_plot else None,
    }


def get_vasp_metrics_path(meta: Dict[str, Any], job_id: str) -> Path:
    metrics_path = meta.get("metrics_path")
    if metrics_path:
        candidate = Path(metrics_path)
        if candidate.exists():
            return candidate

    run_mode = meta.get("run_mode")
    job_path = vasp_job_dir(job_id)
    if run_mode == "vtst_neb":
        return job_path / VTST_METRICS_FILENAME
    if run_mode == "wannier_postw90":
        return job_path / POSTW90_METRICS_FILENAME
    if run_mode in {"wannier", "wannier_post"}:
        return job_path / WANNIER_METRICS_FILENAME

    hdf5_path = job_path / HDF5_METRICS_FILENAME
    if hdf5_path.exists():
        return hdf5_path

    legacy_path = job_path / METRICS_FILENAME
    if legacy_path.exists():
        return legacy_path

    return hdf5_path


def get_vasp_analysis_profile(meta: Dict[str, Any]) -> Dict[str, Any]:
    run_mode = meta.get("run_mode")
    if run_mode == "vtst_neb":
        return {
            "supported": True,
            "stream_fn": stream_vtst_analysis,
            "chat_system_prompt": VTST_CHAT_SYSTEM_PROMPT,
            "metrics_label": VTST_METRICS_FILENAME,
            "analysis_label": "VTST analysis",
            "chat_label": "VTST chat",
        }
    if run_mode in {"wannier", "wannier_post"}:
        return {
            "supported": True,
            "stream_fn": stream_wannier_analysis,
            "chat_system_prompt": WANNIER_CHAT_SYSTEM_PROMPT,
            "metrics_label": WANNIER_METRICS_FILENAME,
            "analysis_label": "Wannier analysis",
            "chat_label": "Wannier chat",
        }
    if run_mode == "wannier_postw90":
        module = str(meta.get("postw90_module") or "").strip() or "postw90"
        module_label = str(meta.get("postw90_module_label") or module).replace("_", " ")
        return {
            "supported": True,
            "stream_fn": stream_postw90_analysis,
            "chat_system_prompt": POSTW90_SHARED_CHAT_SYSTEM_PROMPT,
            "metrics_label": POSTW90_METRICS_FILENAME,
            "analysis_label": f"{module_label} analysis",
            "chat_label": f"{module_label} chat",
        }
    if run_mode == "wannier_scf":
        return {
            "supported": False,
            "metrics_label": "unsupported",
            "analysis_label": "unsupported",
            "chat_label": "unsupported",
        }
    return {
        "supported": True,
        "stream_fn": stream_hdf5_vasp_analysis,
        "chat_system_prompt": HDF5_VASP_CHAT_SYSTEM_PROMPT,
        "metrics_label": HDF5_METRICS_FILENAME,
        "analysis_label": "HDF5 analysis",
        "chat_label": "HDF5 chat",
    }


def request_vasp_stop(job_id: str) -> Dict[str, Any]:
    meta = read_vasp_meta(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail="job not found")

    state = resolve_task_state(job_id, meta, vasp_job_dir(job_id))
    if state in TERMINAL_TASK_STATES:
        return {
            "job_id": job_id,
            "status": state.lower(),
            "stop_requested": bool(meta.get("stop_requested")),
            "signal_sent": False,
        }

    meta["stop_requested"] = True
    meta["stop_requested_at"] = now_iso()
    write_vasp_meta(job_id, meta)

    try:
        celery_app.control.revoke(job_id, terminate=False)
    except Exception:
        pass

    signal_sent = False
    pgid = meta.get("active_process_pgid")
    pid = meta.get("active_process_pid")
    try:
        if pgid and hasattr(os, "killpg"):
            os.killpg(int(pgid), signal.SIGTERM)
            signal_sent = True
        elif pid:
            os.kill(int(pid), signal.SIGTERM)
            signal_sent = True
    except ProcessLookupError:
        signal_sent = False
    except Exception:
        signal_sent = False

    log_file = vasp_log_path(job_id)
    with log_file.open("a", encoding="utf-8") as f:
        f.write("\n== stop request ==\n")
        f.write("stop requested by user\n")
        if meta.get("active_process_section"):
            f.write(f"active section: {meta['active_process_section']}\n")
        if meta.get("active_process_command"):
            f.write(f"active command: {meta['active_process_command']}\n")
        f.write(f"signal sent: {'yes' if signal_sent else 'no'}\n")

    return {
        "job_id": job_id,
        "status": "stopping",
        "stop_requested": True,
        "signal_sent": signal_sent,
    }


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/jobs", response_model=JobSubmitResponse)
def submit_job(payload: JobSubmitRequest) -> JobSubmitResponse:
    job_id = uuid.uuid4().hex
    job_path = create_job_dir(job_id)

    meta = {
        "job_id": job_id,
        "job_status": "PENDING",
        "created_at": now_iso(),
        "model_name": payload.model_name,
        "batch_size": payload.batch_size,
        "num_batches": payload.num_batches,
        "properties_to_condition_on": payload.properties_to_condition_on,
        "diffusion_guidance_factor": payload.diffusion_guidance_factor,
    }
    write_meta(job_id, meta)

    celery_app.send_task(
        "app.tasks.run_mattergen",
        args=[{"job_id": job_id, **payload.model_dump()}],
        task_id=job_id,
        queue=MATTERGEN_QUEUE,
    )

    return JobSubmitResponse(job_id=job_id, status="queued", results_dir=str(job_path))


@app.post("/api/vasp/jobs/{job_id}/postw90", response_model=JobSubmitResponse)
def submit_postw90_job(job_id: str, payload: Postw90SubmitRequest) -> JobSubmitResponse:
    source_meta = read_vasp_meta(job_id)
    if not source_meta:
        raise HTTPException(status_code=404, detail="source job not found")
    source_state = resolve_task_state(job_id, source_meta, vasp_job_dir(job_id))
    if source_state != "SUCCESS":
        raise HTTPException(status_code=400, detail="source Wannier job is not finished successfully")
    if source_meta.get("run_mode") not in {"wannier", "wannier_post"}:
        raise HTTPException(status_code=400, detail="source job must be a successful Wannier post run")

    requested_nproc = payload.nproc or int(source_meta.get("nproc") or VASP_MAX_NPROC)
    if requested_nproc < 1 or requested_nproc > VASP_MAX_NPROC:
        raise HTTPException(
            status_code=400,
            detail=f"nproc must be between 1 and {VASP_MAX_NPROC}",
        )

    child_job_id = uuid.uuid4().hex
    child_job_path = create_vasp_job_dir(child_job_id)
    meta = {
        "job_id": child_job_id,
        "job_status": "PENDING",
        "created_at": now_iso(),
        "job_name": payload.job_name.strip(),
        "run_mode": "wannier_postw90",
        "nproc": requested_nproc,
        "endpoint_nproc": requested_nproc,
        "vasp_exec": source_meta.get("vasp_exec", VASP_EXECUTABLE),
        "files": [],
        "required_files": list(VASP_WANNIER_POSTW90_REQUIRED_INPUTS),
        "optional_files": list(VASP_WANNIER_POSTW90_OPTIONAL_INPUTS),
        "output_files": list(VASP_WANNIER_POSTW90_OUTPUT_FILES),
        "source_job_id": job_id,
        "postw90_module": payload.module,
        "postw90_params": payload.params or {},
    }
    write_vasp_meta(child_job_id, meta)

    celery_app.send_task(
        "app.tasks.run_vasp",
        args=[
            {
                "job_id": child_job_id,
                "run_mode": "wannier_postw90",
                "nproc": requested_nproc,
                "endpoint_nproc": requested_nproc,
                "vasp_exec": source_meta.get("vasp_exec", VASP_EXECUTABLE),
            }
        ],
        task_id=child_job_id,
        queue=VASP_QUEUE,
    )

    return JobSubmitResponse(
        job_id=child_job_id,
        status="queued",
        results_dir=str(child_job_path),
    )


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str) -> JobStatusResponse:
    meta = read_meta(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail="job not found")
    state = resolve_task_state(job_id, meta, job_dir(job_id))
    return JobStatusResponse(
        job_id=job_id,
        status=state,
        results_dir=str(job_dir(job_id)),
        created_at=meta.get("created_at", ""),
        meta=meta,
    )


@app.get("/api/jobs", response_model=List[JobStatusResponse])
def get_jobs() -> List[JobStatusResponse]:
    jobs: List[JobStatusResponse] = []
    for jid in list_jobs():
        meta = read_meta(jid)
        state = resolve_task_state(jid, meta, job_dir(jid))
        jobs.append(
            JobStatusResponse(
                job_id=jid,
                status=state,
                results_dir=str(job_dir(jid)),
                created_at=meta.get("created_at", ""),
                meta=meta,
            )
        )
    return jobs


@app.post("/api/vasp/jobs", response_model=JobSubmitResponse)
async def submit_vasp_job(
    files: List[UploadFile] = File(...),
    job_name: str = Form(""),
    nproc: int = Form(VASP_MAX_NPROC),
    vasp_exec: str = Form(VASP_EXECUTABLE),
    run_mode: str = Form("standard"),
    vtst_mode: str = Form(VASP_VTST_DEFAULT_MODE),
    endpoint_nproc: int = Form(VASP_MAX_NPROC),
    source_job_id: str = Form(""),
    wannier_enable_lwrite_unk: bool = Form(False),
    wannier_enable_plot: bool = Form(False),
) -> JobSubmitResponse:
    if run_mode not in VASP_RUN_MODES:
        raise HTTPException(status_code=400, detail="invalid vasp run mode")
    vtst_mode = vtst_mode.strip() or VASP_VTST_DEFAULT_MODE
    if run_mode == "vtst_neb" and vtst_mode not in VASP_VTST_MODES:
        raise HTTPException(status_code=400, detail="invalid vtst mode")
    if vasp_exec not in VASP_ALLOWED_EXECUTABLES:
        raise HTTPException(status_code=400, detail="invalid vasp executable")
    if nproc < 1 or nproc > VASP_MAX_NPROC:
        raise HTTPException(
            status_code=400,
            detail=f"nproc must be between 1 and {VASP_MAX_NPROC}",
        )
    if endpoint_nproc < 1 or endpoint_nproc > VASP_MAX_NPROC:
        raise HTTPException(
            status_code=400,
            detail=f"endpoint_nproc must be between 1 and {VASP_MAX_NPROC}",
        )
    job_id = uuid.uuid4().hex
    job_path = create_vasp_job_dir(job_id)
    file_sets = get_vasp_file_sets(run_mode, vtst_mode)
    allowed = set(file_sets["required"]) | set(file_sets["optional"])

    saved_files: List[str] = []
    for upload in files:
        if not upload.filename:
            continue
        name = Path(upload.filename).name
        if name not in allowed:
            raise HTTPException(status_code=400, detail=f"invalid file: {name}")
        dest = job_path / name
        with dest.open("wb") as f:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        saved_files.append(name)

    missing = [name for name in file_sets["required"] if not (job_path / name).exists()]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"missing required files: {', '.join(missing)}",
        )

    source_job_id = source_job_id.strip()
    if run_mode == "wannier_post":
        if not source_job_id:
            raise HTTPException(status_code=400, detail="source_job_id is required")
        source_meta = read_vasp_meta(source_job_id)
        if not source_meta:
            raise HTTPException(status_code=400, detail="source SCF job not found")
        source_state = resolve_task_state(
            source_job_id, source_meta, vasp_job_dir(source_job_id)
        )
        if source_state != "SUCCESS":
            raise HTTPException(status_code=400, detail="source SCF job is not finished successfully")
        if source_meta.get("run_mode") not in {"wannier_scf", "wannier"}:
            raise HTTPException(status_code=400, detail="source job must be a Wannier SCF run")
        source_dir = vasp_job_dir(source_job_id)
        required_source_files = ["POSCAR", "POTCAR", "KPOINTS", "WAVECAR"]
        missing_source_files = [
            name for name in required_source_files if not (source_dir / name).exists()
        ]
        if missing_source_files:
            raise HTTPException(
                status_code=400,
                detail=(
                    "source SCF job is missing required carry-over files: "
                    + ", ".join(missing_source_files)
                ),
            )

    wannier_visualization_options = build_wannier_visualization_options(
        run_mode,
        enable_lwrite_unk=wannier_enable_lwrite_unk,
        enable_wannier_plot=wannier_enable_plot,
    )

    meta = {
        "job_id": job_id,
        "job_status": "PENDING",
        "created_at": now_iso(),
        "job_name": job_name.strip(),
        "run_mode": run_mode,
        "vtst_mode": vtst_mode if run_mode == "vtst_neb" else None,
        "nproc": nproc,
        "endpoint_nproc": endpoint_nproc,
        "vasp_exec": vasp_exec,
        "files": saved_files,
        "required_files": list(file_sets["required"]),
        "optional_files": list(file_sets["optional"]),
        "output_files": list(file_sets["outputs"]),
        "source_job_id": source_job_id or None,
        "wannier_visualization_options": wannier_visualization_options,
    }
    write_vasp_meta(job_id, meta)

    celery_app.send_task(
        "app.tasks.run_vasp",
        args=[
            {
                "job_id": job_id,
                "run_mode": run_mode,
                "vtst_mode": vtst_mode,
                "nproc": nproc,
                "endpoint_nproc": endpoint_nproc,
                "vasp_exec": vasp_exec,
                "wannier_visualization_options": wannier_visualization_options,
            }
        ],
        task_id=job_id,
        queue=VASP_QUEUE,
    )

    return JobSubmitResponse(job_id=job_id, status="queued", results_dir=str(job_path))


@app.get("/api/vasp/jobs/{job_id}", response_model=JobStatusResponse)
def get_vasp_job(job_id: str) -> JobStatusResponse:
    meta = read_vasp_meta(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail="job not found")
    state = resolve_task_state(job_id, meta, vasp_job_dir(job_id))
    return JobStatusResponse(
        job_id=job_id,
        status=state,
        results_dir=str(vasp_job_dir(job_id)),
        created_at=meta.get("created_at", ""),
        meta=meta,
    )


@app.post("/api/vasp/jobs/{job_id}/stop")
def stop_vasp_job(job_id: str) -> Dict[str, Any]:
    return request_vasp_stop(job_id)


@app.get("/api/vasp/jobs", response_model=List[JobStatusResponse])
def get_vasp_jobs() -> List[JobStatusResponse]:
    jobs: List[JobStatusResponse] = []
    for jid in list_vasp_jobs():
        meta = read_vasp_meta(jid)
        state = resolve_task_state(jid, meta, vasp_job_dir(jid))
        jobs.append(
            JobStatusResponse(
                job_id=jid,
                status=state,
                results_dir=str(vasp_job_dir(jid)),
                created_at=meta.get("created_at", ""),
                meta=meta,
            )
        )
    return jobs


@app.get("/api/vasp/jobs/{job_id}/logs")
async def stream_vasp_logs(job_id: str) -> StreamingResponse:
    if not read_vasp_meta(job_id):
        raise HTTPException(status_code=404, detail="job not found")

    async def event_generator():
        path = vasp_log_path(job_id)
        last_pos = 0
        idle_ticks = 0
        while True:
            meta = read_vasp_meta(job_id)
            if path.exists():
                with path.open("r", encoding="utf-8") as f:
                    f.seek(last_pos)
                    for line in f:
                        yield f"data: {line.rstrip()}\n\n"
                    last_pos = f.tell()
            else:
                yield ": waiting for logs\n\n"

            state = resolve_task_state(job_id, meta, vasp_job_dir(job_id))
            if state in TERMINAL_TASK_STATES:
                idle_ticks += 1
            else:
                idle_ticks = 0

            if idle_ticks >= 3:
                break

            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/vasp/jobs/{job_id}/metrics")
def get_vasp_metrics(job_id: str) -> Dict[str, Any]:
    meta = read_vasp_meta(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail="job not found")
    if meta.get("run_mode") == "wannier_scf":
        raise HTTPException(status_code=400, detail="metrics are not supported for wannier scf mode")
    path = get_vasp_metrics_path(meta, job_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="metrics not found")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to read metrics file: {exc}")


@app.get("/api/vasp/jobs/{job_id}/analysis")
def get_vasp_analysis(job_id: str) -> Dict[str, str]:
    meta = read_vasp_meta(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail="job not found")
    profile = get_vasp_analysis_profile(meta)
    if not profile.get("supported", False):
        raise HTTPException(status_code=400, detail="analysis is not supported for this vasp mode")
    path = vasp_job_dir(job_id) / ANALYSIS_FILENAME
    if not path.exists():
        raise HTTPException(status_code=404, detail="analysis not found")
    content = path.read_text(encoding="utf-8")
    return {
        "job_id": job_id,
        "analysis": content,
        "analysis_path": str(path),
        "analysis_model": meta.get("analysis_model"),
    }


@app.post("/api/vasp/jobs/{job_id}/analysis/stream")
def run_vasp_analysis_stream(
    job_id: str, payload: Optional[AnalysisRequest] = Body(None)
) -> StreamingResponse:
    meta = read_vasp_meta(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail="job not found")
    profile = get_vasp_analysis_profile(meta)
    if not profile.get("supported", False):
        raise HTTPException(status_code=400, detail="analysis is not supported for this vasp mode")
    metrics_path = get_vasp_metrics_path(meta, job_id)
    if not metrics_path.exists():
        raise HTTPException(status_code=404, detail=f"{profile['metrics_label']} not found")
    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to read metrics file: {exc}")

    analysis_path = vasp_job_dir(job_id) / ANALYSIS_FILENAME
    model_name = payload.model if payload and payload.model else DASHSCOPE_MODEL

    def generator():
        chunks: List[str] = []
        error: Optional[str] = None
        try:
            for delta in profile["stream_fn"](metrics, model=model_name):
                chunks.append(delta)
                yield delta
        except Exception as exc:
            error = str(exc)
            yield f"\n[ERROR] {error}\n"
        finally:
            analysis_text = "".join(chunks).strip()
            if analysis_text:
                analysis_path.write_text(analysis_text, encoding="utf-8")
            meta_update = read_vasp_meta(job_id)
            if error:
                meta_update["analysis_status"] = "failed"
                meta_update["analysis_error"] = error
            else:
                meta_update["analysis_status"] = "ok"
                meta_update["analysis_model"] = model_name
                meta_update["analysis_path"] = str(analysis_path)
                meta_update["analysis_at"] = now_iso()
            write_vasp_meta(job_id, meta_update)

    return StreamingResponse(generator(), media_type="text/plain")


@app.get("/api/vasp/jobs/{job_id}/chat", response_model=ChatHistoryResponse)
def get_vasp_chat(job_id: str) -> ChatHistoryResponse:
    meta = read_vasp_meta(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail="job not found")
    profile = get_vasp_analysis_profile(meta)
    if not profile.get("supported", False):
        raise HTTPException(status_code=400, detail="chat is not supported for this vasp mode")
    analysis_path = vasp_job_dir(job_id) / ANALYSIS_FILENAME
    if not analysis_path.exists():
        raise HTTPException(status_code=404, detail="analysis not found")
    analysis_text = analysis_path.read_text(encoding="utf-8")
    data = ensure_chat(
        job_id,
        vasp_job_dir(job_id),
        profile["chat_system_prompt"],
        analysis_text,
        meta.get("analysis_model"),
    )
    return ChatHistoryResponse(job_id=job_id, messages=public_messages(data))


@app.post("/api/vasp/jobs/{job_id}/chat/stream")
def vasp_chat_stream(job_id: str, payload: ChatMessageRequest) -> StreamingResponse:
    meta = read_vasp_meta(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail="job not found")
    profile = get_vasp_analysis_profile(meta)
    if not profile.get("supported", False):
        raise HTTPException(status_code=400, detail="chat is not supported for this vasp mode")
    analysis_path = vasp_job_dir(job_id) / ANALYSIS_FILENAME
    if not analysis_path.exists():
        raise HTTPException(status_code=404, detail="analysis not found")

    analysis_text = analysis_path.read_text(encoding="utf-8")
    chat_data = ensure_chat(
        job_id,
        vasp_job_dir(job_id),
        profile["chat_system_prompt"],
        analysis_text,
        meta.get("analysis_model"),
    )
    messages = chat_data.get("messages", [])

    user_message = payload.message.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="message is empty")

    messages.append({"role": "user", "content": user_message})
    model_name = payload.model or DASHSCOPE_MODEL

    def generator():
        chunks: List[str] = []
        error: Optional[str] = None
        try:
            for delta in stream_chat_response(messages, model=model_name):
                chunks.append(delta)
                yield delta
        except Exception as exc:
            error = str(exc)
            yield f"\n[ERROR] {error}\n"
        finally:
            assistant_text = "".join(chunks).strip()
            if assistant_text:
                messages.append({"role": "assistant", "content": assistant_text})
            chat_data["messages"] = messages
            save_chat(vasp_job_dir(job_id), chat_data)
            meta_update = read_vasp_meta(job_id)
            if error:
                meta_update["chat_status"] = "failed"
                meta_update["chat_error"] = error
            else:
                meta_update["chat_status"] = "ok"
                meta_update["chat_model"] = model_name
            meta_update["chat_at"] = now_iso()
            write_vasp_meta(job_id, meta_update)

    return StreamingResponse(generator(), media_type="text/plain")


@app.get("/api/vasp/jobs/{job_id}/artifacts/{filename:path}")
def download_vasp_artifact(job_id: str, filename: str) -> FileResponse:
    meta = read_vasp_meta(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail="job not found")
    allowed_outputs = set(meta.get("available_output_files") or meta.get("output_files") or VASP_OUTPUT_FILES)
    safe_name = unquote(filename).strip()
    if safe_name not in allowed_outputs:
        raise HTTPException(status_code=400, detail="invalid artifact name")
    root = vasp_job_dir(job_id).resolve()
    path = (root / Path(safe_name)).resolve()
    if not str(path).startswith(str(root)):
        raise HTTPException(status_code=400, detail="invalid artifact name")
    if not path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path, filename=path.name)


@app.get("/api/jobs/{job_id}/logs")
async def stream_logs(job_id: str) -> StreamingResponse:
    if not read_meta(job_id):
        raise HTTPException(status_code=404, detail="job not found")

    async def event_generator():
        path = log_path(job_id)
        last_pos = 0
        idle_ticks = 0
        while True:
            meta = read_meta(job_id)
            if path.exists():
                with path.open("r", encoding="utf-8") as f:
                    f.seek(last_pos)
                    for line in f:
                        yield f"data: {line.rstrip()}\n\n"
                    last_pos = f.tell()
            else:
                yield ": waiting for logs\n\n"

            state = resolve_task_state(job_id, meta, job_dir(job_id))
            if state in TERMINAL_TASK_STATES:
                idle_ticks += 1
            else:
                idle_ticks = 0

            if idle_ticks >= 3:
                break

            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/jobs/{job_id}/artifacts/{filename}")
def download_artifact(job_id: str, filename: str) -> FileResponse:
    if filename not in ALLOWED_ARTIFACTS:
        raise HTTPException(status_code=400, detail="invalid artifact name")
    path = job_dir(job_id) / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path, filename=filename)


@app.get("/api/jobs/{job_id}/analysis")
def get_analysis(job_id: str) -> Dict[str, str]:
    if not read_meta(job_id):
        raise HTTPException(status_code=404, detail="job not found")
    path = job_dir(job_id) / ANALYSIS_FILENAME
    if not path.exists():
        raise HTTPException(status_code=404, detail="analysis not found")
    content = path.read_text(encoding="utf-8")
    meta = read_meta(job_id)
    return {
        "job_id": job_id,
        "analysis": content,
        "analysis_path": str(path),
        "analysis_model": meta.get("analysis_model"),
    }


@app.get("/api/jobs/{job_id}/metrics")
def get_metrics(job_id: str) -> Dict[str, Any]:
    if not read_meta(job_id):
        raise HTTPException(status_code=404, detail="job not found")
    path = job_dir(job_id) / METRICS_FILENAME
    if not path.exists():
        raise HTTPException(status_code=404, detail="metrics not found")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to read metrics.json: {exc}")


@app.post("/api/jobs/{job_id}/analysis")
def run_analysis(job_id: str, payload: Optional[AnalysisRequest] = Body(None)) -> Dict[str, str]:
    meta = read_meta(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail="job not found")
    metrics_path = job_dir(job_id) / METRICS_FILENAME
    if not metrics_path.exists():
        raise HTTPException(status_code=404, detail="metrics.json not found")
    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to read metrics.json: {exc}")

    model_name = payload.model if payload and payload.model else DASHSCOPE_MODEL
    try:
        analysis = run_ai_analysis(metrics, meta, model=model_name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    analysis_path = job_dir(job_id) / ANALYSIS_FILENAME
    analysis_path.write_text(analysis, encoding="utf-8")

    meta["analysis_status"] = "ok"
    meta["analysis_model"] = model_name
    meta["analysis_path"] = str(analysis_path)
    meta["analysis_at"] = now_iso()
    write_meta(job_id, meta)

    return {"job_id": job_id, "analysis": analysis, "analysis_path": str(analysis_path)}


@app.post("/api/jobs/{job_id}/analysis/stream")
def run_analysis_stream(
    job_id: str, payload: Optional[AnalysisRequest] = Body(None)
) -> StreamingResponse:
    meta = read_meta(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail="job not found")
    metrics_path = job_dir(job_id) / METRICS_FILENAME
    if not metrics_path.exists():
        raise HTTPException(status_code=404, detail="metrics.json not found")
    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to read metrics.json: {exc}")

    analysis_path = job_dir(job_id) / ANALYSIS_FILENAME
    model_name = payload.model if payload and payload.model else DASHSCOPE_MODEL

    def generator():
        chunks: List[str] = []
        error: Optional[str] = None
        try:
            for delta in stream_ai_analysis(metrics, meta, model=model_name):
                chunks.append(delta)
                yield delta
        except Exception as exc:
            error = str(exc)
            yield f"\n[ERROR] {error}\n"
        finally:
            analysis_text = "".join(chunks).strip()
            if analysis_text:
                analysis_path.write_text(analysis_text, encoding="utf-8")
            meta_update = read_meta(job_id)
            if error:
                meta_update["analysis_status"] = "failed"
                meta_update["analysis_error"] = error
            else:
                meta_update["analysis_status"] = "ok"
                meta_update["analysis_model"] = model_name
                meta_update["analysis_path"] = str(analysis_path)
                meta_update["analysis_at"] = now_iso()
            write_meta(job_id, meta_update)

    return StreamingResponse(generator(), media_type="text/plain")


@app.get("/api/jobs/{job_id}/files/{filename}")
def download_job_file(job_id: str, filename: str) -> FileResponse:
    if not read_meta(job_id):
        raise HTTPException(status_code=404, detail="job not found")
    safe_name = unquote(filename).strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="invalid file name")
    pattern = re.compile(
        r"^(metrics\.json|analysis\.txt|magpie\.csv|gen_\d+\.(cif|png|npy))$",
        re.IGNORECASE,
    )
    root = job_dir(job_id).resolve()
    candidate = Path(safe_name)
    if candidate.is_absolute():
        path = candidate.resolve()
    else:
        path = (root / candidate).resolve()
    if not str(path).startswith(str(root)):
        raise HTTPException(status_code=400, detail="invalid file name")
    base_name = path.name
    if not pattern.match(base_name):
        raise HTTPException(status_code=400, detail="invalid file name")
    if not path.exists():
        lowered = base_name.lower()
        if lowered != base_name:
            path = (root / lowered).resolve()
        if not path.exists():
            for child in root.iterdir():
                if child.name.lower() == base_name.lower():
                    path = child
                    break
    if not path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path, filename=path.name)


@app.get("/api/jobs/{job_id}/chat", response_model=ChatHistoryResponse)
def get_chat(job_id: str) -> ChatHistoryResponse:
    meta = read_meta(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail="job not found")
    analysis_path = job_dir(job_id) / ANALYSIS_FILENAME
    if not analysis_path.exists():
        raise HTTPException(status_code=404, detail="analysis not found")
    analysis_text = analysis_path.read_text(encoding="utf-8")
    data = ensure_chat(
        job_id,
        job_dir(job_id),
        CHAT_SYSTEM_PROMPT,
        analysis_text,
        meta.get("analysis_model"),
    )
    return ChatHistoryResponse(job_id=job_id, messages=public_messages(data))


@app.post("/api/jobs/{job_id}/chat/stream")
def chat_stream(job_id: str, payload: ChatMessageRequest) -> StreamingResponse:
    meta = read_meta(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail="job not found")
    analysis_path = job_dir(job_id) / ANALYSIS_FILENAME
    if not analysis_path.exists():
        raise HTTPException(status_code=404, detail="analysis not found")

    analysis_text = analysis_path.read_text(encoding="utf-8")
    chat_data = ensure_chat(
        job_id,
        job_dir(job_id),
        CHAT_SYSTEM_PROMPT,
        analysis_text,
        meta.get("analysis_model"),
    )
    messages = chat_data.get("messages", [])

    user_message = payload.message.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="message is empty")

    messages.append({"role": "user", "content": user_message})
    model_name = payload.model or DASHSCOPE_MODEL

    def generator():
        chunks: List[str] = []
        error: Optional[str] = None
        try:
            for delta in stream_chat_response(messages, model=model_name):
                chunks.append(delta)
                yield delta
        except Exception as exc:
            error = str(exc)
            yield f"\n[ERROR] {error}\n"
        finally:
            assistant_text = "".join(chunks).strip()
            if assistant_text:
                messages.append({"role": "assistant", "content": assistant_text})
            chat_data["messages"] = messages
            save_chat(job_dir(job_id), chat_data)
            meta_update = read_meta(job_id)
            if error:
                meta_update["chat_status"] = "failed"
                meta_update["chat_error"] = error
            else:
                meta_update["chat_status"] = "ok"
                meta_update["chat_model"] = model_name
            meta_update["chat_at"] = now_iso()
            write_meta(job_id, meta_update)

    return StreamingResponse(generator(), media_type="text/plain")
