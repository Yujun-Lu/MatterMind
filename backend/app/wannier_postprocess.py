from __future__ import annotations

import json
import math
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .config import (
    WANNIER_DETAILS_FILENAME,
    WANNIER_MAX_ORBITAL_PLOTS,
    WANNIER_METRICS_FILENAME,
    WANNIER_PLOT_FORMAT,
)
from .storage import now_iso
from .vasp_storage import read_meta as read_vasp_meta


WANNIER_REQUIRED_FILES = (
    "wannier90.wout",
    "wannier90.win",
    "wannier90.chk",
    "wannier90.amn",
    "wannier90.mmn",
    "wannier90.eig",
)

CENTER_SPREAD_RE = re.compile(
    r"WF centre and spread\s+(\d+)\s+\(\s*([^)]+?)\s*\)\s+([-+0-9.Ee]+)"
)
NUM_WANN_RE = re.compile(r"^\s*num_wann\s*=\s*(\d+)", re.IGNORECASE | re.MULTILINE)
SEEDNAME_RE = re.compile(r"^\s*seedname\s*[:=]\s*(\S+)", re.IGNORECASE | re.MULTILINE)
SECONDS_VALUE_RE = re.compile(
    r"([-+]?\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds)\b", re.IGNORECASE
)
GENERIC_FLOAT_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?")

OMEGA_PATTERNS = {
    "omega_I": re.compile(r"Omega\s+I\s*=\s*([-+0-9.Ee]+)", re.IGNORECASE),
    "omega_D": re.compile(r"Omega\s+D\s*=\s*([-+0-9.Ee]+)", re.IGNORECASE),
    "omega_OD": re.compile(r"Omega\s+OD\s*=\s*([-+0-9.Ee]+)", re.IGNORECASE),
    "omega_total": re.compile(r"Omega\s+(?:Total|Tot)\s*=\s*([-+0-9.Ee]+)", re.IGNORECASE),
}

CONVERGED_PATTERNS = (
    "final state",
    "convergence achieved",
    "converged after",
    "wannierisation converged",
)
NON_CONVERGED_PATTERNS = (
    "maximum number of iterations reached",
    "did not converge",
    "convergence not achieved",
    "failed to converge",
)
WARNING_MARKERS = ("warning", "warn", "error", "problem", "failed")

MAX_JSON_HAMILTONIAN_TERMS = 120000
TOP_HOPPING_LIMIT = 40
GRAPH_EDGE_LIMIT = 180
DISTANCE_BIN_WIDTH = 0.25
TRUNCATION_RADII = (2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0)
WANNIER_FUNCTION_PREVIEW_LIMIT = 8
WANNIER_OFFSET_PREVIEW_LIMIT = 8


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _parse_incar_bool(path: Path, key: str) -> Optional[bool]:
    if not path.exists():
        return None
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=?\s*(\S+)", re.IGNORECASE)
    true_tokens = {".TRUE.", "TRUE", "T", ".T.", "YES", "Y", "1"}
    false_tokens = {".FALSE.", "FALSE", "F", ".F.", "NO", "N", "0"}
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.split("#", 1)[0].split("!", 1)[0].strip()
        if not line:
            continue
        match = pattern.match(line)
        if not match:
            continue
        token = match.group(1).rstrip(";").strip().upper()
        if token in true_tokens:
            return True
        if token in false_tokens:
            return False
        return None
    return None


def _detect_spinor_incar_flags(job_dir: Path) -> List[str]:
    incar_path = job_dir / "INCAR"
    enabled_flags: List[str] = []
    for key in ("LSORBIT", "LNONCOLLINEAR"):
        if _parse_incar_bool(incar_path, key) is True:
            enabled_flags.append(key)
    return enabled_flags


def _read_visualization_options(job_meta: Dict[str, Any]) -> Dict[str, Any]:
    options = dict(job_meta.get("wannier_visualization_options") or {})
    return {
        "enable_lwrite_unk": bool(options.get("enable_lwrite_unk")),
        "enable_wannier_plot": bool(options.get("enable_wannier_plot")),
        "wannier_plot_format": options.get("wannier_plot_format") or WANNIER_PLOT_FORMAT,
    }


def _safe_float(value: str | float | int | None) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _format_float(value: float) -> str:
    return f"{value:.8f}"


def _vector_norm(vector: Sequence[float]) -> float:
    return math.sqrt(sum(component * component for component in vector))


def _vector_sub(left: Sequence[float], right: Sequence[float]) -> List[float]:
    return [float(l - r) for l, r in zip(left, right)]


def _translation_cart(
    lattice: Optional[List[List[float]]], translation: Sequence[int]
) -> List[float]:
    if lattice is None:
        return [0.0, 0.0, 0.0]
    cart = [0.0, 0.0, 0.0]
    for coefficient, basis in zip(translation, lattice):
        for axis in range(3):
            cart[axis] += float(coefficient) * float(basis[axis])
    return cart


def _parse_vector(raw: str) -> Optional[List[float]]:
    cleaned = raw.replace(",", " ")
    parts = [part for part in cleaned.split() if part]
    if len(parts) < 3:
        return None
    values: List[float] = []
    for part in parts[:3]:
        value = _safe_float(part)
        if value is None:
            return None
        values.append(value)
    return values


def _parse_num_wann(win_text: str, wout_text: str) -> Optional[int]:
    for text in (win_text, wout_text):
        match = NUM_WANN_RE.search(text)
        if match:
            return int(match.group(1))
    return None


def _parse_seedname(win_text: str, wout_text: str) -> str:
    for text in (win_text, wout_text):
        match = SEEDNAME_RE.search(text)
        if match:
            return match.group(1).strip()
    return "wannier90"


def _parse_final_state(wout_text: str) -> Dict[str, Any]:
    centers: List[List[float]] = []
    spreads: List[float] = []
    functions: List[Dict[str, Any]] = []
    for match in CENTER_SPREAD_RE.finditer(wout_text):
        index = int(match.group(1))
        center = _parse_vector(match.group(2))
        spread = _safe_float(match.group(3))
        if center is None or spread is None:
            continue
        centers.append(center)
        spreads.append(spread)
        functions.append(
            {
                "index": index,
                "center_cartesian": center,
                "spread": spread,
            }
        )
    return {
        "final_centers": centers,
        "final_spreads": spreads,
        "wannier_functions": functions,
    }


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _stddev(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    avg = _mean(values)
    if avg is None:
        return None
    return math.sqrt(sum((value - avg) ** 2 for value in values) / len(values))


def _median(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _preview_wannier_functions(
    functions: Sequence[Dict[str, Any]], limit: int = WANNIER_FUNCTION_PREVIEW_LIMIT
) -> List[Dict[str, Any]]:
    return [dict(item) for item in list(functions)[:limit]]


def _summarize_centers(centers: Sequence[Sequence[float]]) -> Dict[str, Any]:
    if not centers:
        return {
            "count": 0,
            "centroid_cartesian": None,
            "bounds_cartesian": None,
            "max_radius_A": None,
        }

    centroid = [
        sum(center[axis] for center in centers) / len(centers)
        for axis in range(3)
    ]
    minima = [min(center[axis] for center in centers) for axis in range(3)]
    maxima = [max(center[axis] for center in centers) for axis in range(3)]
    radii = [_vector_norm(center) for center in centers]
    return {
        "count": len(centers),
        "centroid_cartesian": centroid,
        "bounds_cartesian": {
            "min": minima,
            "max": maxima,
            "extent": [maxima[axis] - minima[axis] for axis in range(3)],
        },
        "max_radius_A": max(radii) if radii else None,
    }


def _summarize_spreads(
    functions: Sequence[Dict[str, Any]], spreads: Sequence[float]
) -> Dict[str, Any]:
    if not spreads:
        return {
            "count": 0,
            "average": None,
            "median": None,
            "stddev": None,
            "min": None,
            "max": None,
            "counts": {},
            "top_delocalized": [],
        }

    top_delocalized = sorted(
        (dict(item) for item in functions),
        key=lambda item: item.get("spread") or 0.0,
        reverse=True,
    )[:WANNIER_FUNCTION_PREVIEW_LIMIT]

    return {
        "count": len(spreads),
        "average": _mean(spreads),
        "median": _median(spreads),
        "stddev": _stddev(spreads),
        "min": min(spreads),
        "max": max(spreads),
        "counts": {
            "spread_le_1_5": sum(1 for value in spreads if value <= 1.5),
            "spread_gt_1_5": sum(1 for value in spreads if value > 1.5),
            "spread_gt_2_0": sum(1 for value in spreads if value > 2.0),
            "spread_gt_3_0": sum(1 for value in spreads if value > 3.0),
        },
        "top_delocalized": top_delocalized,
    }


def _summarize_center_offsets(offsets: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not offsets:
        return None

    per_orbital = list(offsets.get("per_orbital") or [])
    nearest_atom_distribution: Dict[str, int] = defaultdict(int)
    for item in per_orbital:
        symbol = item.get("nearest_atom_symbol") or "?"
        nearest_atom_distribution[str(symbol)] += 1

    top_offsets = sorted(
        (dict(item) for item in per_orbital),
        key=lambda item: item.get("distance_A") or 0.0,
        reverse=True,
    )[:WANNIER_OFFSET_PREVIEW_LIMIT]

    return {
        "count": len(per_orbital),
        "average_A": offsets.get("average_A"),
        "max_A": offsets.get("max_A"),
        "min_A": offsets.get("min_A"),
        "nearest_atom_distribution": [
            {"symbol": symbol, "count": count}
            for symbol, count in sorted(
                nearest_atom_distribution.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ],
        "top_offsets": top_offsets,
    }


def _build_llm_summary(metrics: Dict[str, Any]) -> Dict[str, Any]:
    quality = metrics.get("quality_assessment") or {}
    spread = metrics.get("spread_summary") or {}
    tight_binding = metrics.get("tight_binding") or {}
    center_offsets = tight_binding.get("orbital_center_offsets") or {}
    compactness = tight_binding.get("compactness_assessment") or {}

    return {
        "seedname": metrics.get("seedname"),
        "num_wann": metrics.get("num_wann"),
        "converged": metrics.get("converged"),
        "quality_grade": quality.get("grade"),
        "quality_score": quality.get("score"),
        "quality_risks": quality.get("abnormal_causes") or [],
        "average_spread": spread.get("average"),
        "max_spread": spread.get("max"),
        "top_delocalized_functions": spread.get("top_delocalized") or [],
        "omega_total": metrics.get("omega_total"),
        "omega_I": metrics.get("omega_I"),
        "omega_D": metrics.get("omega_D"),
        "omega_OD": metrics.get("omega_OD"),
        "average_center_offset_A": center_offsets.get("average_A"),
        "max_center_offset_A": center_offsets.get("max_A"),
        "compactness_grade": compactness.get("grade"),
        "compactness_score": compactness.get("score"),
        "compactness_warnings": compactness.get("warnings") or [],
        "max_hopping_abs": (
            (tight_binding.get("max_hopping_term") or {}).get("abs")
            if tight_binding.get("max_hopping_term")
            else None
        ),
        "nearest_neighbor_abs": (tight_binding.get("nearest_neighbor") or {}).get("max_abs"),
        "next_nearest_neighbor_abs": (
            (tight_binding.get("next_nearest_neighbor") or {}).get("max_abs")
        ),
        "warnings": metrics.get("warnings") or [],
    }


def _parse_omega_values(wout_text: str) -> Dict[str, Optional[float]]:
    values: Dict[str, Optional[float]] = {}
    for key, pattern in OMEGA_PATTERNS.items():
        match = pattern.search(wout_text)
        values[key] = _safe_float(match.group(1)) if match else None
    return values


def _parse_converged(wout_text: str) -> Optional[bool]:
    lowered = wout_text.lower()
    if any(marker in lowered for marker in NON_CONVERGED_PATTERNS):
        return False
    if any(marker in lowered for marker in CONVERGED_PATTERNS):
        return True
    return None


def _parse_timing(wout_text: str) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    total_seconds: Optional[float] = None
    wall_seconds: Optional[float] = None
    cpu_seconds: Optional[float] = None

    for line in wout_text.splitlines():
        lowered = line.lower()
        if "time" not in lowered:
            continue
        seconds_match = SECONDS_VALUE_RE.search(line)
        value = _safe_float(seconds_match.group(1)) if seconds_match else None
        label = line.split(":", 1)[0].strip()
        if value is None:
            numeric_match = GENERIC_FLOAT_RE.search(line)
            value = _safe_float(numeric_match.group(0)) if numeric_match else None
        entries.append({"label": label or line.strip(), "seconds": value, "raw": line.strip()})
        if value is None:
            continue
        if "wall" in lowered:
            wall_seconds = value
        elif "cpu" in lowered:
            cpu_seconds = value
        elif "total" in lowered and total_seconds is None:
            total_seconds = value

    if total_seconds is None:
        for entry in reversed(entries):
            if entry["seconds"] is not None:
                total_seconds = entry["seconds"]
                break

    return {
        "entries": entries,
        "total_seconds": total_seconds,
        "wall_seconds": wall_seconds,
        "cpu_seconds": cpu_seconds,
    }


def _extract_warnings(wout_text: str) -> List[str]:
    warnings: List[str] = []
    seen = set()
    for line in wout_text.splitlines():
        lowered = line.lower()
        if not any(marker in lowered for marker in WARNING_MARKERS):
            continue
        cleaned = line.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        warnings.append(cleaned)
    return warnings


def _classify_quality(metrics: Dict[str, Any], file_presence: Dict[str, bool]) -> Dict[str, Any]:
    score = 100
    reasons: List[str] = []
    abnormal_causes: List[str] = []

    converged = metrics.get("converged")
    spreads = metrics.get("final_spreads") or []
    warnings = metrics.get("warnings") or []
    omega_i = metrics.get("omega_I")
    omega_d = metrics.get("omega_D")
    omega_od = metrics.get("omega_OD")
    omega_total = metrics.get("omega_total")

    avg_spread = sum(spreads) / len(spreads) if spreads else None
    max_spread = max(spreads) if spreads else None

    if converged is False:
        score -= 35
        abnormal_causes.append("Wannierisation did not report convergence.")
    elif converged is True:
        reasons.append("Wannierisation reached a final state.")
    else:
        score -= 10
        abnormal_causes.append("Convergence could not be determined from wannier90.wout.")

    if not file_presence.get("wannier90.chk", False):
        score -= 30
        abnormal_causes.append(
            "Checkpoint file is missing, so downstream postw90.x steps are blocked."
        )
    else:
        reasons.append("Checkpoint file is present for restart and post-processing.")

    for filename in ("wannier90.amn", "wannier90.mmn", "wannier90.eig"):
        if not file_presence.get(filename, False):
            score -= 8
            abnormal_causes.append(f"Interface file {filename} is missing.")

    if avg_spread is None:
        score -= 15
        abnormal_causes.append("Final spreads could not be parsed from wannier90.wout.")
    elif avg_spread <= 1.5:
        reasons.append("Average spread is compact, indicating strong localization.")
    elif avg_spread <= 3.0:
        score -= 8
        reasons.append("Average spread is acceptable for a first-pass Wannier run.")
    else:
        score -= 22
        abnormal_causes.append("Average spread is large; localization is weak.")

    if max_spread is not None:
        if max_spread > 5.0:
            score -= 18
            abnormal_causes.append("At least one Wannier function remains highly delocalized.")
        elif max_spread > 3.0:
            score -= 8
            abnormal_causes.append("One Wannier function has a noticeably large spread.")

    if omega_total is not None and omega_total > 0 and omega_od is not None:
        od_ratio = omega_od / omega_total
        if od_ratio > 0.5:
            score -= 15
            abnormal_causes.append("Off-diagonal spread dominates; disentanglement may be unstable.")
        elif od_ratio > 0.35:
            score -= 6
            abnormal_causes.append("Off-diagonal spread is sizeable and worth checking.")

    if omega_i is not None and omega_d is not None and omega_d > max(omega_i * 1.5, 2.0):
        score -= 10
        abnormal_causes.append("Diagonal spread is much larger than the invariant part.")

    if warnings:
        score -= min(len(warnings), 5) * 4
        abnormal_causes.append("wannier90.wout contains warning-style messages.")

    score = max(score, 0)
    if score >= 85:
        grade = "excellent"
    elif score >= 65:
        grade = "good"
    else:
        grade = "poor"

    if not reasons and not abnormal_causes:
        reasons.append("No obvious issues were detected in the parsed Wannier outputs.")

    return {
        "grade": grade,
        "score": score,
        "reasons": reasons,
        "abnormal_causes": abnormal_causes,
        "average_spread": avg_spread,
        "max_spread": max_spread,
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
    }


def _find_seed_file(job_dir: Path, seedname: str, suffix: str) -> Optional[Path]:
    candidates = [
        job_dir / f"{seedname}{suffix}",
        job_dir / f"wannier90{suffix}",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    matches = sorted(job_dir.glob(f"*{suffix}"))
    return matches[0] if matches else None


def _build_artifacts(job_dir: Path, seedname: str) -> Dict[str, Any]:
    files: Dict[str, str] = {}
    raw_files: List[str] = []
    for name in WANNIER_REQUIRED_FILES:
        path = job_dir / name
        if path.exists():
            files[name] = str(path)
            raw_files.append(str(path))
    for suffix in ("_hr.dat", "_r.dat", "_tb.dat"):
        path = _find_seed_file(job_dir, seedname, suffix)
        if path is not None and path.exists():
            files[path.name] = str(path)
            raw_files.append(str(path))
    for name in ("vasprun.xml", "vasp.out", "OUTCAR"):
        path = job_dir / name
        if path.exists():
            files[name] = str(path)
            raw_files.append(str(path))
    return {"files": files, "raw_files": raw_files}


def _load_structure(job_dir: Path) -> Any:
    try:
        from ase.io import read
    except Exception:
        return None

    for name in ("CONTCAR", "POSCAR"):
        path = job_dir / name
        if path.exists():
            try:
                return read(path)
            except Exception:
                continue
    return None


def _write_wannier_centers_xyz(
    job_dir: Path, structure: Any, centers: List[List[float]]
) -> Optional[str]:
    target = job_dir / "wannier_centers.xyz"
    source = job_dir / "wannier90_centres.xyz"
    if source.exists():
        shutil.copy2(source, target)
        return str(target)

    if structure is None or not centers:
        return None

    try:
        symbols = list(structure.get_chemical_symbols())
        positions = structure.get_positions()
        lines = [str(len(symbols) + len(centers)), "Atoms and Wannier centers"]
        for symbol, pos in zip(symbols, positions):
            lines.append(
                f"{symbol} {_format_float(pos[0])} {_format_float(pos[1])} {_format_float(pos[2])}"
            )
        for center in centers:
            lines.append(
                f"X {_format_float(center[0])} {_format_float(center[1])} {_format_float(center[2])}"
            )
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(target)
    except Exception:
        return None


def _species_colors(symbols: List[str]) -> List[str]:
    palette = [
        "#7bdff2",
        "#b2f7ef",
        "#eff7f6",
        "#f7d6e0",
        "#f2b5d4",
        "#f6bd60",
        "#84a59d",
        "#f28482",
        "#4cc9f0",
        "#90be6d",
    ]
    mapping: Dict[str, str] = {}
    colors: List[str] = []
    for symbol in symbols:
        if symbol not in mapping:
            mapping[symbol] = palette[len(mapping) % len(palette)]
        colors.append(mapping[symbol])
    return colors


def _plot_structure_and_centers(
    structure: Any, centers: List[List[float]], target: Path
) -> Optional[str]:
    if structure is None:
        return None
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return None

    try:
        positions = structure.get_positions()
        colors = _species_colors(list(structure.get_chemical_symbols()))

        fig, axes = plt.subplots(1, 3, figsize=(12, 4), dpi=150)
        for ax, (xlabel, ylabel, i, j) in zip(
            axes,
            (("x", "y", 0, 1), ("x", "z", 0, 2), ("y", "z", 1, 2)),
        ):
            ax.scatter(
                [pos[i] for pos in positions],
                [pos[j] for pos in positions],
                c=colors,
                s=55,
                edgecolors="#0b1014",
                linewidths=0.4,
                alpha=0.95,
            )
            if centers:
                ax.scatter(
                    [pos[i] for pos in centers],
                    [pos[j] for pos in centers],
                    c="#ff8f4a",
                    s=80,
                    marker="x",
                    linewidths=1.5,
                )
            ax.set_xlabel(xlabel)
            ax.set_ylabel(ylabel)
            ax.set_aspect("equal", adjustable="box")
            ax.set_facecolor("#0a0f14")
            ax.grid(alpha=0.12)

        fig.suptitle("Structure + Wannier centers", fontsize=12)
        fig.tight_layout()
        target.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(target, bbox_inches="tight")
        plt.close(fig)
        return str(target)
    except Exception:
        return None


def _canonicalize_orbital_files(job_dir: Path, seedname: str) -> Dict[str, List[Path]]:
    cube_files = sorted(job_dir.glob("*.cube"))
    xsf_files = sorted(job_dir.glob("*.xsf"))
    if not cube_files and not xsf_files:
        cube_files = sorted(job_dir.glob(f"{seedname}*.cube"))
        xsf_files = sorted(job_dir.glob(f"{seedname}*.xsf"))

    canonical_cube: List[Path] = []
    canonical_xsf: List[Path] = []
    for index, path in enumerate(cube_files, start=1):
        canonical = job_dir / f"wf_{index:03d}.cube"
        if path.resolve() != canonical.resolve():
            shutil.copy2(path, canonical)
        canonical_cube.append(canonical)
    for index, path in enumerate(xsf_files, start=1):
        canonical = job_dir / f"wf_{index:03d}.xsf"
        if path.resolve() != canonical.resolve():
            shutil.copy2(path, canonical)
        canonical_xsf.append(canonical)
    return {"cube": canonical_cube, "xsf": canonical_xsf}


def _plot_cube_slice(cube_path: Path, target: Path) -> Optional[str]:
    try:
        from ase.io.cube import read_cube_data
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception:
        return None

    try:
        data, _atoms = read_cube_data(str(cube_path))
        array = np.asarray(data)
        if array.ndim != 3 or min(array.shape) == 0:
            return None
        axis = int(np.argmin(array.shape))
        slice_index = array.shape[axis] // 2
        slice_2d = np.take(array, slice_index, axis=axis)

        fig, ax = plt.subplots(figsize=(4, 4), dpi=150)
        vmax = float(np.max(np.abs(slice_2d))) if slice_2d.size else 1.0
        if not math.isfinite(vmax) or vmax <= 0:
            vmax = 1.0
        image = ax.imshow(
            slice_2d.T, origin="lower", cmap="coolwarm", vmin=-vmax, vmax=vmax
        )
        ax.set_title(cube_path.stem)
        ax.set_xticks([])
        ax.set_yticks([])
        fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
        fig.tight_layout()
        target.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(target, bbox_inches="tight")
        plt.close(fig)
        return str(target)
    except Exception:
        return None


def _plot_spread_overview(
    wannier_functions: List[Dict[str, Any]], target: Path
) -> Optional[str]:
    if not wannier_functions:
        return None
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return None

    try:
        fig, ax = plt.subplots(figsize=(8, 3.5), dpi=150)
        ax.bar(
            [item["index"] for item in wannier_functions],
            [item["spread"] for item in wannier_functions],
            color="#ff8f4a",
            edgecolor="#ffb37e",
        )
        ax.set_xlabel("Wannier function")
        ax.set_ylabel("Spread (Ang^2)")
        ax.set_title("Wannier spread overview")
        ax.grid(axis="y", alpha=0.18)
        fig.tight_layout()
        target.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(target, bbox_inches="tight")
        plt.close(fig)
        return str(target)
    except Exception:
        return None


def _build_orbital_overview(orbital_pngs: List[Path], target: Path) -> Optional[str]:
    if not orbital_pngs:
        return None
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return None

    try:
        count = len(orbital_pngs)
        cols = min(4, count)
        rows = math.ceil(count / cols)
        fig, axes = plt.subplots(rows, cols, figsize=(cols * 3, rows * 3), dpi=150)
        axes_list = axes.ravel().tolist() if hasattr(axes, "ravel") else [axes]
        for ax, path in zip(axes_list, orbital_pngs):
            ax.imshow(plt.imread(path))
            ax.set_title(path.stem, fontsize=9)
            ax.axis("off")
        for ax in axes_list[count:]:
            ax.axis("off")
        fig.suptitle("Wannier orbital overview", fontsize=12)
        fig.tight_layout()
        target.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(target, bbox_inches="tight")
        plt.close(fig)
        return str(target)
    except Exception:
        return None


def _build_visualization(
    job_dir: Path,
    seedname: str,
    centers: List[List[float]],
    wannier_functions: List[Dict[str, Any]],
    visualization_options: Dict[str, Any],
) -> Dict[str, Any]:
    plot_dir = job_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    warnings: List[str] = []

    structure = _load_structure(job_dir)
    centers_xyz = _write_wannier_centers_xyz(job_dir, structure, centers)
    if centers_xyz is None:
        warnings.append("Could not create wannier_centers.xyz from structure and final centers.")

    overlay_png = _plot_structure_and_centers(
        structure, centers, plot_dir / "wannier_centers_overlay.png"
    )
    if overlay_png is None:
        warnings.append("Failed to render the structure + Wannier center overlay.")

    orbital_files = _canonicalize_orbital_files(job_dir, seedname)
    cube_files = orbital_files["cube"][:WANNIER_MAX_ORBITAL_PLOTS]
    xsf_files = orbital_files["xsf"][:WANNIER_MAX_ORBITAL_PLOTS]

    orbital_pngs: List[Dict[str, Any]] = []
    for index, cube_path in enumerate(cube_files, start=1):
        png_path = plot_dir / f"wf_{index:03d}.png"
        rendered = _plot_cube_slice(cube_path, png_path)
        if rendered:
            orbital_pngs.append(
                {"index": index, "path": rendered, "source_file": str(cube_path)}
            )

    if cube_files and not orbital_pngs:
        warnings.append("Cube files were found but orbital PNG generation failed.")
    if not cube_files and xsf_files:
        warnings.append(
            "Only XSF Wannier plots were found; PNG orbital thumbnails are currently generated from cube files."
        )
    if not cube_files and not xsf_files:
        enable_lwrite_unk = bool(visualization_options.get("enable_lwrite_unk"))
        enable_wannier_plot = bool(visualization_options.get("enable_wannier_plot"))
        spinor_flags = _detect_spinor_incar_flags(job_dir)
        if not enable_lwrite_unk and not enable_wannier_plot:
            warnings.append(
                "No Wannier volumetric plot files were found. This run left the optional "
                "LWRITE_UNK and wannier_plot patches disabled."
            )
        elif not enable_lwrite_unk:
            warnings.append(
                "No Wannier volumetric plot files were found. This run enabled wannier_plot, "
                "but left the optional LWRITE_UNK patch disabled."
            )
        elif not enable_wannier_plot:
            warnings.append(
                "No Wannier volumetric plot files were found. This run enabled LWRITE_UNK, "
                "but left the optional wannier_plot patch disabled."
            )
        elif spinor_flags:
            warnings.append(
                "No Wannier volumetric plot files were found even though the user enabled "
                "LWRITE_UNK/wannier_plot. INCAR also sets "
                f"{', '.join(spinor_flags)}."
            )
        else:
            warnings.append(
                "No Wannier volumetric plot files were found even though the optional "
                "LWRITE_UNK and wannier_plot patches were enabled."
            )

    detected_plot_format = None
    if cube_files:
        detected_plot_format = "cube"
    elif xsf_files:
        detected_plot_format = "xsf"
    elif visualization_options.get("enable_wannier_plot"):
        detected_plot_format = str(visualization_options.get("wannier_plot_format") or WANNIER_PLOT_FORMAT)

    overview_png = None
    if orbital_pngs:
        overview_png = _build_orbital_overview(
            [Path(item["path"]) for item in orbital_pngs],
            plot_dir / "wf_overview.png",
        )
    if overview_png is None:
        overview_png = _plot_spread_overview(
            wannier_functions, plot_dir / "wf_overview.png"
        )

    return {
        "plot_format": detected_plot_format,
        "centers_xyz": centers_xyz,
        "structure_centers_png": overlay_png,
        "wf_overview_png": overview_png,
        "orbital_files": [
            {"index": index, "path": str(path), "format": "cube"}
            for index, path in enumerate(cube_files, start=1)
        ]
        + [
            {"index": index, "path": str(path), "format": "xsf"}
            for index, path in enumerate(xsf_files, start=1)
        ],
        "orbital_pngs": orbital_pngs,
        "checkpoint_portability": {
            "chk_path": str(job_dir / "wannier90.chk")
            if (job_dir / "wannier90.chk").exists()
            else None,
            "machine_specific": True,
            "conversion_tool": "w90chk2chk.x",
            "note": (
                "wannier90.chk is machine/compiler dependent. If compute and post-processing nodes differ, "
                "convert through w90chk2chk.x before reuse."
            ),
        },
        "warnings": warnings,
    }


def _center_offsets(structure: Any, centers: List[List[float]]) -> Optional[Dict[str, Any]]:
    if structure is None or not centers:
        return None
    try:
        positions = structure.get_positions()
        symbols = list(structure.get_chemical_symbols())
        lattice = structure.cell.array.tolist() if hasattr(structure, "cell") else None
    except Exception:
        return None

    offsets: List[Dict[str, Any]] = []
    shifts = (-1, 0, 1)
    for index, center in enumerate(centers, start=1):
        best_distance: Optional[float] = None
        best_atom_index: Optional[int] = None
        best_symbol: Optional[str] = None
        for atom_index, (symbol, position) in enumerate(zip(symbols, positions), start=1):
            for shift in ((a, b, c) for a in shifts for b in shifts for c in shifts):
                translation = _translation_cart(lattice, shift)
                trial = _vector_sub(
                    center,
                    [position[axis] + translation[axis] for axis in range(3)],
                )
                distance = _vector_norm(trial)
                if best_distance is None or distance < best_distance:
                    best_distance = distance
                    best_atom_index = atom_index
                    best_symbol = symbol
        offsets.append(
            {
                "index": index,
                "nearest_atom_index": best_atom_index,
                "nearest_atom_symbol": best_symbol,
                "distance_A": best_distance,
            }
        )

    values = [item["distance_A"] for item in offsets if item["distance_A"] is not None]
    if not values:
        return None
    return {
        "per_orbital": offsets,
        "average_A": sum(values) / len(values),
        "max_A": max(values),
        "min_A": min(values),
    }


def _keep_top(entries: List[Dict[str, Any]], item: Dict[str, Any], limit: int) -> None:
    entries.append(item)
    entries.sort(key=lambda entry: entry["abs"], reverse=True)
    del entries[limit:]


def _parse_hr_dat(path: Path, centers: List[List[float]], structure: Any) -> Dict[str, Any]:
    lattice = None
    if structure is not None and hasattr(structure, "cell"):
        try:
            lattice = structure.cell.array.tolist()
        except Exception:
            lattice = None

    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    ]
    if len(lines) < 3:
        raise ValueError(f"{path.name} is too short to be a valid hr.dat")

    comment = lines[0]
    num_wann = int(lines[1].split()[0])
    nrpts = int(lines[2].split()[0])

    degeneracies: List[int] = []
    cursor = 3
    while len(degeneracies) < nrpts and cursor < len(lines):
        degeneracies.extend(int(token) for token in lines[cursor].split())
        cursor += 1
    degeneracies = degeneracies[:nrpts]
    if len(degeneracies) != nrpts:
        raise ValueError(f"{path.name} does not contain enough degeneracy entries")

    expected_terms = nrpts * num_wann * num_wann
    store_full_terms = expected_terms <= MAX_JSON_HAMILTONIAN_TERMS
    full_terms: Optional[List[Dict[str, Any]]] = [] if store_full_terms else None

    top_terms: List[Dict[str, Any]] = []
    graph_edges: List[Dict[str, Any]] = []
    pair_matrix = [[0.0 for _ in range(num_wann)] for _ in range(num_wann)]
    distance_bins: Dict[float, Dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "sum_abs": 0.0, "max_abs": 0.0}
    )
    radius_sums = {radius: 0.0 for radius in TRUNCATION_RADII}

    total_abs = 0.0
    onsite_abs = 0.0
    intersite_abs = 0.0
    onsite_count = 0
    intersite_count = 0

    for raw_line in lines[cursor:]:
        parts = raw_line.split()
        if len(parts) < 7:
            continue
        translation = [int(parts[0]), int(parts[1]), int(parts[2])]
        orbital_i = int(parts[3])
        orbital_j = int(parts[4])
        real = _safe_float(parts[5]) or 0.0
        imag = _safe_float(parts[6]) or 0.0
        abs_value = math.sqrt(real * real + imag * imag)
        distance = None
        if 0 < orbital_i <= len(centers) and 0 < orbital_j <= len(centers):
            cart_shift = _translation_cart(lattice, translation)
            displacement = [
                centers[orbital_j - 1][axis] + cart_shift[axis] - centers[orbital_i - 1][axis]
                for axis in range(3)
            ]
            distance = _vector_norm(displacement)

        term = {
            "translation": translation,
            "i": orbital_i,
            "j": orbital_j,
            "real": real,
            "imag": imag,
            "abs": abs_value,
            "distance_A": distance,
        }
        total_abs += abs_value

        if store_full_terms and full_terms is not None:
            full_terms.append(term)

        pair_matrix[orbital_i - 1][orbital_j - 1] = max(
            pair_matrix[orbital_i - 1][orbital_j - 1],
            abs_value,
        )
        _keep_top(top_terms, term, TOP_HOPPING_LIMIT)

        is_onsite = translation == [0, 0, 0] and orbital_i == orbital_j
        if is_onsite:
            onsite_abs += abs_value
            onsite_count += 1
            continue

        intersite_abs += abs_value
        intersite_count += 1
        if distance is not None:
            distance_key = round(distance / DISTANCE_BIN_WIDTH) * DISTANCE_BIN_WIDTH
            bucket = distance_bins[distance_key]
            bucket["count"] += 1
            bucket["sum_abs"] += abs_value
            bucket["max_abs"] = max(bucket["max_abs"], abs_value)
            for radius in TRUNCATION_RADII:
                if distance <= radius:
                    radius_sums[radius] += abs_value
        _keep_top(graph_edges, term, GRAPH_EDGE_LIMIT)

    distance_stats = [
        {
            "distance_A": distance,
            "count": values["count"],
            "mean_abs": values["sum_abs"] / values["count"] if values["count"] else 0.0,
            "max_abs": values["max_abs"],
        }
        for distance, values in sorted(distance_bins.items())
    ]
    shells = [entry for entry in distance_stats if entry["distance_A"] > 1e-6]
    nearest_neighbor = shells[0] if shells else None
    next_nearest_neighbor = shells[1] if len(shells) > 1 else None
    truncation_summary = [
        {
            "radius_A": radius,
            "retained_abs_weight": radius_sums[radius],
            "retained_fraction": radius_sums[radius] / intersite_abs if intersite_abs > 0 else None,
            "error_proxy": (
                None
                if intersite_abs <= 0
                else 1.0 - radius_sums[radius] / intersite_abs
            ),
        }
        for radius in TRUNCATION_RADII
    ]

    return {
        "path": str(path),
        "comment": comment,
        "num_wann": num_wann,
        "nrpts": nrpts,
        "degeneracies": degeneracies,
        "storage_mode": "full" if store_full_terms else "summary_only",
        "terms": full_terms,
        "total_terms": expected_terms,
        "top_terms": top_terms,
        "pair_max_abs_matrix": pair_matrix,
        "distance_statistics": distance_stats,
        "nearest_neighbor": nearest_neighbor,
        "next_nearest_neighbor": next_nearest_neighbor,
        "truncation_summary": truncation_summary,
        "orbital_center_offsets": _center_offsets(structure, centers),
        "total_abs_hopping": total_abs,
        "onsite_abs_hopping": onsite_abs,
        "intersite_abs_hopping": intersite_abs,
        "onsite_term_count": onsite_count,
        "intersite_term_count": intersite_count,
        "graph_edges": graph_edges,
        "lattice_matrix": lattice,
    }


def _compactness_assessment(tight_binding: Dict[str, Any]) -> Dict[str, Any]:
    score = 100
    reasons: List[str] = []
    warnings: List[str] = []

    nearest_neighbor = tight_binding.get("nearest_neighbor")
    next_nearest_neighbor = tight_binding.get("next_nearest_neighbor")
    truncation_summary = tight_binding.get("truncation_summary") or []
    offsets = tight_binding.get("orbital_center_offsets") or {}

    radius_6 = next(
        (entry for entry in truncation_summary if abs(entry["radius_A"] - 6.0) < 1e-9),
        None,
    )
    radius_8 = next(
        (entry for entry in truncation_summary if abs(entry["radius_A"] - 8.0) < 1e-9),
        None,
    )

    if nearest_neighbor and next_nearest_neighbor:
        nn = nearest_neighbor["max_abs"]
        nnn = next_nearest_neighbor["max_abs"]
        if nn > max(nnn * 2.0, 1e-6):
            reasons.append("Nearest-neighbor hopping clearly dominates over the next shell.")
        elif nn > nnn:
            score -= 6
            reasons.append("Nearest-neighbor hopping remains dominant but the model is less sparse.")
        else:
            score -= 18
            warnings.append("Longer-range terms compete with the nearest shell; the model is diffuse.")

    if radius_6 and radius_6["retained_fraction"] is not None:
        if radius_6["retained_fraction"] >= 0.9:
            reasons.append("A 6 A cutoff already retains most intersite hopping weight.")
        elif radius_6["retained_fraction"] >= 0.75:
            score -= 8
            warnings.append("A 6 A cutoff loses a noticeable fraction of hopping weight.")
        else:
            score -= 20
            warnings.append("The model requires a long cutoff radius to retain intersite weight.")

    if radius_8 and radius_8["retained_fraction"] is not None and radius_8["retained_fraction"] < 0.85:
        score -= 12
        warnings.append("Even an 8 A cutoff is not enough to recover most hopping weight.")

    avg_offset = offsets.get("average_A")
    max_offset = offsets.get("max_A")
    if avg_offset is not None:
        if avg_offset <= 1.1:
            reasons.append("Wannier centers stay close to the atomic or bonding backbone.")
        elif avg_offset <= 2.0:
            score -= 6
            warnings.append("Wannier centers are moderately displaced from nearby atoms.")
        else:
            score -= 18
            warnings.append("Wannier centers drift far from nearby atoms or bonds.")
    if max_offset is not None and max_offset > 3.0:
        score -= 10
        warnings.append("At least one Wannier center is far from the local bonding region.")

    if tight_binding.get("storage_mode") != "full":
        score -= 4
        warnings.append("Hamiltonian JSON was downgraded to summary mode because the full hr.dat is too large.")

    score = max(score, 0)
    if score >= 85:
        verdict = "compact"
        suitable = True
    elif score >= 65:
        verdict = "usable"
        suitable = True
    else:
        verdict = "diffuse"
        suitable = False

    if not reasons and not warnings:
        reasons.append("No obvious compactness issues were detected.")

    return {
        "verdict": verdict,
        "score": score,
        "suitable_for_large_scale_scan": suitable,
        "summary": (
            "Suitable for larger-scale tight-binding scans."
            if suitable
            else "Use with caution; the model is not very compact for large-scale scans."
        ),
        "reasons": reasons,
        "warnings": warnings,
    }


def _compact_tight_binding_for_metrics(tight_binding: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "available": tight_binding.get("available"),
        "source_hr_file": tight_binding.get("source_hr_file"),
        "source_r_file": tight_binding.get("source_r_file"),
        "source_tb_file": tight_binding.get("source_tb_file"),
        "model_dimension": tight_binding.get("model_dimension"),
        "seedname": tight_binding.get("seedname"),
        "source_step": tight_binding.get("source_step"),
        "storage_mode": tight_binding.get("storage_mode"),
        "total_terms": tight_binding.get("total_terms"),
        "nrpts": tight_binding.get("nrpts"),
        "compactness_assessment": tight_binding.get("compactness_assessment"),
        "max_hopping_term": tight_binding.get("max_hopping_term"),
        "top_terms": list((tight_binding.get("top_terms") or [])[:8]),
        "top_orbital_pairs": list((tight_binding.get("top_orbital_pairs") or [])[:8]),
        "model_summary": tight_binding.get("model_summary"),
        "nearest_neighbor": tight_binding.get("nearest_neighbor"),
        "next_nearest_neighbor": tight_binding.get("next_nearest_neighbor"),
        "truncation_summary": tight_binding.get("truncation_summary"),
        "distance_statistics_preview": list(
            (tight_binding.get("distance_statistics") or [])[:12]
        ),
        "orbital_center_offsets": _summarize_center_offsets(
            tight_binding.get("orbital_center_offsets")
        ),
        "onsite_abs_hopping": tight_binding.get("onsite_abs_hopping"),
        "intersite_abs_hopping": tight_binding.get("intersite_abs_hopping"),
        "onsite_term_count": tight_binding.get("onsite_term_count"),
        "intersite_term_count": tight_binding.get("intersite_term_count"),
        "warnings": tight_binding.get("warnings"),
        "artifacts": tight_binding.get("artifacts"),
    }


def _write_json(path: Path, payload: Dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _plot_hopping_vs_distance(
    distance_stats: List[Dict[str, Any]], target: Path
) -> Optional[str]:
    if not distance_stats:
        return None
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return None

    try:
        fig, ax = plt.subplots(figsize=(7, 4), dpi=150)
        ax.plot(
            [entry["distance_A"] for entry in distance_stats],
            [entry["mean_abs"] for entry in distance_stats],
            marker="o",
            color="#7bdff2",
            label="Mean |t|",
        )
        ax.plot(
            [entry["distance_A"] for entry in distance_stats],
            [entry["max_abs"] for entry in distance_stats],
            marker="s",
            color="#ff8f4a",
            label="Max |t|",
        )
        ax.set_xlabel("Distance (Angstrom)")
        ax.set_ylabel("|hopping|")
        ax.set_title("Distance-sorted hopping statistics")
        ax.grid(alpha=0.18)
        ax.legend()
        fig.tight_layout()
        target.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(target, bbox_inches="tight")
        plt.close(fig)
        return str(target)
    except Exception:
        return None


def _plot_hopping_heatmap(matrix: List[List[float]], target: Path) -> Optional[str]:
    if not matrix:
        return None
    try:
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception:
        return None

    try:
        data = np.asarray(matrix, dtype=float)
        fig, ax = plt.subplots(figsize=(5.5, 4.8), dpi=150)
        image = ax.imshow(data, cmap="magma", origin="lower")
        ax.set_xlabel("Orbital j")
        ax.set_ylabel("Orbital i")
        ax.set_title("Max |hopping| by orbital pair")
        fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
        fig.tight_layout()
        target.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(target, bbox_inches="tight")
        plt.close(fig)
        return str(target)
    except Exception:
        return None


def _plot_hopping_graph(
    centers: List[List[float]], spreads: List[float], edges: List[Dict[str, Any]], target: Path
) -> Optional[str]:
    if not centers or not edges:
        return None
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return None

    try:
        fig, ax = plt.subplots(figsize=(6, 6), dpi=150)
        sizes = [80 + 30 * spread for spread in spreads] if spreads else [90] * len(centers)
        ax.scatter(
            [center[0] for center in centers],
            [center[1] for center in centers],
            s=sizes,
            c="#7bdff2",
            edgecolors="#081116",
            linewidths=0.5,
            zorder=3,
        )

        max_abs = max((entry["abs"] for entry in edges[:60]), default=1.0)
        for entry in edges[:60]:
            i = entry["i"] - 1
            j = entry["j"] - 1
            if i < 0 or j < 0 or i >= len(centers) or j >= len(centers):
                continue
            ax.plot(
                [centers[i][0], centers[j][0]],
                [centers[i][1], centers[j][1]],
                color="#ff8f4a",
                alpha=max(0.15, entry["abs"] / max_abs),
                linewidth=0.8 + 2.2 * (entry["abs"] / max_abs),
                zorder=2,
            )

        for index, center in enumerate(centers, start=1):
            ax.text(center[0], center[1], str(index), fontsize=8, ha="center", va="center")

        ax.set_xlabel("Center x (Angstrom)")
        ax.set_ylabel("Center y (Angstrom)")
        ax.set_title("Truncated hopping graph")
        ax.set_aspect("equal", adjustable="box")
        ax.grid(alpha=0.12)
        fig.tight_layout()
        target.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(target, bbox_inches="tight")
        plt.close(fig)
        return str(target)
    except Exception:
        return None


def _plot_truncation_summary(
    truncation_summary: List[Dict[str, Any]], target: Path
) -> Optional[str]:
    if not truncation_summary:
        return None
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return None

    try:
        x = [entry["radius_A"] for entry in truncation_summary]
        retained = [
            entry["retained_fraction"] if entry["retained_fraction"] is not None else 0.0
            for entry in truncation_summary
        ]
        error = [
            entry["error_proxy"] if entry["error_proxy"] is not None else 0.0
            for entry in truncation_summary
        ]
        fig, ax1 = plt.subplots(figsize=(7, 4), dpi=150)
        ax1.plot(x, retained, marker="o", color="#7bdff2", label="Retained weight")
        ax1.set_xlabel("Cutoff radius (Angstrom)")
        ax1.set_ylabel("Retained fraction")
        ax1.set_ylim(0.0, 1.05)
        ax1.grid(alpha=0.18)

        ax2 = ax1.twinx()
        ax2.plot(x, error, marker="s", color="#ff8f4a", label="Error proxy")
        ax2.set_ylabel("1 - retained fraction")
        ax2.set_ylim(0.0, 1.05)

        lines = ax1.get_lines() + ax2.get_lines()
        ax1.legend(lines, [line.get_label() for line in lines], loc="center right")
        fig.tight_layout()
        target.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(target, bbox_inches="tight")
        plt.close(fig)
        return str(target)
    except Exception:
        return None


def _build_orbital_pair_ranking(
    pair_matrix: List[List[float]], limit: int = 20
) -> List[Dict[str, Any]]:
    pairs: List[Dict[str, Any]] = []
    for i, row in enumerate(pair_matrix, start=1):
        for j, value in enumerate(row, start=1):
            if value <= 0:
                continue
            pairs.append({"i": i, "j": j, "max_abs": value})
    pairs.sort(key=lambda item: item["max_abs"], reverse=True)
    return pairs[:limit]


def _relative_to_job_dir(job_dir: Path, absolute_path: str) -> str:
    try:
        return Path(absolute_path).resolve().relative_to(job_dir.resolve()).as_posix()
    except Exception:
        return Path(absolute_path).name


def _register_artifact(
    artifact_files: Dict[str, str],
    job_dir: Path,
    absolute_path: Optional[str],
    label: Optional[str] = None,
) -> Optional[str]:
    if not absolute_path:
        return None
    rel_path = label or _relative_to_job_dir(job_dir, absolute_path)
    artifact_files[rel_path] = absolute_path
    return rel_path


def _build_tb_layer(
    job_dir: Path,
    seedname: str,
    centers: List[List[float]],
    spreads: List[float],
    structure: Any,
    source_step: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    warnings: List[str] = []
    hr_path = _find_seed_file(job_dir, seedname, "_hr.dat")
    r_path = _find_seed_file(job_dir, seedname, "_r.dat")
    tb_path = _find_seed_file(job_dir, seedname, "_tb.dat")

    if hr_path is None:
        return {
            "available": False,
            "warnings": ["No seedname_hr.dat file was found; tight-binding export is unavailable."],
            "artifacts": {},
        }

    try:
        parsed = _parse_hr_dat(hr_path, centers, structure)
    except Exception as exc:
        return {
            "available": False,
            "warnings": [f"Failed to parse {hr_path.name}: {exc}"],
            "artifacts": {"hr_dat": str(hr_path)},
        }

    parsed["available"] = True
    parsed["source_hr_file"] = str(hr_path)
    parsed["source_r_file"] = str(r_path) if r_path else None
    parsed["source_tb_file"] = str(tb_path) if tb_path else None
    parsed["model_dimension"] = parsed["num_wann"]
    parsed["seedname"] = seedname
    parsed["source_step"] = source_step
    parsed["compactness_assessment"] = _compactness_assessment(parsed)
    parsed["max_hopping_term"] = parsed["top_terms"][0] if parsed["top_terms"] else None
    parsed["top_orbital_pairs"] = _build_orbital_pair_ranking(
        parsed["pair_max_abs_matrix"], limit=20
    )
    parsed["model_summary"] = {
        "dimension": parsed["num_wann"],
        "nrpts": parsed["nrpts"],
        "storage_mode": parsed["storage_mode"],
        "largest_hopping_abs": (
            parsed["top_terms"][0]["abs"] if parsed["top_terms"] else None
        ),
        "nearest_neighbor_abs": (
            parsed["nearest_neighbor"]["max_abs"]
            if parsed.get("nearest_neighbor")
            else None
        ),
        "next_nearest_neighbor_abs": (
            parsed["next_nearest_neighbor"]["max_abs"]
            if parsed.get("next_nearest_neighbor")
            else None
        ),
        "average_center_offset_A": (
            parsed["orbital_center_offsets"]["average_A"]
            if parsed.get("orbital_center_offsets")
            else None
        ),
        "max_center_offset_A": (
            parsed["orbital_center_offsets"]["max_A"]
            if parsed.get("orbital_center_offsets")
            else None
        ),
    }

    hamiltonian_json = _write_json(
        job_dir / "hamiltonian.json",
        {
            "version": "0.1",
            "seedname": seedname,
            "source_step": source_step,
            "num_wann": parsed["num_wann"],
            "nrpts": parsed["nrpts"],
            "comment": parsed["comment"],
            "storage_mode": parsed["storage_mode"],
            "total_terms": parsed["total_terms"],
            "degeneracies": parsed["degeneracies"],
            "lattice_matrix": parsed["lattice_matrix"],
            "orbital_centers": centers,
            "orbital_spreads": spreads,
            "top_terms": parsed["top_terms"],
            "pair_max_abs_matrix": parsed["pair_max_abs_matrix"],
            "truncation_summary": parsed["truncation_summary"],
            "terms": parsed["terms"],
        },
    )
    hopping_graph_json = _write_json(
        job_dir / "hopping_graph.json",
        {
            "version": "0.1",
            "seedname": seedname,
            "nodes": [
                {
                    "id": index,
                    "label": f"WF {index}",
                    "center_cartesian": centers[index - 1] if index - 1 < len(centers) else None,
                    "spread": spreads[index - 1] if index - 1 < len(spreads) else None,
                    "center_offset_A": (
                        parsed["orbital_center_offsets"]["per_orbital"][index - 1]["distance_A"]
                        if parsed.get("orbital_center_offsets")
                        and index - 1 < len(parsed["orbital_center_offsets"]["per_orbital"])
                        else None
                    ),
                }
                for index in range(1, parsed["num_wann"] + 1)
            ],
            "edges": parsed["graph_edges"],
            "selection": {
                "max_edges": GRAPH_EDGE_LIMIT,
                "ordered_by": "absolute hopping magnitude",
            },
        },
    )

    plot_dir = job_dir / "plots"
    hopping_distance_png = _plot_hopping_vs_distance(
        parsed["distance_statistics"], plot_dir / "hopping_vs_distance.png"
    )
    pair_heatmap_png = _plot_hopping_heatmap(
        parsed["pair_max_abs_matrix"], plot_dir / "hopping_pair_heatmap.png"
    )
    graph_png = _plot_hopping_graph(
        centers, spreads, parsed["graph_edges"], plot_dir / "hopping_graph.png"
    )
    truncation_png = _plot_truncation_summary(
        parsed["truncation_summary"], plot_dir / "hopping_truncation.png"
    )

    if parsed["storage_mode"] != "full":
        warnings.append(
            "Hamiltonian JSON was downgraded to summary mode because the full hr.dat is too large."
        )
    if hopping_distance_png is None:
        warnings.append("Could not render hopping_vs_distance.png.")
    if pair_heatmap_png is None:
        warnings.append("Could not render hopping_pair_heatmap.png.")
    if graph_png is None:
        warnings.append("Could not render hopping_graph.png.")
    if truncation_png is None:
        warnings.append("Could not render hopping_truncation.png.")

    parsed["artifacts"] = {
        "hr_dat": str(hr_path),
        "r_dat": str(r_path) if r_path else None,
        "tb_dat": str(tb_path) if tb_path else None,
        "hamiltonian_json": hamiltonian_json,
        "hopping_graph_json": hopping_graph_json,
        "hopping_vs_distance_png": hopping_distance_png,
            "hopping_pair_heatmap_png": pair_heatmap_png,
        "hopping_graph_png": graph_png,
        "hopping_truncation_png": truncation_png,
    }
    parsed["warnings"] = warnings
    parsed.pop("pair_max_abs_matrix", None)
    parsed.pop("terms", None)
    return parsed


def _write_metrics(job_dir: Path, metrics: Dict[str, Any]) -> None:
    path = job_dir / WANNIER_METRICS_FILENAME
    path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


def postprocess_wannier(job_id: str, job_dir: Path, job_meta: Dict[str, Any]) -> Dict[str, Any]:
    wout_text = _read_text(job_dir / "wannier90.wout")
    win_text = _read_text(job_dir / "wannier90.win")
    file_presence = {name: (job_dir / name).exists() for name in WANNIER_REQUIRED_FILES}

    final_state = _parse_final_state(wout_text)
    omega_values = _parse_omega_values(wout_text)
    warnings = _extract_warnings(wout_text)
    for name in WANNIER_REQUIRED_FILES:
        if not file_presence[name]:
            warnings.append(f"Required Wannier file is missing: {name}")
    warnings = list(dict.fromkeys(warnings))

    num_wann = _parse_num_wann(win_text, wout_text)
    if num_wann is None and final_state["wannier_functions"]:
        num_wann = len(final_state["wannier_functions"])

    seedname = _parse_seedname(win_text, wout_text)
    source_step = _build_source_step(job_meta)
    visualization_options = _read_visualization_options(job_meta)
    structure = _load_structure(job_dir)
    final_centers = final_state["final_centers"]
    final_spreads = final_state["final_spreads"]
    wannier_functions = final_state["wannier_functions"]

    metrics: Dict[str, Any] = {
        "version": "0.2",
        "status": "ok",
        "meta": {
            "task_id": job_id,
            "workdir": str(job_dir),
            "parser": "wannier90",
            "generated_at": now_iso(),
        },
        "seedname": seedname,
        "source_step": source_step,
        "num_wann": num_wann,
        "final_centers": final_centers,
        "final_spreads": final_spreads,
        "wannier_functions": wannier_functions,
        "omega_I": omega_values["omega_I"],
        "omega_D": omega_values["omega_D"],
        "omega_OD": omega_values["omega_OD"],
        "omega_total": omega_values["omega_total"],
        "converged": _parse_converged(wout_text),
        "timing": _parse_timing(wout_text),
        "warnings": warnings,
        "artifacts": _build_artifacts(job_dir, seedname),
    }

    metrics["quality_assessment"] = _classify_quality(metrics, file_presence)

    visualization = _build_visualization(
        job_dir,
        seedname,
        final_centers,
        wannier_functions,
        visualization_options,
    )
    metrics["visualization"] = visualization
    metrics["visualization_options"] = visualization_options
    artifact_files = metrics["artifacts"]["files"]
    if visualization.get("centers_xyz"):
        _register_artifact(artifact_files, job_dir, visualization["centers_xyz"])
    if visualization.get("structure_centers_png"):
        _register_artifact(artifact_files, job_dir, visualization["structure_centers_png"])
    if visualization.get("wf_overview_png"):
        _register_artifact(artifact_files, job_dir, visualization["wf_overview_png"])
    for orbital in visualization.get("orbital_files", []):
        _register_artifact(artifact_files, job_dir, orbital["path"])
    for orbital_png in visualization.get("orbital_pngs", []):
        _register_artifact(artifact_files, job_dir, orbital_png["path"])
    if visualization["warnings"]:
        metrics["warnings"] = list(dict.fromkeys(metrics["warnings"] + visualization["warnings"]))

    tight_binding = _build_tb_layer(
        job_dir,
        seedname,
        final_centers,
        final_spreads,
        structure,
        source_step,
    )
    for value in (tight_binding.get("artifacts") or {}).values():
        if value:
            _register_artifact(artifact_files, job_dir, value)
    if tight_binding.get("warnings"):
        metrics["warnings"] = list(dict.fromkeys(metrics["warnings"] + tight_binding["warnings"]))

    details_path = _write_json(
        job_dir / WANNIER_DETAILS_FILENAME,
        {
            "version": "0.1",
            "seedname": seedname,
            "source_step": source_step,
            "num_wann": num_wann,
            "final_centers": final_centers,
            "final_spreads": final_spreads,
            "wannier_functions": wannier_functions,
            "orbital_center_offsets": tight_binding.get("orbital_center_offsets"),
        },
    )
    metrics["details_files"] = {
        "wannier_details_json": details_path,
    }
    metrics["center_summary"] = _summarize_centers(final_centers)
    metrics["spread_summary"] = _summarize_spreads(wannier_functions, final_spreads)
    metrics["wannier_functions_preview"] = _preview_wannier_functions(wannier_functions)
    metrics["tight_binding"] = _compact_tight_binding_for_metrics(tight_binding)
    metrics["llm_summary"] = _build_llm_summary(metrics)
    metrics.pop("final_centers", None)
    metrics.pop("final_spreads", None)
    metrics.pop("wannier_functions", None)

    if metrics["quality_assessment"]["grade"] == "poor" or metrics["warnings"]:
        metrics["status"] = "degraded"

    download_candidates = [
        "vasprun.xml",
        "vasp.out",
        "OUTCAR",
        "wannier90.win",
        "wannier90.mmn",
        "wannier90.amn",
        "wannier90.eig",
        "wannier90.nnkp",
        "wannier90.wout",
        "wannier90.chk",
        "wannier90_hr.dat",
        "wannier90_r.dat",
        "wannier90_tb.dat",
        "wannier90_centres.xyz",
        "wannier_centers.xyz",
        WANNIER_DETAILS_FILENAME,
        "hamiltonian.json",
        "hopping_graph.json",
        "plots/wannier_centers_overlay.png",
        "plots/wf_overview.png",
        "plots/hopping_vs_distance.png",
        "plots/hopping_pair_heatmap.png",
        "plots/hopping_graph.png",
        "plots/hopping_truncation.png",
        WANNIER_METRICS_FILENAME,
    ]
    for orbital in visualization["orbital_files"]:
        orbital_path = Path(orbital["path"])
        if orbital_path.exists():
            download_candidates.append(orbital_path.name)
    for orbital_png in visualization["orbital_pngs"]:
        orbital_png_path = Path(orbital_png["path"])
        if orbital_png_path.exists():
            download_candidates.append(f"plots/{orbital_png_path.name}")

    metrics["download_files"] = [
        name
        for name in dict.fromkeys(download_candidates)
        if (job_dir / name).exists()
    ]

    _write_metrics(job_dir, metrics)
    return metrics
