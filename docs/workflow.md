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
3. Generate a mesh artifact and normalized result metadata.
4. Persist mesh outputs and sidecar artifact metadata.
5. Raise structured diagnostics if the selected backend is unavailable or fails.

With `tool: auto`, the workflow prefers `gmsh` and falls back to `mock`.
