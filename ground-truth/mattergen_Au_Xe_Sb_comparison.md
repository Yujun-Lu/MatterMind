# MatterGen Ground-Truth Comparison

## Case Metadata

- Case root: `Experiment Data/VASP/mattergen_ground`
- Task type: MatterGen conditional generation
- On-disk job configuration from `job.json` / `job.log`:
  - `model_name = chemical_system_energy_above_hull`
  - `chemical_system = Au-Xe-Sb`
  - `energy_above_hull = 0.04`
  - `diffusion_guidance_factor = 2.0`
  - `batch_size = 2`
  - `num_batches = 2`
  - total generated frames = `4`
- LLM input: `metrics.json`
- LLM output used for comparison: only the final answer block in `analysis.txt`

## Method

Agreement was scored as `Full = 1.0`, `Partial = 0.5`, and `None = 0.0`.

Whenever a generated summary conflicted with raw generation artifacts, the raw files (`generated_crystals.extxyz`, CIFs, `job.json`, `job.log`) were treated as authoritative.

## Validation Table

| Module / Case | Ground-truth source | Evaluation target | Ground-truth value / conclusion | LLM interpretation | Agreement | Score | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MatterGen, `mattergen_ground` | `job.json`, `job.log`, `generated_crystals.extxyz` | Execution success and sample count | The generation run completed successfully with `return_code = 0` and produced `4` structures. `generated_crystals.extxyz` also contains `4` frames. | The answer consistently discusses a batch of four generated structures. | Full | 1.0 | Correct basic task accounting. |
| MatterGen, `mattergen_ground` | `job.json`, `generated_crystals.extxyz`, `gen_*.cif`, `magpie.csv` | Chemical-system conditioning fidelity | The requested chemical system is `Au-Xe-Sb`, but all `4/4` generated structures are binary `Au-Sb` phases. `Xe` appears in `0/4` frames, so the exact chemical-system match rate is `0/4`. | The answer silently reframes the batch as "four generated Au-Sb structures" and never flags that the conditioning target `Au-Xe-Sb` failed completely. | None | 0.0 | This is the main failure in this case. The model noticed the output chemistry but did not compare it against the requested target chemistry. |
| MatterGen, `mattergen_ground` | `metrics.json`, `generated_crystals.extxyz`, `gen_*.cif` | Geometric validity / close-contact screening | All `4/4` structures have `num_close_contacts = 0`, empty warning lists, and minimum interatomic distances between `2.806` and `2.916 A`, well above the `1.5 A` close-contact threshold. | The answer correctly states that all four structures pass basic geometric validation and steric screening. | Full | 1.0 | Good geometry triage. |
| MatterGen, `mattergen_ground` | `metrics.json` | Deduplication / structural diversity | `dedup_summary.num_groups = 4` for `4` frames, so none of the four generated structures were merged as duplicates by the current matcher settings. | The answer correctly mentions consistent deduplication and unique groups. | Full | 1.0 | Correct use of the dedup summary. |
| MatterGen, `mattergen_ground` | `job.json`, `metrics.json`, output file inventory | Thermodynamic evidence and energy-above-hull validation | The task is conditioned on `energy_above_hull`, but the output bundle contains no relaxed energies, forces, or hull values for the generated candidates. Therefore the success of the `energy_above_hull` condition cannot be validated from the available files. | The answer correctly states that definitive thermodynamic ranking is impossible because energy / stability metrics are absent. | Full | 1.0 | Appropriate restraint. |
| MatterGen, `mattergen_ground` | `metrics.json`, `generated_crystals.extxyz`, `gen_*.cif` | Top-K prioritization for follow-up | Structures `2` and `3` can be defended only as geometry-based screening choices: `2` has the smallest cell (`4` atoms) and `3` has the lowest volume per atom. But because no candidate satisfies the requested `Au-Xe-Sb` chemistry and no thermodynamic data is available, these are not validated top candidates for the conditioned generation task. | The answer ranks `2` and `3` as the top two candidates with moderate-to-high confidence. | Partial | 0.5 | The heuristic triage is understandable, but it is not ground-truth support for the intended conditioned objective. |

## Score Summary

- Total score: `4.5 / 6.0`
- Mean agreement score: `0.75`

Interpretation: for this MatterGen case, the LLM performs well on geometry screening, deduplication, and recognizing when thermodynamic claims are unsupported. The critical miss is target-fidelity checking: the generated batch completely fails the requested `Au-Xe-Sb` chemistry condition, and the LLM does not call that out explicitly.

## Important Ground-Truth Caveats

1. The files on disk do not match the user-provided command.

   The user described:
   - `batch_size = 4`
   - `num_batches = 4`
   - `energy_above_hull = 0.05`

   But `job.json` and `job.log` show:
   - `batch_size = 2`
   - `num_batches = 2`
   - `energy_above_hull = 0.04`

   This comparison therefore uses the on-disk artifacts as authoritative.

2. Conditioning fidelity and geometry validity must be evaluated separately.

   In this batch:
   - geometry validity is good (`4/4` pass close-contact screening)
   - chemistry conditioning fidelity is poor (`0/4` exact matches to `Au-Xe-Sb`)

   A generation batch can therefore look geometrically plausible while still failing the requested conditional objective.
