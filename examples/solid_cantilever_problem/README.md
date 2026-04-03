# Solid Cantilever Problem

This Phase 2 example runs the new 3D solid workflow from the cantilever STEP
reference geometry:
[`inputs/geometry/cantilever.stp`](/Users/markleader/git/mass_town/examples/solid_cantilever_problem/inputs/geometry/cantilever.stp).

- Inputs:
  - [`config.yaml`](/Users/markleader/git/mass_town/examples/solid_cantilever_problem/config.yaml)
  - [`design_state.yaml`](/Users/markleader/git/mass_town/examples/solid_cantilever_problem/design_state.yaml)
  - [`inputs/geometry/cantilever.stp`](/Users/markleader/git/mass_town/examples/solid_cantilever_problem/inputs/geometry/cantilever.stp)

- Outputs under `results/solid-cantilever-problem/`:
  - `logs/`
  - `mesh/`
  - `solver/`
  - `reports/`

## Notes

- `gmsh` imports the STEP solid and prefers a hexahedral-only volume mesh using
  a transfinite/recombine path when the geometry is a single box-like solid.
- If that hex-preferred path cannot be satisfied, the backend falls back to a
  tetrahedral volume mesh and records the reason in the gmsh log and mesh
  metadata.
- `fea.solid_setup` clamps the `min_x` face and applies the design-state force
  as an equal nodal load on the `max_x` face.

## Run

```bash
pixi install -e fea
pixi run -e fea run-solid-cantilever-example
```
