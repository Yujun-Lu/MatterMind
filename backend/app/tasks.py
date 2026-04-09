from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .celery_app import celery_app
from celery.exceptions import Ignore
from .ai_analysis import run_ai_analysis
from .config import (
    ANALYSIS_FILENAME,
    AUTO_ANALYSIS,
    HDF5_LIB,
    HDF5_METRICS_FILENAME,
    HF_ENDPOINT,
    MATTERGEN_QUEUE,
    MATTERGEN_REPO,
    METRICS_FILENAME,
    PIP_CACHE_DIR,
    POSTW90_METRICS_FILENAME,
    TMPDIR,
    VTST_METRICS_FILENAME,
    WANNIER_METRICS_FILENAME,
    VASP_ALLOWED_EXECUTABLES,
    VASP_EXECUTABLE,
    VASP_HDF5_HOME,
    VASP_QUEUE,
    VASP_MAX_NPROC,
    VASP_PLAIN_HOME,
    VASP_REQUIRED_INPUTS,
    VASP_RUN_MODES,
    VASP_STANDARD_OUTPUT_FILES,
    VASP_STANDARD_REQUIRED_INPUTS,
    VASP_VTST_DEFAULT_MODE,
    VASP_VTST_MODES,
    VASP_WANNIER_POST_OUTPUT_FILES,
    VASP_WANNIER_POST_REQUIRED_INPUTS,
    VASP_WANNIER_POSTW90_OUTPUT_FILES,
    VASP_WANNIER_POSTW90_REQUIRED_INPUTS,
    VASP_WANNIER_SCF_OUTPUT_FILES,
    VASP_WANNIER_SCF_REQUIRED_INPUTS,
    WANNIER_PLOT_FORMAT,
    WANNIER90_HOME,
    VASP_VTST_OUTPUT_FILES,
    VASP_VTST_PRE_RELAXED_REQUIRED_INPUTS,
    VASP_VTST_RELAX_FIRST_REQUIRED_INPUTS,
    VTST_SCRIPTS_DIR,
    XDG_CACHE_HOME,
)
from .storage import create_job_dir, log_path, read_meta, write_meta, now_iso
from .vasp_storage import (
    create_job_dir as create_vasp_job_dir,
    job_dir as vasp_job_dir,
    log_path as vasp_log_path,
    read_meta as read_vasp_meta,
    write_meta as write_vasp_meta,
)


MetaReadFn = Callable[[str], Dict[str, Any]]
MetaWriteFn = Callable[[str, Dict[str, Any]], None]


class JobStopRequested(RuntimeError):
    pass


def build_command(payload: Dict[str, Any], results_dir: str) -> List[str]:
    cmd = [
        "mattergen-generate",
        results_dir,
        f"--pretrained-name={payload['model_name']}",
        f"--batch_size={payload['batch_size']}",
        f"--num_batches={payload['num_batches']}",
    ]
    props = payload.get("properties_to_condition_on")
    if props:
        cmd.append(f"--properties_to_condition_on={json.dumps(props, ensure_ascii=False)}")
    guidance = payload.get("diffusion_guidance_factor")
    if guidance is not None:
        cmd.append(f"--diffusion_guidance_factor={guidance}")
    return cmd


def build_vasp_command(nproc: int, vasp_exec: str, home: Path) -> List[str]:
    vasp_binary = Path(home) / "bin" / vasp_exec
    return ["mpirun", "-np", str(nproc), str(vasp_binary)]


def ensure_vasp_inputs(job_path: Path, required_inputs: tuple[str, ...]) -> None:
    missing = [name for name in required_inputs if not (job_path / name).exists()]
    if missing:
        raise RuntimeError(f"missing required input files: {', '.join(missing)}")


def parse_incar_int(path: Path, key: str) -> Optional[int]:
    if not path.exists():
        return None
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=?\s*(\S+)", re.IGNORECASE)
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.split("#", 1)[0].split("!", 1)[0].strip()
        if not line:
            continue
        match = pattern.match(line)
        if not match:
            continue
        token = match.group(1).rstrip(";")
        try:
            return int(float(token))
        except ValueError:
            return None
    return None


def parse_incar_bool(path: Path, key: str) -> Optional[bool]:
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


def detect_spinor_wannier_incar_flags(job_path: Path) -> List[str]:
    incar_path = job_path / "INCAR"
    enabled_flags: List[str] = []
    for key in ("LSORBIT", "LNONCOLLINEAR"):
        if parse_incar_bool(incar_path, key) is True:
            enabled_flags.append(key)
    return enabled_flags


def get_wannier_visualization_options(job_id: str) -> Dict[str, Any]:
    meta = read_vasp_meta(job_id)
    options = dict(meta.get("wannier_visualization_options") or {})
    return {
        "enable_lwrite_unk": bool(options.get("enable_lwrite_unk")),
        "enable_wannier_plot": bool(options.get("enable_wannier_plot")),
        "wannier_plot_format": str(options.get("wannier_plot_format") or WANNIER_PLOT_FORMAT),
    }


def upsert_key_value_line(
    path: Path,
    key: str,
    value: str,
    *,
    separator: str = " = ",
    comment_prefixes: tuple[str, ...] = ("#", "!"),
) -> None:
    lines: List[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()

    pattern = re.compile(rf"^\s*{re.escape(key)}\s*(?:=|:)?", re.IGNORECASE)
    replacement = f"{key}{separator}{value}"
    updated = False
    output: List[str] = []

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            output.append(raw_line)
            continue
        if any(stripped.startswith(prefix) for prefix in comment_prefixes):
            output.append(raw_line)
            continue
        if pattern.match(raw_line):
            if not updated:
                output.append(replacement)
                updated = True
            continue
        output.append(raw_line)

    if not updated:
        if output and output[-1].strip():
            output.append("")
        output.append(replacement)

    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def prepare_wannier_visualization_inputs(
    job_path: Path,
    log_file: Path,
    visualization_options: Dict[str, Any],
) -> None:
    enable_lwrite_unk = bool(visualization_options.get("enable_lwrite_unk"))
    spinor_flags = detect_spinor_wannier_incar_flags(job_path)
    if enable_lwrite_unk:
        incar_path = job_path / "INCAR"
        upsert_key_value_line(incar_path, "LWRITE_UNK", ".TRUE.")

    with log_file.open("a", encoding="utf-8") as log_fp:
        log_fp.write("\n== Wannier visualization options ==\n")
        if enable_lwrite_unk:
            log_fp.write("applied user option: LWRITE_UNK = .TRUE.\n")
            if spinor_flags:
                log_fp.write(
                    "note: INCAR also enables "
                    f"{', '.join(spinor_flags)}; explicit user opt-in overrides the automatic safety skip.\n"
                )
        else:
            log_fp.write(
                "optional INCAR patch disabled: not adding LWRITE_UNK = .TRUE. automatically.\n"
            )
        log_fp.flush()


def prepare_wannier_visualization_win(
    job_path: Path,
    log_file: Path,
    visualization_options: Dict[str, Any],
) -> None:
    win_path = job_path / "wannier90.win"
    if not win_path.exists():
        return

    upsert_key_value_line(win_path, "write_xyz", "true")
    upsert_key_value_line(win_path, "write_hr", "true")
    upsert_key_value_line(win_path, "write_rmn", "true")
    upsert_key_value_line(win_path, "write_tb", "true")
    enable_wannier_plot = bool(visualization_options.get("enable_wannier_plot"))
    plot_format = str(visualization_options.get("wannier_plot_format") or WANNIER_PLOT_FORMAT)
    spinor_flags = detect_spinor_wannier_incar_flags(job_path)
    if enable_wannier_plot:
        upsert_key_value_line(win_path, "wannier_plot", "true")
        upsert_key_value_line(win_path, "wannier_plot_format", plot_format)

    with log_file.open("a", encoding="utf-8") as log_fp:
        log_fp.write("patched wannier90.win for TB export and optional visualization:\n")
        log_fp.write("  write_xyz = true\n")
        log_fp.write("  write_hr = true\n")
        log_fp.write("  write_rmn = true\n")
        log_fp.write("  write_tb = true\n")
        if enable_wannier_plot:
            log_fp.write("  wannier_plot = true\n")
            log_fp.write(f"  wannier_plot_format = {plot_format}\n")
            if spinor_flags:
                log_fp.write(
                    "  note: INCAR also enables "
                    f"{', '.join(spinor_flags)}; explicit user opt-in overrides the automatic safety skip.\n"
                )
        else:
            log_fp.write(
                "  optional wannier90 plot patch disabled: not adding wannier_plot/wannier_plot_format automatically.\n"
            )
        log_fp.flush()


POSTW90_SUPPORTED_MODULES = {
    "band_interp": "Band interpolation",
    "dos": "Density of states",
    "berry_ahc": "Berry / AHC",
    "fermi_surface": "Fermi surface",
    "boltzwann": "Boltzmann transport",
}


SEEDNAME_WIN_RE = re.compile(r"^\s*seedname\s*[:=]\s*(\S+)", re.IGNORECASE | re.MULTILINE)


def parse_seedname_from_win(path: Path) -> str:
    if not path.exists():
        return "wannier90"
    text = path.read_text(encoding="utf-8", errors="ignore")
    match = SEEDNAME_WIN_RE.search(text)
    return match.group(1).strip() if match else "wannier90"


def extract_fermi_energy_from_vasprun(path: Path) -> Optional[float]:
    if not path.exists():
        return None
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return None

    for node in root.findall(".//i[@name='efermi']"):
        try:
            return float((node.text or "").strip())
        except (TypeError, ValueError):
            continue
    return None


def replace_named_block(path: Path, block_name: str, body_lines: List[str]) -> None:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    begin_re = re.compile(rf"^\s*begin\s+{re.escape(block_name)}\s*$", re.IGNORECASE)
    end_re = re.compile(rf"^\s*end\s+{re.escape(block_name)}\s*$", re.IGNORECASE)

    output: List[str] = []
    in_block = False
    replaced = False
    for raw_line in lines:
        if begin_re.match(raw_line):
            if not replaced:
                output.append(f"begin {block_name}")
                output.extend(body_lines)
                output.append(f"end {block_name}")
                replaced = True
            in_block = True
            continue
        if in_block:
            if end_re.match(raw_line):
                in_block = False
            continue
        output.append(raw_line)

    if not replaced:
        if output and output[-1].strip():
            output.append("")
        output.append(f"begin {block_name}")
        output.extend(body_lines)
        output.append(f"end {block_name}")

    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def build_seekpath_kpoint_block(job_path: Path) -> List[str]:
    try:
        from ase.io import read
        import seekpath
    except Exception as exc:
        raise RuntimeError(f"seekpath path generation is unavailable: {exc}") from exc

    structure_path = job_path / "CONTCAR"
    if not structure_path.exists():
        structure_path = job_path / "POSCAR"
    if not structure_path.exists():
        raise RuntimeError("POSCAR or CONTCAR is required to build the postw90 k-point path")

    atoms = read(structure_path)
    cell = atoms.cell.array.tolist()
    scaled_positions = atoms.get_scaled_positions(wrap=False).tolist()
    numbers = atoms.get_atomic_numbers().tolist()
    path_data = seekpath.get_path((cell, scaled_positions, numbers))
    point_coords = path_data["point_coords"]

    lines: List[str] = []
    for start_label, end_label in path_data["path"]:
        start = point_coords[start_label]
        end = point_coords[end_label]
        lines.append(
            f"{start_label} {start[0]:.8f} {start[1]:.8f} {start[2]:.8f} "
            f"{end_label} {end[0]:.8f} {end[1]:.8f} {end[2]:.8f}"
        )
    return lines


def mesh_triplet(value: int) -> str:
    v = max(2, int(value))
    return f"{v} {v} {v}"


def prepare_postw90_win(job_id: str, job_path: Path, log_file: Path) -> None:
    meta = read_vasp_meta(job_id)
    module = (meta.get("postw90_module") or "").strip()
    params = dict(meta.get("postw90_params") or {})
    if module not in POSTW90_SUPPORTED_MODULES:
        raise RuntimeError(f"unsupported postw90 module '{module}'")

    win_path = job_path / "wannier90.win"
    if not win_path.exists():
        raise RuntimeError("wannier90.win is missing for postw90")

    updates: List[str] = []
    if module == "band_interp":
        upsert_key_value_line(win_path, "kpath", "true")
        upsert_key_value_line(win_path, "kpath_task", "bands")
        upsert_key_value_line(
            win_path,
            "bands_num_points",
            str(int(params.get("bands_num_points", 80))),
        )
        kpath_lines = build_seekpath_kpoint_block(job_path)
        replace_named_block(win_path, "kpoint_path", kpath_lines)
        updates.extend(
            [
                "kpath = true",
                "kpath_task = bands",
                f"bands_num_points = {int(params.get('bands_num_points', 80))}",
                "begin/end kpoint_path = auto-generated from SeeK-path",
            ]
        )
    elif module == "dos":
        dos_kmesh = int(params.get("dos_kmesh", 24))
        upsert_key_value_line(win_path, "dos", "true")
        upsert_key_value_line(win_path, "dos_kmesh", mesh_triplet(dos_kmesh))
        upsert_key_value_line(win_path, "dos_energy_min", str(params.get("dos_energy_min", -10)))
        upsert_key_value_line(win_path, "dos_energy_max", str(params.get("dos_energy_max", 10)))
        upsert_key_value_line(win_path, "dos_energy_step", str(params.get("dos_energy_step", 0.02)))
        updates.extend(
            [
                "dos = true",
                f"dos_kmesh = {mesh_triplet(dos_kmesh)}",
                f"dos_energy_min = {params.get('dos_energy_min', -10)}",
                f"dos_energy_max = {params.get('dos_energy_max', 10)}",
                f"dos_energy_step = {params.get('dos_energy_step', 0.02)}",
            ]
        )
    elif module == "berry_ahc":
        berry_kmesh = int(params.get("berry_kmesh", 24))
        upsert_key_value_line(win_path, "berry", "true")
        upsert_key_value_line(win_path, "berry_task", "ahc")
        upsert_key_value_line(win_path, "berry_kmesh", mesh_triplet(berry_kmesh))
        upsert_key_value_line(win_path, "fermi_energy_min", str(params.get("fermi_energy_min", -1.0)))
        upsert_key_value_line(win_path, "fermi_energy_max", str(params.get("fermi_energy_max", 1.0)))
        upsert_key_value_line(win_path, "fermi_energy_step", str(params.get("fermi_energy_step", 0.02)))
        updates.extend(
            [
                "berry = true",
                "berry_task = ahc",
                f"berry_kmesh = {mesh_triplet(berry_kmesh)}",
                f"fermi_energy_min = {params.get('fermi_energy_min', -1.0)}",
                f"fermi_energy_max = {params.get('fermi_energy_max', 1.0)}",
                f"fermi_energy_step = {params.get('fermi_energy_step', 0.02)}",
            ]
        )
    elif module == "fermi_surface":
        fermi_energy = params.get("fermi_energy")
        if fermi_energy in (None, ""):
            fermi_energy = extract_fermi_energy_from_vasprun(job_path / "vasprun.xml")
        try:
            fermi_energy_value = float(fermi_energy) if fermi_energy not in (None, "") else None
        except (TypeError, ValueError):
            fermi_energy_value = None
        if fermi_energy_value is None:
            raise RuntimeError("failed to determine Fermi energy for Fermi-surface plotting")
        fermi_surface_plot_format = str(params.get("fermi_surface_plot_format", "xcrysden")).strip().lower()
        if fermi_surface_plot_format == "bxsf":
            fermi_surface_plot_format = "xcrysden"
        upsert_key_value_line(win_path, "restart", "plot")
        upsert_key_value_line(win_path, "fermi_energy", str(fermi_energy_value))
        upsert_key_value_line(win_path, "wannier_plot", "false")
        upsert_key_value_line(win_path, "fermi_surface_plot", "true")
        upsert_key_value_line(
            win_path,
            "fermi_surface_num_points",
            str(int(params.get("fermi_surface_num_points", 80))),
        )
        upsert_key_value_line(
            win_path,
            "fermi_surface_plot_format",
            fermi_surface_plot_format,
        )
        updates.extend(
            [
                "restart = plot",
                f"fermi_energy = {fermi_energy_value}",
                "wannier_plot = false",
                "fermi_surface_plot = true",
                f"fermi_surface_num_points = {int(params.get('fermi_surface_num_points', 80))}",
                f"fermi_surface_plot_format = {fermi_surface_plot_format}",
            ]
        )
    elif module == "boltzwann":
        boltz_kmesh = int(params.get("boltz_kmesh", 28))
        upsert_key_value_line(win_path, "boltzwann", "true")
        upsert_key_value_line(win_path, "boltz_calc_also_dos", "true")
        upsert_key_value_line(win_path, "boltz_kmesh", mesh_triplet(boltz_kmesh))
        upsert_key_value_line(win_path, "boltz_mu_min", str(params.get("boltz_mu_min", -1.0)))
        upsert_key_value_line(win_path, "boltz_mu_max", str(params.get("boltz_mu_max", 1.0)))
        upsert_key_value_line(win_path, "boltz_mu_step", str(params.get("boltz_mu_step", 0.05)))
        upsert_key_value_line(win_path, "boltz_temp_min", str(params.get("boltz_temp_min", 100)))
        upsert_key_value_line(win_path, "boltz_temp_max", str(params.get("boltz_temp_max", 800)))
        upsert_key_value_line(win_path, "boltz_temp_step", str(params.get("boltz_temp_step", 100)))
        upsert_key_value_line(win_path, "boltz_relax_time", str(params.get("boltz_relax_time", 10.0)))
        updates.extend(
            [
                "boltzwann = true",
                "boltz_calc_also_dos = true",
                f"boltz_kmesh = {mesh_triplet(boltz_kmesh)}",
                f"boltz_mu_min = {params.get('boltz_mu_min', -1.0)}",
                f"boltz_mu_max = {params.get('boltz_mu_max', 1.0)}",
                f"boltz_mu_step = {params.get('boltz_mu_step', 0.05)}",
                f"boltz_temp_min = {params.get('boltz_temp_min', 100)}",
                f"boltz_temp_max = {params.get('boltz_temp_max', 800)}",
                f"boltz_temp_step = {params.get('boltz_temp_step', 100)}",
                f"boltz_relax_time = {params.get('boltz_relax_time', 10.0)}",
            ]
        )

    with log_file.open("a", encoding="utf-8") as log_fp:
        log_fp.write("\n== postw90 win patch ==\n")
        log_fp.write(f"module: {module} ({POSTW90_SUPPORTED_MODULES[module]})\n")
        for line in updates:
            log_fp.write(f"  {line}\n")
        log_fp.flush()


def build_vasp_env(
    *,
    include_vtst: bool = False,
    include_hdf5_lib: bool = True,
    include_wannier: bool = False,
) -> Dict[str, str]:
    env = os.environ.copy()
    if include_hdf5_lib:
        existing_ld = env.get("LD_LIBRARY_PATH", "")
        prefix = str(HDF5_LIB)
        env["LD_LIBRARY_PATH"] = f"{prefix}:{existing_ld}" if existing_ld else prefix
    if include_vtst:
        existing_path = env.get("PATH", "")
        vtst_prefix = str(VTST_SCRIPTS_DIR)
        env["PATH"] = f"{vtst_prefix}:{existing_path}" if existing_path else vtst_prefix
    if include_wannier:
        existing_path = env.get("PATH", "")
        wannier_prefix = str(WANNIER90_HOME)
        env["PATH"] = (
            f"{wannier_prefix}:{existing_path}" if existing_path else wannier_prefix
        )
    return env


def is_stop_requested(read_meta_fn: MetaReadFn, job_id: str) -> bool:
    return bool(read_meta_fn(job_id).get("stop_requested"))


def ensure_job_not_stopped(read_meta_fn: MetaReadFn, job_id: str) -> None:
    if is_stop_requested(read_meta_fn, job_id):
        raise JobStopRequested("stop requested by user")


def register_active_process(
    job_id: str,
    read_meta_fn: MetaReadFn,
    write_meta_fn: MetaWriteFn,
    process: subprocess.Popen,
    section: Optional[str],
    cmd: List[str],
) -> None:
    meta = read_meta_fn(job_id)
    pgid = None
    if hasattr(os, "getpgid"):
        try:
            pgid = os.getpgid(process.pid)
        except Exception:
            pgid = None
    meta["active_process_pid"] = process.pid
    meta["active_process_pgid"] = pgid
    meta["active_process_section"] = section or ""
    meta["active_process_command"] = " ".join(cmd)
    meta["active_process_started_at"] = now_iso()
    write_meta_fn(job_id, meta)


def clear_active_process(job_id: str, read_meta_fn: MetaReadFn, write_meta_fn: MetaWriteFn) -> None:
    meta = read_meta_fn(job_id)
    for key in (
        "active_process_pid",
        "active_process_pgid",
        "active_process_section",
        "active_process_command",
        "active_process_started_at",
    ):
        meta.pop(key, None)
    write_meta_fn(job_id, meta)


def ensure_command_succeeded(
    return_code: int,
    *,
    job_id: str,
    read_meta_fn: MetaReadFn,
    failure_message: str,
) -> None:
    if return_code == 0:
        ensure_job_not_stopped(read_meta_fn, job_id)
        return
    if is_stop_requested(read_meta_fn, job_id):
        raise JobStopRequested("stop requested by user")
    raise RuntimeError(failure_message)


def stream_command(
    cmd: List[str],
    cwd: Path,
    env: Dict[str, str],
    log_fp,
    output_paths: Optional[List[Path]] = None,
    section: Optional[str] = None,
    job_id: Optional[str] = None,
    read_meta_fn: Optional[MetaReadFn] = None,
    write_meta_fn: Optional[MetaWriteFn] = None,
) -> int:
    mirrors = []
    for path in output_paths or []:
        path.parent.mkdir(parents=True, exist_ok=True)
        mirrors.append(path.open("a", encoding="utf-8"))
    try:
        if section:
            log_fp.write(f"\n== {section} ==\n")
        log_fp.write(f"cwd: {cwd}\n")
        log_fp.write("command: " + " ".join(cmd) + "\n")
        log_fp.flush()
        process = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        if job_id and read_meta_fn and write_meta_fn:
            register_active_process(
                job_id,
                read_meta_fn,
                write_meta_fn,
                process,
                section,
                cmd,
            )
        if process.stdout:
            for line in process.stdout:
                log_fp.write(line)
                log_fp.flush()
                for mirror in mirrors:
                    mirror.write(line)
                    mirror.flush()
        return_code = process.wait()
        log_fp.write(f"\nprocess exited with code {return_code}\n")
        log_fp.flush()
        return return_code
    finally:
        if job_id and read_meta_fn and write_meta_fn:
            clear_active_process(job_id, read_meta_fn, write_meta_fn)
        for mirror in mirrors:
            mirror.close()


def copy_if_exists(src: Path, dest: Path) -> None:
    if src.exists():
        shutil.copy2(src, dest)


def copy_required_file(src: Path, dest: Path) -> None:
    if not src.exists():
        raise RuntimeError(f"missing required input file: {src.name}")
    shutil.copy2(src, dest)


def get_vtst_required_inputs(vtst_mode: str) -> tuple[str, ...]:
    if vtst_mode == "relax_first":
        return VASP_VTST_RELAX_FIRST_REQUIRED_INPUTS
    return VASP_VTST_PRE_RELAXED_REQUIRED_INPUTS


def prepare_vtst_neb_inputs(job_path: Path) -> None:
    copy_required_file(job_path / "INCAR_neb", job_path / "INCAR")


def prepare_vtst_endpoint_inputs(
    endpoint_dir: Path, job_path: Path, source_poscar_name: str
) -> None:
    endpoint_dir.mkdir(parents=True, exist_ok=True)
    copy_required_file(job_path / "INCAR_endpoint", endpoint_dir / "INCAR")
    copy_required_file(job_path / "KPOINTS", endpoint_dir / "KPOINTS")
    copy_required_file(job_path / "POTCAR", endpoint_dir / "POTCAR")
    copy_required_file(job_path / source_poscar_name, endpoint_dir / "POSCAR")


def promote_vtst_endpoint_contcar(endpoint_dir: Path, job_path: Path, target_name: str) -> None:
    copy_required_file(endpoint_dir / "CONTCAR", job_path / target_name)


def mirror_vtst_endpoint_results(endpoint_dir: Path, neb_endpoint_dir: Path) -> None:
    neb_endpoint_dir.mkdir(parents=True, exist_ok=True)
    copy_required_file(endpoint_dir / "OUTCAR", neb_endpoint_dir / "OUTCAR")
    for name in ("CONTCAR", "OSZICAR", "vasp.out", "vasprun.xml", "vaspout.h5"):
        copy_if_exists(endpoint_dir / name, neb_endpoint_dir / name)


def collect_vtst_endpoint_outputs(endpoint_dir: Path, job_path: Path, prefix: str) -> None:
    copy_if_exists(endpoint_dir / "vasp.out", job_path / f"{prefix}_vasp.out")
    copy_if_exists(endpoint_dir / "OUTCAR", job_path / f"{prefix}_OUTCAR")
    copy_if_exists(endpoint_dir / "vasprun.xml", job_path / f"{prefix}_vasprun.xml")
    copy_if_exists(endpoint_dir / "vaspout.h5", job_path / f"{prefix}_vaspout.h5")


def list_existing_outputs(job_path: Path, output_files: tuple[str, ...]) -> List[str]:
    return [name for name in output_files if (job_path / name).exists()]


def run_standard_vasp_job(
    job_id: str,
    job_path: Path,
    log_file: Path,
    nproc: int,
    vasp_exec: str,
) -> int:
    ensure_vasp_inputs(job_path, VASP_STANDARD_REQUIRED_INPUTS)
    ensure_job_not_stopped(read_vasp_meta, job_id)
    env = build_vasp_env()
    cmd = build_vasp_command(nproc, vasp_exec, VASP_HDF5_HOME)
    vasp_out_path = job_path / "vasp.out"

    with log_file.open("a", encoding="utf-8") as log_fp:
        return_code = stream_command(
            cmd,
            cwd=job_path,
            env=env,
            log_fp=log_fp,
            output_paths=[vasp_out_path],
            section="standard VASP run",
            job_id=job_id,
            read_meta_fn=read_vasp_meta,
            write_meta_fn=write_vasp_meta,
        )
    ensure_command_succeeded(
        return_code,
        job_id=job_id,
        read_meta_fn=read_vasp_meta,
        failure_message=f"standard VASP run failed with code {return_code}",
    )
    return return_code


def run_vtst_neb_job(
    job_id: str,
    job_path: Path,
    log_file: Path,
    nproc: int,
    endpoint_nproc: int,
    vasp_exec: str,
    vtst_mode: str,
) -> Dict[str, Any]:
    if vtst_mode not in VASP_VTST_MODES:
        raise RuntimeError(f"unknown vtst mode '{vtst_mode}'")
    ensure_vasp_inputs(job_path, get_vtst_required_inputs(vtst_mode))
    ensure_job_not_stopped(read_vasp_meta, job_id)
    if not VTST_SCRIPTS_DIR.exists():
        raise RuntimeError(f"VTST scripts directory not found: {VTST_SCRIPTS_DIR}")

    prepare_vtst_neb_inputs(job_path)
    images = parse_incar_int(job_path / "INCAR", "IMAGES")
    if images is None or images < 1:
        raise RuntimeError("failed to parse IMAGES from INCAR")
    if nproc % images != 0:
        raise RuntimeError(f"VTST NEB requires nproc to be a multiple of IMAGES ({images})")

    final_index = images + 1
    final_dir_name = f"{final_index:02d}"
    env = build_vasp_env(include_vtst=True)
    endpoint_mirror_pairs: List[tuple[Path, Path]] = []

    with log_file.open("a", encoding="utf-8") as log_fp:
        log_fp.write(f"\n== VTST mode ==\n{vtst_mode}\n")
        log_fp.flush()

        if vtst_mode == "relax_first":
            for prefix, source_name, target_name in (
                ("endpoint_initial", "POSCAR_i", "POSCAR_initial"),
                ("endpoint_final", "POSCAR_f", "POSCAR_final"),
            ):
                ensure_job_not_stopped(read_vasp_meta, job_id)
                endpoint_dir = job_path / prefix
                prepare_vtst_endpoint_inputs(endpoint_dir, job_path, source_name)
                endpoint_cmd = build_vasp_command(endpoint_nproc, vasp_exec, VASP_HDF5_HOME)
                return_code = stream_command(
                    endpoint_cmd,
                    cwd=endpoint_dir,
                    env=env,
                    log_fp=log_fp,
                    output_paths=[endpoint_dir / "vasp.out"],
                    section=f"{prefix} relax",
                    job_id=job_id,
                    read_meta_fn=read_vasp_meta,
                    write_meta_fn=write_vasp_meta,
                )
                ensure_command_succeeded(
                    return_code,
                    job_id=job_id,
                    read_meta_fn=read_vasp_meta,
                    failure_message=f"{prefix} relax failed with code {return_code}",
                )
                collect_vtst_endpoint_outputs(endpoint_dir, job_path, prefix)
                promote_vtst_endpoint_contcar(endpoint_dir, job_path, target_name)
                endpoint_mirror_pairs.append((endpoint_dir, job_path / ("00" if prefix == "endpoint_initial" else final_dir_name)))
        else:
            copy_required_file(job_path / "POSCAR_i", job_path / "POSCAR_initial")
            copy_required_file(job_path / "POSCAR_f", job_path / "POSCAR_final")

        make_cmd = ["nebmake.pl", "POSCAR_initial", "POSCAR_final", str(images)]
        return_code = stream_command(
            make_cmd,
            cwd=job_path,
            env=env,
            log_fp=log_fp,
            section="VTST nebmake",
            job_id=job_id,
            read_meta_fn=read_vasp_meta,
            write_meta_fn=write_vasp_meta,
        )
        ensure_command_succeeded(
            return_code,
            job_id=job_id,
            read_meta_fn=read_vasp_meta,
            failure_message=f"nebmake.pl failed with code {return_code}",
        )

        initial_dir = job_path / "00"
        final_dir = job_path / final_dir_name
        if not initial_dir.exists() or not final_dir.exists():
            raise RuntimeError(
                f"nebmake.pl did not produce expected endpoint directories 00 and {final_dir_name}"
            )

        neb_cmd = build_vasp_command(nproc, vasp_exec, VASP_HDF5_HOME)
        return_code = stream_command(
            neb_cmd,
            cwd=job_path,
            env=env,
            log_fp=log_fp,
            output_paths=[job_path / "vasp.out"],
            section="VTST NEB run",
            job_id=job_id,
            read_meta_fn=read_vasp_meta,
            write_meta_fn=write_vasp_meta,
        )
        ensure_command_succeeded(
            return_code,
            job_id=job_id,
            read_meta_fn=read_vasp_meta,
            failure_message=f"VTST NEB run failed with code {return_code}",
        )

        if endpoint_mirror_pairs:
            log_fp.write("\n== VTST endpoint mirror ==\n")
            for source_dir, target_dir in endpoint_mirror_pairs:
                mirror_vtst_endpoint_results(source_dir, target_dir)
                log_fp.write(f"mirrored {source_dir.name} -> {target_dir.name}\n")
            log_fp.flush()

        if (initial_dir / "OUTCAR").exists() and (final_dir / "OUTCAR").exists():
            nebresults_code = stream_command(
                ["nebresults.pl"],
                cwd=job_path,
                env=env,
                log_fp=log_fp,
                output_paths=[job_path / "nebresults.txt"],
                section="VTST nebresults",
                job_id=job_id,
                read_meta_fn=read_vasp_meta,
                write_meta_fn=write_vasp_meta,
            )
            ensure_command_succeeded(
                nebresults_code,
                job_id=job_id,
                read_meta_fn=read_vasp_meta,
                failure_message=f"nebresults.pl failed with code {nebresults_code}",
            )
        else:
            log_fp.write(
                "\n== VTST nebresults ==\n"
                f"skipped: missing endpoint OUTCAR in 00 or {final_dir_name}; "
                "nebresults.pl requires standard endpoint outputs.\n"
            )
            log_fp.flush()

    return {
        "return_code": 0,
        "images": images,
        "final_dir_name": final_dir_name,
        "vtst_mode": vtst_mode,
    }


def run_wannier_job(
    job_id: str,
    job_path: Path,
    log_file: Path,
    nproc: int,
    vasp_exec: str,
) -> int:
    ensure_vasp_inputs(job_path, VASP_WANNIER_POST_REQUIRED_INPUTS)
    ensure_job_not_stopped(read_vasp_meta, job_id)
    if not VASP_PLAIN_HOME.exists():
        raise RuntimeError(f"Plain VASP directory not found: {VASP_PLAIN_HOME}")
    if not WANNIER90_HOME.exists():
        raise RuntimeError(f"Wannier90 directory not found: {WANNIER90_HOME}")
    wannier_executable = Path(WANNIER90_HOME) / "wannier90.x"
    if not wannier_executable.exists():
        raise RuntimeError(f"Wannier90 executable not found: {wannier_executable}")

    visualization_options = get_wannier_visualization_options(job_id)
    prepare_wannier_visualization_inputs(job_path, log_file, visualization_options)
    env = build_vasp_env(include_hdf5_lib=False)
    vasp_cmd = build_vasp_command(nproc, vasp_exec, VASP_PLAIN_HOME)

    with log_file.open("a", encoding="utf-8") as log_fp:
        return_code = stream_command(
            vasp_cmd,
            cwd=job_path,
            env=env,
            log_fp=log_fp,
            output_paths=[job_path / "vasp.out"],
            section="Wannier interface VASP run",
            job_id=job_id,
            read_meta_fn=read_vasp_meta,
            write_meta_fn=write_vasp_meta,
        )
        ensure_command_succeeded(
            return_code,
            job_id=job_id,
            read_meta_fn=read_vasp_meta,
            failure_message=f"Wannier interface VASP run failed with code {return_code}",
        )

        ensure_job_not_stopped(read_vasp_meta, job_id)
        prepare_wannier_visualization_win(job_path, log_file, visualization_options)
        wannier_code = stream_command(
            [str(wannier_executable), "wannier90"],
            cwd=job_path,
            env=env,
            log_fp=log_fp,
            section="Wannier90 run",
            job_id=job_id,
            read_meta_fn=read_vasp_meta,
            write_meta_fn=write_vasp_meta,
        )
        ensure_command_succeeded(
            wannier_code,
            job_id=job_id,
            read_meta_fn=read_vasp_meta,
            failure_message=f"wannier90.x failed with code {wannier_code}",
        )

    return 0


def run_wannier_scf_job(
    job_id: str,
    job_path: Path,
    log_file: Path,
    nproc: int,
    vasp_exec: str,
) -> int:
    ensure_vasp_inputs(job_path, VASP_WANNIER_SCF_REQUIRED_INPUTS)
    ensure_job_not_stopped(read_vasp_meta, job_id)
    env = build_vasp_env()
    cmd = build_vasp_command(nproc, vasp_exec, VASP_HDF5_HOME)
    vasp_out_path = job_path / "vasp.out"

    with log_file.open("a", encoding="utf-8") as log_fp:
        return_code = stream_command(
            cmd,
            cwd=job_path,
            env=env,
            log_fp=log_fp,
            output_paths=[vasp_out_path],
            section="Wannier SCF run",
            job_id=job_id,
            read_meta_fn=read_vasp_meta,
            write_meta_fn=write_vasp_meta,
        )
    ensure_command_succeeded(
        return_code,
        job_id=job_id,
        read_meta_fn=read_vasp_meta,
        failure_message=f"Wannier SCF run failed with code {return_code}",
    )
    return return_code


def prepare_wannier_post_inputs(job_id: str, job_path: Path, log_file: Path) -> None:
    meta = read_vasp_meta(job_id)
    source_job_id = meta.get("source_job_id")
    if not source_job_id:
        raise RuntimeError("Wannier post run requires source_job_id")

    source_job_path = vasp_job_dir(source_job_id)
    if not source_job_path.exists():
        raise RuntimeError(f"source SCF job directory not found: {source_job_id}")

    required_files = ("POSCAR", "POTCAR", "KPOINTS", "WAVECAR")
    for name in required_files:
        src = source_job_path / name
        if not src.exists():
            raise RuntimeError(f"source SCF file missing: {name}")
        shutil.copy2(src, job_path / name)

    chgcar = source_job_path / "CHGCAR"
    if chgcar.exists():
        shutil.copy2(chgcar, job_path / "CHGCAR")

    with log_file.open("a", encoding="utf-8") as log_fp:
        log_fp.write("\n== Wannier source copy ==\n")
        log_fp.write(f"source job: {source_job_id}\n")
        for name in required_files:
            log_fp.write(f"copied: {name}\n")
        if chgcar.exists():
            log_fp.write("copied: CHGCAR\n")
        log_fp.flush()


def prepare_postw90_inputs(job_id: str, job_path: Path, log_file: Path) -> None:
    meta = read_vasp_meta(job_id)
    source_job_id = meta.get("source_job_id")
    if not source_job_id:
        raise RuntimeError("postw90 run requires source_job_id")

    source_job_path = vasp_job_dir(source_job_id)
    if not source_job_path.exists():
        raise RuntimeError(f"source Wannier job directory not found: {source_job_id}")

    source_meta = read_vasp_meta(source_job_id)
    if source_meta.get("run_mode") not in {"wannier", "wannier_post"}:
        raise RuntimeError("postw90 source job must be a successful Wannier post run")

    copy_candidates = {
        "POSCAR",
        "CONTCAR",
        "OUTCAR",
        "vasprun.xml",
        "wannier90.win",
        "wannier90.chk",
        "wannier90.wout",
        "wannier90.eig",
        "wannier90.mmn",
        "wannier90.amn",
        "wannier90.nnkp",
        "wannier90_hr.dat",
        "wannier90_r.dat",
        "wannier90_tb.dat",
        "wannier90_centres.xyz",
        "wannier_centers.xyz",
    }

    for pattern in ("wannier90.*", "wannier90_*", "*.spn", "*.uHu", "*.uIu", "*.sHu", "*.sIu"):
        for path in source_job_path.glob(pattern):
            if path.is_file():
                copy_candidates.add(path.name)

    copied_files: List[str] = []
    for name in sorted(copy_candidates):
        src = source_job_path / name
        if not src.exists() or not src.is_file():
            continue
        shutil.copy2(src, job_path / name)
        copied_files.append(name)

    required = ["wannier90.win", "wannier90.chk", "wannier90_hr.dat"]
    missing = [name for name in required if not (job_path / name).exists()]
    if missing:
        raise RuntimeError(
            "source Wannier job is missing required postw90 inputs: " + ", ".join(missing)
        )

    prepare_postw90_win(job_id, job_path, log_file)

    baseline_files = sorted(
        path.relative_to(job_path).as_posix()
        for path in job_path.rglob("*")
        if path.is_file()
    )
    meta = read_vasp_meta(job_id)
    meta["seedname"] = parse_seedname_from_win(job_path / "wannier90.win")
    meta["postw90_baseline_files"] = baseline_files
    meta["copied_files"] = copied_files
    write_vasp_meta(job_id, meta)

    with log_file.open("a", encoding="utf-8") as log_fp:
        log_fp.write("\n== postw90 source copy ==\n")
        log_fp.write(f"source job: {source_job_id}\n")
        log_fp.write(f"copied files: {', '.join(copied_files)}\n")
        log_fp.flush()


def run_postw90_job(
    job_id: str,
    job_path: Path,
    log_file: Path,
    nproc: int,
) -> int:
    ensure_vasp_inputs(job_path, VASP_WANNIER_POSTW90_REQUIRED_INPUTS)
    ensure_job_not_stopped(read_vasp_meta, job_id)
    if not WANNIER90_HOME.exists():
        raise RuntimeError(f"Wannier90 directory not found: {WANNIER90_HOME}")

    module = (read_vasp_meta(job_id).get("postw90_module") or "").strip()
    seedname = parse_seedname_from_win(job_path / "wannier90.win")
    env = build_vasp_env(include_hdf5_lib=False, include_wannier=True)
    if module == "fermi_surface":
        wannier_executable = Path(WANNIER90_HOME) / "wannier90.x"
        if not wannier_executable.exists():
            raise RuntimeError(f"wannier90 executable not found: {wannier_executable}")
        cmd = [str(wannier_executable), seedname]
        section = "wannier90 plot fermi_surface"
        failure_message = f"wannier90.x plot run failed with code {{return_code}}"
    else:
        postw90_executable = Path(WANNIER90_HOME) / "postw90.x"
        if not postw90_executable.exists():
            raise RuntimeError(f"postw90 executable not found: {postw90_executable}")
        cmd = ["mpirun", "-np", str(nproc), str(postw90_executable), seedname]
        section = f"postw90 {module}"
        failure_message = f"postw90.x failed with code {{return_code}}"

    with log_file.open("a", encoding="utf-8") as log_fp:
        return_code = stream_command(
            cmd,
            cwd=job_path,
            env=env,
            log_fp=log_fp,
            output_paths=[job_path / "postw90.out"],
            section=section,
            job_id=job_id,
            read_meta_fn=read_vasp_meta,
            write_meta_fn=write_vasp_meta,
        )
    ensure_command_succeeded(
        return_code,
        job_id=job_id,
        read_meta_fn=read_vasp_meta,
        failure_message=failure_message.format(return_code=return_code),
    )
    return return_code


def mark_vasp_job_stopped(
    self,
    *,
    job_id: str,
    job_path: Path,
    log_file: Path,
    run_mode: str,
    reason: str,
) -> None:
    meta = read_vasp_meta(job_id)
    meta["job_status"] = "REVOKED"
    meta["finished_at"] = now_iso()
    meta["stopped_at"] = now_iso()
    meta["stop_status"] = "stopped"
    meta["stop_reason"] = reason
    meta["metrics_status"] = "stopped"
    if run_mode == "vtst_neb":
        meta["available_output_files"] = list_existing_outputs(
            job_path, VASP_VTST_OUTPUT_FILES
        )
    elif run_mode == "wannier_postw90":
        meta["available_output_files"] = list_existing_outputs(
            job_path, VASP_WANNIER_POSTW90_OUTPUT_FILES
        )
    elif run_mode in {"wannier", "wannier_scf", "wannier_post"}:
        meta["available_output_files"] = list_existing_outputs(
            job_path,
            VASP_WANNIER_POST_OUTPUT_FILES
            if run_mode in {"wannier", "wannier_post"}
            else VASP_WANNIER_SCF_OUTPUT_FILES,
        )
    else:
        meta["available_output_files"] = list_existing_outputs(
            job_path, VASP_STANDARD_OUTPUT_FILES
        )
    write_vasp_meta(job_id, meta)
    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"job stopped: {reason}\n")
    self.update_state(state="REVOKED", meta={"reason": reason})
    raise Ignore()


@celery_app.task(bind=True, name="app.tasks.run_mattergen", queue=MATTERGEN_QUEUE)
def run_mattergen(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    job_id = payload["job_id"]
    job_dir = create_job_dir(job_id)
    log_file = log_path(job_id)

    meta = read_meta(job_id)
    meta["job_status"] = "STARTED"
    meta["started_at"] = now_iso()
    write_meta(job_id, meta)

    env = os.environ.copy()
    env["TMPDIR"] = TMPDIR
    env["PIP_CACHE_DIR"] = PIP_CACHE_DIR
    env["XDG_CACHE_HOME"] = XDG_CACHE_HOME
    if HF_ENDPOINT:
        env["HF_ENDPOINT"] = HF_ENDPOINT

    cmd = build_command(payload, str(job_dir))

    with log_file.open("a", encoding="utf-8") as f:
        f.write("command: " + " ".join(cmd) + "\n")
        f.flush()
        process = subprocess.Popen(
            cmd,
            cwd=str(MATTERGEN_REPO),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if process.stdout:
            for line in process.stdout:
                f.write(line)
                f.flush()
        return_code = process.wait()
        f.write(f"\nprocess exited with code {return_code}\n")
        f.flush()

    meta = read_meta(job_id)
    meta["command_finished_at"] = now_iso()
    meta["return_code"] = return_code
    write_meta(job_id, meta)

    if return_code != 0:
        meta = read_meta(job_id)
        meta["job_status"] = "FAILURE"
        meta["finished_at"] = now_iso()
        write_meta(job_id, meta)
        raise RuntimeError(f"mattergen failed with code {return_code}")

    metrics = None
    try:
        from .postprocess import postprocess_job

        metrics = postprocess_job(job_id, job_dir)
        meta = read_meta(job_id)
        meta["metrics_path"] = str(job_dir / METRICS_FILENAME)
        meta["metrics_status"] = metrics.get("status", "ok")
        write_meta(job_id, meta)
    except Exception as exc:
        meta = read_meta(job_id)
        meta["metrics_status"] = "failed"
        meta["metrics_error"] = str(exc)
        write_meta(job_id, meta)
        with log_file.open("a", encoding="utf-8") as f:
            f.write(f"postprocess failed: {exc}\n")

    auto_analysis = str(AUTO_ANALYSIS).strip().lower() in {"1", "true", "yes", "on"}
    if metrics is not None and auto_analysis:
        analysis_path = job_dir / ANALYSIS_FILENAME
        if not analysis_path.exists():
            try:
                analysis = run_ai_analysis(metrics, read_meta(job_id))
                analysis_path.write_text(analysis, encoding="utf-8")
                meta = read_meta(job_id)
                meta["analysis_status"] = "ok"
                meta["analysis_path"] = str(analysis_path)
                meta["analysis_at"] = now_iso()
                write_meta(job_id, meta)
            except Exception as exc:
                meta = read_meta(job_id)
                meta["analysis_status"] = "failed"
                meta["analysis_error"] = str(exc)
                write_meta(job_id, meta)
                with log_file.open("a", encoding="utf-8") as f:
                    f.write(f"analysis failed: {exc}\n")

    meta = read_meta(job_id)
    meta["job_status"] = "SUCCESS"
    meta["finished_at"] = now_iso()
    write_meta(job_id, meta)

    return {"job_id": job_id, "return_code": return_code}


@celery_app.task(bind=True, name="app.tasks.run_vasp", queue=VASP_QUEUE)
def run_vasp(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    job_id = payload["job_id"]
    job_path = create_vasp_job_dir(job_id)
    log_file = vasp_log_path(job_id)

    meta = read_vasp_meta(job_id)
    meta["job_status"] = "STARTED"
    meta["started_at"] = now_iso()
    write_vasp_meta(job_id, meta)

    nproc = int(payload.get("nproc", VASP_MAX_NPROC))
    endpoint_nproc = int(payload.get("endpoint_nproc", VASP_MAX_NPROC))
    vasp_exec = payload.get("vasp_exec", VASP_EXECUTABLE)
    run_mode = payload.get("run_mode", "standard")
    vtst_mode = str(payload.get("vtst_mode", VASP_VTST_DEFAULT_MODE)).strip() or VASP_VTST_DEFAULT_MODE
    if nproc < 1 or nproc > VASP_MAX_NPROC:
        raise RuntimeError(f"nproc must be between 1 and {VASP_MAX_NPROC}")
    if endpoint_nproc < 1 or endpoint_nproc > VASP_MAX_NPROC:
        raise RuntimeError(f"endpoint_nproc must be between 1 and {VASP_MAX_NPROC}")
    if vasp_exec not in VASP_ALLOWED_EXECUTABLES:
        raise RuntimeError(f"vasp executable '{vasp_exec}' is not allowed")
    if run_mode not in VASP_RUN_MODES:
        raise RuntimeError(f"unknown vasp run mode '{run_mode}'")
    if run_mode == "vtst_neb" and vtst_mode not in VASP_VTST_MODES:
        raise RuntimeError(f"unknown vtst mode '{vtst_mode}'")

    try:
        ensure_job_not_stopped(read_vasp_meta, job_id)

        if run_mode == "vtst_neb":
            vtst_result = run_vtst_neb_job(
                job_id=job_id,
                job_path=job_path,
                log_file=log_file,
                nproc=nproc,
                endpoint_nproc=endpoint_nproc,
                vasp_exec=vasp_exec,
                vtst_mode=vtst_mode,
            )
            return_code = int(vtst_result["return_code"])
        elif run_mode == "wannier_scf":
            return_code = run_wannier_scf_job(
                job_id=job_id,
                job_path=job_path,
                log_file=log_file,
                nproc=nproc,
                vasp_exec=vasp_exec,
            )
        elif run_mode in {"wannier", "wannier_post"}:
            prepare_wannier_post_inputs(job_id, job_path, log_file)
            return_code = run_wannier_job(
                job_id=job_id,
                job_path=job_path,
                log_file=log_file,
                nproc=nproc,
                vasp_exec=vasp_exec,
            )
        elif run_mode == "wannier_postw90":
            prepare_postw90_inputs(job_id, job_path, log_file)
            return_code = run_postw90_job(
                job_id=job_id,
                job_path=job_path,
                log_file=log_file,
                nproc=nproc,
            )
        else:
            return_code = run_standard_vasp_job(
                job_id=job_id,
                job_path=job_path,
                log_file=log_file,
                nproc=nproc,
                vasp_exec=vasp_exec,
            )
    except JobStopRequested as exc:
        mark_vasp_job_stopped(
            self,
            job_id=job_id,
            job_path=job_path,
            log_file=log_file,
            run_mode=run_mode,
            reason=str(exc),
        )

    meta = read_vasp_meta(job_id)
    meta["command_finished_at"] = now_iso()
    meta["return_code"] = return_code
    meta["run_mode"] = run_mode
    if run_mode == "vtst_neb":
        meta["vtst_images"] = vtst_result["images"]
        meta["vtst_final_dir"] = vtst_result["final_dir_name"]
        meta["vtst_mode"] = vtst_result["vtst_mode"]
    elif run_mode == "wannier_postw90":
        meta["metrics_status"] = "unsupported"
        meta["analysis_status"] = "unsupported"
        meta["available_output_files"] = list_existing_outputs(
            job_path, VASP_WANNIER_POSTW90_OUTPUT_FILES
        )
    elif run_mode in {"wannier", "wannier_scf", "wannier_post"}:
        meta["metrics_status"] = "unsupported"
        meta["available_output_files"] = list_existing_outputs(
            job_path,
            VASP_WANNIER_POST_OUTPUT_FILES
            if run_mode in {"wannier", "wannier_post"}
            else VASP_WANNIER_SCF_OUTPUT_FILES,
        )
    else:
        meta["available_output_files"] = list_existing_outputs(
            job_path, VASP_STANDARD_OUTPUT_FILES
        )
    write_vasp_meta(job_id, meta)

    if return_code != 0:
        meta = read_vasp_meta(job_id)
        meta["job_status"] = "FAILURE"
        meta["finished_at"] = now_iso()
        write_vasp_meta(job_id, meta)
        raise RuntimeError(f"vasp failed with code {return_code}")

    try:
        ensure_job_not_stopped(read_vasp_meta, job_id)

        if run_mode == "standard":
            try:
                from .vasp_postprocess import postprocess_vasp

                metrics = postprocess_vasp(job_id, job_path)
                meta = read_vasp_meta(job_id)
                meta["metrics_path"] = str(job_path / HDF5_METRICS_FILENAME)
                meta["metrics_status"] = metrics.get("status", "ok")
                meta["available_output_files"] = metrics.get(
                    "download_files",
                    list_existing_outputs(job_path, VASP_STANDARD_OUTPUT_FILES),
                )
                write_vasp_meta(job_id, meta)
            except Exception as exc:
                meta = read_vasp_meta(job_id)
                meta["metrics_status"] = "failed"
                meta["metrics_error"] = str(exc)
                write_vasp_meta(job_id, meta)
                with log_file.open("a", encoding="utf-8") as f:
                    f.write(f"vasp postprocess failed: {exc}\n")
        elif run_mode == "vtst_neb":
            try:
                from .vtst_postprocess import postprocess_vtst

                vtst_metrics = postprocess_vtst(job_id, job_path, read_vasp_meta(job_id))
                meta = read_vasp_meta(job_id)
                meta["metrics_path"] = str(job_path / VTST_METRICS_FILENAME)
                meta["metrics_status"] = vtst_metrics.get("status", "ok")
                meta["available_output_files"] = vtst_metrics.get("download_files", [])
                write_vasp_meta(job_id, meta)
            except Exception as exc:
                meta = read_vasp_meta(job_id)
                meta["metrics_status"] = "failed"
                meta["metrics_error"] = str(exc)
                meta["available_output_files"] = list_existing_outputs(
                    job_path, VASP_VTST_OUTPUT_FILES
                )
                write_vasp_meta(job_id, meta)
                with log_file.open("a", encoding="utf-8") as f:
                    f.write(f"vtst postprocess failed: {exc}\n")
        elif run_mode in {"wannier", "wannier_post"}:
            try:
                from .wannier_postprocess import postprocess_wannier

                wannier_metrics = postprocess_wannier(job_id, job_path, read_vasp_meta(job_id))
                meta = read_vasp_meta(job_id)
                meta["metrics_path"] = str(job_path / WANNIER_METRICS_FILENAME)
                meta["metrics_status"] = wannier_metrics.get("status", "ok")
                meta["analysis_status"] = "unsupported"
                meta["available_output_files"] = wannier_metrics.get(
                    "download_files",
                    list_existing_outputs(job_path, VASP_WANNIER_POST_OUTPUT_FILES),
                )
                write_vasp_meta(job_id, meta)
            except Exception as exc:
                meta = read_vasp_meta(job_id)
                meta["metrics_status"] = "failed"
                meta["metrics_error"] = str(exc)
                meta["analysis_status"] = "unsupported"
                meta["available_output_files"] = list_existing_outputs(
                    job_path, VASP_WANNIER_POST_OUTPUT_FILES
                )
                write_vasp_meta(job_id, meta)
                with log_file.open("a", encoding="utf-8") as f:
                    f.write(f"wannier postprocess failed: {exc}\n")
        elif run_mode == "wannier_postw90":
            try:
                from .postw90_postprocess import postprocess_postw90

                postw90_metrics = postprocess_postw90(job_id, job_path, read_vasp_meta(job_id))
                meta = read_vasp_meta(job_id)
                meta["metrics_path"] = str(job_path / POSTW90_METRICS_FILENAME)
                meta["metrics_status"] = postw90_metrics.get("status", "ok")
                meta["analysis_status"] = "unsupported"
                meta["available_output_files"] = postw90_metrics.get(
                    "download_files",
                    list_existing_outputs(job_path, VASP_WANNIER_POSTW90_OUTPUT_FILES),
                )
                write_vasp_meta(job_id, meta)
            except Exception as exc:
                meta = read_vasp_meta(job_id)
                meta["metrics_status"] = "failed"
                meta["metrics_error"] = str(exc)
                meta["analysis_status"] = "unsupported"
                meta["available_output_files"] = list_existing_outputs(
                    job_path, VASP_WANNIER_POSTW90_OUTPUT_FILES
                )
                write_vasp_meta(job_id, meta)
                with log_file.open("a", encoding="utf-8") as f:
                    f.write(f"postw90 postprocess failed: {exc}\n")
        else:
            meta = read_vasp_meta(job_id)
            meta["metrics_status"] = "unsupported"
            meta["analysis_status"] = "unsupported"
            meta["available_output_files"] = list_existing_outputs(
                job_path,
                VASP_WANNIER_POST_OUTPUT_FILES
                if run_mode in {"wannier", "wannier_post"}
                else VASP_WANNIER_SCF_OUTPUT_FILES,
            )
            write_vasp_meta(job_id, meta)
    except JobStopRequested as exc:
        mark_vasp_job_stopped(
            self,
            job_id=job_id,
            job_path=job_path,
            log_file=log_file,
            run_mode=run_mode,
            reason=str(exc),
        )

    meta = read_vasp_meta(job_id)
    meta["job_status"] = "SUCCESS"
    meta["finished_at"] = now_iso()
    write_vasp_meta(job_id, meta)

    return {"job_id": job_id, "return_code": return_code}
