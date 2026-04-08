# OpenMDAO Mock Structural Problem

This example is the Phase 5.3 OpenMDAO baseline for MassTown. It runs a
mock-backed structural optimization through the additive `--runtime openmdao`
path and keeps geometry/meshing outside the OpenMDAO model.

- Inputs live directly in the example directory:
  - [`config.yaml`](/Users/markleader/git/mass_town/examples/openmdao_mock_structural_problem/config.yaml): OpenMDAO-ready workflow definition
  - [`design_state.yaml`](/Users/markleader/git/mass_town/examples/openmdao_mock_structural_problem/design_state.yaml): seed design state
  - [`inputs/model/mock_panel.bdf`](/Users/markleader/git/mass_town/examples/openmdao_mock_structural_problem/inputs/model/mock_panel.bdf): placeholder direct model input with named regions
- Analysis and optimization assumptions:
  - OpenMDAO connects design variables, structural analysis, post-processing, and the SLSQP driver
  - geometry and meshing are intentionally out of scope for this runtime
  - the objective is mass minimization
  - the constraint is maximum stress not exceeding the allowable limit
  - the mock FEA backend provides analytic sensitivities for all active design variables

Generated outputs are standardized under `results/openmdao-mock-structural-problem/`:

- `logs/`: workflow and mock FEA logs
- `reports/`: resolved `problem_schema.json`, mock FEA summary, OpenMDAO summary, and `run_summary.json`
- `solver/`: reserved for future solver-side artifacts

Run it with:

```bash
pixi install -e mdao
pixi run -e mdao run-openmdao-mock-example
```

The regression summary is written to
`results/openmdao-mock-structural-problem/reports/run_summary.json`.
