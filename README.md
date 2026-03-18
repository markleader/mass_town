# mass_town

`mass_town` is a prototype engineering workflow supervision system for brittle
pipelines such as `CAD -> mesh -> solver -> postprocess -> optimization`.

The project focuses on failure triage and recovery rather than replacing
deterministic engineering tools. A Chief Engineer observes workflow state,
classifies anomalies, selects corrective actions, dispatches bounded discipline
agents, and persists the evolving design state to disk.

## Features

- Deterministic workflow supervision loop
- Structured design state and artifact tracking with `pydantic`
- Failure taxonomy and rule-based triage engine
- Bounded geometry, mesh, FEA, and optimizer agents
- Plugin-based meshing discipline with optional tool backends
- Filesystem-backed state and artifact storage
- Typer-based CLI
- Example structural problem and unit tests

## Quick start

```bash
pixi install
pixi run run-example
pixi run mass-town status examples/simple_structural_problem/design_state.yaml
pixi run test
```

## Repository layout

- `src/mass_town/`: application package
- `plugins/`: optional tool plugins such as `gmsh` and built-in mock backends
- `docs/`: architecture, workflow, taxonomy, and roadmap notes
- `examples/simple_structural_problem/`: runnable example input
- `tests/`: unit tests for the core orchestration and CLI

## Discipline and plugin separation

MassTown separates discipline orchestration from concrete engineering tools.
Core code owns the stable discipline interfaces, workflow state, Chief Engineer,
and discipline leads. Tool-specific code lives behind plugin backends.

Meshing is the first discipline using this split:

- core meshing orchestration depends on normalized request/result models
- concrete meshing tools are loaded lazily from `plugins/`
- `gmsh` is the first real meshing plugin
- a deterministic `mock` backend keeps the repo runnable without `gmsh`

This keeps core MassTown free of hard dependencies on any one meshing tool.

## Meshing backends

Meshing configuration now lives under `meshing:` in `config.yaml`.

```yaml
meshing:
  tool: auto
  geometry_input_path: geometry/model.step
  gmsh_executable: gmsh
  target_quality: 0.75
```

Backend selection rules:

- `auto` tries `gmsh` first and falls back to `mock`
- `gmsh` requires the external `gmsh` executable at runtime
- `mock` is always available for tests and examples

The checked-in example stays pinned to `mock` so the quick start works even
when `gmsh` is not installed.

## Running with the `gmsh` plugin

1. Install the `gmsh` executable and ensure it is on your `PATH`.
2. Provide a `.step` geometry file.
3. Update your project config:

```yaml
meshing:
  tool: gmsh
  geometry_input_path: geometry/model.step
  gmsh_executable: gmsh
  target_quality: 0.75
```

4. Run the workflow:

```bash
pixi run mass-town run examples/simple_structural_problem
```

If `gmsh` is explicitly selected but unavailable, MassTown will fail the mesh
task with a clear diagnostic instead of failing during import.

## Adding future meshing plugins

To add another meshing tool:

1. Implement the core `MeshingBackend` contract.
2. Place the tool-specific code under `plugins/<tool>/`.
3. Register a lazy loader in the meshing registry.
4. Keep all tool-specific subprocess or API logic inside the plugin.

## What the prototype does

The included workflow runs four bounded tasks:

1. geometry validation and sizing
2. mesh generation or repair
3. simplified structural analysis
4. design variable update

Failures are persisted as diagnostics, then triaged into corrective actions such
as repairing geometry, refining mesh quality, or increasing thickness to satisfy
stress constraints.
