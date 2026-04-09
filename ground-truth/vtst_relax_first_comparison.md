# VTST Ground-Truth Comparison

## Case Metadata

- Case: `Experiment Data/VASP/vtst_ground`
- Workflow: VTST NEB, `relax_first`
- Formula: `Sr2Ti2O5`
- NEB setup: `IMAGES = 3`, `LCLIMB = .TRUE.`, `NSW = 80`, `EDIFFG = -0.08`
- LLM input: `Experiment Data/VASP/vtst_ground/output/vtst_metrics.json`
- LLM output used for comparison: only the final answer block in `Experiment Data/VASP/vtst_ground/output/analysis.txt`
- Raw ground-truth files used here: `INCAR_neb`, `neb.dat`, `spline.dat`, `exts.dat`, `nebresults.txt`, `image_energy_table.csv`, `00-04/OUTCAR.gz`, `00-04/OSZICAR`, `endpoint_initial/OUTCAR`, `endpoint_final/OUTCAR`

## Method

Agreement was scored as `Full = 1.0`, `Partial = 0.5`, and `None = 0.0`.

The comparison below treats the raw VTST artifacts as authoritative whenever they disagree with `vtst_metrics.json`.

## Validation Table

| Module / Case | Ground-truth source | Evaluation target | Ground-truth value / conclusion | LLM interpretation | Agreement | Score | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| VTST, `vtst_ground` | `job.json`, `vtst_metrics.json`, `00-04/OUTCAR.gz` | Overall run credibility | The process exited successfully (`return_code = 0`), but the scientific result is degraded: images `01-03` did not reach the ionic criterion before `NSW = 80`, so this is not a validated converged NEB path. | The run has low credibility and should not be treated as a validated saddle-point search. | Full | 1.0 | Good high-level triage. The model focused on scientific reliability rather than only job success. |
| VTST, `vtst_ground` | `neb.dat`, `image_energy_table.csv`, `exts.dat`, `vtst_metrics.json` | Highest-energy image / TS image | Image `2` is the highest-energy image. `vtst_metrics.json` also reports `ts_image_index = 2`. | Highest-energy image is `Image 2`. | Full | 1.0 | Exact match. |
| VTST, `vtst_ground` | `neb.dat`, `exts.dat`, `image_energy_table.csv` | Raw barrier definition | The raw VTST energies are `0.000000, 0.044045, 0.960280, -0.094160, -0.116292` eV relative to image 0. This means the forward barrier from the initial state is `0.960280` eV, while `1.076572` eV is the full energy span between the highest point and the lower final endpoint. | The raw barrier is about `1.08 eV`. | Partial | 0.5 | The model repeated the `vtst_metrics.json` number correctly, but it used it as a generic "barrier" without separating forward barrier from full path energy span. |
| VTST, `vtst_ground` | `spline.dat`, `neb.dat`, `vtst_metrics.json`, `INCAR_neb` | Spline reliability | `barrier_spline_eV = 4.189969` is far larger than the raw VTST profile, while only `3` intermediate images were used. This is a strong sign of spline overfitting / undersampling. | The spline barrier is not trustworthy and mainly reflects severe undersampling / spline distortion. | Full | 1.0 | Correct diagnosis and appropriate caution. |
| VTST, `vtst_ground` | `neb.dat`, `structure_change_summary` in `vtst_metrics.json` | Path shape and continuity | The path is non-monotonic, rising to image `2` and then dropping below the initial state. Consecutive structure-matcher failures appear for pairs `[1, 2]` and `[2, 3]`, so the path is not structurally smooth. | The path is non-monotonic with an internal peak and significant structural discontinuities. | Full | 1.0 | Correct on both energy-profile shape and continuity warning. |
| VTST, `vtst_ground` | `nebresults.txt`, `image_energy_table.csv`, `INCAR_neb`, `00-04/OUTCAR.gz` | Convergence / force diagnosis | `nebresults.txt` reports force values of `0.000000` for every image and even emits gnuplot warnings about missing valid force points. `EDIFFG = -0.08` is loose for NEB. However, raw `OUTCAR.gz` shows images `00` and `04` reached required accuracy, while `01-03` did not. | The zero-force output likely reflects a parsing gap or incomplete termination; convergence is too loose, and all five images are treated as not finished. | Partial | 0.5 | The parser-gap explanation and loose-convergence warning are well supported. The overstatement is the claim that all five images failed; the endpoints did converge. |
| VTST, `vtst_ground` | `structure_change_summary` in `vtst_metrics.json`, `endpoint_initial/OUTCAR`, `endpoint_final/OUTCAR` | Mechanism-level interpretation | One oxygen moves by `2.611 A`; endpoint symmetry changes from `P4/mmm` to `Pmmm`; the TS image is `Pm`; endpoint fit is `false`. These facts support a large structural rearrangement, but they do not by themselves uniquely prove the exact mechanism. | The path likely reflects significant distortion / defect migration rather than a simple localized hop, and the final state may be a reconstructed configuration. | Partial | 0.5 | The caution is reasonable, but the mechanism wording is more specific than the raw evidence strictly requires. |

## Score Summary

- Total score: `5.5 / 7.0`
- Mean agreement score: `0.79`

Interpretation: for this VTST case, the LLM is strong at QC triage, identifying the unstable image, and recognizing when the path is not publication-ready. Its weaker points are barrier-definition precision and mechanism-level specificity when the raw outputs remain ambiguous.

## Important Ground-Truth Caveat

`vtst_metrics.json` contains the warning `exts.dat was not found or had no parseable points`, but `Experiment Data/VASP/vtst_ground/output/exts.dat` is present and contains parseable extrema for images `0-4`.

This looks like a metrics-parser defect, not an LLM error. For this reason, the raw VTST files were treated as authoritative whenever they disagreed with the generated summary JSON.
