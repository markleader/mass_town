# Shell Cantilever Problem

This Phase 2 companion example uses the same cantilever STEP geometry as the
solid benchmark but extracts a single planar face for a shell comparison model.

- Inputs:
  - [`config.yaml`](/Users/markleader/git/mass_town/examples/shell_cantilever_problem/config.yaml)
  - [`design_state.yaml`](/Users/markleader/git/mass_town/examples/shell_cantilever_problem/design_state.yaml)
  - Geometry source:
    [`../solid_cantilever_problem/inputs/geometry/cantilever.stp`](/Users/markleader/git/mass_town/examples/solid_cantilever_problem/inputs/geometry/cantilever.stp)

- Outputs under `results/shell-cantilever-problem/`:
  - `logs/`
  - `mesh/`
  - `solver/`
  - `reports/`

## Notes

- The gmsh shell path selects the `max_y` planar face from the shared STEP file.
- `fea.shell_setup` uses bounding-box edge selectors to clamp the `min_x` edge
  and apply the design-state force on the `max_x` edge.
- The shell comparison model uses a fixed shell thickness of `10.0` so it acts
  as a same-envelope surrogate for the solid cantilever.

## Run

```bash
pixi install -e fea
pixi run -e fea run-shell-cantilever-example
```
