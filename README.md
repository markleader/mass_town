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
- Plugin-based meshing and FEA disciplines with optional tool backends
- Filesystem-backed state and artifact storage
- Typer-based CLI
- Example structural problem and unit tests

## Quick start

```bash
pixi install
pixi run test
```

The test suite does not require optional solver installations. The checked-in
structural example is now a TACS-backed workflow, so `pixi run run-example`
requires TACS plus the sample `.bdf` input.

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

Meshing and FEA now use this split directly:

- core meshing orchestration depends on normalized request/result models
- core FEA orchestration depends on normalized request/result models
- concrete meshing tools are loaded lazily from `plugins/`
- concrete FEA tools are loaded lazily from `plugins/`
- `gmsh` is the first real meshing plugin
- `tacs` is the first real FEA plugin
- a deterministic `mock` backend keeps meshing runnable without `gmsh`

This keeps core MassTown free of hard dependencies on any one meshing or solver tool.

## Meshing backends

Meshing configuration now lives under `meshing:` in `config.yaml`.

```yaml
meshing:
  tool: auto
  geometry_input_path: geometry/model.step
  gmsh_executable: gmsh
  output_format: msh
  target_quality: 0.75
```

Backend selection rules:

- `auto` tries `gmsh` first and falls back to `mock`
- `gmsh` requires the external `gmsh` executable at runtime
- `gmsh` can emit either `.msh` or `.bdf` via `meshing.output_format`
- `mock` is always available for tests and examples

The checked-in example stays pinned to `mock` for meshing so `gmsh` is still
optional when running the TACS-backed workflow.

## Running with the `gmsh` plugin

1. Install the `gmsh` executable and ensure it is on your `PATH`.
2. Provide a `.step` geometry file.
3. Update your project config:

```yaml
meshing:
  tool: gmsh
  geometry_input_path: geometry/model.step
  gmsh_executable: gmsh
  output_format: bdf
  target_quality: 0.75
```

4. Run the workflow:

```bash
pixi run mass-town run examples/simple_structural_problem
pixi run mass-town status examples/simple_structural_problem/design_state.yaml
```

If `gmsh` is explicitly selected but unavailable, MassTown will fail the mesh
task with a clear diagnostic instead of failing during import.

When `output_format: bdf`, the gmsh plugin writes a lightweight structural BDF
intended for downstream TACS / pyTACS import. The exporter includes:

- `GRID` nodes
- `CTRIA3`, `CQUAD4`, `CTETRA`, and `CHEXA` elements
- deterministic `PID` assignment from gmsh physical groups
- placeholder `PSHELL` / `PSOLID` cards plus a default `MAT1`
- `$ REGION ...` metadata comments that preserve gmsh physical names

Elements without a physical group are exported into an `UNASSIGNED` region.
Current limitations:

- only gmsh element types `2`, `3`, `4`, and `5` are supported for BDF export
- loads and boundary conditions are not converted into BDF cards automatically
- physical-group metadata is only preserved when it exists in the gmsh mesh

A typical downstream flow is:

1. define gmsh physical groups on the model you mesh
2. set `meshing.output_format: bdf`
3. run the mesh task or workflow to produce `artifacts/<run_id>/<name>.bdf`
4. point the TACS backend or a pyTACS script at that exported BDF

## FEA backends

FEA configuration now lives under `fea:` in `config.yaml`.

```yaml
fea:
  tool: auto
  model_input_path: analysis/model.bdf
  case_name: static
  write_solution: true
```

Backend selection rules:

- `auto` tries `tacs` and fails clearly if it is unavailable
- `tacs` requires the optional TACS Python package at runtime
- the TACS MVP expects a `.bdf` structural model input
- the TACS MVP currently uses the load cases defined in that `.bdf`

Core MassTown never imports TACS eagerly, so the package still imports cleanly
when TACS is not installed.

## Running with the `tacs` plugin

1. Install TACS and its Python bindings in your environment.
2. Provide a `.bdf` structural model file for the analysis case.
   The current MVP expects loads and boundary conditions to be encoded in that
   BDF model.
3. Update your project config:

```yaml
fea:
  tool: tacs
  model_input_path: analysis/model.bdf
  case_name: static
  write_solution: true
```

4. Run the workflow:

```bash
pixi run mass-town run examples/simple_structural_problem
```

If `tacs` is explicitly selected but unavailable, MassTown will fail the FEA
task with a structured backend-unavailable diagnostic.

## Adding future meshing plugins

To add another meshing tool:

1. Implement the core `MeshingBackend` contract.
2. Place the tool-specific code under `plugins/<tool>/`.
3. Register a lazy loader in the meshing registry.
4. Keep all tool-specific subprocess or API logic inside the plugin.

## Adding future FEA plugins

To add another FEA solver:

1. Implement the core `FEABackend` contract.
2. Place the solver-specific code under `plugins/<solver>/`.
3. Register a lazy loader in the FEA registry.
4. Keep solver imports and API assumptions inside the plugin.

## What the prototype does

The included workflow runs four bounded tasks:

1. geometry validation and sizing
2. mesh generation or repair
3. structural analysis through the FEA backend contract
4. design variable update

Failures are persisted as diagnostics, then triaged into corrective actions such
as repairing geometry, refining mesh quality, or increasing thickness to satisfy
stress constraints.
