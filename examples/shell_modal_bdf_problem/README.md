# Shell Modal BDF Problem

This Phase 2 example is BDF-first and skips geometry/meshing. It runs a shell
modal analysis directly from:
[`inputs/model/plate.bdf`](/Users/markleader/git/mass_town/examples/shell_modal_bdf_problem/inputs/model/plate.bdf).

- Inputs:
  - [`config.yaml`](/Users/markleader/git/mass_town/examples/shell_modal_bdf_problem/config.yaml)
  - [`design_state.yaml`](/Users/markleader/git/mass_town/examples/shell_modal_bdf_problem/design_state.yaml)
  - [`inputs/model/plate.bdf`](/Users/markleader/git/mass_town/examples/shell_modal_bdf_problem/inputs/model/plate.bdf)

- Outputs under `results/shell-modal-bdf-problem/`:
  - `logs/`
  - `mesh/` (unused for this BDF-first path)
  - `solver/`
  - `reports/`

## Notes

- The checked-in BDF comes from the local TACS `stiffened_plate/plate.bdf`
  reference and carries the SPC cards used to suppress rigid-body modes for the
  modal solve.
- `fea.analysis_type: modal` solves for eigenvalues that correspond to squared
  angular frequencies; MassTown records both the raw eigenvalues and converted
  natural frequencies in Hz.
- The run summary records both the generic eigenvalue fields and the
  modal-specific aliases `critical_natural_frequency_hz` and
  `natural_frequencies_hz`.
- This example is frequency-constrained and intentionally does not apply
  external loads; transient dynamics remains out of scope for now.

## Run

```bash
pixi install -e fea
pixi run -e fea run-shell-modal-bdf-example
```
