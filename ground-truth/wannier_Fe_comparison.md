# Fe Wannier Ground-Truth Comparison

## Case Metadata

- Case root: `Experiment Data/VASP/wannier_Fe_ground`
- Material: bcc Fe with SOC-enabled Wannier workflow
- Subcases included here:
  - `1. post wannier/2. wannier post`
  - `2. berry and ahc`
  - `3. fermi surface`
- LLM inputs:
  - `wannier_metrics.json` for the Wannier post case
  - `postw90_metrics.json` for the Berry / AHC case
  - `postw90_metrics.json` for the Fermi-surface case
- LLM outputs used for comparison: only the final answer blocks in the three `analysis.txt` files

## Method

Agreement was scored as `Full = 1.0`, `Partial = 0.5`, and `None = 0.0`.

Whenever a generated metrics JSON disagreed with raw Wannier / postw90 artifacts, the raw files were treated as authoritative.

## Validation Table

| Module / Case | Ground-truth source | Evaluation target | Ground-truth value / conclusion | LLM interpretation | Agreement | Score | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Wannier post, Fe SOC | `wannier90.wout`, `INCAR`, `wannier90.win`, `job.json` | Overall run quality and meaning of `degraded` | The run completed and reached a final Wannier state. The raw warning is `Maximum number of disentanglement iterations reached`. `LSORBIT = .TRUE.` is active and both `LWRITE_UNK` and `wannier_plot` remain commented out, so missing volumetric plots are expected rather than a failure. | The Wannierisation is reliable despite a `degraded` status, and the degraded label comes from the disentanglement warning plus deliberately skipped volumetric plots under SOC. | Full | 1.0 | Strong interpretation of what the warning does and does not mean. |
| Wannier post, Fe SOC | `wannier90.wout` final-state block | Quantitative spread statistics | The final state contains `18` Wannier functions with average spread `0.9096 A^2`, max spread `1.8236 A^2`, and `6` functions above `1.5 A^2`; none exceed `2.0 A^2`. | The model is well localized, but the answer quotes `average_spread = 0.911`, `max_spread = 1.998`, and `1215` functions above `1.5 A^2`. | Partial | 0.5 | The qualitative verdict is right, but several quantitative details were inherited from a faulty summary instead of the raw final-state block. |
| Wannier post, Fe SOC | `wannier90.wout` final-state block, `wannier90_centres.xyz` | Center localization on the Fe site | The final-state centers remain extremely close to the single Fe site. In the raw final-state block, the largest center radius is about `6.61e-4 A`. | The centers are exceptionally tight and chemically plausible, but the answer quotes a larger `max_center_offset_A = 0.0108 A`. | Partial | 0.5 | Directionally correct, numerically inflated by the metrics layer. |
| Wannier post, Fe SOC | `wannier90_hr.dat`, file inventory in the task directory | Tight-binding model size and artifact completeness | `wannier90_hr.dat` reports `num_wann = 18` and `nrpts = 1909`. The checkpoint and core interface files (`.chk`, `.amn`, `.mmn`, `.eig`, `.hr.dat`, `.tb.dat`) are present. | The answer correctly describes an `18 x 18` model with `1909` lattice points and states that the critical interface files are present. | Full | 1.0 | This is a clean raw-file match. |
| Berry / AHC, Fe SOC | `wannier90.win`, `wannier90-ahc-fermiscan.dat`, `job.json`, `postw90_metrics.json` | Scan configuration and peak magnitude | The run is successful. The input requests `berry_task = ahc`, `berry_kmesh = 60 60 60`, and a `-0.5 to 0.5 eV` scan with `0.02 eV` step. The scan file contains `51` points, `3` AHC components, and a maximum absolute value of `1.979`. | The answer correctly reports a successful AHC scan over `51` points and three components across a symmetric `+-0.5 eV` window, with maximum absolute AHC `1.979`. | Full | 1.0 | Quantitatively correct. |
| Berry / AHC, Fe SOC | `wannier90-ahc-fermiscan.dat`, `wannier90.win`, `job.json` | Interpretive restraint | The available raw outputs do not by themselves establish the physical-Fermi-level AHC, topological invariants, or k-mesh convergence. They only provide the scan itself and the chosen numerical setup. | The answer explicitly states that the current output does not establish topological character, finite-temperature transport, or numerical convergence, and that Fermi-level alignment still needs verification. | Full | 1.0 | Good example of calibrated restraint. |
| Fermi surface, Fe SOC | `wannier90.win`, `wannier90.bxsf`, `job.json`, `postw90_metrics.json` | Export success and numerical settings | The run is successful and writes `wannier90.bxsf`. The requested settings are `fermi_energy = 5.4986400355` and `fermi_surface_num_points = 120`. The BXSF header stores a periodic `121 x 121 x 121` grid, consistent with a `120`-interval request. | The answer correctly states that the export succeeded, reports `5.49864 eV` as the Fermi energy, and describes the mesh as `120` points per dimension. | Full | 1.0 | The only nuance is that BXSF stores the periodic endpoint, so the file header shows `121` rather than `120`. |
| Fermi surface, Fe SOC | `wannier90.bxsf`, `wannier90.win`, `job.json` | Interpretive restraint | The raw result is an isosurface export only. Pocket multiplicity, nesting, spin texture, dimensionality, and effective masses require separate visualization or analysis. | The answer explicitly says that such physical properties cannot be inferred from the current export metric alone. | Full | 1.0 | Again, the restraint is appropriate. |

## Score Summary

- Total score: `7.0 / 8.0`
- Mean agreement score: `0.88`

Interpretation: in the Fe Wannier dataset, the LLM is reliable at workflow-level interpretation, artifact triage, and deciding what should not be claimed from the available outputs. Its main weakness in this case is not free-form hallucination, but propagation of incorrect quantitative localization statistics from the generated `wannier_metrics.json`.

## Important Ground-Truth Caveats

1. `wannier_metrics.json` is internally inconsistent with raw Wannier outputs in the Fe Wannier-post case.

   Examples:
   - raw `wannier90.wout` final state contains `18` Wannier functions, but `center_summary.count` is `3636`
   - raw final-state `max spread` is `1.82356217 A^2`, but `wannier_metrics.json` reports `1.99822127 A^2`
   - raw final-state count above `1.5 A^2` is `6`, not `1215`

   The LLM repeated some of these incorrect derived numbers, so those rows were scored down even though the qualitative localization verdict remained correct.

2. `postw90.out` is zero bytes in both postw90 subcases in this dataset.

   For Berry / AHC and Fermi-surface export, execution success was therefore judged from `job.json`, empty warning lists, and the presence plus contents of the generated data artifacts (`wannier90-ahc-fermiscan.dat` and `wannier90.bxsf`).
