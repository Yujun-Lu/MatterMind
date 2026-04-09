from __future__ import annotations

import os
from pathlib import Path

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MATTERGEN_QUEUE = os.getenv("MATTERGEN_QUEUE", "mattergen")
VASP_QUEUE = os.getenv("VASP_QUEUE", "vasp")

MATTERGEN_REPO = Path(os.getenv("MATTERGEN_REPO", "/root/autodl-tmp/MatterGen/mattergen"))
RESULTS_BASE_DIR = Path(os.getenv("RESULTS_BASE_DIR", "/root/autodl-tmp/mattergen-results"))
VASP_RESULTS_BASE_DIR = Path(os.getenv("VASP_RESULTS_BASE_DIR", "/root/autodl-tmp/vasp-tasks"))

TMPDIR = os.getenv("TMPDIR", "/root/autodl-tmp/tmp")
PIP_CACHE_DIR = os.getenv("PIP_CACHE_DIR", "/root/autodl-tmp/pip-cache")
XDG_CACHE_HOME = os.getenv("XDG_CACHE_HOME", "/root/autodl-tmp/.cache")
HF_ENDPOINT = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")

LOG_FILENAME = "job.log"
JOB_META_FILENAME = "job.json"
METRICS_FILENAME = "metrics.json"
HDF5_METRICS_FILENAME = "HDF5_metrics.json"
VTST_METRICS_FILENAME = "vtst_metrics.json"
WANNIER_METRICS_FILENAME = "wannier_metrics.json"
WANNIER_DETAILS_FILENAME = "wannier_details.json"
POSTW90_METRICS_FILENAME = "postw90_metrics.json"
ANALYSIS_FILENAME = "analysis.txt"
CHAT_FILENAME = "chat.json"

DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
DASHSCOPE_MODEL = os.getenv("DASHSCOPE_MODEL", "qwen3.6-plus")
AUTO_ANALYSIS = os.getenv("AUTO_ANALYSIS", "false")

HDF5_LIB = Path(os.getenv("HDF5_LIB", "/root/autodl-tmp/vasp/hdf5-1.14.5/build/lib"))
VASP_HDF5_HOME = Path(
    os.getenv("VASP_HDF5_HOME", "/root/autodl-tmp/vasp/vasp.6.5.0-hdf5")
)
VASP_PLAIN_HOME = Path(
    os.getenv("VASP_PLAIN_HOME", "/root/autodl-tmp/vasp/vasp.6.5.0")
)
VTST_SCRIPTS_DIR = Path(
    os.getenv("VTST_SCRIPTS_DIR", "/root/autodl-tmp/vasp/vtstscripts-1040")
)
WANNIER90_HOME = Path(
    os.getenv("WANNIER90_HOME", "/root/autodl-tmp/vasp/wannier90-3.1.0")
)
WANNIER_PLOT_FORMAT = os.getenv("WANNIER_PLOT_FORMAT", "cube").strip().lower() or "cube"
WANNIER_MAX_ORBITAL_PLOTS = int(os.getenv("WANNIER_MAX_ORBITAL_PLOTS", "12"))
VASP_MAX_NPROC = int(os.getenv("VASP_MAX_NPROC", "16"))
VASP_EXECUTABLE = os.getenv("VASP_EXECUTABLE", "vasp_std")
VASP_ALLOWED_EXECUTABLES = tuple(
    name.strip()
    for name in os.getenv(
        "VASP_ALLOWED_EXECUTABLES", "vasp_std,vasp_gam,vasp_ncl"
    ).split(",")
    if name.strip()
)
VASP_RUN_MODES = tuple(
    name.strip()
    for name in os.getenv(
        "VASP_RUN_MODES", "standard,vtst_neb,wannier_scf,wannier_post,wannier_postw90"
    ).split(",")
    if name.strip()
)
VASP_VTST_MODES = tuple(
    name.strip()
    for name in os.getenv("VASP_VTST_MODES", "pre_relaxed,relax_first").split(",")
    if name.strip()
)
VASP_VTST_DEFAULT_MODE = (
    os.getenv("VASP_VTST_DEFAULT_MODE", "pre_relaxed").strip() or "pre_relaxed"
)
VASP_STANDARD_REQUIRED_INPUTS = tuple(
    name.strip()
    for name in os.getenv(
        "VASP_STANDARD_REQUIRED_INPUTS", "INCAR,KPOINTS,POSCAR,POTCAR"
    ).split(",")
    if name.strip()
)
VASP_STANDARD_OPTIONAL_INPUTS = tuple(
    name.strip()
    for name in os.getenv("VASP_STANDARD_OPTIONAL_INPUTS", "CHGCAR,WAVECAR").split(",")
    if name.strip()
)
VASP_STANDARD_OUTPUT_FILES = tuple(
    name.strip()
    for name in os.getenv(
        "VASP_STANDARD_OUTPUT_FILES",
        (
            "vasprun.xml,vasp.out,OUTCAR,vaspout.h5,HDF5_metrics.json,"
            "plots/energy.png,plots/dos.png,plots/band.png,plots/phonon_dos.png,"
            "plots/phonon_band.png,plots/magnetism.png"
        ),
    ).split(",")
    if name.strip()
)
VASP_VTST_PRE_RELAXED_REQUIRED_INPUTS = tuple(
    name.strip()
    for name in os.getenv(
        "VASP_VTST_PRE_RELAXED_REQUIRED_INPUTS",
        "INCAR_neb,KPOINTS,POTCAR,POSCAR_i,POSCAR_f",
    ).split(",")
    if name.strip()
)
VASP_VTST_RELAX_FIRST_REQUIRED_INPUTS = tuple(
    name.strip()
    for name in os.getenv(
        "VASP_VTST_RELAX_FIRST_REQUIRED_INPUTS",
        "INCAR_neb,INCAR_endpoint,KPOINTS,POTCAR,POSCAR_i,POSCAR_f",
    ).split(",")
    if name.strip()
)
VASP_VTST_REQUIRED_INPUTS = VASP_VTST_RELAX_FIRST_REQUIRED_INPUTS
VASP_VTST_OPTIONAL_INPUTS = tuple(
    name.strip()
    for name in os.getenv("VASP_VTST_OPTIONAL_INPUTS", "CHGCAR,WAVECAR").split(",")
    if name.strip()
)
VASP_VTST_OUTPUT_FILES = tuple(
    name.strip()
    for name in os.getenv(
        "VASP_VTST_OUTPUT_FILES",
        (
            "vasprun.xml,vasp.out,OUTCAR,vaspout.h5,neb.dat,spline.dat,exts.dat,"
            "nebresults.txt,POSCAR_initial,POSCAR_final,"
            "endpoint_initial_vasp.out,endpoint_initial_OUTCAR,endpoint_initial_vasprun.xml,"
            "endpoint_initial_vaspout.h5,endpoint_final_vasp.out,endpoint_final_OUTCAR,"
            "endpoint_final_vasprun.xml,endpoint_final_vaspout.h5,vtst_metrics.json,"
            "image_energy_table.csv,plots/barrier_raw.png,plots/barrier_spline.png,"
            "plots/force_along_path.png,plots/reaction_movie.gif,plots/endpoint_vs_ts.png"
        ),
    ).split(",")
    if name.strip()
)
VASP_WANNIER_SCF_REQUIRED_INPUTS = tuple(
    name.strip()
    for name in os.getenv(
        "VASP_WANNIER_SCF_REQUIRED_INPUTS",
        "INCAR,KPOINTS,POSCAR,POTCAR",
    ).split(",")
    if name.strip()
)
VASP_WANNIER_SCF_OPTIONAL_INPUTS = tuple(
    name.strip()
    for name in os.getenv("VASP_WANNIER_SCF_OPTIONAL_INPUTS", "").split(",")
    if name.strip()
)
VASP_WANNIER_SCF_OUTPUT_FILES = tuple(
    name.strip()
    for name in os.getenv(
        "VASP_WANNIER_SCF_OUTPUT_FILES",
        (
            "vasprun.xml,vasp.out,OUTCAR,vaspout.h5,WAVECAR,CHGCAR,CONTCAR,OSZICAR,EIGENVAL,DOSCAR"
        ),
    ).split(",")
    if name.strip()
)
VASP_WANNIER_POST_REQUIRED_INPUTS = tuple(
    name.strip()
    for name in os.getenv("VASP_WANNIER_POST_REQUIRED_INPUTS", "INCAR").split(",")
    if name.strip()
)
VASP_WANNIER_POST_OPTIONAL_INPUTS = tuple(
    name.strip()
    for name in os.getenv("VASP_WANNIER_POST_OPTIONAL_INPUTS", "").split(",")
    if name.strip()
)
VASP_WANNIER_POST_OUTPUT_FILES = tuple(
    name.strip()
    for name in os.getenv(
        "VASP_WANNIER_POST_OUTPUT_FILES",
        (
            "vasprun.xml,vasp.out,OUTCAR,"
            "wannier90.win,wannier90.mmn,wannier90.amn,wannier90.eig,wannier90.nnkp,"
            "wannier90.wout,wannier90.chk,wannier90_hr.dat,wannier90_r.dat,wannier90_tb.dat,"
            "wannier90_centres.xyz,wannier_metrics.json,wannier_details.json,"
            "wannier_centers.xyz,hamiltonian.json,"
            "hopping_graph.json,plots/wannier_centers_overlay.png,plots/wf_overview.png,"
            "plots/hopping_vs_distance.png,plots/hopping_pair_heatmap.png,"
            "plots/hopping_graph.png,plots/hopping_truncation.png"
        ),
    ).split(",")
    if name.strip()
)
VASP_WANNIER_POSTW90_REQUIRED_INPUTS = tuple(
    name.strip()
    for name in os.getenv("VASP_WANNIER_POSTW90_REQUIRED_INPUTS", "").split(",")
    if name.strip()
)
VASP_WANNIER_POSTW90_OPTIONAL_INPUTS = tuple(
    name.strip()
    for name in os.getenv("VASP_WANNIER_POSTW90_OPTIONAL_INPUTS", "").split(",")
    if name.strip()
)
VASP_WANNIER_POSTW90_OUTPUT_FILES = tuple(
    name.strip()
    for name in os.getenv(
        "VASP_WANNIER_POSTW90_OUTPUT_FILES",
        (
            "postw90.out,postw90_metrics.json,wannier90.win,wannier90.chk,wannier90_hr.dat,"
            "wannier90_r.dat,wannier90_tb.dat,wannier90.bxsf,wannier90.wpout,"
            "plots/postw90_band.png,plots/postw90_dos.png,plots/postw90_ahc.png,"
            "plots/postw90_seebeck.png,plots/postw90_elcond.png,plots/postw90_boltzdos.png"
        ),
    ).split(",")
    if name.strip()
)
VASP_REQUIRED_INPUTS = VASP_STANDARD_REQUIRED_INPUTS
VASP_OPTIONAL_INPUTS = VASP_STANDARD_OPTIONAL_INPUTS
VASP_OUTPUT_FILES = VASP_STANDARD_OUTPUT_FILES
VASP_QC_FORCE_THRESHOLD = float(os.getenv("VASP_QC_FORCE_THRESHOLD", "0.10"))
VASP_QC_STRESS_THRESHOLD_KBAR = float(
    os.getenv("VASP_QC_STRESS_THRESHOLD_KBAR", "10.0")
)

ALLOWED_ARTIFACTS = (
    "generated_crystals.extxyz",
    "generated_trajectories.zip",
    "generated_crystals_cif.zip",
)
