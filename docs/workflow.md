# Workflow

The prototype implements a deterministic supervision loop:

1. Load persisted design state and workflow configuration.
2. Select the next pending task.
3. Execute the responsible discipline agent.
4. Record artifacts, metrics, and diagnostics.
5. If a task fails, triage the failure and apply a corrective action.
6. Continue until all tasks succeed or the run reaches a safety limit.

This is intentionally a triage loop, not a single linear pipeline.

Each run now writes generated outputs under `results/<run_id>/` with
standardized `logs/`, `mesh/`, `solver/`, and `reports/` subdirectories. The
final regression-friendly summary lives at `reports/run_summary.json`.

## Meshing workflow

The mesh agent now works through a discipline-level backend contract.

1. Read normalized meshing config.
2. Resolve a meshing backend through the registry.
3. Generate a gmsh mesh artifact, then export either `.msh` or `.bdf`
   depending on `meshing.output_format`.
4. When configured for planar-face STEP meshing, use the gmsh Python API to
   select the largest planar face and generate a 2D shell mesh from that face.
5. Persist mesh outputs under `results/<run_id>/mesh` and write gmsh logs under
   `results/<run_id>/logs`.
5. Raise structured diagnostics if the selected backend is unavailable or fails.

With `tool: auto`, the workflow prefers `gmsh` and falls back to `mock`.

For `output_format: bdf`, the gmsh backend preserves physical groups as
deterministic BDF regions when possible and falls back to an `UNASSIGNED`
region for ungrouped elements.

## FEA workflow

The FEA agent now works through a discipline-level backend contract.

1. Read normalized FEA config.
2. Build an `FEARequest` from config, workflow state, and available mesh context.
3. Resolve an FEA backend through the registry.
4. If no explicit model path is configured and the mesh artifact is a `.bdf`,
   use that generated mesh file as the solver input.
5. For shell BDF inputs, build the TACS shell problem in code and apply
   boundary conditions and nodal loads from `fea.shell_setup` or existing BDF
   SPC cards.
6. Run analysis and persist normalized summaries under `results/<run_id>/reports`
   plus solver-native outputs under `results/<run_id>/solver`.
7. When `constraints.aggregated_stress` is configured in the design state, use
   the per-load-case stress results to evaluate a KS or p-norm aggregate for
   overall pass/fail while preserving worst-case load-case reporting in
   `analysis_state.max_stress` and `worst_case_name`.
8. For TACS runs with aggregated stress enabled, write
   `reports/stress_aggregation_summary.json` to compare the aggregate surrogate
   against the raw per-case maximum element stresses.
9. Raise structured diagnostics if the selected backend is unavailable, the
   configured model input is missing, or the backend fails.

With `tool: auto`, the workflow prefers `tacs` when it is available.

## Design-variable workflow

Design variables are now config-defined and validated during config load.

1. Read `design_variables` definitions from `config.yaml`.
2. Resolve runtime DV values from persisted state with initial-value fallback.
3. Clamp values to DV bounds before optimizer and analysis hand-off.
4. Map DVs into normalized analysis assignments grouped by scope:
   global, region, and element.
5. Fail fast with structured diagnostics when DV selectors do not match the
   analysis model metadata (for example unknown regions or elements).
