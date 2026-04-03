# Shell Buckling BDF Problem

This Phase 2 example is BDF-first and skips geometry/meshing. It runs a shell
buckling analysis directly from:
[`inputs/model/plate.bdf`](/Users/markleader/git/mass_town/examples/shell_buckling_bdf_problem/inputs/model/plate.bdf).

- Inputs:
  - [`config.yaml`](/Users/markleader/git/mass_town/examples/shell_buckling_bdf_problem/config.yaml)
  - [`design_state.yaml`](/Users/markleader/git/mass_town/examples/shell_buckling_bdf_problem/design_state.yaml)
  - [`inputs/model/plate.bdf`](/Users/markleader/git/mass_town/examples/shell_buckling_bdf_problem/inputs/model/plate.bdf)

- Outputs under `results/shell-buckling-bdf-problem/`:
  - `logs/`
  - `mesh/` (unused for this BDF-first path)
  - `solver/`
  - `reports/`

## Notes

- The checked-in BDF comes from the local TACS `stiffened_plate/plate.bdf`
  reference and already includes the SPCs needed to suppress rigid-body modes.
- `fea.shell_setup.loads` applies a compressive axial edge load on the `max_x`
  boundary, while the buckling solve reports linearized load factors for that
  preload state.
- The checked-in load uses a negative `force_x` value because the configured
  nodal load direction is already `-x`; together they produce the intended
  compressive preload.
- The run summary records both the generic eigenvalue fields and the
  buckling-specific aliases `critical_buckling_load_factor` and
  `buckling_load_factors`.

## Run

```bash
pixi install -e fea
pixi run -e fea run-shell-buckling-bdf-example
```
