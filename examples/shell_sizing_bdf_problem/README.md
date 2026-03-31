# Shell Sizing BDF Problem

This Phase 1 example is intentionally BDF-first. It bypasses STEP->mesh export
and runs TACS directly from:
[`inputs/model/plate.bdf`](/Users/markleader/git/mass_town/examples/shell_sizing_bdf_problem/inputs/model/plate.bdf).

- Inputs:
  - [`config.yaml`](/Users/markleader/git/mass_town/examples/shell_sizing_bdf_problem/config.yaml)
  - [`design_state.yaml`](/Users/markleader/git/mass_town/examples/shell_sizing_bdf_problem/design_state.yaml)
  - [`inputs/model/plate.bdf`](/Users/markleader/git/mass_town/examples/shell_sizing_bdf_problem/inputs/model/plate.bdf)

- Outputs under `results/shell-sizing-bdf-problem/`:
  - `logs/`
  - `mesh/` (unused for this BDF-first path)
  - `solver/`
  - `reports/`

## Notes

- The BDF deck is component-partitioned (`PID=1..9`), so this example uses
  region-wise shell thickness DVs (`pid_1` through `pid_9`).
- Shell elements and constitutive models are built in the TACS callback
  following the same pattern as the plate pyTACS reference setup.
- If a shell BDF has no region comments, MassTown automatically exposes
  synthetic region names in the form `pid_<PID>`.

## Run

```bash
pixi install -e fea
pixi run -e fea run-shell-bdf-example
```
