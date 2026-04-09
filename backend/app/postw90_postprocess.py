from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .config import POSTW90_METRICS_FILENAME
from .storage import now_iso
from .vasp_storage import read_meta as read_vasp_meta


MODULE_LABELS = {
    "band_interp": "Band interpolation",
    "dos": "Density of states",
    "berry_ahc": "Berry / AHC",
    "fermi_surface": "Fermi surface",
    "boltzwann": "Boltzmann transport",
}

SEEDNAME_RE = re.compile(r"^\s*seedname\s*[:=]\s*(\S+)", re.IGNORECASE | re.MULTILINE)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _safe_float(value: str | float | int | None) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _relative(job_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(job_dir.resolve()).as_posix()
    except Exception:
        return path.name


def _parse_seedname(job_dir: Path) -> str:
    text = _read_text(job_dir / "wannier90.win")
    match = SEEDNAME_RE.search(text)
    return match.group(1).strip() if match else "wannier90"


def _read_numeric_table(path: Path) -> List[List[float]]:
    rows: List[List[float]] = []
    for raw_line in _read_text(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "!", "%")):
            continue
        parts = line.replace(",", " ").split()
        values: List[float] = []
        for part in parts:
            parsed = _safe_float(part)
            if parsed is None:
                values = []
                break
            values.append(parsed)
        if values:
            rows.append(values)
    return rows


def _plot_series(
    x: Sequence[float],
    series: Sequence[Tuple[str, Sequence[float]]],
    target: Path,
    *,
    title: str,
    x_label: str,
    y_label: str,
) -> Optional[str]:
    if not x or not series:
        return None
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return None

    try:
        fig, ax = plt.subplots(figsize=(7, 4), dpi=150)
        palette = ["#7bdff2", "#ff8f4a", "#90be6d", "#f28482", "#c77dff", "#ffd166"]
        for index, (label, y) in enumerate(series):
            if not y:
                continue
            ax.plot(x, y, color=palette[index % len(palette)], linewidth=1.35, label=label)
        ax.set_title(title)
        ax.set_xlabel(x_label)
        ax.set_ylabel(y_label)
        ax.grid(alpha=0.18)
        if len(series) > 1:
            ax.legend()
        fig.tight_layout()
        target.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(target, bbox_inches="tight")
        plt.close(fig)
        return str(target)
    except Exception:
        return None


def _plot_band_file(path: Path, target: Path) -> Tuple[Optional[str], Dict[str, Any]]:
    rows = _read_numeric_table(path)
    if not rows or len(rows[0]) < 2:
        return None, {}
    energy_columns = min(len(rows[0]) - 1, 32)
    x = list(range(len(rows)))
    series = []
    for column in range(1, energy_columns + 1):
        series.append((f"Band {column}", [row[column] for row in rows if len(row) > column]))
    energies = [value for row in rows for value in row[1 : energy_columns + 1]]
    plot = _plot_series(
        x,
        series,
        target,
        title="Wannier band interpolation",
        x_label="Path index",
        y_label="Energy (eV)",
    )
    return plot, {
        "output_file": str(path),
        "n_kpoints": len(rows),
        "n_bands": energy_columns,
        "energy_min": min(energies) if energies else None,
        "energy_max": max(energies) if energies else None,
    }


def _plot_dos_file(path: Path, target: Path, title: str) -> Tuple[Optional[str], Dict[str, Any]]:
    rows = _read_numeric_table(path)
    if not rows or len(rows[0]) < 2:
        return None, {}
    x = [row[0] for row in rows]
    y = [row[1] for row in rows]
    plot = _plot_series(
        x,
        [("DOS", y)],
        target,
        title=title,
        x_label="Energy (eV)",
        y_label="DOS",
    )
    return plot, {
        "output_file": str(path),
        "n_points": len(rows),
        "energy_min": min(x) if x else None,
        "energy_max": max(x) if x else None,
        "max_dos": max(y) if y else None,
    }


def _plot_ahc_file(path: Path, target: Path) -> Tuple[Optional[str], Dict[str, Any]]:
    rows = _read_numeric_table(path)
    if not rows or len(rows[0]) < 2:
        return None, {}
    component_count = min(max(len(rows[0]) - 1, 1), 3)
    x = [row[0] for row in rows]
    labels = ["AHC_x", "AHC_y", "AHC_z"]
    series = [
        (labels[index], [row[index + 1] for row in rows if len(row) > index + 1])
        for index in range(component_count)
    ]
    plot = _plot_series(
        x,
        series,
        target,
        title="AHC vs chemical potential",
        x_label="Chemical potential / energy (eV)",
        y_label="AHC",
    )
    flattened = [value for _, y in series for value in y]
    return plot, {
        "output_file": str(path),
        "n_points": len(rows),
        "components": component_count,
        "x_min": min(x) if x else None,
        "x_max": max(x) if x else None,
        "max_abs_ahc": max((abs(value) for value in flattened), default=None),
    }


def _select_transport_axes(rows: List[List[float]]) -> Tuple[int, int, Optional[int]]:
    if not rows or len(rows[0]) < 3:
        return 0, 1, None
    first_unique = len({round(row[0], 8) for row in rows})
    second_unique = len({round(row[1], 8) for row in rows if len(row) > 1})
    if first_unique <= max(6, len(rows) // 8) and second_unique > first_unique:
        fixed_value = sorted({round(row[0], 8) for row in rows}, key=lambda value: abs(value - 300.0))[0]
        return 1, 2, fixed_value
    if second_unique <= max(6, len(rows) // 8) and first_unique > second_unique:
        fixed_value = sorted({round(row[1], 8) for row in rows}, key=lambda value: abs(value - 300.0))[0]
        return 0, 2, fixed_value
    return 0, 1, None


def _plot_transport_file(path: Path, target: Path, title: str) -> Tuple[Optional[str], Dict[str, Any]]:
    rows = _read_numeric_table(path)
    if not rows or len(rows[0]) < 2:
        return None, {}
    x_col, y_start, fixed_value = _select_transport_axes(rows)
    filtered_rows = rows
    fixed_axis_label = None
    if fixed_value is not None:
        fixed_col = 1 - x_col
        filtered_rows = [row for row in rows if len(row) > fixed_col and round(row[fixed_col], 8) == fixed_value]
        fixed_axis_label = "temperature" if fixed_col == 0 else "chemical_potential"
    if not filtered_rows:
        filtered_rows = rows
        fixed_value = None
        fixed_axis_label = None

    component_count = min(max(len(filtered_rows[0]) - y_start, 1), 3)
    x = [row[x_col] for row in filtered_rows]
    labels = ["xx", "yy", "zz"]
    series = [
        (labels[index], [row[y_start + index] for row in filtered_rows if len(row) > y_start + index])
        for index in range(component_count)
    ]
    plot = _plot_series(
        x,
        series,
        target,
        title=title,
        x_label="mu (eV)" if x_col == 0 else "Temperature (K)",
        y_label="Value",
    )
    return plot, {
        "output_file": str(path),
        "n_points": len(filtered_rows),
        "component_count": component_count,
        "fixed_axis": fixed_axis_label,
        "fixed_value": fixed_value,
        "x_min": min(x) if x else None,
        "x_max": max(x) if x else None,
    }


def _build_source_step(job_meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    source_job_id = job_meta.get("source_job_id")
    if not source_job_id:
        return None
    source_meta = read_vasp_meta(source_job_id)
    return {
        "job_id": source_job_id,
        "job_name": source_meta.get("job_name"),
        "run_mode": source_meta.get("run_mode"),
        "created_at": source_meta.get("created_at"),
        "seedname": source_meta.get("seedname"),
    }


def _write_metrics(job_dir: Path, metrics: Dict[str, Any]) -> None:
    (job_dir / POSTW90_METRICS_FILENAME).write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def postprocess_postw90(job_id: str, job_dir: Path, job_meta: Dict[str, Any]) -> Dict[str, Any]:
    module = (job_meta.get("postw90_module") or "").strip()
    seedname = job_meta.get("seedname") or _parse_seedname(job_dir)
    baseline_files = set(job_meta.get("postw90_baseline_files") or [])
    current_files = sorted(
        path.relative_to(job_dir).as_posix()
        for path in job_dir.rglob("*")
        if path.is_file()
    )
    new_files = [name for name in current_files if name not in baseline_files]
    log_path = job_dir / "postw90.out"
    warnings: List[str] = []
    log_text = _read_text(log_path)
    for raw_line in log_text.splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if not line:
            continue
        if any(marker in lowered for marker in ("warning", "error", "failed", "problem")):
            warnings.append(line)
    warnings = list(dict.fromkeys(warnings))

    metrics: Dict[str, Any] = {
        "version": "0.1",
        "status": "ok",
        "meta": {
            "task_id": job_id,
            "workdir": str(job_dir),
            "parser": "postw90",
            "generated_at": now_iso(),
        },
        "module": module,
        "module_label": MODULE_LABELS.get(module, module or "unknown"),
        "seedname": seedname,
        "source_step": _build_source_step(job_meta),
        "module_params": dict(job_meta.get("postw90_params") or {}),
        "generated_files": new_files,
        "warnings": warnings,
        "artifacts": {
            "files": {},
            "plots": {},
            "raw_files": [],
        },
        "summaries": {},
    }

    artifact_files: Dict[str, str] = {}
    for name in (
        "postw90.out",
        "wannier90.win",
        "wannier90.chk",
        "wannier90_hr.dat",
        "wannier90_r.dat",
        "wannier90_tb.dat",
        "wannier90.bxsf",
        "wannier90.wpout",
    ):
        path = job_dir / name
        if path.exists():
            artifact_files[name] = str(path)
    for name in new_files:
        artifact_files[name] = str(job_dir / name)
    metrics["artifacts"]["files"] = artifact_files
    metrics["artifacts"]["raw_files"] = list(artifact_files.values())

    plot_dir = job_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)

    def rel(path_str: Optional[str]) -> Optional[str]:
        if not path_str:
            return None
        return _relative(job_dir, Path(path_str))

    if module == "band_interp":
        candidates = sorted(
            path for path in job_dir.glob("*.dat") if "band" in path.name.lower() or "geninterp" in path.name.lower()
        )
        if candidates:
            plot, summary = _plot_band_file(candidates[0], plot_dir / "postw90_band.png")
            metrics["summaries"]["band_interp"] = summary
            if plot:
                metrics["artifacts"]["plots"]["band"] = plot
                artifact_files[rel(plot)] = plot
        else:
            warnings.append("No band interpolation data file was found after postw90.")

    elif module == "dos":
        candidates = sorted(
            path
            for path in job_dir.glob("*.dat")
            if "dos" in path.name.lower() and "boltz" not in path.name.lower()
        )
        if candidates:
            plot, summary = _plot_dos_file(candidates[0], plot_dir / "postw90_dos.png", "Wannier DOS")
            metrics["summaries"]["dos"] = summary
            if plot:
                metrics["artifacts"]["plots"]["dos"] = plot
                artifact_files[rel(plot)] = plot
        else:
            warnings.append("No DOS data file was found after postw90.")

    elif module == "berry_ahc":
        candidates = sorted(
            path for path in job_dir.glob("*.dat") if "ahc" in path.name.lower() or "berry" in path.name.lower()
        )
        if candidates:
            plot, summary = _plot_ahc_file(candidates[0], plot_dir / "postw90_ahc.png")
            metrics["summaries"]["berry_ahc"] = summary
            if plot:
                metrics["artifacts"]["plots"]["ahc"] = plot
                artifact_files[rel(plot)] = plot
        else:
            warnings.append("No AHC or Berry output data file was found after postw90.")

    elif module == "fermi_surface":
        candidates = sorted(path for path in job_dir.glob("*.bxsf")) + sorted(
            path for path in job_dir.glob("*.xsf") if "fermi" in path.name.lower()
        )
        if candidates:
            metrics["summaries"]["fermi_surface"] = {
                "output_file": str(candidates[0]),
                "format": candidates[0].suffix.lstrip("."),
            }
            artifact_files[rel(str(candidates[0]))] = str(candidates[0])
        else:
            warnings.append("No Fermi-surface export (BXSF/XSF) was found after the wannier90 plot run.")

    elif module == "boltzwann":
        file_patterns = {
            "seebeck": ("*seebeck*.dat", "plots/postw90_seebeck.png", "Seebeck coefficient"),
            "elcond": ("*elcond*.dat", "plots/postw90_elcond.png", "Electrical conductivity"),
            "boltzdos": ("*boltzdos*.dat", "plots/postw90_boltzdos.png", "Boltzmann DOS"),
        }
        transport_summary: Dict[str, Any] = {}
        for key, (pattern, plot_name, title) in file_patterns.items():
            candidates = sorted(job_dir.glob(pattern))
            if not candidates:
                continue
            if key == "boltzdos":
                plot, summary = _plot_dos_file(candidates[0], job_dir / plot_name, title)
            else:
                plot, summary = _plot_transport_file(candidates[0], job_dir / plot_name, title)
            transport_summary[key] = summary
            if plot:
                metrics["artifacts"]["plots"][key] = plot
                artifact_files[rel(plot)] = plot
        if transport_summary:
            metrics["summaries"]["boltzwann"] = transport_summary
        else:
            warnings.append("No BoltzWann transport data file was found after postw90.")

    metrics["warnings"] = list(dict.fromkeys(warnings))
    if metrics["warnings"]:
        metrics["status"] = "degraded"

    download_files = sorted(
        {
            *artifact_files.keys(),
            POSTW90_METRICS_FILENAME,
        }
    )
    metrics["download_files"] = [name for name in download_files if (job_dir / name).exists()]

    _write_metrics(job_dir, metrics)
    return metrics
