# Simple Structural Problem

This example runs a real gmsh-to-TACS shell workflow from
[`crank.stp`](/Users/markleader/git/mass_town/examples/simple_structural_problem/crank.stp).

- `gmsh` imports the STEP geometry, picks the largest planar face, meshes that
  face in 2D, and exports a `.bdf` shell model.
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

Outputs are written under `artifacts/simple-structural-problem/`.
