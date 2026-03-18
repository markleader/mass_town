# Simple Structural Problem

This example models a simple plate-like component with one adjustable design
variable: thickness.

- Low thickness can trigger an `analysis.stress_exceeded` failure.
- Poor mesh quality can trigger a `mesh.poor_quality` failure.
- The workflow recovers by refining the mesh and increasing thickness until the
  analysis passes.

Run it with:

```bash
mass-town run examples/simple_structural_problem
```

The example is pinned to the `mock` meshing backend so it runs without external
meshing tools. To try the real `gmsh` plugin, point `meshing.geometry_input_path`
at a `.step` file and set `meshing.tool: gmsh` or `meshing.tool: auto`.
