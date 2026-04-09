from __future__ import annotations

import csv
import json
import math
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from ase.io import read as ase_read
from ase.visualize.plot import plot_atoms
from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.io.vasp.inputs import Incar, Kpoints, Poscar
from pymatgen.io.vasp.outputs import Oszicar, Vasprun
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from .config import VTST_METRICS_FILENAME, VASP_QC_FORCE_THRESHOLD
from .storage import now_iso

FINISH_MARKERS = (
    "General timing and accounting informations for this job",
    "Voluntary context switches",
)

ERROR_PATTERNS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("VERY_BAD_NEWS", "error", ("VERY BAD NEWS",)),
    ("SEGMENTATION_FAULT", "error", ("segmentation fault",)),
    ("ZBRENT_ERROR", "error", ("ZBRENT",)),
    ("EDDDAV_FAILED", "error", ("EDDDAV",)),
    ("BRMIX_WARNING", "warn", ("BRMIX",)),
    ("CNORMN_WARNING", "warn", ("CNORMN",)),
    ("INTERNAL_ERROR", "error", ("internal error",)),
)


def _safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _mark_degraded(metrics: Dict[str, Any]) -> None:
    metrics["status"] = "degraded"


def _add_warning(metrics: Dict[str, Any], message: str) -> None:
    metrics.setdefault("warnings", []).append(message)
    _mark_degraded(metrics)


def _add_flag(metrics: Dict[str, Any], code: str, severity: str, evidence: str) -> None:
    qc = metrics.setdefault("qc", {})
    flags = qc.setdefault("flags", [])
    entry = {"code": code, "severity": severity, "evidence": evidence}
    if entry not in flags:
        flags.append(entry)
    if severity in {"warn", "error"}:
        _mark_degraded(metrics)


def _tail_text(path: Path, line_count: int = 20) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return "\n".join(lines[-line_count:])


def _read_numeric_rows(path: Path, min_cols: int = 2) -> List[List[float]]:
    rows: List[List[float]] = []
    if not path.exists():
        return rows
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        values: List[float] = []
        valid = True
        for token in line.split():
            try:
                values.append(float(token))
            except ValueError:
                valid = False
                break
        if valid and len(values) >= min_cols:
            rows.append(values)
    return rows


def _parse_neb_rows(rows: List[List[float]]) -> Tuple[List[Dict[str, Any]], str]:
    if not rows:
        return [], "empty"

    width = max(len(row) for row in rows)
    parsed: List[Dict[str, Any]] = []

    if width >= 5:
        variant = "distance_energy_force_image"
        for index, row in enumerate(rows):
            parsed.append(
                {
                    "row": index,
                    "image": int(round(row[4])),
                    "path_coordinate": float(row[1]),
                    "energy_rel_eV": float(row[2]),
                    "force_eVA": float(row[3]),
                }
            )
        return parsed, variant

    if width == 4:
        first_is_index = all(abs(row[0] - round(row[0])) < 1e-8 for row in rows)
        third_is_absolute = max(abs(row[2]) for row in rows) > 100.0
        second_monotonic = all(rows[i + 1][1] >= rows[i][1] for i in range(len(rows) - 1))

        if first_is_index and third_is_absolute:
            variant = "image_force_energy_absolute_energy_relative"
            for index, row in enumerate(rows):
                parsed.append(
                    {
                        "row": index,
                        "image": int(round(row[0])),
                        "path_coordinate": float(row[0]),
                        "energy_abs_eV": float(row[2]),
                        "energy_rel_eV": float(row[3]),
                        "force_eVA": float(row[1]),
                    }
                )
            return parsed, variant

        if first_is_index and second_monotonic:
            variant = "image_distance_energy_force"
            for index, row in enumerate(rows):
                parsed.append(
                    {
                        "row": index,
                        "image": int(round(row[0])),
                        "path_coordinate": float(row[1]),
                        "energy_rel_eV": float(row[2]),
                        "force_eVA": float(row[3]),
                    }
                )
            return parsed, variant

        variant = "distance_energy_force_extra"
        for index, row in enumerate(rows):
            parsed.append(
                {
                    "row": index,
                    "image": index,
                    "path_coordinate": float(row[0]),
                    "energy_rel_eV": float(row[1]),
                    "force_eVA": float(row[2]),
                }
            )
        return parsed, variant

    variant = "distance_energy_force"
    for index, row in enumerate(rows):
        parsed.append(
            {
                "row": index,
                "image": index,
                "path_coordinate": float(row[0]),
                "energy_rel_eV": float(row[1]),
                "force_eVA": float(row[2]) if len(row) >= 3 else None,
            }
        )
    return parsed, variant


def _parse_xy_rows(path: Path) -> List[Dict[str, float]]:
    points: List[Dict[str, float]] = []
    for row in _read_numeric_rows(path, min_cols=2):
        points.append({"x": float(row[0]), "y": float(row[1])})
    return points


def _read_incar_tags(path: Path) -> Dict[str, Any]:
    tags: Dict[str, Any] = {}
    if not path.exists():
        return tags
    try:
        incar = Incar.from_file(str(path))
        for key, value in incar.items():
            tags[str(key)] = value
        return tags
    except Exception:
        pass

    pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=?\s*(.+?)\s*$")
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.split("#", 1)[0].split("!", 1)[0].strip()
        if not line:
            continue
        match = pattern.match(line)
        if match:
            tags[match.group(1).upper()] = match.group(2).strip()
    return tags


def _kpoints_summary(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        kpoints = Kpoints.from_file(str(path))
        if kpoints.kpts:
            mesh = "x".join(str(int(v)) for v in kpoints.kpts[0])
            return f"{mesh} {kpoints.style.name}"
        return kpoints.style.name
    except Exception:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return " | ".join(line.strip() for line in lines[:4] if line.strip()) or None


def _structure_file(image_dir: Path) -> Optional[Path]:
    for name in ("CONTCAR", "POSCAR"):
        candidate = image_dir / name
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    return None


def _structure_summary(structure) -> Dict[str, Any]:
    species = [str(site.specie) for site in structure.sites]
    return {
        "formula": structure.composition.reduced_formula,
        "natoms": len(structure),
        "volume": _safe_float(structure.volume),
        "species": species,
        "lattice_matrix": [[float(v) for v in row] for row in structure.lattice.matrix.tolist()],
        "fractional_positions": [
            [float(v) for v in row] for row in structure.frac_coords.tolist()
        ],
    }


def _symmetry_summary(structure) -> Optional[Dict[str, Any]]:
    try:
        analyzer = SpacegroupAnalyzer(structure, symprec=1e-2)
        return {
            "number": int(analyzer.get_space_group_number()),
            "symbol": analyzer.get_space_group_symbol(),
            "crystal_system": analyzer.get_crystal_system(),
        }
    except Exception:
        return None


def _load_structure(image_dir: Path) -> Tuple[Any, Any, Optional[Path]]:
    source = _structure_file(image_dir)
    if source is None:
        return None, None, None

    pmg_structure = None
    ase_atoms = None
    try:
        pmg_structure = Poscar.from_file(str(source)).structure
    except Exception:
        pmg_structure = None
    try:
        ase_atoms = ase_read(str(source), format="vasp")
    except Exception:
        ase_atoms = None
    return pmg_structure, ase_atoms, source


def _file_finished_cleanly(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    return any(marker in text for marker in FINISH_MARKERS)


def _scan_error_patterns(path: Path) -> List[Tuple[str, str, str]]:
    hits: List[Tuple[str, str, str]] = []
    if not path.exists():
        return hits
    text = path.read_text(encoding="utf-8", errors="ignore").lower()
    for code, severity, patterns in ERROR_PATTERNS:
        for pattern in patterns:
            if pattern.lower() in text:
                hits.append((code, severity, pattern))
                break
    return hits


def _parse_outcar_max_force(path: Path) -> Optional[float]:
    if not path.exists():
        return None

    last_block: List[float] = []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    line_count = len(lines)
    index = 0
    while index < line_count:
        if "TOTAL-FORCE" not in lines[index]:
            index += 1
            continue

        probe = index + 1
        while probe < line_count and not lines[probe].strip().startswith("-"):
            probe += 1
        probe += 1

        current_block: List[float] = []
        while probe < line_count:
            parts = lines[probe].split()
            if len(parts) < 6:
                break
            try:
                fx, fy, fz = map(float, parts[-3:])
            except ValueError:
                break
            current_block.append(math.sqrt(fx * fx + fy * fy + fz * fz))
            probe += 1

        if current_block:
            last_block = current_block
        index = probe

    return max(last_block) if last_block else None


def _parse_oszicar(path: Path, nelm: Optional[int]) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "final_energy_eV": None,
        "electronic_converged": None,
        "ionic_steps": None,
        "last_electronic_steps": None,
    }
    if not path.exists():
        return data
    try:
        oszicar = Oszicar(str(path))
        data["final_energy_eV"] = _safe_float(getattr(oszicar, "final_energy", None))

        ionic_steps = getattr(oszicar, "ionic_steps", None)
        if ionic_steps is not None:
            data["ionic_steps"] = len(ionic_steps)
            if data["final_energy_eV"] is None and ionic_steps:
                last_step = ionic_steps[-1]
                for key in ("E0", "F", "E"):
                    if key in last_step:
                        data["final_energy_eV"] = _safe_float(last_step.get(key))
                        if data["final_energy_eV"] is not None:
                            break

        electronic_steps = getattr(oszicar, "electronic_steps", None)
        if electronic_steps:
            data["last_electronic_steps"] = len(electronic_steps[-1])
            if nelm is not None:
                data["electronic_converged"] = len(electronic_steps[-1]) < nelm
    except Exception:
        return data
    return data


def _parse_vasprun_convergence(path: Path) -> Dict[str, Any]:
    data = {
        "converged": None,
        "electronic_converged": None,
        "ionic_converged": None,
    }
    if not path.exists():
        return data
    try:
        vasprun = Vasprun(
            str(path),
            parse_dos=False,
            parse_eigen=False,
            parse_projected_eigen=False,
            parse_potcar_file=False,
        )
        data["converged"] = bool(vasprun.converged)
        data["electronic_converged"] = bool(vasprun.converged_electronic)
        data["ionic_converged"] = bool(vasprun.converged_ionic)
    except Exception:
        pass
    return data


def _discover_image_dirs(job_dir: Path) -> List[Path]:
    dirs = [path for path in job_dir.iterdir() if path.is_dir() and path.name.isdigit()]
    return sorted(dirs, key=lambda path: int(path.name))


def _displacement_norms(atoms_a, atoms_b) -> Optional[np.ndarray]:
    if atoms_a is None or atoms_b is None:
        return None
    if len(atoms_a) != len(atoms_b):
        return None

    frac_a = np.array(atoms_a.get_scaled_positions(wrap=False), dtype=float)
    frac_b = np.array(atoms_b.get_scaled_positions(wrap=False), dtype=float)
    delta = frac_b - frac_a

    pbc = np.array(atoms_a.pbc, dtype=bool) & np.array(atoms_b.pbc, dtype=bool)
    for axis in range(3):
        if pbc[axis]:
            delta[:, axis] -= np.round(delta[:, axis])

    cell = np.array(atoms_a.cell.array, dtype=float)
    cart = delta @ cell
    return np.linalg.norm(cart, axis=1)


def _monotonic(values: List[float], tol: float = 1e-8) -> bool:
    if len(values) < 2:
        return False
    diffs = [values[index + 1] - values[index] for index in range(len(values) - 1)]
    nonnegative = all(diff >= -tol for diff in diffs)
    nonpositive = all(diff <= tol for diff in diffs)
    return nonnegative or nonpositive


def _load_images(
    image_dirs: List[Path],
    neb_points: List[Dict[str, Any]],
    nelm: Optional[int],
) -> List[Dict[str, Any]]:
    neb_by_image = {int(point["image"]): point for point in neb_points if point.get("image") is not None}
    entries: List[Dict[str, Any]] = []

    for image_dir in image_dirs:
        image_index = int(image_dir.name)
        pmg_structure, ase_atoms, structure_path = _load_structure(image_dir)
        outcar_path = image_dir / "OUTCAR"
        oszicar_path = image_dir / "OSZICAR"
        vasprun_path = image_dir / "vasprun.xml"

        oszicar_data = _parse_oszicar(oszicar_path, nelm)
        vasprun_data = _parse_vasprun_convergence(vasprun_path)
        neb_point = neb_by_image.get(image_index, {})

        max_force = _parse_outcar_max_force(outcar_path)
        finished_cleanly = _file_finished_cleanly(outcar_path) or _file_finished_cleanly(
            image_dir / "vasp.out"
        )

        electronic_converged = vasprun_data["electronic_converged"]
        if electronic_converged is None:
            electronic_converged = oszicar_data["electronic_converged"]

        converged = vasprun_data["converged"]
        if converged is None and finished_cleanly and electronic_converged is not None:
            converged = bool(electronic_converged)

        entry = {
            "image": image_index,
            "directory": image_dir.name,
            "path_coordinate": _safe_float(neb_point.get("path_coordinate")),
            "energy_rel_eV": _safe_float(neb_point.get("energy_rel_eV")),
            "neb_force_eVA": _safe_float(neb_point.get("force_eVA")),
            "force_eVA": _safe_float(neb_point.get("force_eVA")),
            "final_energy_eV": _safe_float(oszicar_data["final_energy_eV"]),
            "max_force_eVA": _safe_float(max_force),
            "finished_cleanly": bool(finished_cleanly),
            "electronic_converged": electronic_converged,
            "converged": converged,
            "outcar_path": str(outcar_path.resolve()) if outcar_path.exists() else None,
            "oszicar_path": str(oszicar_path.resolve()) if oszicar_path.exists() else None,
            "structure_path": str(structure_path.resolve()) if structure_path else None,
            "structure": _structure_summary(pmg_structure) if pmg_structure is not None else None,
            "symmetry": _symmetry_summary(pmg_structure) if pmg_structure is not None else None,
            "warnings": [],
            "_pmg_structure": pmg_structure,
            "_ase_atoms": ase_atoms,
        }
        if entry["path_coordinate"] is None:
            entry["path_coordinate"] = float(image_index)
        entries.append(entry)

    absolute_energies = [
        entry["final_energy_eV"] for entry in entries if entry.get("final_energy_eV") is not None
    ]
    if absolute_energies and all(entry.get("energy_rel_eV") is None for entry in entries):
        baseline = min(absolute_energies)
        for entry in entries:
            energy = entry.get("final_energy_eV")
            if energy is not None:
                entry["energy_rel_eV"] = energy - baseline

    return entries


def _structure_change_summary(metrics: Dict[str, Any], image_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "segment_displacements_A": [],
        "reaction_coordinate_A": [],
        "total_path_displacement_A": None,
        "endpoint_difference": None,
        "key_atom_displacements": [],
        "endpoint_symmetry": {},
        "ts_symmetry": None,
        "structure_matcher": None,
    }

    usable = [entry for entry in image_entries if entry.get("_ase_atoms") is not None]
    if len(usable) < 2:
        return summary

    cumulative = 0.0
    reaction_coords = [0.0]
    segment_rows: List[Dict[str, Any]] = []
    for left, right in zip(usable, usable[1:]):
        norms = _displacement_norms(left["_ase_atoms"], right["_ase_atoms"])
        if norms is None:
            continue
        segment_rms = float(np.sqrt(np.mean(norms**2)))
        cumulative += segment_rms
        reaction_coords.append(cumulative)
        segment_rows.append(
            {
                "from": left["image"],
                "to": right["image"],
                "mean_displacement_A": float(np.mean(norms)),
                "rms_displacement_A": segment_rms,
                "max_displacement_A": float(np.max(norms)),
            }
        )

    summary["segment_displacements_A"] = segment_rows
    summary["reaction_coordinate_A"] = reaction_coords
    summary["total_path_displacement_A"] = cumulative

    first = usable[0]
    last = usable[-1]
    endpoint_norms = _displacement_norms(first["_ase_atoms"], last["_ase_atoms"])
    if endpoint_norms is not None:
        summary["endpoint_difference"] = {
            "rms_displacement_A": float(np.sqrt(np.mean(endpoint_norms**2))),
            "max_displacement_A": float(np.max(endpoint_norms)),
            "mean_displacement_A": float(np.mean(endpoint_norms)),
        }
        ranked = sorted(
            enumerate(endpoint_norms.tolist()), key=lambda item: item[1], reverse=True
        )[:8]
        summary["key_atom_displacements"] = [
            {
                "index": int(index),
                "element": first["_ase_atoms"][index].symbol,
                "displacement_A": float(value),
            }
            for index, value in ranked
        ]

    if first.get("symmetry") is not None:
        summary["endpoint_symmetry"]["initial"] = first["symmetry"]
    if last.get("symmetry") is not None:
        summary["endpoint_symmetry"]["final"] = last["symmetry"]

    ts_entry = max(
        (
            entry
            for entry in image_entries
            if entry.get("energy_rel_eV") is not None and entry.get("symmetry") is not None
        ),
        key=lambda entry: entry["energy_rel_eV"],
        default=None,
    )
    if ts_entry is not None:
        summary["ts_symmetry"] = {
            "image": ts_entry["image"],
            **ts_entry["symmetry"],
        }

    pmg_structures = [entry.get("_pmg_structure") for entry in usable]
    if all(structure is not None for structure in pmg_structures):
        try:
            matcher = StructureMatcher()
            consecutive_failures = []
            for left, right in zip(usable, usable[1:]):
                if not matcher.fit(left["_pmg_structure"], right["_pmg_structure"]):
                    consecutive_failures.append([left["image"], right["image"]])
            summary["structure_matcher"] = {
                "consecutive_fit_failures": consecutive_failures,
                "endpoint_fit": matcher.fit(first["_pmg_structure"], last["_pmg_structure"]),
            }
            if consecutive_failures:
                _add_flag(
                    metrics,
                    "STRUCTURE_MATCHER_DISCONTINUITY",
                    "warn",
                    f"Consecutive images not matched for pairs: {consecutive_failures}",
                )
        except Exception as exc:
            _add_warning(metrics, f"StructureMatcher check failed: {exc}")

    return summary


def _plot_series(
    path: Path,
    x_values: List[float],
    y_values: List[float],
    title: str,
    xlabel: str,
    ylabel: str,
    scatter: bool = True,
    extra_points: Optional[List[Tuple[float, float, str]]] = None,
) -> Optional[str]:
    if not x_values or not y_values or len(x_values) != len(y_values):
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(7.2, 4.6), dpi=160)
    plt.plot(x_values, y_values, lw=2.2, color="#ff8f4a")
    if scatter:
        plt.scatter(x_values, y_values, s=28, color="#141b22", edgecolors="#ff8f4a", zorder=3)
    if extra_points:
        for x_pos, y_pos, label in extra_points:
            plt.scatter([x_pos], [y_pos], s=42, color="#1f77b4", zorder=4)
            plt.annotate(label, (x_pos, y_pos), xytext=(6, 6), textcoords="offset points")
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.grid(alpha=0.25)
    plt.tight_layout()
    plt.savefig(path)
    plt.close()
    return str(path.resolve())


def _ts_candidate_entry(image_entries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    internal = [
        entry
        for entry in image_entries[1:-1]
        if entry.get("_ase_atoms") is not None and entry.get("energy_rel_eV") is not None
    ]
    if internal:
        return max(internal, key=lambda entry: entry["energy_rel_eV"])

    any_entry = [
        entry
        for entry in image_entries
        if entry.get("_ase_atoms") is not None and entry.get("energy_rel_eV") is not None
    ]
    if any_entry:
        return max(any_entry, key=lambda entry: entry["energy_rel_eV"])
    return None


def _draw_atoms_panel(ax, atoms, title: str, subtitle: str = "") -> None:
    plot_atoms(
        atoms,
        ax=ax,
        rotation="20x,-35y,10z",
        radii=0.42,
        show_unit_cell=1,
    )
    ax.set_axis_off()
    ax.set_title(title, fontsize=11, pad=10)
    if subtitle:
        ax.text(
            0.5,
            -0.08,
            subtitle,
            ha="center",
            va="top",
            transform=ax.transAxes,
            fontsize=9,
            color="#45515f",
        )


def _entry_subtitle(entry: Dict[str, Any]) -> str:
    formula = (entry.get("structure") or {}).get("formula") or "unknown"
    rel_energy = entry.get("energy_rel_eV")
    energy_text = (
        f"E_rel {rel_energy:.4f} eV" if isinstance(rel_energy, (int, float)) else "E_rel -"
    )
    return f"{formula} | {energy_text}"


def _plot_endpoint_vs_ts(path: Path, image_entries: List[Dict[str, Any]]) -> Optional[str]:
    usable = [entry for entry in image_entries if entry.get("_ase_atoms") is not None]
    if len(usable) < 2:
        return None

    initial = usable[0]
    final = usable[-1]
    ts_entry = _ts_candidate_entry(usable) or usable[len(usable) // 2]

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 3, figsize=(12.8, 4.8), dpi=170)
    panels = [
        (initial, f"Initial ({initial['directory']})"),
        (ts_entry, f"Highest-energy image ({ts_entry['directory']})"),
        (final, f"Final ({final['directory']})"),
    ]
    for ax, (entry, title) in zip(axes, panels):
        _draw_atoms_panel(ax, entry["_ase_atoms"], title, _entry_subtitle(entry))
    plt.tight_layout()
    plt.savefig(path)
    plt.close(fig)
    return str(path.resolve())


def _render_gif_frame(entry: Dict[str, Any]):
    try:
        from PIL import Image
    except Exception as exc:
        raise RuntimeError(f"Pillow is not available: {exc}") from exc

    atoms = entry.get("_ase_atoms")
    if atoms is None:
        return None

    fig, ax = plt.subplots(figsize=(4.6, 4.9), dpi=150)
    _draw_atoms_panel(ax, atoms, f"Image {entry['directory']}", _entry_subtitle(entry))
    buffer = BytesIO()
    fig.tight_layout()
    fig.savefig(buffer, format="png")
    plt.close(fig)
    buffer.seek(0)
    image = Image.open(buffer).convert("RGBA").copy()
    buffer.close()
    return image


def _write_reaction_gif(path: Path, image_entries: List[Dict[str, Any]]) -> Optional[str]:
    usable = [entry for entry in image_entries if entry.get("_ase_atoms") is not None]
    if len(usable) < 2:
        return None

    frames = [frame for frame in (_render_gif_frame(entry) for entry in usable) if frame is not None]
    if len(frames) < 2:
        return None

    path.parent.mkdir(parents=True, exist_ok=True)
    first, *rest = frames
    first.save(
        path,
        save_all=True,
        append_images=rest,
        duration=700,
        loop=0,
        disposal=2,
    )
    return str(path.resolve())


def _write_image_csv(image_entries: List[Dict[str, Any]], path: Path) -> Optional[str]:
    if not image_entries:
        return None
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "image",
                "directory",
                "path_coordinate",
                "final_energy_eV",
                "energy_rel_eV",
                "neb_force_eVA",
                "max_force_eVA",
                "finished_cleanly",
                "electronic_converged",
                "converged",
                "formula",
                "natoms",
            ]
        )
        for entry in image_entries:
            structure = entry.get("structure") or {}
            writer.writerow(
                [
                    entry.get("image"),
                    entry.get("directory"),
                    entry.get("path_coordinate"),
                    entry.get("final_energy_eV"),
                    entry.get("energy_rel_eV"),
                    entry.get("neb_force_eVA"),
                    entry.get("max_force_eVA"),
                    entry.get("finished_cleanly"),
                    entry.get("electronic_converged"),
                    entry.get("converged"),
                    structure.get("formula"),
                    structure.get("natoms"),
                ]
            )
    return str(path.resolve())


def _build_llm_payload(metrics: Dict[str, Any], job_dir: Path, image_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    barrier = metrics.get("barrier_summary", {})
    qc = metrics.get("qc", {})
    warnings = metrics.get("warnings", [])

    verdict = (
        f"NEB barrier raw={barrier.get('barrier_raw_eV')} eV, "
        f"spline={barrier.get('barrier_spline_eV')} eV, "
        f"TS image={barrier.get('ts_image_index')}, "
        f"path_monotonic={barrier.get('path_monotonic')}, "
        f"finished_cleanly={qc.get('finished_cleanly')}."
    )

    middle_entry = image_entries[len(image_entries) // 2] if image_entries else None
    middle_tail = ""
    if middle_entry is not None:
        middle_tail = _tail_text(job_dir / middle_entry["directory"] / "OSZICAR", line_count=12)

    return {
        "verdict_inputs": verdict,
        "warnings": warnings,
        "tails": {
            "root_vasp_out_tail": _tail_text(job_dir / "vasp.out", line_count=20),
            "image_mid_oszicar_tail": middle_tail,
        },
    }


def postprocess_vtst(job_id: str, job_dir: Path, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta = meta or {}
    plots_dir = job_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    metrics: Dict[str, Any] = {
        "version": "0.1",
        "status": "ok",
        "warnings": [],
        "meta": {
            "task_id": job_id,
            "task_type": "neb",
            "n_images": None,
            "root_dir": str(job_dir.resolve()),
            "vasp_binary": meta.get("vasp_exec"),
            "vtst_enabled": True,
            "vtst_mode": meta.get("vtst_mode"),
            "generated_at": now_iso(),
        },
        "inputs_summary": {
            "incar_key_tags": {},
            "kpoints_summary": None,
            "formula": None,
        },
        "qc": {
            "finished_cleanly": False,
            "endpoint_outcars_present": False,
            "neb_dat_present": False,
            "image_count_matches_input": None,
            "nproc_multiple_of_images": None,
            "flags": [],
        },
        "barrier_summary": {
            "barrier_raw_eV": None,
            "barrier_spline_eV": None,
            "ts_image_index": None,
            "ts_path_coordinate": None,
            "spline_max_path_coordinate": None,
            "raw_max_path_coordinate": None,
            "path_monotonic": None,
            "interpolated_extrema": [],
            "raw_barrier_source": None,
        },
        "image_table": [],
        "structure_change_summary": {},
        "artifacts": {
            "neb_dat": None,
            "spline_dat": None,
            "exts_dat": None,
            "barrier_raw_png": None,
            "barrier_spline_png": None,
            "force_along_path_png": None,
            "image_energy_table_csv": None,
            "reaction_gif": None,
            "endpoint_vs_ts_png": None,
        },
        "llm_payload": {},
    }

    incar_tags = _read_incar_tags(job_dir / "INCAR")
    selected_tags = {
        key: incar_tags.get(key)
        for key in ("IMAGES", "SPRING", "IBRION", "IOPT", "NSW", "EDIFFG", "NELM")
        if key in incar_tags
    }
    metrics["inputs_summary"]["incar_key_tags"] = selected_tags
    metrics["meta"]["n_images"] = int(selected_tags["IMAGES"]) if "IMAGES" in selected_tags else None
    metrics["inputs_summary"]["kpoints_summary"] = _kpoints_summary(job_dir / "KPOINTS")

    endpoint_poscar = job_dir / "POSCAR_initial"
    if not endpoint_poscar.exists():
        endpoint_poscar = job_dir / "POSCAR_i"

    try:
        poscar_initial = Poscar.from_file(str(endpoint_poscar))
        metrics["inputs_summary"]["formula"] = poscar_initial.structure.composition.reduced_formula
    except Exception as exc:
        _add_warning(metrics, f"Failed to read {endpoint_poscar.name}: {exc}")

    neb_path = job_dir / "neb.dat"
    spline_path = job_dir / "spline.dat"
    exts_path = job_dir / "exts.dat"

    metrics["qc"]["neb_dat_present"] = neb_path.exists()
    metrics["artifacts"]["neb_dat"] = str(neb_path.resolve()) if neb_path.exists() else None
    metrics["artifacts"]["spline_dat"] = (
        str(spline_path.resolve()) if spline_path.exists() else None
    )
    metrics["artifacts"]["exts_dat"] = str(exts_path.resolve()) if exts_path.exists() else None

    if not neb_path.exists():
        _add_flag(metrics, "NEB_DAT_MISSING", "error", "neb.dat was not generated")

    neb_points, neb_variant = _parse_neb_rows(_read_numeric_rows(neb_path, min_cols=3))
    if not neb_points:
        _add_flag(metrics, "NEB_DAT_EMPTY", "error", "neb.dat has no parseable numeric rows")
    else:
        metrics["barrier_summary"]["raw_barrier_source"] = neb_variant

    spline_points = _parse_xy_rows(spline_path)
    exts_points = _parse_xy_rows(exts_path)

    image_dirs = _discover_image_dirs(job_dir)
    expected_images = metrics["meta"]["n_images"]
    if expected_images is not None:
        expected_total = int(expected_images) + 2
        metrics["qc"]["image_count_matches_input"] = len(image_dirs) == expected_total
        if len(image_dirs) != expected_total:
            _add_flag(
                metrics,
                "IMAGE_COUNT_MISMATCH",
                "error",
                f"Expected {expected_total} image directories, found {len(image_dirs)}",
            )

        nproc = meta.get("nproc")
        if nproc is not None:
            metrics["qc"]["nproc_multiple_of_images"] = int(nproc) % int(expected_images) == 0
            if not metrics["qc"]["nproc_multiple_of_images"]:
                _add_flag(
                    metrics,
                    "NPROC_NOT_MULTIPLE_OF_IMAGES",
                    "error",
                    f"nproc={nproc} is not a multiple of IMAGES={expected_images}",
                )

    endpoint_outcars_present = (
        (job_dir / "endpoint_initial_OUTCAR").exists()
        and (job_dir / "endpoint_final_OUTCAR").exists()
    ) or (
        (job_dir / "00" / "OUTCAR").exists()
        and bool(image_dirs)
        and (image_dirs[-1] / "OUTCAR").exists()
    )
    metrics["qc"]["endpoint_outcars_present"] = endpoint_outcars_present
    if not endpoint_outcars_present:
        severity = "error" if meta.get("vtst_mode") == "relax_first" else "warn"
        _add_flag(
            metrics,
            "ENDPOINT_OUTCAR_MISSING",
            severity,
            "Endpoint OUTCAR files were not found for both endpoints",
        )

    nelm = _safe_float(selected_tags.get("NELM"))
    image_entries = _load_images(image_dirs, neb_points, int(nelm) if nelm is not None else None)
    metrics["image_table"] = image_entries

    energies_rel = [
        entry["energy_rel_eV"] for entry in image_entries if entry.get("energy_rel_eV") is not None
    ]
    if energies_rel:
        baseline = min(energies_rel)
        shifted = [energy - baseline for energy in energies_rel]
        max_entry = max(
            (entry for entry in image_entries if entry.get("energy_rel_eV") is not None),
            key=lambda entry: entry["energy_rel_eV"],
        )
        metrics["barrier_summary"]["barrier_raw_eV"] = max(shifted)
        metrics["barrier_summary"]["ts_image_index"] = max_entry["image"]
        metrics["barrier_summary"]["ts_path_coordinate"] = max_entry.get("path_coordinate")
        metrics["barrier_summary"]["raw_max_path_coordinate"] = max_entry.get("path_coordinate")
        metrics["barrier_summary"]["path_monotonic"] = _monotonic(shifted)
        if metrics["barrier_summary"]["path_monotonic"]:
            _add_flag(
                metrics,
                "PATH_MONOTONIC",
                "warn",
                "Relative energy is monotonic along the path; this often indicates a non-bracketing path.",
            )
        if max_entry["image"] in {image_entries[0]["image"], image_entries[-1]["image"]}:
            _add_flag(
                metrics,
                "TS_AT_ENDPOINT",
                "warn",
                f"Maximum energy occurs at endpoint image {max_entry['image']}",
            )

    if spline_points:
        spline_y = [point["y"] for point in spline_points]
        spline_x = [point["x"] for point in spline_points]
        min_spline = min(spline_y)
        max_index = max(range(len(spline_points)), key=lambda index: spline_points[index]["y"])
        metrics["barrier_summary"]["barrier_spline_eV"] = max(spline_y) - min_spline
        metrics["barrier_summary"]["spline_max_path_coordinate"] = spline_x[max_index]

    if exts_points:
        metrics["barrier_summary"]["interpolated_extrema"] = [
            {"path_coordinate": point["x"], "energy_rel_eV": point["y"]} for point in exts_points
        ]
        highest_ext = max(exts_points, key=lambda point: point["y"])
        metrics["barrier_summary"]["spline_max_path_coordinate"] = highest_ext["x"]
        if metrics["barrier_summary"]["barrier_spline_eV"] is None:
            metrics["barrier_summary"]["barrier_spline_eV"] = highest_ext["y"] - min(
                point["y"] for point in exts_points
            )

    if not spline_points:
        _add_warning(metrics, "spline.dat was not found or had no parseable points")
    if not exts_points:
        _add_warning(metrics, "exts.dat was not found or had no parseable points")

    metrics["qc"]["finished_cleanly"] = bool(image_entries) and all(
        entry.get("finished_cleanly") for entry in image_entries
    )
    if not metrics["qc"]["finished_cleanly"]:
        failing = [entry["image"] for entry in image_entries if not entry.get("finished_cleanly")]
        _add_flag(
            metrics,
            "IMAGE_NOT_FINISHED",
            "error",
            f"Images without clean finish markers: {failing}",
        )

    for entry in image_entries:
        image_dir = job_dir / entry["directory"]
        outcar_path = image_dir / "OUTCAR"
        for code, severity, evidence in _scan_error_patterns(outcar_path):
            _add_flag(
                metrics,
                code,
                severity,
                f"Image {entry['image']} matched pattern '{evidence}' in {outcar_path.name}",
            )
        if entry.get("electronic_converged") is False:
            _add_flag(
                metrics,
                "IMAGE_ELECTRONIC_NOT_CONVERGED",
                "warn",
                f"Image {entry['image']} did not reach electronic convergence",
            )
        if (
            entry.get("max_force_eVA") is not None
            and entry["max_force_eVA"] > VASP_QC_FORCE_THRESHOLD
        ):
            _add_flag(
                metrics,
                "IMAGE_FORCE_HIGH",
                "warn",
                (
                    f"Image {entry['image']} max force {entry['max_force_eVA']:.4f} eV/A "
                    f"exceeds threshold {VASP_QC_FORCE_THRESHOLD:.4f} eV/A"
                ),
            )

    if energies_rel:
        median = float(np.median(energies_rel))
        deviations = [abs(value - median) for value in energies_rel]
        mad = float(np.median(deviations)) if deviations else 0.0
        if mad > 0:
            outliers = [
                entry["image"]
                for entry in image_entries
                if entry.get("energy_rel_eV") is not None
                and abs(entry["energy_rel_eV"] - median) > 5.0 * mad
            ]
            if outliers:
                _add_flag(
                    metrics,
                    "IMAGE_ENERGY_OUTLIER",
                    "warn",
                    f"Energy outlier images detected: {outliers}",
                )

    metrics["structure_change_summary"] = _structure_change_summary(metrics, image_entries)

    raw_x = [
        entry["path_coordinate"] if entry.get("path_coordinate") is not None else float(entry["image"])
        for entry in image_entries
        if entry.get("energy_rel_eV") is not None
    ]
    raw_y = [entry["energy_rel_eV"] for entry in image_entries if entry.get("energy_rel_eV") is not None]
    force_y = [
        entry["neb_force_eVA"] for entry in image_entries if entry.get("neb_force_eVA") is not None
    ]
    force_x = [
        entry["path_coordinate"] if entry.get("path_coordinate") is not None else float(entry["image"])
        for entry in image_entries
        if entry.get("neb_force_eVA") is not None
    ]

    metrics["artifacts"]["barrier_raw_png"] = _plot_series(
        plots_dir / "barrier_raw.png",
        raw_x,
        raw_y,
        title="Discrete NEB energy profile",
        xlabel="Reaction coordinate",
        ylabel="Relative energy (eV)",
    )
    metrics["artifacts"]["force_along_path_png"] = _plot_series(
        plots_dir / "force_along_path.png",
        force_x,
        force_y,
        title="NEB force along path",
        xlabel="Reaction coordinate",
        ylabel="NEB force (eV/A)",
    )

    if spline_points:
        spline_extra = [
            (point["x"], point["y"], f"ext {index + 1}")
            for index, point in enumerate(exts_points)
        ]
        metrics["artifacts"]["barrier_spline_png"] = _plot_series(
            plots_dir / "barrier_spline.png",
            [point["x"] for point in spline_points],
            [point["y"] for point in spline_points],
            title="Spline-interpolated NEB profile",
            xlabel="Reaction coordinate",
            ylabel="Relative energy (eV)",
            scatter=False,
            extra_points=spline_extra or None,
        )

    metrics["artifacts"]["image_energy_table_csv"] = _write_image_csv(
        image_entries, job_dir / "image_energy_table.csv"
    )
    try:
        metrics["artifacts"]["reaction_gif"] = _write_reaction_gif(
            plots_dir / "reaction_movie.gif",
            image_entries,
        )
    except Exception as exc:
        _add_warning(metrics, f"Failed to generate reaction_movie.gif: {exc}")
    try:
        metrics["artifacts"]["endpoint_vs_ts_png"] = _plot_endpoint_vs_ts(
            plots_dir / "endpoint_vs_ts.png",
            image_entries,
        )
    except Exception as exc:
        _add_warning(metrics, f"Failed to generate endpoint_vs_ts.png: {exc}")

    metrics["llm_payload"] = _build_llm_payload(metrics, job_dir, image_entries)

    for entry in metrics["image_table"]:
        entry.pop("_pmg_structure", None)
        entry.pop("_ase_atoms", None)

    download_files = [
        "vtst_metrics.json",
        "image_energy_table.csv",
        "neb.dat",
        "spline.dat",
        "exts.dat",
        "nebresults.txt",
        "POSCAR_initial",
        "POSCAR_final",
        "plots/barrier_raw.png",
        "plots/barrier_spline.png",
        "plots/force_along_path.png",
        "plots/reaction_movie.gif",
        "plots/endpoint_vs_ts.png",
        "endpoint_initial_vasp.out",
        "endpoint_initial_OUTCAR",
        "endpoint_initial_vasprun.xml",
        "endpoint_initial_vaspout.h5",
        "endpoint_final_vasp.out",
        "endpoint_final_OUTCAR",
        "endpoint_final_vasprun.xml",
        "endpoint_final_vaspout.h5",
        "vasp.out",
        "OUTCAR",
        "vasprun.xml",
        "vaspout.h5",
    ]
    metrics["download_files"] = [name for name in download_files if (job_dir / name).exists()]
    metrics_path = job_dir / VTST_METRICS_FILENAME
    metrics["metrics_path"] = str(metrics_path.resolve())
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return metrics
