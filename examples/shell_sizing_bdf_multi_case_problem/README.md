# Shell Sizing BDF Multi-Case Problem

This Phase 1 example is intentionally BDF-first. It bypasses STEP->mesh export
and runs TACS directly from:
[`inputs/model/plate.bdf`](/Users/markleader/git/mass_town/examples/shell_sizing_bdf_multi_case_problem/inputs/model/plate.bdf).

- Inputs:
  - [`config.yaml`](/Users/markleader/git/mass_town/examples/shell_sizing_bdf_multi_case_problem/config.yaml)
  - [`design_state.yaml`](/Users/markleader/git/mass_town/examples/shell_sizing_bdf_multi_case_problem/design_state.yaml)
  - [`inputs/model/plate.bdf`](/Users/markleader/git/mass_town/examples/shell_sizing_bdf_multi_case_problem/inputs/model/plate.bdf)

- Outputs under `results/shell-sizing-bdf-multi-case-problem/`:
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
- The design state defines two static load cases that share one thickness design
  vector:
  - `center_bending` applies `force_z`
  - `center_shear` applies `force_x`
- Overall feasibility and `analysis_state.max_stress` use the reported
  worst-case load case. Per-case metrics are written into
  `reports/run_summary.json`.

## Future Aggregation

Constraint aggregation is intentionally deferred to TODO item 1.4. The intended
future problem-definition shape is documented here so the multi-case example can
evolve without changing its structure:

```yaml
constraints:
  max_stress: 3000000000.0
  aggregated_stress:
    method: ks
    source: load_cases
    allowable: 3000000000.0
```

The current implementation does not execute this stanza yet. Worst-case
reporting is the active behavior for this example.

## Run

```bash
pixi install -e fea
pixi run -e fea run-shell-bdf-multi-case-example
```
