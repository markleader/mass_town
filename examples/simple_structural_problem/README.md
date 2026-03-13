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
