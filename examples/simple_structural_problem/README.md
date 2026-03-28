# Simple Structural Problem

This is the Phase 0 baseline regression for MassTown. It runs a real
STEP -> gmsh -> BDF -> TACS -> thickness-update loop from
[`inputs/geometry/crank.stp`](/Users/markleader/git/mass_town/examples/simple_structural_problem/inputs/geometry/crank.stp).

- Inputs live directly in the example directory:
  - [`config.yaml`](/Users/markleader/git/mass_town/examples/simple_structural_problem/config.yaml): workflow definition
  - [`design_state.yaml`](/Users/markleader/git/mass_town/examples/simple_structural_problem/design_state.yaml): seed design state
  - [`inputs/geometry/crank.stp`](/Users/markleader/git/mass_town/examples/simple_structural_problem/inputs/geometry/crank.stp): baseline STEP geometry

- Generated outputs are standardized under `results/simple-structural-problem/`:
  - `logs/`: `gmsh`, `tacs`, and workflow logs
  - `mesh/`: generated `.msh` and `.bdf`
  - `solver/`: solver-side outputs such as `.f5`
  - `reports/`: geometry summary, optimizer summary, TACS summary, and `run_summary.json`

## Baseline assumptions

- STEP input requirements:
  - the file must contain at least one planar face
  - the selected face must remain suitable for 2D plane-stress shell meshing
- Gmsh meshing assumptions:
  - `mesh_dimension: 2`
  - `step_face_selector: largest_planar`
  - only the largest planar face is meshed
- BDF export assumptions:
  - the gmsh mesh is exported as a shell-oriented BDF
  - the exporter currently supports `CTRIA3` and `CQUAD4` shell elements plus deterministic property assignment
- TACS BC and load application:
  - the left bore is fixed in all six DOFs
  - the right bore receives the design-state force in global `-y`
  - shell thickness comes from the scalar `thickness` design variable
- Objective and constraint definition:
  - the current Phase 0 loop is a deterministic feasibility-recovery loop, not a full optimizer
  - the optimizer agent increases thickness in fixed `0.2` steps when the stress constraint fails
  - mass is recorded as a regression metric alongside the feasibility result
  - constraint: keep the KS-based failure metric below the allowable stress limit
  - feasibility means the final analysis passes with `max_stress <= allowable_stress`

## Running the baseline

- `gmsh` imports the STEP geometry, picks the largest planar face, meshes that face in 2D, and exports a `.bdf` shell model.
- `tacs` consumes the generated `.bdf` directly from the mesh artifact.
- The analysis script applies boundary conditions and loads in memory:
  the left bore is fixed and the right bore receives the design-state force in
  global `-y`.
- The example keeps the existing `thickness` design variable, which is used as
  the shell thickness in the TACS element callback.

Run it with:

```bash
pixi install -e fea
pixi run -e fea run-fea-example
```

If TACS is only available from a local checkout, wire it into the `fea`
environment first:

```bash
pixi run -e fea install-local-tacs
```

The baseline regression summary is written to
`results/simple-structural-problem/reports/run_summary.json`.
