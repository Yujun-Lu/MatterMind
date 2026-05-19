<div align="center">

# MatterMind

### An LLM-assisted AI4Science workspace for crystal generation, first-principles simulation, and intelligent materials analysis.



<br>

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Frontend](https://img.shields.io/badge/Frontend-React%20%2B%20Vite-61DAFB)
![Backend](https://img.shields.io/badge/Backend-FastAPI-009688)
![Queue](https://img.shields.io/badge/Queue-Celery%20%2B%20Redis-brightgreen)
![AI4Science](https://img.shields.io/badge/AI4Science-Materials%20Discovery-purple)
![Status](https://img.shields.io/badge/Status-Research%20Prototype-orange)

</div>

---

## Overview

**MatterMind** is a unified web workspace designed to reduce the friction between generative materials design, first-principles simulation, automated post-processing, and AI-assisted interpretation.

Instead of treating crystal generation, DFT calculation, NEB analysis, Wannier workflows, transport analysis, and result interpretation as disconnected scripts, MatterMind brings them into one traceable and interactive platform.

It currently supports:

- **MatterGen Studio** for crystal generation and structure analysis
- **VASP Studio** for first-principles calculation workflows
- **VTST NEB workflows** for transition-state and energy-barrier analysis
- **Wannier90 / postw90 workflows** for band, DOS, Berry, Fermi-surface, and transport analysis
- **LLM-assisted result interpretation** through an OpenAI-compatible DashScope API interface
- **Real-time logs, job tracking, artifact downloads, and follow-up scientific chat**

> This repository contains the orchestration layer and web UI. It does **not** include proprietary binaries, licensed pseudopotentials, or private experiment data.

---

## Demo Videos

### VASP Studio

https://github.com/user-attachments/assets/8375afbe-3c6c-49a6-a2cb-4fb44e15b42c

### MatterGen Studio

https://github.com/user-attachments/assets/43bf0146-9f53-4edc-ae49-213472dfef97

---

## Why MatterMind?

Materials research workflows often require researchers to move across isolated tools, command-line scripts, raw output files, plotting utilities, and manual interpretation. This makes the process difficult to reproduce, difficult to teach, and difficult to scale.

MatterMind aims to make this workflow more accessible by building a bridge between:

| Layer | Capability |
|---|---|
| Generative design | MatterGen-based crystal generation |
| First-principles simulation | VASP calculation orchestration |
| Reaction/path analysis | VTST NEB workflow support |
| Electronic structure analysis | Wannier90 and postw90 workflows |
| Automated post-processing | Structured metrics, plots, and downloadable artifacts |
| Scientific reasoning | LLM-assisted analysis and follow-up chat |
| User interaction | Web-based UI with real-time logs |

The goal is not to replace expert judgment, but to make complex materials workflows more transparent, reproducible, and easier to operate.

---

## Core Features

### MatterGen Studio

- Launch unconditional or property-conditioned MatterGen generation jobs
- Support conditioning targets such as:
  - chemical system
  - space group
  - band gap
  - magnetic density
  - bulk modulus
  - multi-condition generation
- Parse generated structures and collect metrics
- Export generated crystals, CIF files, images, and result artifacts
- Generate AI-assisted analysis from `metrics.json`
- Continue scientific discussion through follow-up chat

### VASP Studio

- Run standard VASP HDF5 workflows
- Upload and manage standard VASP input files
- Stream real-time calculation logs
- Generate structured post-processing results and plots
- Run AI-assisted analysis on processed results
- Download calculation artifacts

### VTST NEB Workflows

- Support both `pre_relaxed` and `relax_first` modes
- Manage endpoint and NEB image inputs
- Stream NEB calculation logs
- Parse barrier data and NEB metrics
- Generate barrier plots and structured analysis

### Wannier90 and postw90 Workflows

- Run Wannier SCF workflows
- Launch Wannier post-processing from successful SCF jobs
- Launch postw90 workflows from successful Wannier jobs
- Current postw90 modules include:
  - band interpolation
  - density of states
  - Berry curvature / anomalous Hall conductivity
  - Fermi surface
  - BoltzWann transport

### AI-Assisted Interpretation

- Analyze MatterGen, VASP, VTST, Wannier, and postw90 outputs
- Generate structured scientific summaries
- Support follow-up question answering based on saved analysis context
- Use OpenAI-compatible APIs through DashScope-compatible endpoints

---

## System Architecture

```text
frontend/
React + Vite single-page application
        |
        v
backend/
FastAPI API server
        |
        +--> Celery worker for MatterGen jobs
        |
        +--> Celery worker for VASP / VTST / Wannier / postw90 jobs
        |
        v
Redis
message broker and task backend
        |
        v
External scientific tools
MatterGen CLI / VASP / VTST scripts / Wannier90 / postw90 / mpirun
```

---

## Repository Layout

```text
.
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── tasks.py
│   │   ├── vasp_postprocess.py
│   │   ├── vtst_postprocess.py
│   │   ├── wannier_postprocess.py
│   │   └── postw90_postprocess.py
│   ├── run_api.sh
│   ├── run_worker.sh
│   ├── run_worker_mattergen.sh
│   └── run_worker_vasp.sh
│
├── frontend/
│   ├── src/
│   ├── package.json
│   └── .env.example
│
├── images/
├── run_all.sh
└── README.md
```

---

## Tech Stack

| Component | Technology |
|---|---|
| Frontend | React 18, Vite, react-markdown |
| Backend API | FastAPI, Uvicorn |
| Task queue | Celery, Redis |
| Materials processing | ASE, pymatgen, spglib, SeeK-path, py4vasp |
| Visualization | matplotlib and generated workflow plots |
| AI analysis | OpenAI-compatible client with DashScope-compatible endpoint |
| External engines | MatterGen, VASP, VTST, Wannier90, postw90 |

---

## Quick Start

### 1. Prerequisites

Recommended environment:

- Linux
- Python 3.10
- Node.js 18+
- Redis
- `tmux`
- `mpirun`

External scientific software required but not included:

- MatterGen
- VASP
- VTST scripts
- Wannier90 / postw90

> VASP binaries, licensed pseudopotentials such as `POTCAR`, and private experiment data are intentionally excluded from this repository.

### 2. Install Dependencies

Backend API environment:

```bash
pip install -r backend/requirements.txt
```

MatterGen worker environment:

```bash
pip install -r backend/requirements-mattergen-worker.txt
```

VASP worker environment:

```bash
pip install -r backend/requirements-vasp-worker.txt
```

Frontend:

```bash
cd frontend
npm install
```

### 3. Configure Environment

The provided shell scripts are currently designed for a Linux server layout and default to paths under:

```bash
/root/autodl-tmp/
```

At minimum, review or override:

```bash
REDIS_URL
MATTERGEN_REPO
RESULTS_BASE_DIR
VASP_RESULTS_BASE_DIR
VASP_HDF5_HOME
VASP_PLAIN_HOME
VTST_SCRIPTS_DIR
WANNIER90_HOME
VASP_EXECUTABLE
VASP_MAX_NPROC
```

For AI analysis and chat:

```bash
DASHSCOPE_API_KEY
DASHSCOPE_BASE_URL
DASHSCOPE_MODEL
```

Frontend API base:

```bash
VITE_API_BASE=http://127.0.0.1:8000
```

### 4. Start Services

Start the API server:

```bash
bash backend/run_api.sh
```

Start the workers:

```bash
bash backend/run_worker.sh both
```

Start the frontend:

```bash
cd frontend
npm run dev
```

If your environment matches the scripted layout, you can also run:

```bash
bash run_all.sh
```

`run_all.sh` starts the API server, workers, and frontend together, and attaches to a `tmux` session when available.

---

## Workflow Examples

### MatterGen Workflow

```text
Select model
   ↓
Set optional conditioning targets
   ↓
Launch crystal generation
   ↓
Inspect structures, metrics, images, and downloadable artifacts
   ↓
Run AI-assisted analysis and follow-up chat
```

### VASP Workflow

```text
Upload INCAR / POSCAR / POTCAR / KPOINTS
   ↓
Launch standard VASP HDF5 calculation
   ↓
Stream logs and monitor job status
   ↓
Review post-processed metrics and plots
   ↓
Run AI-assisted analysis
```

### Wannier / postw90 Workflow

```text
Run Wannier SCF job
   ↓
Launch Wannier post-processing
   ↓
Run postw90 modules
   ↓
Analyze band, DOS, Berry, Fermi surface, or transport outputs
```

---

## API Overview

Main endpoint groups:

```text
/api/jobs*        MatterGen workflows
/api/vasp/jobs*   VASP-family workflows
/health           service health check
```

The backend supports:

- job submission
- job listing and detail lookup
- log streaming
- metrics retrieval
- AI analysis generation
- chat history and streaming replies
- artifact downloads
- VASP job stop requests

---

## Important Notes

- This repository does not include VASP binaries.
- This repository does not include Wannier90 binaries.
- Licensed pseudopotentials such as `POTCAR` are not distributed.
- Heavy raw calculation outputs and private experiment files are excluded from version control.
- The launch scripts are currently Linux/HPC oriented.
- AI analysis is optional. Core job orchestration can run without LLM access.

---

## Roadmap

- [ ] Add more complete deployment documentation
- [ ] Add Docker-based deployment option
- [ ] Add example input files without licensed content
- [ ] Add more screenshots for each workflow
- [ ] Add benchmark examples for MatterGen and VASP outputs
- [ ] Add documentation for prompt templates
- [ ] Improve multi-user project management
- [ ] Add more scientific workflow templates

---

## Citation

If you use MatterMind in academic work, please cite this repository or contact the author for citation information.

```bibtex
@software{mattermind2026,
  title  = {MatterMind: An LLM-Assisted Platform for Crystal Generation, Materials Simulation, and AI-Guided Analysis},
  author = {Lu, Yujun},
  year   = {2026},
  url    = {https://github.com/Yujun-Lu/MatterMind}
}
```

---

## Contact

For questions, suggestions, or collaboration opportunities, please open an issue on GitHub.

---

<div align="center">

**MatterMind turns fragmented materials workflows into an interactive AI4Science cockpit.**

</div>
