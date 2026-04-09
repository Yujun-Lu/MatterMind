from __future__ import annotations

import csv
import hashlib
import io
import importlib.metadata
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import METRICS_FILENAME
from .storage import now_iso, read_meta


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


SYMPREC_DEFAULT = _float_env("SYMPREC", 1e-2)
CLOSE_CONTACT_THRESHOLD = _float_env("MIN_DISTANCE_THRESHOLD", 1.5)
DEDUP_LTOL = _float_env("DEDUP_LTOL", 0.2)
DEDUP_STOL = _float_env("DEDUP_STOL", 0.3)
DEDUP_ANGLE_TOL = _float_env("DEDUP_ANGLE_TOL", 5.0)
MAGPIE_MAX_FEATURES = _int_env("MAGPIE_MAX_FEATURES", 30)
SOAP_R_CUT = _float_env("SOAP_R_CUT", 5.0)
SOAP_N_MAX = _int_env("SOAP_N_MAX", 6)
SOAP_L_MAX = _int_env("SOAP_L_MAX", 4)
SOAP_SIGMA = _float_env("SOAP_SIGMA", 0.5)
SOAP_AVERAGE = os.getenv("SOAP_AVERAGE", "inner")
OVITO_IMG_WIDTH = _int_env("OVITO_IMG_WIDTH", 1024)
OVITO_IMG_HEIGHT = _int_env("OVITO_IMG_HEIGHT", 768)


def _flag_degraded(metrics: Dict[str, Any]) -> None:
    metrics["status"] = "degraded"


def _add_warning(metrics: Dict[str, Any], message: str) -> None:
    metrics.setdefault("warnings", []).append(message)
    _flag_degraded(metrics)


def _add_structure_warning(
    metrics: Dict[str, Any], entry: Dict[str, Any], message: str
) -> None:
    entry.setdefault("warnings", []).append(message)
    _flag_degraded(metrics)


def _write_metrics(job_dir: Path, metrics: Dict[str, Any]) -> None:
    path = job_dir / METRICS_FILENAME
    with path.open("w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)


def _safe_version(module: Any) -> Optional[str]:
    version = getattr(module, "__version__", None)
    if version:
        return str(version)

    module_name = getattr(module, "__name__", None)
    if not module_name:
        return None

    candidates = [module_name]
    if "." in module_name:
        candidates.append(module_name.split(".", 1)[0])

    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            return importlib.metadata.version(candidate)
        except importlib.metadata.PackageNotFoundError:
            continue
        except Exception:
            continue

    return None


def _safe_number(value: Any) -> Any:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _dataset_value(dataset: Any, key: str) -> Any:
    if dataset is None:
        return None
    if isinstance(dataset, dict):
        return dataset.get(key)
    return getattr(dataset, key, None)


def _compute_min_distance(
    structure: Any,
    threshold: float,
) -> Tuple[Optional[float], Optional[Dict[str, Any]], Optional[int]]:
    n = len(structure)
    if n < 2:
        return None, None, None

    dist = structure.distance_matrix
    min_value = None
    min_pair = None

    num_close = 0
    for i in range(n):
        for j in range(i + 1, n):
            value = float(dist[i][j])
            if value < threshold:
                num_close += 1
            if min_value is None or value < min_value:
                min_value = value
                el_i = str(structure[i].specie)
                el_j = str(structure[j].specie)
                min_pair = {
                    "elements": [el_i, el_j],
                    "pair": "-".join(sorted([el_i, el_j])),
                    "indices": [i, j],
                }

    return min_value, min_pair, num_close


def postprocess_job(
    job_id: str,
    job_dir: Path,
    ltol: Optional[float] = None,
    stol: Optional[float] = None,
    angle_tol: Optional[float] = None,
) -> Dict[str, Any]:
    extxyz_path = job_dir / "generated_crystals.extxyz"

    meta = read_meta(job_id)

    ltol_value = DEDUP_LTOL if ltol is None else float(ltol)
    stol_value = DEDUP_STOL if stol is None else float(stol)
    angle_tol_value = DEDUP_ANGLE_TOL if angle_tol is None else float(angle_tol)

    metrics: Dict[str, Any] = {
        "version": "0.4",
        "job_id": job_id,
        "status": "ok",
        "timestamps": {
            "created_at": meta.get("created_at"),
            "started_at": meta.get("started_at"),
            "finished_at": meta.get("finished_at"),
            "generated_at": now_iso(),
        },
        "tool_versions": {},
        "source": {
            "path": str(extxyz_path),
            "sha256": None,
            "frames": 0,
        },
        "dedup_summary": {
            "num_groups": None,
            "mapping": {},
            "ltol": ltol_value,
            "stol": stol_value,
            "angle_tol": angle_tol_value,
        },
        "structures": [],
        "warnings": [],
    }

    if not extxyz_path.exists():
        _add_warning(metrics, f"missing extxyz file: {extxyz_path}")
        _write_metrics(job_dir, metrics)
        return metrics

    try:
        from ase.io import read as ase_read
        import ase

        metrics["tool_versions"]["ase"] = _safe_version(ase)
    except Exception as exc:  # pragma: no cover - optional dependency
        _add_warning(metrics, f"ASE not available: {exc}")
        _write_metrics(job_dir, metrics)
        return metrics

    try:
        extxyz_bytes = extxyz_path.read_bytes()
        metrics["source"]["sha256"] = hashlib.sha256(extxyz_bytes).hexdigest()
        extxyz_text = extxyz_bytes.decode("utf-8", errors="replace")
        frames = ase_read(io.StringIO(extxyz_text), index=":", format="extxyz")
    except Exception as exc:
        _add_warning(metrics, f"failed to read extxyz: {exc}")
        _write_metrics(job_dir, metrics)
        return metrics

    if not isinstance(frames, list):
        frames = [frames]

    metrics["source"]["frames"] = len(frames)

    try:
        from pymatgen.io.ase import AseAtomsAdaptor
        import pymatgen

        metrics["tool_versions"]["pymatgen"] = _safe_version(pymatgen)
    except Exception as exc:  # pragma: no cover - optional dependency
        _add_warning(metrics, f"pymatgen not available: {exc}")
        _write_metrics(job_dir, metrics)
        return metrics

    try:
        import spglib

        metrics["tool_versions"]["spglib"] = _safe_version(spglib)
    except Exception as exc:  # pragma: no cover - optional dependency
        spglib = None
        _add_warning(metrics, f"spglib not available: {exc}")

    adaptor = AseAtomsAdaptor()
    structures_by_index: List[Optional[Any]] = []
    atoms_by_index: List[Optional[Any]] = []

    for idx, atoms in enumerate(frames):
        entry: Dict[str, Any] = {
            "index": idx,
            "natoms": None,
            "elements_count": None,
            "reduced_formula": None,
            "lattice": None,
            "pbc": None,
            "geometry": None,
            "symmetry": None,
            "cif": None,
            "dedup": {"group_id": None, "group_size": None},
            "features": {"magpie": None},
            "soap_summary": None,
            "render": {"png": None},
            "warnings": [],
        }

        try:
            atoms = atoms.copy()
            atoms.pbc = (True, True, True)
            entry["natoms"] = len(atoms)
            entry["pbc"] = [True, True, True]
        except Exception as exc:
            _add_structure_warning(metrics, entry, f"ASE frame {idx} error: {exc}")
            metrics["structures"].append(entry)
            structures_by_index.append(None)
            atoms_by_index.append(None)
            continue

        try:
            structure = adaptor.get_structure(atoms)
        except Exception as exc:
            _add_structure_warning(
                metrics, entry, f"pymatgen conversion failed on frame {idx}: {exc}"
            )
            metrics["structures"].append(entry)
            structures_by_index.append(None)
            atoms_by_index.append(None)
            continue

        try:
            composition = structure.composition
            entry["elements_count"] = composition.get_el_amt_dict()
            entry["reduced_formula"] = composition.reduced_formula
        except Exception as exc:
            _add_structure_warning(metrics, entry, f"composition failed: {exc}")

        try:
            lattice = structure.lattice
            entry["lattice"] = {
                "a": lattice.a,
                "b": lattice.b,
                "c": lattice.c,
                "alpha": lattice.alpha,
                "beta": lattice.beta,
                "gamma": lattice.gamma,
                "volume": lattice.volume,
            }
        except Exception as exc:
            _add_structure_warning(metrics, entry, f"lattice failed: {exc}")

        try:
            min_dist, min_pair, num_close = _compute_min_distance(
                structure, CLOSE_CONTACT_THRESHOLD
            )
            entry["geometry"] = {
                "min_distance": min_dist,
                "min_distance_pair": min_pair,
                "num_close_contacts": num_close,
                "close_contact_threshold": CLOSE_CONTACT_THRESHOLD,
                "unit": "angstrom",
            }
        except Exception as exc:
            _add_structure_warning(metrics, entry, f"geometry failed: {exc}")

        if spglib is not None:
            try:
                cell = (
                    structure.lattice.matrix,
                    structure.frac_coords,
                    structure.atomic_numbers,
                )
                dataset = spglib.get_symmetry_dataset(cell, symprec=SYMPREC_DEFAULT)
                entry["symmetry"] = {
                    "number": _dataset_value(dataset, "number"),
                    "international": _dataset_value(dataset, "international"),
                    "hall": _dataset_value(dataset, "hall"),
                    "symprec": SYMPREC_DEFAULT,
                }
            except Exception as exc:
                _add_structure_warning(metrics, entry, f"symmetry failed: {exc}")
        else:
            entry["symmetry"] = {"symprec": SYMPREC_DEFAULT}

        try:
            cif_path = job_dir / f"gen_{idx}.cif"
            structure.to(filename=str(cif_path))
            entry["cif"] = str(cif_path)
        except Exception as exc:
            _add_structure_warning(metrics, entry, f"cif write failed: {exc}")

        metrics["structures"].append(entry)
        structures_by_index.append(structure)
        atoms_by_index.append(atoms)

    try:
        from pymatgen.analysis.structure_matcher import StructureMatcher
    except Exception as exc:  # pragma: no cover - optional dependency
        StructureMatcher = None
        _add_warning(metrics, f"StructureMatcher not available: {exc}")

    if StructureMatcher is not None:
        valid_indices = [i for i, s in enumerate(structures_by_index) if s is not None]
        valid_structures = [
            s for s in structures_by_index if s is not None
        ]

        if valid_structures:
            matcher = StructureMatcher(
                ltol=ltol_value,
                stol=stol_value,
                angle_tol=angle_tol_value,
            )
            groups = matcher.group_structures(valid_structures)
            metrics["dedup_summary"]["num_groups"] = len(groups)

            id_to_index = {
                id(structure): idx
                for idx, structure in zip(valid_indices, valid_structures)
            }
            mapping: Dict[str, int] = {}

            for group_id, group in enumerate(groups):
                group_size = len(group)
                for struct in group:
                    idx = id_to_index.get(id(struct))
                    if idx is None:
                        _add_warning(
                            metrics,
                            f"dedup mapping failed for group {group_id}",
                        )
                        continue
                    mapping[str(idx)] = group_id
                    metrics["structures"][idx]["dedup"] = {
                        "group_id": group_id,
                        "group_size": group_size,
                    }

            for idx in valid_indices:
                if str(idx) not in mapping:
                    _add_structure_warning(
                        metrics,
                        metrics["structures"][idx],
                        "dedup mapping missing for structure",
                    )
                    metrics["structures"][idx]["dedup"] = {
                        "group_id": None,
                        "group_size": None,
                    }

            metrics["dedup_summary"]["mapping"] = mapping
        else:
            metrics["dedup_summary"]["num_groups"] = 0
    else:
        for idx, struct in enumerate(structures_by_index):
            if struct is None:
                continue
            metrics["structures"][idx]["dedup"] = {
                "group_id": None,
                "group_size": None,
            }

    try:
        from matminer.featurizers.composition import ElementProperty
        import matminer

        metrics["tool_versions"]["matminer"] = _safe_version(matminer)
        magpie_featurizer = ElementProperty.from_preset("magpie")
        magpie_labels = magpie_featurizer.feature_labels()
        if MAGPIE_MAX_FEATURES > 0:
            magpie_selected = magpie_labels[:MAGPIE_MAX_FEATURES]
        else:
            magpie_selected = magpie_labels
    except Exception as exc:  # pragma: no cover - optional dependency
        magpie_featurizer = None
        magpie_labels = []
        magpie_selected = []
        _add_warning(metrics, f"matminer magpie not available: {exc}")

    if magpie_featurizer is not None:
        magpie_rows: List[List[Any]] = []
        for entry, structure in zip(metrics["structures"], structures_by_index):
            if structure is None:
                magpie_rows.append([entry["index"], entry.get("reduced_formula")] + [""] * len(magpie_selected))
                continue
            try:
                values = magpie_featurizer.featurize(structure.composition)
                features = dict(zip(magpie_labels, values))
                selected_features = {
                    name: _safe_number(features.get(name)) for name in magpie_selected
                }
                entry["features"]["magpie"] = selected_features
                row = [entry["index"], entry.get("reduced_formula")]
                row.extend([selected_features.get(name) for name in magpie_selected])
                magpie_rows.append(row)
            except Exception as exc:
                _add_structure_warning(metrics, entry, f"magpie featurize failed: {exc}")
                magpie_rows.append([entry["index"], entry.get("reduced_formula")] + [""] * len(magpie_selected))

        try:
            csv_path = job_dir / "magpie.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                header = ["index", "reduced_formula", *magpie_selected]
                writer.writerow(header)
                writer.writerows(magpie_rows)
        except Exception as exc:
            _add_warning(metrics, f"magpie.csv write failed: {exc}")

    try:
        import numpy as np
        from dscribe.descriptors import SOAP
        import dscribe

        metrics["tool_versions"]["dscribe"] = _safe_version(dscribe)
    except Exception as exc:  # pragma: no cover - optional dependency
        SOAP = None
        np = None
        _add_warning(metrics, f"dscribe SOAP not available: {exc}")

    if SOAP is not None and np is not None:
        species_set = set()
        for structure in structures_by_index:
            if structure is None:
                continue
            species_set.update([str(el) for el in structure.composition.elements])

        species = sorted(species_set)
        if not species:
            _add_warning(metrics, "SOAP skipped: no species found")
        else:
            average = SOAP_AVERAGE
            if average and average.lower() in {"none", "false", "0"}:
                average = None
            try:
                soap = SOAP(
                    species=species,
                    r_cut=SOAP_R_CUT,
                    n_max=SOAP_N_MAX,
                    l_max=SOAP_L_MAX,
                    sigma=SOAP_SIGMA,
                    periodic=True,
                    average=average,
                )
            except Exception as exc:
                soap = None
                _add_warning(metrics, f"SOAP init failed: {exc}")

            if soap is not None:
                for idx, (entry, atoms, structure) in enumerate(
                    zip(metrics["structures"], atoms_by_index, structures_by_index)
                ):
                    if atoms is None or structure is None:
                        continue
                    try:
                        if atoms.cell is None or atoms.cell.volume == 0:
                            atoms.set_cell(structure.lattice.matrix)
                        atoms.pbc = (True, True, True)
                        vector = soap.create(atoms)
                        vector = np.asarray(vector)
                        npy_path = job_dir / f"gen_{idx}.npy"
                        np.save(npy_path, vector)
                        if vector.ndim == 1:
                            norms = np.linalg.norm(vector)
                            mean_norm = float(norms)
                            std_norm = 0.0
                            n_features = int(vector.shape[0])
                        else:
                            norms = np.linalg.norm(vector, axis=1)
                            mean_norm = float(np.mean(norms))
                            std_norm = float(np.std(norms))
                            n_features = int(vector.shape[1])

                        entry["soap_summary"] = {
                            "n_features": n_features,
                            "mean_norm": mean_norm,
                            "std_norm": std_norm,
                            "file_path": str(npy_path),
                        }
                    except Exception as exc:
                        _add_structure_warning(
                            metrics, entry, f"SOAP failed on frame {idx}: {exc}"
                        )

    try:
        from ovito.io import import_file
        from ovito.vis import Viewport, TachyonRenderer
        import ovito

        metrics["tool_versions"]["ovito"] = _safe_version(ovito)
    except Exception as exc:  # pragma: no cover - optional dependency
        import_file = None
        Viewport = None
        _add_warning(metrics, f"ovito not available: {exc}")

    if import_file is not None and Viewport is not None:
        renderer = None
        try:
            renderer = TachyonRenderer()
        except Exception:
            renderer = None

        for entry in metrics["structures"]:
            cif_path = entry.get("cif")
            if not cif_path:
                _add_structure_warning(metrics, entry, "ovito render skipped: missing cif")
                continue
            try:
                pipeline = import_file(cif_path)
                pipeline.add_to_scene()
                pipeline.compute()
                viewport = Viewport(type=Viewport.Type.PERSPECTIVE)
                viewport.zoom_all()
                png_path = job_dir / f"gen_{entry['index']}.png"
                render_kwargs = {
                    "filename": str(png_path),
                    "size": (OVITO_IMG_WIDTH, OVITO_IMG_HEIGHT),
                    "alpha": True,
                    "background": (0, 0, 0),
                }
                if renderer is not None:
                    render_kwargs["renderer"] = renderer
                viewport.render_image(**render_kwargs)
                pipeline.remove_from_scene()
                entry["render"]["png"] = str(png_path)
            except Exception as exc:
                _add_structure_warning(metrics, entry, f"ovito render failed: {exc}")

    _write_metrics(job_dir, metrics)
    return metrics
