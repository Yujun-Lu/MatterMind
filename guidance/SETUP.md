# Run MatterMind

This guide describes the code in this repository: a React/Vite interface, a FastAPI API, and separate Celery workers for MatterGen and VASP-family jobs. Use Linux for the execution services. The launch commands below are derived from the source; a complete scientific installation and calculation have not been re-run for this documentation update.

## Choose what to run

| Component | What you need |
| --- | --- |
| Interface | Node.js 18 or later; npm |
| API and queue | Python 3.10, Redis, `requirements-common.txt` |
| Crystal generation | A working MatterGen installation, its model checkpoints and compatible compute environment; `requirements-mattergen-worker.txt` |
| VASP workflows | A licensed VASP installation, MPI, user-supplied inputs and pseudopotentials; `requirements-vasp-worker.txt` |
| NEB | A VASP build configured for the requested VTST calculation, and VTST scripts including `nebmake.pl` and `nebresults.pl` |
| Wannier workflows | A compatible VASP/Wannier setup, `wannier90.x`, and `postw90.x` for the applicable property modules |
| AI interpretation | An OpenAI-compatible endpoint configured through the `DASHSCOPE_*` variables |

The site and interface can be viewed independently of the scientific engines. Executing a job requires that job's engine, inputs, and worker. VASP binaries and licensed `POTCAR` files are not distributed here.

## 1. Prepare the Python environments

Clone the repository and run these commands from its root. `python3.10` must already be installed.

```bash
python3.10 -m venv .venv/api
.venv/api/bin/python -m pip install -r backend/requirements-common.txt

python3.10 -m venv .venv/vasp
.venv/vasp/bin/python -m pip install -r backend/requirements-vasp-worker.txt
```

Install MatterGen according to its own installation instructions in a **separate environment**. Activate that environment and add MatterMind's worker dependencies from this repository root:

```bash
source /absolute/path/to/mattergen-environment/bin/activate
python -m pip install -r backend/requirements-mattergen-worker.txt
command -v mattergen-generate
```

Use your environment manager's activation command if MatterGen is installed through Conda or another manager. `mattergen-generate` must be on the MatterGen worker's `PATH`, and `MATTERGEN_REPO` must identify its working checkout.

Do not combine the two worker requirement files in one environment: the MatterGen file requires `numpy<2`, while the VASP file requires `numpy>=2,<3`. The older combined `backend/requirements.txt` also has different NumPy and py4vasp constraints; use the split files for the split-worker setup documented here. These are dependency ranges, not frozen, tested environment lockfiles.

MatterGen's optional feature and rendering stages also use **matminer**, **DScribe**, and **OVITO**. They are not included in the worker requirement file. Install compatible versions in the MatterGen environment if you need Magpie features, SOAP descriptors, or rendered structure images. The postprocessor records warnings and a degraded status when optional capabilities are unavailable.

## 2. Configure the services

Create `backend/.env.local` with the following shell-compatible contents and replace the absolute paths with your installation paths. This file is ignored by Git. The API and both workers must load the same results directories and Redis configuration.

```bash
MATTERMIND_ROOT="/absolute/path/to/MatterMind"
REDIS_URL="redis://127.0.0.1:6379/0"
MATTERGEN_QUEUE="mattergen"
VASP_QUEUE="vasp"

MATTERGEN_REPO="/absolute/path/to/MatterGen"
RESULTS_BASE_DIR="$MATTERMIND_ROOT/results/mattergen"
VASP_RESULTS_BASE_DIR="$MATTERMIND_ROOT/results/vasp"
TMPDIR="$MATTERMIND_ROOT/tmp"
PIP_CACHE_DIR="$MATTERMIND_ROOT/.cache/pip"
XDG_CACHE_HOME="$MATTERMIND_ROOT/.cache"
HF_ENDPOINT="https://huggingface.co"

VASP_HDF5_HOME="/absolute/path/to/vasp-hdf5"
VASP_PLAIN_HOME="/absolute/path/to/vasp-plain"
HDF5_LIB="/absolute/path/to/hdf5/lib"
VTST_SCRIPTS_DIR="/absolute/path/to/vtst-scripts"
WANNIER90_HOME="/absolute/path/to/wannier90"
VASP_EXECUTABLE="vasp_std"
VASP_MAX_NPROC="16"

AUTO_ANALYSIS="false"
```

Only the paths for workflows you execute must point to working scientific installations. The VASP worker constructs the binary path as `${VASP_HDF5_HOME}/bin/${VASP_EXECUTABLE}` or `${VASP_PLAIN_HOME}/bin/${VASP_EXECUTABLE}`. `WANNIER90_HOME` must directly contain `wannier90.x` and `postw90.x`; it is not assumed to have a `bin` subdirectory. `HDF5_LIB` is prepended to `LD_LIBRARY_PATH` for the applicable VASP runs. Set `VASP_MAX_NPROC` to the allocation available to the worker.

Load the configuration from the repository root and create writable directories:

```bash
set -a
source backend/.env.local
set +a
mkdir -p "$RESULTS_BASE_DIR" "$VASP_RESULTS_BASE_DIR" "$TMPDIR" "$PIP_CACHE_DIR" "$XDG_CACHE_HOME"
```

For optional AI interpretation, provide `DASHSCOPE_API_KEY` through your environment or local secret configuration. `DASHSCOPE_BASE_URL` selects the compatible API endpoint and `DASHSCOPE_MODEL` selects a model available to your account. The source defaults to DashScope; no key is bundled. Leave `AUTO_ANALYSIS=false` for generation without automatic AI analysis. On-demand analysis and chat still require a configured key and endpoint.

## 3. Start Redis, the API, and workers

Start your local Redis service using your installation's service manager. Confirm it responds with `PONG`:

```bash
redis-cli -u redis://127.0.0.1:6379/0 ping
```

Open a separate terminal for each process. Start each terminal in the repository root and load the configuration before starting the process.

**API**

```bash
set -a
source backend/.env.local
set +a
source .venv/api/bin/activate
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**MatterGen worker** — activate the environment where `mattergen-generate` is installed:

```bash
set -a
source backend/.env.local
set +a
source /absolute/path/to/mattergen-environment/bin/activate
cd backend
celery -A app.celery_app.celery_app worker -l info -c 1 \
  --prefetch-multiplier=1 -Q "$MATTERGEN_QUEUE" -n mattergen@%h
```

**VASP worker**

```bash
set -a
source backend/.env.local
set +a
source .venv/vasp/bin/activate
cd backend
celery -A app.celery_app.celery_app worker -l info -c 1 \
  --prefetch-multiplier=1 -Q "$VASP_QUEUE" -n vasp@%h
```

You can start only the worker needed for your workflow. The direct commands above preserve your configuration. The existing `run_api.sh`, `run_worker_*.sh`, and `run_all.sh` retain the original `/root/autodl-tmp/...` deployment layout. In particular, the service scripts overwrite several variables after loading an environment file and change to a hard-coded backend directory. Review and adapt those scripts before using them on a different machine.

## 4. Start the interface

From the repository root in another terminal:

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`. The example environment points `VITE_API_BASE` to `http://127.0.0.1:8000`. Change it if the browser accesses the API through a different address. Vite reads this variable at startup/build time, so restart or rebuild after changing it. A production interface build is available with `npm run build`.

The API responds at `http://127.0.0.1:8000/health` and exposes its generated API documentation at `http://127.0.0.1:8000/docs`. `/health` reports that the API process is responding; it does **not** verify Redis, workers, model checkpoints, or licensed engines.

This research application has no built-in account authentication and uses permissive CORS configuration. The commands bind the API and development interface to the local machine. A shared deployment needs an authenticated reverse proxy, suitable network controls, and a review of access to uploaded files, results, and AI requests.

## First scientific run

| Workflow | Starting inputs | Result evidence |
| --- | --- | --- |
| MatterGen | Model name; batch settings; optional conditioning and guidance | Generated structures, `metrics.json`, CIFs, optional feature/render outputs |
| Standard VASP | `INCAR`, `POSCAR`, `POTCAR`, `KPOINTS` | `HDF5_metrics.json`, VASP outputs, applicable plots |
| VTST NEB | `INCAR_neb`, `KPOINTS`, `POTCAR`, `POSCAR_i`, `POSCAR_f`; add `INCAR_endpoint` for `relax_first` | `vtst_metrics.json`, image energies, barrier/force plots |
| Wannier SCF → post | SCF input set; successful source SCF job plus a new post-processing `INCAR` | Wannier files, `wannier_metrics.json`, centers and available hopping/orbital visualizations |
| Derived property workflow | Successful Wannier post job with required intermediate files; selected module and parameters | `postw90_metrics.json`, applicable band/DOS/AHC/transport plots or Fermi-surface mesh |

Start with inputs already validated for your engines and compute environment. Inspect both the engine's logs and the postprocessor's warnings before interpreting a successful task as a scientifically valid result. See [Reproducibility and scope](REPRODUCIBILITY.md).
