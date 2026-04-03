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

## Pixi environments

This repository uses three Pixi environments:

- `default`: lightweight core development and tests
- `mdao`: `default` plus OpenMDAO support
- `fea`: `mdao` plus FEA-oriented tasks and local TACS wiring

Pixi environments are selected one at a time. They are not mixed at runtime.
Use `pixi run -e <env> ...` or `pixi shell -e <env>` explicitly.

## Quick start

```bash
pixi install -e default
pixi run -e default test
```

Core tests run in `default` and do not require optional solver installations.

OpenMDAO workflows use:

```bash
pixi install -e mdao
pixi run -e mdao python -c "import openmdao.api as om; print(om.__version__)"
```

The checked-in structural workflow is TACS-backed and should be run from `fea`:

```bash
pixi install -e fea
pixi run -e fea run-fea-example
pixi run -e fea run-shell-bdf-example
pixi run -e fea run-shell-bdf-multi-case-example
pixi run -e fea test-fea-baseline
pixi run -e fea test-shell-bdf-example
pixi run -e fea test-shell-bdf-multi-case-example
```

TACS local wiring is intentionally explicit and local-only. The repository does
not assume TACS is available automatically:

```bash
pixi run -e fea install-local-tacs
```

By default, `install-local-tacs` installs from `~/git/tacs`. Set `TACS_DIR` if
your checkout is elsewhere.

## Repository layout

- `src/mass_town/`: application package
- `plugins/`: optional tool plugins such as `gmsh` and built-in mock backends
- `docs/`: architecture, workflow, taxonomy, and roadmap notes
- `examples/simple_structural_problem/`: runnable example input
- `examples/shell_sizing_bdf_problem/`: BDF-first shell sizing example
- `examples/shell_sizing_bdf_multi_case_problem/`: BDF-first shell sizing example with multiple static load cases and configurable aggregated stress constraints
- `examples/solid_cantilever_problem/`: STEP-driven 3D solid cantilever benchmark
- `examples/shell_cantilever_problem/`: shell companion benchmark using the same cantilever STEP geometry
- `tests/`: unit tests for the core orchestration and CLI

Example projects now follow a canonical Phase 0 layout:

- root: `config.yaml`, `design_state.yaml`, `run_registry.yaml`
- `inputs/`: geometry and other checked-in problem inputs
- `results/<run_id>/logs`: workflow, gmsh, and solver logs
- `results/<run_id>/mesh`: generated `.msh` / `.bdf` artifacts
- `results/<run_id>/solver`: solver-native outputs such as `.f5`
- `results/<run_id>/reports`: normalized summaries, including `run_summary.json`

The multi-case shell sizing example also writes
`results/<run_id>/reports/stress_aggregation_summary.json`, which compares the
configured KS or p-norm surrogate against the reported raw per-case maximum
element stresses.

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
- a deterministic `mock` backend keeps tests runnable without `gmsh`

This keeps core MassTown free of hard dependencies on any one meshing or solver tool.

## Meshing backends

Meshing configuration now lives under `meshing:` in `config.yaml`.

```yaml
meshing:
  tool: auto
  geometry_input_path: geometry/model.step
  gmsh_executable: gmsh
  mesh_dimension: 3
  step_face_selector: null
  volume_element_preference: hex_preferred
  output_format: msh
  target_quality: 0.75
```

Backend selection rules:

- `auto` tries `gmsh` first and falls back to `mock`
- `gmsh` supports executable-driven meshing, Python-API planar-face meshing, and Python-API hex-preferred solid meshing for simple box-like STEP solids
- `gmsh` can emit either `.msh` or `.bdf` via `meshing.output_format`
- `mock` is always available for tests

## Running with the `gmsh` plugin

1. Install the `fea` Pixi environment so the gmsh Python package is available.
2. Provide a STEP geometry file (`.step` or `.stp`).
3. Update your project config:

```yaml
meshing:
  tool: gmsh
  geometry_input_path: geometry/model.step
  gmsh_executable: gmsh
  mesh_dimension: 2
  step_face_selector: max_y
  output_format: bdf
  target_quality: 0.75
```

4. Run the workflow:

```bash
pixi run -e fea mass-town run examples/simple_structural_problem
pixi run -e fea mass-town status examples/simple_structural_problem/design_state.yaml
```

If `gmsh` is explicitly selected but unavailable, MassTown will fail the mesh
task with a clear diagnostic instead of failing during import.

When `output_format: bdf`, the gmsh plugin writes a lightweight structural BDF
intended for downstream TACS / pyTACS import. The exporter includes:

- `GRID` nodes
- `CTRIA3`, `CQUAD4`, `CTETRA`, and `CHEXA` elements
- deterministic `PID` assignment from gmsh physical groups
- placeholder `PSHELL` / `PSOLID` cards plus a default isotropic `MAT1`
- `$ REGION ...` metadata comments that preserve gmsh physical names

Elements without a physical group are exported into an `UNASSIGNED` region.
Current limitations:

- only gmsh element types `2`, `3`, `4`, and `5` are supported for BDF export
- selector-driven shell and solid loads/boundary conditions must still be configured downstream in solver setup
- physical-group metadata is only preserved when it exists in the gmsh mesh
- for 3D meshes, point and edge entities are ignored during BDF export and lower-dimensional boundary faces are dropped when volume elements are present

Additional gmsh selector rules:

- `step_face_selector` now supports `largest_planar`, `min_x`, `max_x`, `min_y`, `max_y`, `min_z`, and `max_z`
- `volume_element_preference: hex_preferred` tries a transfinite/recombine hex-only volume mesh for single-volume box-like solids and falls back to tetrahedra with explicit metadata/logging when that is not possible

The checked-in structural example now uses this path directly, extracting the
largest planar face from
`examples/simple_structural_problem/inputs/geometry/crank.stp`.

The new cantilever benchmarks use the same gmsh plugin in two ways:

- `pixi run -e fea run-solid-cantilever-example`
- `pixi run -e fea run-shell-cantilever-example`

## FEA backends

FEA configuration now lives under `fea:` in `config.yaml`.

```yaml
fea:
  tool: auto
  model_input_path: null
  case_name: static
  write_solution: true
  shell_setup: null
  solid_setup: null
```

Backend selection rules:

- `auto` tries `tacs` and fails clearly if it is unavailable
- `tacs` requires the optional TACS Python package at runtime
- the TACS backend expects a `.bdf` structural model input
- if `fea.model_input_path` is omitted and meshing produced a `.bdf`, the FEA
  agent will use that generated mesh artifact automatically
- for shell meshes, the backend creates TACS shell elements in code and applies
  boundary conditions and nodal loads from `fea.shell_setup`
- for solid meshes, the backend creates TACS solid elements in code and applies
  boundary conditions and nodal loads from `fea.solid_setup`

Shell selector setup for generated shell models lives with the example or
problem definition, not inside `plugins/tacs`. A minimal example:

```yaml
fea:
  tool: tacs
  shell_setup:
    node_sets:
      fixed_edge:
        selector: boundary_loop
        family: outer
        order_by: area
        index: 0
      loaded_edge:
        selector: boundary_loop
        family: inner
        order_by: centroid_x
        index: 1
    boundary_conditions:
      - node_set: fixed_edge
        dof: "123456"
    loads:
      - node_set: loaded_edge
        load_key: force
        direction: [0.0, -1.0, 0.0]
        distribution: equal
```

Generated shell models also support a coordinate-based selector:

```yaml
shell_setup:
  node_sets:
    fixed_edge:
      selector: bounding_box_extreme
      axis: x
      extreme: min
```

Solid selector setup mirrors the same pattern for face-node selection:

```yaml
fea:
  tool: tacs
  solid_setup:
    node_sets:
      fixed_face:
        selector: bounding_box_extreme
        axis: x
        extreme: min
      loaded_face:
        selector: bounding_box_extreme
        axis: x
        extreme: max
    boundary_conditions:
      - node_set: fixed_face
        dof: "123456"
    loads:
      - node_set: loaded_face
        load_key: force
        direction: [0.0, -1.0, 0.0]
        distribution: equal
```

Core MassTown never imports TACS eagerly, so the package still imports cleanly
when TACS is not installed.

## Design variables

Design-variable definitions can now be provided in `config.yaml` under
`design_variables:` and are validated on load.

```yaml
design_variables:
  - id: thickness
    name: Global Thickness
    type: scalar_thickness
    initial_value: 0.8
    bounds:
      lower: 0.1
      upper: 2.0
    units: mm
    active: true
```

Supported DV types:

- `scalar_thickness`
- `region_thickness` (requires `region`)
- `element_thickness` (requires `element_ids`)

The workflow maps active DVs into normalized analysis assignments (`global`,
`region`, `element`) before calling solver backends.

For BDF inputs without `$ REGION ...` comments, region selectors can use
synthetic names in the form `pid_<PID>`.

## Running with the `tacs` plugin

1. Install TACS and its Python bindings in your environment.
2. Provide a `.bdf` structural model file for the analysis case, or let the
   mesh step generate one for you.
3. Update your project config:

```yaml
fea:
  tool: tacs
  case_name: static
  write_solution: true
```

4. Run the workflow:

```bash
pixi run -e fea mass-town run examples/simple_structural_problem
```

If `tacs` is explicitly selected but unavailable, MassTown will fail the FEA
task with a structured backend-unavailable diagnostic.

## Baseline regression contract

The Phase 0 baseline example writes a machine-readable summary to:

`examples/simple_structural_problem/results/simple-structural-problem/reports/run_summary.json`

That summary records the primary regression metrics:

- mass
- max stress
- final thickness
- iteration count
- final pass/fail status

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
