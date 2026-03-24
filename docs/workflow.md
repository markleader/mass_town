# Workflow

The prototype implements a deterministic supervision loop:

1. Load persisted design state and workflow configuration.
2. Select the next pending task.
3. Execute the responsible discipline agent.
4. Record artifacts, metrics, and diagnostics.
5. If a task fails, triage the failure and apply a corrective action.
6. Continue until all tasks succeed or the run reaches a safety limit.

This is intentionally a triage loop, not a single linear pipeline.

## Meshing workflow

The mesh agent now works through a discipline-level backend contract.

1. Read normalized meshing config.
2. Resolve a meshing backend through the registry.
3. Generate a gmsh mesh artifact, then export either `.msh` or `.bdf`
   depending on `meshing.output_format`.
4. Persist mesh outputs and sidecar artifact metadata.
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
4. Run analysis and persist normalized result metadata and output artifacts.
5. Raise structured diagnostics if the selected backend is unavailable, the
   configured model input is missing, or the backend fails.

With `tool: auto`, the workflow prefers `tacs` when it is available.
