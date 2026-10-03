# Reproducibility and scope

MatterMind connects materials-generation and first-principles tools through a common interface, job system, structured results, and AI-assisted interpretation. Its contribution is the workflow and analysis layer. The external engines retain responsibility for the underlying generation and numerical calculations.

## Read the publication and implementation together

The [journal article](https://doi.org/10.1002/mgea.70075) records an earlier stage of MatterMind. The supplied expanded manuscript describes the later React/FastAPI/Celery/Redis implementation and broader HDF5, NEB, Wannier, and postw90 workflows reflected in this source tree. These are different research artifacts and should be identified separately when cited or compared.

For deployment, the source and [setup guide](SETUP.md) are the operational reference:

| Concern | This repository's implementation |
| --- | --- |
| Interface | React 18 with Vite |
| API | FastAPI |
| Queued execution | Celery with Redis as broker and result backend; separate MatterGen and VASP queues |
| Persistent job data | Filesystem directories containing job metadata, logs, metrics, analysis, and chat |
| Streaming | Server-sent events for logs and streamed responses |
| Optional language-model access | OpenAI-compatible client configured with `DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL`, and `DASHSCOPE_MODEL` |

Descriptions of MongoDB, Ollama, or WebSocket components in the earlier journal architecture are not installation requirements for this checkout. The current code does not implement those services. This reflects project evolution; it is not a claim that the historical implementation used the current stack.

## What can be reproduced from the repository

The repository provides the interface, API, execution orchestration, postprocessing code, and dependency specifications. It does not provide a turnkey, frozen scientific environment. Full calculations additionally require:

- The appropriate external engine and, where relevant, a license, compiled binary, MPI runtime, GPU stack, or model checkpoint.
- Valid inputs, pseudopotentials, and job settings appropriate to the material and scientific question.
- Matching parser versions, numerical settings, and available compute resources.
- A configured external language-model service if AI interpretation is requested.

The worker dependency specifications intentionally differ. The MatterGen worker uses NumPy below version 2; the VASP worker uses NumPy 2.x and a newer py4vasp range. Dependency ranges are not lockfiles. MatterGen feature extraction and rendering have optional matminer, DScribe, and OVITO dependencies that are not installed by the supplied worker requirement file.

The documentation and project-site update did not re-run model inference, VASP, VTST, Wannier90, or postw90 calculations. Existing paper figures, interface captures, and reported examples demonstrate the supplied research record; they are not fresh benchmark runs on the documentation build machine. A frontend build or successful API health check is not scientific validation.

## Preserve evidence for each run

Archive the repository commit, resolved Python and frontend package versions, engine build/version, MPI and hardware details, complete numerical input settings, and all applicable random seeds and checkpoint identifiers. Keep `job.json`, `job.log`, original scientific outputs, and the derived metrics together. Record the language-model name and endpoint configuration when retaining an AI interpretation; keep credentials out of the archive.

Useful implementation entry points:

| File | Responsibility |
| --- | --- |
| [`backend/app/main.py`](../backend/app/main.py) | Submission, job inspection, uploads/downloads, streamed logs, analysis, and chat |
| [`backend/app/tasks.py`](../backend/app/tasks.py) | MatterGen and VASP-family execution, source-job derivation, and postprocessing dispatch |
| [`backend/app/postprocess.py`](../backend/app/postprocess.py) | Crystal geometry, symmetry, structure deduplication, optional descriptors/rendering; source extxyz SHA-256 |
| [`backend/app/vasp_postprocess.py`](../backend/app/vasp_postprocess.py) | HDF5/XML parsing, crystallographic summaries, plots, and calculation quality checks |
| [`backend/app/vtst_postprocess.py`](../backend/app/vtst_postprocess.py) | NEB image/path evidence, barrier and force summaries, and quality flags |
| [`backend/app/wannier_postprocess.py`](../backend/app/wannier_postprocess.py) | Wannier centers/spreads, tight-binding summaries, and available visualizations |
| [`backend/app/postw90_postprocess.py`](../backend/app/postw90_postprocess.py) | Derived-property output parsing and plots |
| [`backend/app/ai_analysis.py`](../backend/app/ai_analysis.py) | Workflow-specific prompts and compatible-API calls |

Generated outputs are written under `RESULTS_BASE_DIR` and `VASP_RESULTS_BASE_DIR`. The code persists timestamps, task metadata, logs, and metrics on disk. MatterGen postprocessing also records the SHA-256 of its source extxyz file and versions for several parsing tools. These support provenance, but they do not constitute a complete environment snapshot for every engine.

## Interpret results within their limits

Task completion and scientific validity are separate checks. A task can finish while optional postprocessing is degraded or a particular output is unavailable. Inspect metric `status`, warnings, quality flags, convergence evidence, and the original engine output. A missing property is not a zero, and a generated candidate is not automatically a stable, synthesizable, or experimentally verified material.

For NEB, inspect endpoint preparation, force convergence, image count, and the sampled energy path before using a barrier. For Wannier and derived-property calculations, inspect model convergence, the chosen subspace and projections, interpolation quality, sampling, and module-specific assumptions. For example, the BoltzWann interface exposes transport calculations in the relaxation-time approximation. Available plots depend on the actual files and information produced by each run.

AI-generated analysis is an interpretation of the available metrics and conversation context. It is not an independent calculation or a substitute for convergence tests and domain review. Reproducing prose also depends on the endpoint, model version, prompt, and inference settings; a model identifier alone does not guarantee identical text.

## Artifact and licensing boundaries

The public source excludes the local `Experiment Data/` directory, runtime results, environment files, and licensed/heavy scientific artifacts through its ignore rules. Do not assume every paper experiment or original job directory is distributed in this repository. Selected figures or demonstration assets should retain their own provenance and captions.

No source-code license has been added by this documentation update. Public visibility does not itself grant a software license. The journal article, author manuscript, upstream projects, VASP executables, and pseudopotentials have their own rights and terms; an article's license does not automatically apply to this code or to third-party inputs. Consult the authors regarding reuse where a software license is needed.
