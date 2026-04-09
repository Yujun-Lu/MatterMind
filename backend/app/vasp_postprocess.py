from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import (
    HDF5_METRICS_FILENAME,
    VASP_OPTIONAL_INPUTS,
    VASP_QC_FORCE_THRESHOLD,
    VASP_QC_STRESS_THRESHOLD_KBAR,
    VASP_REQUIRED_INPUTS,
)
from .storage import now_iso

FINISH_MARKERS = (
    "General timing and accounting informations for this job",
    "Voluntary context switches",
)

QC_RAW_OUTPUT_FILES: Tuple[str, ...] = (
    "vasprun.xml",
    "vasp.out",
    "OUTCAR",
    "vaspout.h5",
)

ERROR_PATTERNS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("VERY_BAD_NEWS", "error", ("VERY BAD NEWS",)),
    ("SEGMENTATION_FAULT", "error", ("segmentation fault",)),
    ("ZBRENT_ERROR", "error", ("ZBRENT",)),
    ("EDDDAV_FAILED", "error", ("EDDDAV",)),
    ("PSSYEV_ERROR", "error", ("PSSYEVX/PDSYEVX/PDHEEVX",)),
    ("BRMIX_WARNING", "warn", ("BRMIX",)),
    ("SUBSPACE_MATRIX", "warn", ("Sub-Space-Matrix is not hermitian",)),
    ("CNORMN_WARNING", "warn", ("CNORMN",)),
    ("RHOSYG_WARNING", "warn", ("RHOSYG",)),
    ("INTERNAL_ERROR", "error", ("internal error",)),
)


def _mark_degraded(metrics: Dict[str, Any]) -> None:
    metrics["status"] = "degraded"


def _add_warning(metrics: Dict[str, Any], message: str) -> None:
    metrics.setdefault("warnings", []).append(message)
    _mark_degraded(metrics)


def _add_flag(
    metrics: Dict[str, Any],
    code: str,
    severity: str,
    evidence: str,
) -> None:
    qc = metrics.setdefault("qc", {})
    flags = qc.setdefault("flags", [])
    entry = {"code": code, "severity": severity, "evidence": evidence}
    if entry not in flags:
        flags.append(entry)
    if severity in {"warn", "error"}:
        _mark_degraded(metrics)


def _safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _first_non_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _to_dict(obj: Any) -> Optional[Dict[str, Any]]:
    if obj is None:
        return None
    if hasattr(obj, "to_dict"):
        try:
            return obj.to_dict()
        except Exception:
            return None
    return None


def _to_array(value: Any) -> Optional[List[Any]]:
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    try:
        import numpy as np

        if isinstance(value, np.ndarray):
            return value.tolist()
    except Exception:
        pass
    return None


def _extract_energy_summary(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {"final_total": None, "final_free": None, "trace": None}
    if not data:
        return summary

    for key in ("free_energy", "free", "F"):
        if key in data:
            trace = _to_array(data.get(key))
            if trace:
                summary["final_free"] = _safe_float(trace[-1])
                summary["trace"] = trace
                break

    for key in ("total_energy", "energy", "E0", "e0"):
        if key in data:
            trace = _to_array(data.get(key))
            if trace:
                summary["final_total"] = _safe_float(trace[-1])
                if summary["trace"] is None:
                    summary["trace"] = trace
                break
    return summary


def _extract_energy_summary_from_vasprun(vasprun: Any) -> Dict[str, Any]:
    summary = {"final_total": None, "final_free": None, "trace": None}
    if vasprun is None:
        return summary

    summary["final_total"] = _safe_float(getattr(vasprun, "final_energy", None))

    ionic_steps = getattr(vasprun, "ionic_steps", None) or []
    total_trace: List[float] = []
    free_trace: List[float] = []
    for step in ionic_steps:
        if not isinstance(step, dict):
            continue
        total_value = _safe_float(
            _first_non_none(
                step.get("e_wo_entrp"),
                step.get("e_0_energy"),
                step.get("e_fr_energy"),
            )
        )
        free_value = _safe_float(
            _first_non_none(
                step.get("e_fr_energy"),
                step.get("e_0_energy"),
                step.get("e_wo_entrp"),
            )
        )
        if total_value is not None:
            total_trace.append(total_value)
        if free_value is not None:
            free_trace.append(free_value)

    if total_trace:
        summary["trace"] = total_trace
        if summary["final_total"] is None:
            summary["final_total"] = total_trace[-1]
    if free_trace:
        summary["final_free"] = free_trace[-1]

    return summary


def _forces_stats(forces: Optional[List[List[float]]]) -> Tuple[Optional[float], Optional[float]]:
    if not forces:
        return None, None
    norms: List[float] = []
    for vec in forces:
        if not isinstance(vec, (list, tuple)) or len(vec) < 3:
            continue
        norm = math.sqrt(vec[0] ** 2 + vec[1] ** 2 + vec[2] ** 2)
        norms.append(norm)
    if not norms:
        return None, None
    max_force = max(norms)
    rms_force = math.sqrt(sum(n * n for n in norms) / len(norms))
    return max_force, rms_force


def _extract_efermi(data: Optional[Dict[str, Any]]) -> Optional[float]:
    if not data:
        return None
    for key in ("efermi", "fermi_energy", "Efermi"):
        if key in data:
            return _safe_float(data.get(key))
    return None


def _extract_band_gap(data: Optional[Dict[str, Any]]) -> Optional[float]:
    if not data:
        return None
    for key in ("band_gap", "gap", "bandgap"):
        if key in data:
            return _safe_float(data.get(key))
    return None


def _extract_magnetism(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {"total_magnetization": None, "site_moments": None}
    if not data:
        return summary
    for key in ("total_magnetization", "total", "magnetization"):
        if key in data:
            summary["total_magnetization"] = _safe_float(data.get(key))
            break
    for key in ("site_moments", "site_magnetization", "moments", "magnetic_moments"):
        if key in data:
            summary["site_moments"] = _to_array(data.get(key))
            break
    return summary


def _structure_from_pymatgen(structure: Any) -> Optional[Dict[str, Any]]:
    try:
        return {
            "lattice_matrix": structure.lattice.matrix.tolist(),
            "atomic_species": [str(site.specie) for site in structure.sites],
            "fractional_positions": [
                list(map(float, site.frac_coords)) for site in structure.sites
            ],
            "volume": float(structure.lattice.volume),
            "num_atoms": len(structure),
        }
    except Exception:
        return None


def _structure_to_spglib_cell(structure: Any) -> Tuple[List[List[float]], List[List[float]], List[int]]:
    return (
        structure.lattice.matrix.tolist(),
        [list(map(float, site.frac_coords)) for site in structure.sites],
        [int(site.specie.Z) for site in structure.sites],
    )


def _lattice_delta(original: Any, standardized: Any) -> Dict[str, Any]:
    try:
        import numpy as np
    except Exception:
        np = None

    delta = {
        "volume_delta": None,
        "volume_ratio": None,
        "num_atoms_delta": None,
        "lattice_matrix_frobenius_delta": None,
    }
    try:
        delta["volume_delta"] = float(standardized.lattice.volume - original.lattice.volume)
        if original.lattice.volume:
            delta["volume_ratio"] = float(standardized.lattice.volume / original.lattice.volume)
        delta["num_atoms_delta"] = int(len(standardized) - len(original))
        if np is not None:
            matrix_delta = np.array(standardized.lattice.matrix) - np.array(original.lattice.matrix)
            delta["lattice_matrix_frobenius_delta"] = float(np.linalg.norm(matrix_delta))
    except Exception:
        pass
    return delta


def _extract_crystallography_summary(metrics: Dict[str, Any], structure: Any) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "spacegroup": None,
        "symmetry_dataset": None,
        "equivalent_atoms": None,
        "wyckoffs": None,
        "primitive_cell": None,
        "conventional_cell": None,
        "standardization_delta": {
            "primitive": None,
            "conventional": None,
        },
        "high_symmetry_path": None,
    }

    try:
        import spglib
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    except Exception as exc:
        _add_warning(metrics, f"crystallography tools unavailable: {exc}")
        return summary

    try:
        analyzer = SpacegroupAnalyzer(structure, symprec=1e-3, angle_tolerance=5.0)
        dataset = spglib.get_symmetry_dataset(_structure_to_spglib_cell(structure), symprec=1e-3)
        if dataset is not None:
            summary["spacegroup"] = {
                "number": int(dataset.number),
                "international": str(dataset.international),
                "hall": str(dataset.hall),
                "pointgroup": str(dataset.pointgroup),
                "choice": str(dataset.choice),
                "crystal_system": analyzer.get_crystal_system(),
            }
            summary["symmetry_dataset"] = {
                "number": int(dataset.number),
                "international": str(dataset.international),
                "hall": str(dataset.hall),
                "pointgroup": str(dataset.pointgroup),
                "choice": str(dataset.choice),
                "transformation_matrix": [
                    [float(value) for value in row] for row in dataset.transformation_matrix
                ],
                "origin_shift": [float(value) for value in dataset.origin_shift],
            }
            summary["equivalent_atoms"] = [int(value) for value in dataset.equivalent_atoms]
            summary["wyckoffs"] = [str(value) for value in dataset.wyckoffs]
    except Exception as exc:
        _add_warning(metrics, f"spglib symmetry dataset failed: {exc}")

    try:
        primitive = analyzer.get_primitive_standard_structure()
        if primitive is not None:
            summary["primitive_cell"] = _structure_from_pymatgen(primitive)
            summary["standardization_delta"]["primitive"] = _lattice_delta(structure, primitive)
    except Exception as exc:
        _add_warning(metrics, f"primitive cell standardization failed: {exc}")

    try:
        conventional = analyzer.get_conventional_standard_structure()
        if conventional is not None:
            summary["conventional_cell"] = _structure_from_pymatgen(conventional)
            summary["standardization_delta"]["conventional"] = _lattice_delta(structure, conventional)
    except Exception as exc:
        _add_warning(metrics, f"conventional cell standardization failed: {exc}")

    try:
        import seekpath

        path_data = seekpath.get_path(_structure_to_spglib_cell(structure), symprec=1e-3)
        summary["high_symmetry_path"] = {
            "spacegroup_number": int(path_data["spacegroup_number"]),
            "spacegroup_international": str(path_data["spacegroup_international"]),
            "bravais_lattice": str(path_data["bravais_lattice"]),
            "bravais_lattice_extended": str(path_data["bravais_lattice_extended"]),
            "point_coords": {
                str(key): [float(value) for value in values]
                for key, values in path_data["point_coords"].items()
            },
            "path": [[str(left), str(right)] for left, right in path_data["path"]],
            "primitive_lattice": [
                [float(value) for value in row] for row in path_data["primitive_lattice"]
            ],
            "reciprocal_primitive_lattice": [
                [float(value) for value in row]
                for row in path_data["reciprocal_primitive_lattice"]
            ],
            "primitive_positions": [
                [float(value) for value in row] for row in path_data["primitive_positions"]
            ],
            "primitive_types": [int(value) for value in path_data["primitive_types"]],
        }
    except Exception as exc:
        _add_warning(metrics, f"SeeK-path high-symmetry path failed: {exc}")

    return summary


def _save_plot(obj: Any, path: Path) -> bool:
    if obj is None or not hasattr(obj, "to_image"):
        return False
    try:
        obj.to_image(filename=str(path))
        return True
    except Exception:
        return False


def _plot_series(values: Optional[List[float]], path: Path, title: str, ylabel: str) -> bool:
    if not values:
        return False
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return False
    try:
        fig, ax = plt.subplots(figsize=(6, 3.5))
        ax.plot(range(1, len(values) + 1), values, marker="o", linewidth=1.8, color="#0f7b8f")
        ax.set_xlabel("Step")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(alpha=0.25)
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        return True
    except Exception:
        return False


def _plot_dos_fallback(vasprun: Any, path: Path) -> bool:
    if vasprun is None:
        return False
    try:
        import matplotlib.pyplot as plt
        from pymatgen.electronic_structure.plotter import DosPlotter
    except Exception:
        return False

    try:
        complete_dos = getattr(vasprun, "complete_dos", None)
        total_dos = getattr(vasprun, "tdos", None) or complete_dos
        if total_dos is None:
            return False

        plotter = DosPlotter(sigma=0.05)
        plotter.add_dos("Total DOS", total_dos)
        plotter.get_plot()
        plt.tight_layout()
        plt.savefig(path, dpi=150)
        plt.close("all")
        return True
    except Exception:
        return False


def _plot_band_structure_fallback(vasprun: Any, path: Path, line_mode: bool) -> bool:
    if vasprun is None or not line_mode:
        return False
    try:
        import matplotlib.pyplot as plt
        from pymatgen.electronic_structure.plotter import BSPlotter
    except Exception:
        return False

    try:
        band_structure = vasprun.get_band_structure(line_mode=True)
        if band_structure is None:
            return False
        plotter = BSPlotter(band_structure)
        plotter.get_plot()
        plt.tight_layout()
        plt.savefig(path, dpi=150)
        plt.close("all")
        return True
    except Exception:
        return False


def _plot_magnetism_bar(site_moments: List[float], path: Path) -> bool:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return False
    try:
        fig, ax = plt.subplots(figsize=(6, 3))
        ax.bar(range(len(site_moments)), site_moments, color="#ff8f4a")
        ax.set_xlabel("Site index")
        ax.set_ylabel("Magnetic moment")
        ax.set_title("Site magnetization")
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        return True
    except Exception:
        return False


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _contains_finish_marker(texts: List[str]) -> bool:
    for text in texts:
        for marker in FINISH_MARKERS:
            if marker in text:
                return True
    return False


def _find_pattern_evidence(text: str, keywords: Tuple[str, ...]) -> Optional[str]:
    lines = text.splitlines()
    lowered_keywords = tuple(keyword.lower() for keyword in keywords)
    for line in lines:
        lowered = line.lower()
        if any(keyword in lowered for keyword in lowered_keywords):
            return line.strip()[:240]
    return None


def _max_abs_tensor_component(tensor: Any) -> Optional[float]:
    values = _to_array(tensor)
    if not values:
        return None
    flat: List[float] = []
    for row in values:
        if isinstance(row, (list, tuple)):
            for value in row:
                number = _safe_float(value)
                if number is not None:
                    flat.append(abs(number))
    if not flat:
        return None
    return max(flat)


def _normalize_potcar_title(title: str) -> str:
    return " ".join(title.split()).strip().lower()


def _file_code(prefix: str, name: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
    return f"{prefix}_{normalized}"


def _read_potcar_titles(path: Path) -> List[str]:
    text = _read_text(path)
    titles: List[str] = []
    for match in re.finditer(r"TITEL\s*=\s*(.+)", text):
        titles.append(_normalize_potcar_title(match.group(1)))
    return titles


def _load_vasprun(metrics: Dict[str, Any], job_dir: Path) -> Any:
    vasprun_path = job_dir / "vasprun.xml"
    if not vasprun_path.exists():
        _add_flag(metrics, "MISSING_VASPRUN_XML", "warn", "vasprun.xml is missing")
        return None
    if vasprun_path.stat().st_size == 0:
        _add_flag(metrics, "EMPTY_VASPRUN_XML", "error", "vasprun.xml is empty")
        return None
    try:
        from pymatgen.io.vasp.outputs import Vasprun

        return Vasprun(str(vasprun_path))
    except Exception as exc:
        _add_flag(
            metrics,
            "CORRUPT_VASPRUN_XML",
            "error",
            f"failed to parse vasprun.xml: {exc}",
        )
        return None


def _parse_inputs(job_dir: Path) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {
        "incar": None,
        "kpoints": None,
        "poscar": None,
        "potcar_titles": [],
    }
    try:
        from pymatgen.io.vasp.inputs import Incar, Kpoints, Poscar
    except Exception:
        Incar = None
        Kpoints = None
        Poscar = None

    if Incar is not None:
        try:
            incar_path = job_dir / "INCAR"
            if incar_path.exists():
                parsed["incar"] = Incar.from_file(str(incar_path))
        except Exception:
            pass

    if Kpoints is not None:
        try:
            kpoints_path = job_dir / "KPOINTS"
            if kpoints_path.exists():
                parsed["kpoints"] = Kpoints.from_file(str(kpoints_path))
        except Exception:
            pass

    if Poscar is not None:
        try:
            poscar_path = job_dir / "POSCAR"
            if poscar_path.exists():
                parsed["poscar"] = Poscar.from_file(str(poscar_path))
        except Exception:
            pass

    potcar_path = job_dir / "POTCAR"
    if potcar_path.exists():
        parsed["potcar_titles"] = _read_potcar_titles(potcar_path)

    return parsed


def _run_qc(
    metrics: Dict[str, Any],
    job_dir: Path,
    hdf5_ready: bool,
    vasprun: Any,
    parsed_inputs: Dict[str, Any],
) -> None:
    qc = {
        "finished_cleanly": False,
        "hdf5_parsed": bool(hdf5_ready),
        "electronic_converged": None,
        "ionic_converged": None,
        "max_force_eVA": metrics.get("force_stress_summary", {}).get("max_force"),
        "max_stress_kbar": _max_abs_tensor_component(
            metrics.get("force_stress_summary", {}).get("stress_tensor")
        ),
        "force_threshold_eVA": VASP_QC_FORCE_THRESHOLD,
        "stress_threshold_kbar": VASP_QC_STRESS_THRESHOLD_KBAR,
        "flags": [],
    }
    metrics["qc"] = qc

    if not hdf5_ready:
        _add_flag(
            metrics,
            "HDF5_PARSE_UNAVAILABLE",
            "error",
            "py4vasp could not parse vaspout.h5",
        )

    for name in VASP_REQUIRED_INPUTS:
        path = job_dir / name
        if not path.exists():
            _add_flag(metrics, _file_code("MISSING", name), "error", f"{name} is missing")
        elif path.stat().st_size == 0:
            _add_flag(metrics, _file_code("EMPTY", name), "error", f"{name} is empty")

    for name in QC_RAW_OUTPUT_FILES:
        path = job_dir / name
        if not path.exists():
            _add_flag(metrics, _file_code("MISSING", name), "warn", f"{name} is missing")
        elif path.stat().st_size == 0:
            _add_flag(metrics, _file_code("EMPTY", name), "error", f"{name} is empty")

    texts = []
    for name in ("OUTCAR", "vasp.out", "job.log"):
        path = job_dir / name
        if path.exists():
            texts.append(_read_text(path))
    qc["finished_cleanly"] = _contains_finish_marker(texts)
    if not qc["finished_cleanly"]:
        _add_flag(
            metrics,
            "NOT_FINISHED_CLEANLY",
            "error",
            "missing standard VASP completion markers",
        )

    if vasprun is not None:
        qc["electronic_converged"] = bool(
            getattr(vasprun, "converged_electronic", False)
        )
        qc["ionic_converged"] = bool(getattr(vasprun, "converged_ionic", False))
        if qc["electronic_converged"] is False:
            _add_flag(
                metrics,
                "NELM_NOT_CONVERGED",
                "warn",
                "vasprun.xml reports unconverged electronic steps",
            )

    max_force = qc["max_force_eVA"]
    if max_force is not None and max_force > VASP_QC_FORCE_THRESHOLD:
        _add_flag(
            metrics,
            "MAX_FORCE_EXCEEDED",
            "warn",
            (
                f"max force {max_force:.4f} eV/A exceeds "
                f"{VASP_QC_FORCE_THRESHOLD:.4f} eV/A"
            ),
        )

    max_stress = qc["max_stress_kbar"]
    if max_stress is not None and max_stress > VASP_QC_STRESS_THRESHOLD_KBAR:
        _add_flag(
            metrics,
            "STRESS_EXCEEDED",
            "warn",
            (
                f"max stress component {max_stress:.4f} kbar exceeds "
                f"{VASP_QC_STRESS_THRESHOLD_KBAR:.4f} kbar"
            ),
        )

    combined_text = "\n".join(texts)
    for code, severity, keywords in ERROR_PATTERNS:
        evidence = _find_pattern_evidence(combined_text, keywords)
        if evidence:
            _add_flag(metrics, code, severity, evidence)

    incar = parsed_inputs.get("incar")
    kpoints = parsed_inputs.get("kpoints")
    poscar = parsed_inputs.get("poscar")
    potcar_titles = parsed_inputs.get("potcar_titles") or []

    if incar is not None:
        istart = incar.get("ISTART")
        if istart is not None and int(istart) > 0 and not (job_dir / "WAVECAR").exists():
            _add_flag(
                metrics,
                "MISSING_WAVECAR",
                "info",
                f"ISTART={istart} but WAVECAR is missing",
            )

        icharg = incar.get("ICHARG")
        if icharg is not None and int(icharg) in {1, 11} and not (job_dir / "CHGCAR").exists():
            _add_flag(
                metrics,
                "MISSING_CHGCAR",
                "info",
                f"ICHARG={icharg} but CHGCAR is missing",
            )

        if vasprun is not None:
            runtime_ispin = None
            try:
                runtime_ispin = int(vasprun.parameters.get("ISPIN"))
            except Exception:
                runtime_ispin = None
            input_ispin = incar.get("ISPIN")
            if input_ispin is not None and runtime_ispin is not None:
                if int(input_ispin) != runtime_ispin:
                    _add_flag(
                        metrics,
                        "ISPIN_MISMATCH",
                        "warn",
                        f"INCAR ISPIN={input_ispin} but output ISPIN={runtime_ispin}",
                    )

    if poscar is not None and metrics.get("inputs_summary", {}).get("num_atoms") is not None:
        input_atoms = len(poscar.structure)
        output_atoms = metrics["inputs_summary"]["num_atoms"]
        if input_atoms != output_atoms:
            _add_flag(
                metrics,
                "ATOM_COUNT_MISMATCH",
                "error",
                f"POSCAR atoms={input_atoms} but output atoms={output_atoms}",
            )
        input_species = Counter(str(site.specie) for site in poscar.structure.sites)
        output_species = Counter(metrics.get("structure_summary", {}).get("atomic_species") or [])
        if output_species and input_species != output_species:
            _add_flag(
                metrics,
                "SPECIES_MISMATCH",
                "warn",
                f"POSCAR species={dict(input_species)} output species={dict(output_species)}",
            )

    if kpoints is not None and vasprun is not None:
        try:
            actual_kpoints = getattr(vasprun, "actual_kpoints", None)
            if not actual_kpoints:
                _add_flag(
                    metrics,
                    "KPOINTS_OUTPUT_MISSING",
                    "warn",
                    "KPOINTS input exists but no actual k-points were parsed from output",
                )
        except Exception:
            _add_flag(
                metrics,
                "KPOINTS_PARSE_UNAVAILABLE",
                "info",
                "could not verify output k-points against input",
            )

    if potcar_titles and vasprun is not None:
        output_titles: List[str] = []
        try:
            for item in getattr(vasprun, "potcar_spec", []) or []:
                if isinstance(item, dict):
                    title = item.get("titel") or item.get("title")
                else:
                    title = str(item)
                if title:
                    output_titles.append(_normalize_potcar_title(title))
        except Exception:
            output_titles = []
        if output_titles and output_titles != potcar_titles:
            _add_flag(
                metrics,
                "POTCAR_MISMATCH",
                "warn",
                f"input POTCAR titles={potcar_titles} output POTCAR titles={output_titles}",
            )

    if incar is not None and int(incar.get("ISPIN", 1)) == 2:
        has_magnetism = metrics.get("electronic_summary", {}).get("total_magnetization")
        if has_magnetism is None:
            _add_flag(
                metrics,
                "MAGNETISM_OUTPUT_MISSING",
                "info",
                "ISPIN=2 but total magnetization was not extracted",
            )


def _sum_dos_density(dos: Any) -> Tuple[Optional[List[float]], Optional[List[float]]]:
    if dos is None:
        return None, None
    energies = getattr(dos, "energies", None)
    densities = getattr(dos, "densities", None)
    if energies is None or densities is None:
        return None, None
    energy_list = [float(value) for value in energies]
    total_density = [0.0 for _ in energy_list]
    try:
        for spin_density in densities.values():
            for index, value in enumerate(spin_density):
                total_density[index] += float(value)
    except Exception:
        return None, None
    return energy_list, total_density


def _top_dos_peaks(dos: Any, limit: int = 5) -> List[Dict[str, float]]:
    energies, total_density = _sum_dos_density(dos)
    if not energies or not total_density or len(energies) < 3:
        return []
    peaks: List[Dict[str, float]] = []
    for index in range(1, len(energies) - 1):
        left = total_density[index - 1]
        center = total_density[index]
        right = total_density[index + 1]
        if center >= left and center >= right:
            peaks.append(
                {"energy": float(energies[index]), "height": float(center)}
            )
    peaks.sort(key=lambda item: item["height"], reverse=True)
    deduped: List[Dict[str, float]] = []
    for peak in peaks:
        if any(abs(existing["energy"] - peak["energy"]) < 0.15 for existing in deduped):
            continue
        deduped.append(peak)
        if len(deduped) >= limit:
            break
    return deduped


def _dos_contributions_near_fermi(complete_dos: Any, efermi: Optional[float]) -> Dict[str, Any]:
    if complete_dos is None or efermi is None:
        return {"elements": [], "orbitals": []}
    window = 0.5

    def integrate(dos: Any) -> Optional[float]:
        energies, densities = _sum_dos_density(dos)
        if not energies or not densities:
            return None
        total = 0.0
        for energy, density in zip(energies, densities):
            if abs(energy - efermi) <= window:
                total += density
        return total

    element_scores: List[Dict[str, Any]] = []
    orbital_scores: List[Dict[str, Any]] = []

    try:
        for element, dos in (complete_dos.get_element_dos() or {}).items():
            value = integrate(dos)
            if value is not None:
                element_scores.append({"label": str(element), "weight": float(value)})
    except Exception:
        pass

    try:
        for orbital, dos in (complete_dos.get_spd_dos() or {}).items():
            value = integrate(dos)
            if value is not None:
                orbital_scores.append({"label": str(orbital), "weight": float(value)})
    except Exception:
        pass

    element_scores.sort(key=lambda item: item["weight"], reverse=True)
    orbital_scores.sort(key=lambda item: item["weight"], reverse=True)
    return {
        "elements": element_scores[:5],
        "orbitals": orbital_scores[:5],
        "window_eV": window,
    }


def _format_kpoint(kpoint: Any) -> Optional[Dict[str, Any]]:
    if not kpoint:
        return None
    coords = getattr(kpoint, "frac_coords", None)
    if coords is None:
        coords = getattr(kpoint, "cart_coords", None)
    label = getattr(kpoint, "label", None)
    return {
        "label": str(label) if label is not None else None,
        "coords": [float(value) for value in coords] if coords is not None else None,
    }


def _run_postprocess_plugins(
    metrics: Dict[str, Any],
    job_dir: Path,
    structure: Any,
    vasprun: Any,
    parsed_inputs: Dict[str, Any],
) -> None:
    incar = parsed_inputs.get("incar")
    kpoints = parsed_inputs.get("kpoints")

    nsw = int(incar.get("NSW", 0)) if incar is not None and incar.get("NSW") is not None else 0
    ibrion = (
        int(incar.get("IBRION", -1))
        if incar is not None and incar.get("IBRION") is not None
        else -1
    )
    is_line_mode = bool(getattr(kpoints, "style", None) and "line" in str(kpoints.style).lower())

    plugin_results: Dict[str, Any] = {}
    active_plugins: List[str] = []

    if structure is not None:
        static_type = "relax" if nsw > 0 and ibrion != 0 else "single_point"
        if nsw == 0:
            static_type = "static"
        plugin_results["static_relax"] = {
            "task_variant": static_type,
            "final_total_energy": metrics.get("energy_summary", {}).get("final_total"),
            "final_free_energy": metrics.get("energy_summary", {}).get("final_free"),
            "volume": metrics.get("structure_summary", {}).get("volume"),
            "density_g_cm3": _safe_float(getattr(structure.density, "real", structure.density)),
            "num_atoms": metrics.get("structure_summary", {}).get("num_atoms"),
            "max_force_eVA": metrics.get("force_stress_summary", {}).get("max_force"),
            "rms_force_eVA": metrics.get("force_stress_summary", {}).get("rms_force"),
            "stress_tensor_kbar": metrics.get("force_stress_summary", {}).get("stress_tensor"),
            "total_magnetization": metrics.get("electronic_summary", {}).get("total_magnetization"),
            "site_moments": metrics.get("electronic_summary", {}).get("site_moments"),
            "efermi": metrics.get("electronic_summary", {}).get("efermi"),
        }
        active_plugins.append("static_relax")

    band_dos_available = bool(vasprun is not None and (is_line_mode or getattr(vasprun, "complete_dos", None) is not None))
    if band_dos_available:
        band_dos_summary: Dict[str, Any] = {
            "available": True,
            "band_gap": None,
            "is_direct_gap": None,
            "vbm": None,
            "cbm": None,
            "fermi_nearby_contributions": {"elements": [], "orbitals": []},
            "dos_peaks": [],
            "artifacts": {
                "band_plot": metrics.get("artifacts", {}).get("plots", {}).get("band"),
                "dos_plot": metrics.get("artifacts", {}).get("plots", {}).get("dos"),
            },
        }

        complete_dos = getattr(vasprun, "complete_dos", None)
        tdos = getattr(vasprun, "tdos", None) or complete_dos
        band_dos_summary["dos_peaks"] = _top_dos_peaks(tdos)
        band_dos_summary["fermi_nearby_contributions"] = _dos_contributions_near_fermi(
            complete_dos,
            metrics.get("electronic_summary", {}).get("efermi"),
        )

        try:
            band_structure = vasprun.get_band_structure(line_mode=is_line_mode)
        except Exception:
            band_structure = None

        if band_structure is not None:
            try:
                gap_info = band_structure.get_band_gap()
                band_dos_summary["band_gap"] = _safe_float(gap_info.get("energy"))
                band_dos_summary["is_direct_gap"] = bool(gap_info.get("direct"))
                band_dos_summary["transition"] = gap_info.get("transition")
            except Exception:
                pass
            try:
                band_dos_summary["vbm"] = {
                    "energy": _safe_float(band_structure.get_vbm().get("energy")),
                    "kpoint": _format_kpoint(band_structure.get_vbm().get("kpoint")),
                    "band_indices": {
                        str(spin): [int(value) for value in indices]
                        for spin, indices in (band_structure.get_vbm().get("band_index") or {}).items()
                    },
                }
            except Exception:
                pass
            try:
                band_dos_summary["cbm"] = {
                    "energy": _safe_float(band_structure.get_cbm().get("energy")),
                    "kpoint": _format_kpoint(band_structure.get_cbm().get("kpoint")),
                    "band_indices": {
                        str(spin): [int(value) for value in indices]
                        for spin, indices in (band_structure.get_cbm().get("band_index") or {}).items()
                    },
                }
            except Exception:
                pass

        plugin_results["band_dos"] = band_dos_summary
        active_plugins.append("band_dos")

    plugin_results["phonon"] = {
        "implemented": False,
        "detected_inputs": [
            name
            for name in ("phonopy.yaml", "phonopy_disp.yaml", "FORCE_SETS", "FORCE_CONSTANTS", "band.yaml")
            if (job_dir / name).exists()
        ],
    }
    plugin_results["bonding_charge"] = {
        "implemented": False,
        "detected_inputs": [
            name
            for name in ("ACF.dat", "BCF.dat", "COHPCAR.lobster", "ICOHPLIST.lobster")
            if (job_dir / name).exists()
        ],
    }
    plugin_results["transport"] = {
        "implemented": False,
        "detected_inputs": [
            name
            for name in ("boltztrap.out", "boltztrap.json", "boltztrap.h5")
            if (job_dir / name).exists()
        ],
    }
    plugin_results["wannier_topology"] = {
        "implemented": False,
        "detected_inputs": [
            name
            for name in ("wannier90.win", "wannier90.wout", "wannier90_hr.dat")
            if (job_dir / name).exists()
        ],
    }
    plugin_results["visualization"] = {
        "implemented": False,
        "available_artifacts": metrics.get("artifacts", {}).get("plots", {}),
    }

    primary_task_type = "static"
    if nsw > 0 and ibrion != 0:
        primary_task_type = "relax"
    if is_line_mode:
        primary_task_type = "band"
    if plugin_results["phonon"]["detected_inputs"]:
        primary_task_type = "phonon"
    if plugin_results["wannier_topology"]["detected_inputs"]:
        primary_task_type = "wannier"

    metrics["postprocess"] = {
        "primary_task_type": primary_task_type,
        "active_plugins": active_plugins,
        "plugin_results": plugin_results,
    }


def postprocess_vasp(job_id: str, job_dir: Path) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {
        "version": "0.2",
        "status": "ok",
        "meta": {
            "task_id": job_id,
            "workdir": str(job_dir),
            "parser": "py4vasp",
            "source_file": "vaspout.h5",
            "generated_at": now_iso(),
        },
        "inputs_summary": {
            "system_name": None,
            "num_atoms": None,
            "hdf5_used": False,
        },
        "structure_summary": {},
        "crystallography_summary": {},
        "energy_summary": {},
        "force_stress_summary": {},
        "electronic_summary": {},
        "artifacts": {"plots": {}, "raw_files": []},
        "qc_placeholders": [],
        "qc": {},
        "warnings": [],
    }

    vaspout_path = job_dir / "vaspout.h5"
    metrics["artifacts"]["raw_files"].append(str(vaspout_path))
    for name in (*VASP_REQUIRED_INPUTS, *VASP_OPTIONAL_INPUTS, "job.log"):
        path = job_dir / name
        if path.exists():
            metrics["artifacts"]["raw_files"].append(str(path))
    for name in QC_RAW_OUTPUT_FILES:
        path = job_dir / name
        if path.exists():
            metrics["artifacts"]["raw_files"].append(str(path))

    calc = None
    hdf5_ready = False
    pmg_structure = None
    parsed_inputs = _parse_inputs(job_dir)
    vasprun = _load_vasprun(metrics, job_dir)
    if not vaspout_path.exists():
        _add_warning(metrics, "vaspout.h5 not found")
    else:
        metrics["inputs_summary"]["hdf5_used"] = True
        try:
            from py4vasp import Calculation

            calc = Calculation.from_file(str(vaspout_path))
            hdf5_ready = True
        except Exception as exc:
            _add_warning(metrics, f"py4vasp parse failed: {exc}")

    if calc is not None:
        try:
            structure_obj = getattr(calc, "structure", None)
            for method in ("to_pymatgen", "to_structure", "to_pymatgen_structure"):
                if structure_obj is not None and hasattr(structure_obj, method):
                    try:
                        pmg_structure = getattr(structure_obj, method)()
                        break
                    except Exception:
                        pmg_structure = None
            if pmg_structure is None and vasprun is not None:
                pmg_structure = _first_non_none(
                    getattr(vasprun, "final_structure", None),
                    getattr(vasprun, "initial_structure", None),
                )
            if pmg_structure is not None:
                metrics["structure_summary"] = _structure_from_pymatgen(pmg_structure) or {}
                metrics["inputs_summary"]["num_atoms"] = len(pmg_structure)
                metrics["inputs_summary"]["system_name"] = (
                    pmg_structure.composition.reduced_formula
                )
            else:
                data = _to_dict(structure_obj) or {}
                lattice = _first_non_none(data.get("lattice"), data.get("lattice_vectors"))
                species = _first_non_none(data.get("species"), data.get("atoms"))
                positions = _first_non_none(
                    data.get("positions"),
                    data.get("fractional_positions"),
                )
                metrics["structure_summary"] = {
                    "lattice_matrix": _to_array(lattice),
                    "atomic_species": species,
                    "fractional_positions": _to_array(positions),
                    "volume": _safe_float(data.get("volume")),
                }
                metrics["inputs_summary"]["num_atoms"] = data.get("num_atoms")
                metrics["inputs_summary"]["system_name"] = data.get("system_name")
            if pmg_structure is not None:
                metrics["crystallography_summary"] = _extract_crystallography_summary(
                    metrics, pmg_structure
                )
        except Exception as exc:
            _add_warning(metrics, f"structure parse failed: {exc}")

        try:
            energy_obj = getattr(calc, "energy", None)
            energy_data = _to_dict(energy_obj)
            metrics["energy_summary"] = _extract_energy_summary(energy_data)
            fallback_energy = _extract_energy_summary_from_vasprun(vasprun)
            if metrics["energy_summary"].get("final_total") is None:
                metrics["energy_summary"]["final_total"] = fallback_energy.get("final_total")
            if metrics["energy_summary"].get("final_free") is None:
                metrics["energy_summary"]["final_free"] = fallback_energy.get("final_free")
            if metrics["energy_summary"].get("trace") is None:
                metrics["energy_summary"]["trace"] = fallback_energy.get("trace")
        except Exception as exc:
            _add_warning(metrics, f"energy parse failed: {exc}")

        try:
            forces_obj = getattr(calc, "forces", None) or getattr(calc, "force", None)
            forces_data = _to_dict(forces_obj) or {}
            forces = None
            for key in ("forces", "force", "values"):
                if key in forces_data:
                    forces = _to_array(forces_data.get(key))
                    break
            max_force, rms_force = _forces_stats(forces)

            stress_obj = getattr(calc, "stress", None)
            stress_data = _to_dict(stress_obj) or {}
            stress_tensor = None
            for key in ("stress", "tensor", "values"):
                if key in stress_data:
                    stress_tensor = _to_array(stress_data.get(key))
                    break

            metrics["force_stress_summary"] = {
                "max_force": max_force,
                "rms_force": rms_force,
                "stress_tensor": stress_tensor,
                "stress_unit": "kbar",
            }
        except Exception as exc:
            _add_warning(metrics, f"force/stress parse failed: {exc}")

        magnetism_data = None
        try:
            dos_obj = getattr(calc, "dos", None)
            band_obj = getattr(calc, "band", None)
            magnetism_obj = getattr(calc, "magnetism", None)
            dos_data = _to_dict(dos_obj)
            band_data = _to_dict(band_obj)
            magnetism_data = _to_dict(magnetism_obj)

            electronic_summary = {
                "efermi": _extract_efermi(dos_data) or _extract_efermi(band_data),
                "total_magnetization": _extract_magnetism(magnetism_data).get(
                    "total_magnetization"
                ),
                "band_gap": _extract_band_gap(band_data)
                or _extract_band_gap(dos_data),
            }
            site_moments = _extract_magnetism(magnetism_data).get("site_moments")
            if site_moments is not None:
                electronic_summary["site_moments"] = site_moments
            metrics["electronic_summary"] = electronic_summary
        except Exception as exc:
            _add_warning(metrics, f"electronic parse failed: {exc}")

        plots_dir = job_dir / "plots"
        plots_dir.mkdir(parents=True, exist_ok=True)
        kpoints = parsed_inputs.get("kpoints")
        is_line_mode = bool(
            getattr(kpoints, "style", None) and "line" in str(kpoints.style).lower()
        )

        def register_plot(key: str, filename: str, obj: Any) -> None:
            path = plots_dir / filename
            if _save_plot(obj, path):
                metrics["artifacts"]["plots"][key] = str(path)

        try:
            register_plot("energy", "energy.png", getattr(calc, "energy", None))
            register_plot("dos", "dos.png", getattr(calc, "dos", None))
            register_plot("band", "band.png", getattr(calc, "band", None))
            register_plot("phonon_dos", "phonon_dos.png", getattr(calc, "phonon_dos", None))
            register_plot(
                "phonon_band",
                "phonon_band.png",
                getattr(calc, "phonon_band", None),
            )
            magnetism_obj = getattr(calc, "magnetism", None)
            magnetism_path = plots_dir / "magnetism.png"
            if _save_plot(magnetism_obj, magnetism_path):
                metrics["artifacts"]["plots"]["magnetism"] = str(magnetism_path)
            else:
                site_moments = metrics.get("electronic_summary", {}).get("site_moments")
                if site_moments and _plot_magnetism_bar(site_moments, magnetism_path):
                    metrics["artifacts"]["plots"]["magnetism"] = str(magnetism_path)
        except Exception as exc:
            _add_warning(metrics, f"plot generation failed: {exc}")

        if "energy" not in metrics["artifacts"]["plots"]:
            energy_path = plots_dir / "energy.png"
            if _plot_series(
                metrics.get("energy_summary", {}).get("trace"),
                energy_path,
                "Energy trace",
                "Energy (eV)",
            ):
                metrics["artifacts"]["plots"]["energy"] = str(energy_path)

        if "dos" not in metrics["artifacts"]["plots"]:
            dos_path = plots_dir / "dos.png"
            if _plot_dos_fallback(vasprun, dos_path):
                metrics["artifacts"]["plots"]["dos"] = str(dos_path)

        if "band" not in metrics["artifacts"]["plots"]:
            band_path = plots_dir / "band.png"
            if _plot_band_structure_fallback(vasprun, band_path, is_line_mode):
                metrics["artifacts"]["plots"]["band"] = str(band_path)

    _run_qc(
        metrics,
        job_dir,
        hdf5_ready=hdf5_ready,
        vasprun=vasprun,
        parsed_inputs=parsed_inputs,
    )
    _run_postprocess_plugins(
        metrics,
        job_dir,
        structure=pmg_structure,
        vasprun=vasprun,
        parsed_inputs=parsed_inputs,
    )
    metrics["download_files"] = [
        name
        for name in [
            "vasprun.xml",
            "vasp.out",
            "OUTCAR",
            "vaspout.h5",
            HDF5_METRICS_FILENAME,
            "plots/energy.png",
            "plots/dos.png",
            "plots/band.png",
            "plots/phonon_dos.png",
            "plots/phonon_band.png",
            "plots/magnetism.png",
        ]
        if (job_dir / name).exists()
    ]
    _write_metrics(job_dir, metrics)
    return metrics


def _write_metrics(job_dir: Path, metrics: Dict[str, Any]) -> None:
    path = job_dir / HDF5_METRICS_FILENAME
    with path.open("w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
