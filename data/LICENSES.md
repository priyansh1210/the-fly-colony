# Dataset licenses

Generated from `config/datasets.yaml` by `colony data licenses`. Do not edit by hand.

| Dataset | License | Status | Restrictions |
|---|---|---|---|
| `door_v2` | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | verified | Share-alike. Tables derived from DoOR (config/senses/door_tuning.yaml) carry the same license and attribution. |
| `fafb783_annotations` | [CC BY 4.0 (assumed)](https://creativecommons.org/licenses/by/4.0/) | assumed | Treated as attribution-only. Confirm with the authors before public redistribution. |
| `fafb783_connectome` | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | verified | Attribution required. No non-commercial restriction. |
| `flyvis_pretrained` | [MIT](https://github.com/TuragaLab/flyvis/blob/main/LICENSE) | verified | Keep the MIT notice with any copied parameters. |
| `malecns_v1` | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | verified | Attribution required. No non-commercial restriction. |
| `shiu2024_model` | [MIT (code); data derived from FlyWire 783 (CC BY 4.0)](https://github.com/philshiu/Drosophila_brain_model/blob/main/LICENSE) | verified | Keep the MIT notice with any copied code. FlyWire attribution applies to the data. |

## `door_v2`: DoOR 2.0 - Database of Odorant Responses (DoOR.data)

- **Version:** commit db323a496577c4b4a72b5c2fcd1859e07521ffb5 (2.0.1.9001)
- **Source:** https://github.com/ropensci/DoOR.data
- **License:** [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) (verified, checked 2026-10-13)
- **Evidence:** DESCRIPTION file of the repository ("License CC BY-SA 4.0")
- **Restrictions:** Share-alike. Tables derived from DoOR (config/senses/door_tuning.yaml) carry the same license and attribution.
- **Required attribution:** Münch D., Galizia C.G. (2016) DoOR 2.0 - Comprehensive Mapping of Drosophila melanogaster Odorant Responses, Sci Rep 6:21841, doi:10.1038/srep21841.

## `fafb783_annotations`: FlyWire neuron annotations (flywire_annotations v3.2.0, materialization 783)

- **Version:** v3.2.0 (a83b2776d60d5764cef36b927f5f9679c16c47a2)
- **Source:** https://github.com/flyconnectome/flywire_annotations
- **License:** [CC BY 4.0 (assumed)](https://creativecommons.org/licenses/by/4.0/) (assumed, checked 2026-10-12)
- **Evidence:** The repository has no LICENSE file. Its files are the supplementary data of Schlegel et al. 2024 (Nature 634:139-152), an open-access article published under CC BY 4.0.
- **Restrictions:** Treated as attribution-only. Confirm with the authors before public redistribution.
- **Required attribution:** Schlegel P. et al. (2024) Whole-brain annotation and multi-connectome cell typing of Drosophila, Nature 634:139-152, doi:10.1038/s41586-024-07686-5.

## `fafb783_connectome`: FlyWire whole-brain connectome, connectivity data (FAFB v783)

- **Version:** 783.0
- **Source:** https://doi.org/10.5281/zenodo.10676866
- **License:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (verified, checked 2026-10-12)
- **Evidence:** Zenodo record 10676866 license field (cc-by-4.0)
- **Restrictions:** Attribution required. No non-commercial restriction.
- **Required attribution:** FlyWire Consortium. Dorkenwald S. et al. (2024) Neuronal wiring diagram of an adult brain, Nature 634:124-138, doi:10.1038/s41586-024-07558-y; Schlegel P. et al. (2024) Whole-brain annotation and multi-connectome cell typing of Drosophila, Nature 634:139-152, doi:10.1038/s41586-024-07686-5; synapse detection Buhmann et al. (2021), Heinrich et al. (2018); neurotransmitter prediction Eckstein, Bates et al. (2024). Data: Zenodo doi:10.5281/zenodo.10676866.

## `flyvis_pretrained`: flyvis pretrained ensemble (connectome-constrained visual system model)

- **Version:** results_pretrained_models.zip (sha256 pinned by the flyvis download tool)
- **Source:** https://github.com/TuragaLab/flyvis
- **License:** [MIT](https://github.com/TuragaLab/flyvis/blob/main/LICENSE) (verified, checked 2026-10-12)
- **Evidence:** license.txt in the published download folder and LICENSE in the repository (MIT)
- **Restrictions:** Keep the MIT notice with any copied parameters.
- **Required attribution:** Lappalainen J.K. et al. (2024) Connectome-constrained networks predict neural activity across the fly visual system, Nature 634:1132-1140, doi:10.1038/s41586-024-07939-3.

## `malecns_v1`: Janelia/Google male adult nervous system (MaleCNS v1.0)

- **Version:** v1.0
- **Source:** https://male-cns.janelia.org/download/
- **License:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (verified, checked 2026-10-12)
- **Evidence:** male-cns.janelia.org states "The Male CNS dataset is licensed under CC-BY"
- **Restrictions:** Attribution required. No non-commercial restriction.
- **Required attribution:** Janelia FlyEM and Google, MaleCNS v1.0, male-cns.janelia.org, CC BY 4.0. Paper: Berg S. et al. (2026), Cell 189:5504-5526, doi:10.1016/j.cell.2026.08.015 (TO CONFIRM: this citation comes from a third-party listing; the official site gives no citation text).

## `shiu2024_model`: Shiu et al. 2024 Drosophila whole-brain LIF model, inputs for FlyWire 783

- **Version:** commit 91bdd1e7dcf193f3e7ca5a8933497fcef63b7960
- **Source:** https://github.com/philshiu/Drosophila_brain_model
- **License:** [MIT (code); data derived from FlyWire 783 (CC BY 4.0)](https://github.com/philshiu/Drosophila_brain_model/blob/main/LICENSE) (verified, checked 2026-10-12)
- **Evidence:** LICENSE file in the repository (MIT)
- **Restrictions:** Keep the MIT notice with any copied code. FlyWire attribution applies to the data.
- **Required attribution:** Shiu P.K. et al. (2024) A Drosophila computational brain model reveals sensorimotor processing, Nature 634:210-219, doi:10.1038/s41586-024-07763-9.
