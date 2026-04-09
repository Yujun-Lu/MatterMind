# SrTiO3 Wannier Ground-Truth Comparison

## Case Metadata

- Case root: `Experiment Data/VASP/wannier_SrTiO3_ground`
- Material: cubic SrTiO3
- Subcases included here:
  - `2. band interpolation`
  - `3. DOS`
- LLM inputs:
  - `postw90_metrics.json` for the band-interpolation task
  - `postw90_metrics.json` for the DOS task
- LLM outputs used for comparison: only the final answer blocks in the two `analysis.txt` files

## Method

Agreement was scored as `Full = 1.0`, `Partial = 0.5`, and `None = 0.0`.

Whenever a generated metrics JSON disagreed with raw postw90 artifacts, the raw files were treated as authoritative.

## Validation Table

| Module / Case | Ground-truth source | Evaluation target | Ground-truth value / conclusion | LLM interpretation | Agreement | Score | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Band interpolation, SrTiO3 | `job.json`, `wannier90.wpout`, file inventory | Execution success and artifact completeness | The task finished successfully with `return_code = 0`. The raw output set includes `wannier90-bands.dat`, `wannier90-bands.gnu`, `wannier90-bands.py`, `wannier90-path.kpt`, `wannier90.wpout`, and `plots/postw90_band.png`. | The task completed successfully with all standard interpolation artifacts generated and no runtime failures reported in the summary. | Full | 1.0 | Correct workflow-level reading. |
| Band interpolation, SrTiO3 | `wannier90-bands.dat`, `wannier90-path.kpt`, `wannier90.wpout`, `postw90_metrics.json` | Band multiplicity and path sampling | Raw `wannier90-bands.dat` contains `14` band segments, each sampled on `756` path points. `wannier90-path.kpt` also reports `756` path points. The metrics JSON field `n_bands = 1` and `n_kpoints = 10584` is a parser artifact: `10584 = 14 x 756` is the total number of data rows, not the number of k-points. | The answer states that only `1` band was interpolated and that `10,584` k-points were sampled along the path, then treats this as an immediate configuration problem. | None | 0.0 | This is the main quantitative miss in this case, but it is traceable to the summary JSON rather than free-form invention. |
| Band interpolation, SrTiO3 | `wannier90-bands.dat`, `wannier90.wpout`, `wannier90.win` | Energy window and interpretive restraint | The interpolated energy range is `-1.3338227` to `11.231804` eV. The raw postw90 outputs do not include a separate DFT reference curve or an interpolation-error metric, so fidelity to the parent DFT bands cannot be established from this dataset alone. | The answer correctly reports the broad energy window and correctly withholds any claim of DFT-Wannier agreement because no explicit comparison metric is present. | Full | 1.0 | Appropriate restraint. |
| DOS, SrTiO3 | `job.json`, `wannier90-dos.dat`, `wannier90.wpout`, `postw90_metrics.json` | Execution success and numerical consistency | The DOS task finished successfully. The setup is `dos_kmesh = 20 20 20`, `dos_energy_min = -8`, `dos_energy_max = 8`, `dos_energy_step = 0.02`. The raw DOS file contains `801` points and reaches a maximum DOS of `18.855817`, matching the summary JSON. | The answer correctly identifies a successful run with `801` points over `-8 to 8 eV` at `0.02 eV` spacing and a peak DOS near `18.86`. | Full | 1.0 | Numerically correct. |
| DOS, SrTiO3 | `wannier90.wpout`, `wannier90-dos.dat` | Availability of Fermi reference and immediate DOS-at-zero inference | `wannier90.wpout` explicitly reports `Fermi energy (eV) = 0.000`, and `wannier90-dos.dat` gives a finite DOS of about `4.81` at `E = 0`. This means a zero-energy reference is present in the raw output, and the interpolated DOS does not show a clean gap at that chosen reference. | The answer says that the Fermi position and zero-energy alignment are not reported, so metallicity or band-edge conclusions cannot be drawn. | Partial | 0.5 | The answer is too conservative here. The missing Fermi-reference claim is false in the raw output, but the broader caution about overinterpreting DOS without more context is still reasonable. |
| DOS, SrTiO3 | `wannier90-dos.dat`, `wannier90.wpout` | Limits on orbital / spin interpretation | The distributed DOS data file has only `2` columns and the raw output excerpt provided here does not give orbital- or spin-resolved channels. More detailed character assignment would require additional decomposition outputs or separate analysis. | The answer correctly notes that orbital or spin decomposition is not available in the current metadata and therefore cannot support detailed character assignment. | Full | 1.0 | Correct limitation statement. |

## Score Summary

- Total score: `4.5 / 6.0`
- Mean agreement score: `0.75`

Interpretation: for the SrTiO3 postw90 tasks, the LLM is reliable at workflow triage, run-status checking, artifact completeness, and knowing when not to overclaim interpolation fidelity. The weaker points come from sparse or incorrect upstream summaries: the band-interpolation JSON collapsed a 14-band result into a single-band summary, and the DOS JSON omitted the explicit Fermi-reference information that is present in the raw `wannier90.wpout`.

## Important Ground-Truth Caveats

1. `postw90_metrics.json` is wrong in the band-interpolation case.

   Raw artifacts show:
   - `14` band segments in `wannier90-bands.dat`
   - `756` path points in `wannier90-path.kpt`
   - total data rows `10584 = 14 x 756`

   But the generated summary reports `n_bands = 1` and `n_kpoints = 10584`. The LLM trusted that faulty summary, so the main band-interpolation error should be attributed to the parser layer, not to unsupported free-form generation.

2. `postw90.out` is zero bytes in both SrTiO3 subcases.

   Execution success was therefore judged from `job.json`, `wannier90.wpout`, and the generated data artifacts themselves rather than from `postw90.out`.
