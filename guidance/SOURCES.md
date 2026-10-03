# Papers, figures, and attribution

The public project accompanies two distinct manuscripts. Their author lists, scope, and publication status are intentionally kept separate.

## Journal article

**Kaiyang Xu, Yujun Lu, Lifeng Liu, and Lei Zhang.** *MatterMind: A User-Friendly Material Design Platform Assisted by Large Language Model.* Materials Genome Engineering Advances **4**(2), e70075 (2026). [DOI: 10.1002/mgea.70075](https://doi.org/10.1002/mgea.70075).

The publisher records first publication on 2 June 2026 and an affiliation correction on 26 July 2026. The supplied nine-page PDF is preserved byte for byte at [`docs/papers/mattermind-published.pdf`](../docs/papers/mattermind-published.pdf). It carries a Creative Commons Attribution notice. The publisher's [article page](https://onlinelibrary.wiley.com/doi/10.1002/mgea.70075) remains the authoritative version of record.

## Extended manuscript and its supporting information

**Yujun Lu, Kaiyang Xu, and Lei Zhang.** *MatterMind: An LLM-Assisted Platform for Crystal Generation, Materials Simulation, and AI-Guided Analysis.*

The 37-page manuscript and 43-page supporting information were supplied by the project author and archived on 3 October 2026. Although their original filenames contain `arXiv`, no public arXiv identifier was verified. They are labelled **extended manuscript** and **extended supporting information**, not a second journal publication or the journal's own supplement.

- [Extended manuscript](../docs/papers/mattermind-preprint.pdf)
- [Extended supporting information](../docs/papers/mattermind-supporting-information.pdf)

The supporting information belongs to the extended manuscript. Neither file is edited, corrected, compressed, or re-exported by this documentation update. Author order comes from the visible title page, not inherited PDF editor metadata.

## Integrity

[`docs/papers/manifest.json`](../docs/papers/manifest.json) records the byte length and SHA-256 of each supplied PDF. Run `python scripts/verify_publication.py` from the repository root to verify the public copies, local resource links, and basic citation consistency.

## Figure provenance

The following JPEGs were extracted from the supplied PDFs as original embedded image bytes. They are reproduced without redrawing or alteration.

| Asset in `docs/assets/` | Original source | Content |
| --- | --- | --- |
| `figure-overview.jpg` | Extended manuscript, Figure 1, p. 6 | Current platform architecture |
| `figure-generation.jpg` | Extended manuscript, Figure 4, p. 13 | Eight representatives of the 16-candidate unconditioned run |
| `figure-wannier.jpg` | Extended manuscript, Figure 8, p. 22 | SrTiO3 Wannier centers and Hamiltonian diagnostics |
| `figure-fermi.jpg` | Extended manuscript, Figure 15, p. 32 | Fe SOC Fermi surface exported by MatterMind and visualized externally in XCrySDen |
| `figure-validation.jpg` | Journal article, Figure 2, p. 6 | Si, Au, and SiAu3 relaxation, DOS, and interpretation |

Credit the extended-manuscript figures to Yujun Lu, Kaiyang Xu, and Lei Zhang. Credit the journal figure to Kaiyang Xu, Yujun Lu, Lifeng Liu, and Lei Zhang, DOI [10.1002/mgea.70075](https://doi.org/10.1002/mgea.70075), under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The website lattice and README banner are newly drawn schematic illustrations, not calculation outputs.

## Reuse boundaries

The journal PDF's Creative Commons Attribution notice applies to that article and its figures, with attribution to the authors and DOI. The extended manuscript and its figures retain their existing author rights; this repository does not assign a new license to them. The source repository currently has no software license, and the article's license does not license the software. External tools, model weights, VASP binaries, and pseudopotentials retain their respective terms.

Existing `images/* Cover.png` files are promotional cover artwork, not measured scientific results or screenshots. Any use as video thumbnails is labelled accordingly.

## Research interpretation

The website reports examples from the supplied papers; it does not represent a new computational rerun. The extended manuscript is a platform-validation study. Successful execution, geometric screening, target-property satisfaction, and physical convergence are separate outcomes.

The symmetry-conditioned generation example illustrates this explicitly: 16 candidates completed processing, but none was assigned to the requested space group 225 under the reported symmetry analysis. A 14-orbital SrTiO3 Wannier model is a model dimension, not an accuracy score. The published Si and Au bond lengths are individual relaxation examples, not a statistical benchmark.

Some values differ between the extended manuscript and its raw-output audits in the supporting information. In particular, NEB barrier values, Fe Wannier spread summaries, and SrTiO3 band-sampling counts should be checked against the supplement before quantitative reuse. The homepage therefore avoids presenting these values as headline validated benchmarks. See [reproducibility notes](REPRODUCIBILITY.md).
