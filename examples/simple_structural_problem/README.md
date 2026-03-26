# Simple Structural Problem

This example models a simple plate-like component with one adjustable design
variable: thickness.

- Low thickness can trigger an `analysis.stress_exceeded` failure.
- Poor mesh quality can trigger a `mesh.poor_quality` failure.
- The workflow recovers by refining the mesh and increasing thickness until the
  analysis passes.

Run it with:

```bash
pixi run -e fea mass-town run examples/simple_structural_problem
```

This checked-in example now targets the real `tacs` FEA backend. Running the
full workflow requires TACS plus the sample `analysis/model.bdf` input. The
current MVP expects structural loads and boundary conditions to be defined in
that BDF file.

The example is pinned to the `mock` meshing backend so it runs without external
meshing tools. To try the real `gmsh` plugin, point `meshing.geometry_input_path`
at a `.step` file and set `meshing.tool: gmsh` or `meshing.tool: auto`. If you
want the mesh step to produce a TACS-ready structural model directly, also set
`meshing.output_format: bdf`.

FEA now follows the same plugin architecture. `config.tacs.yaml` is included as
an explicit reference config showing how to select the `tacs` backend:

```bash
cp examples/simple_structural_problem/config.tacs.yaml examples/simple_structural_problem/config.yaml
pixi run -e fea mass-town run examples/simple_structural_problem
```

The TACS MVP expects `fea.model_input_path` to point to a `.bdf` structural
model file. Future FEA backends can be added under `plugins/` without changing
core orchestration.

Example gmsh-to-TACS flow:

1. create gmsh physical groups on the geometry you want preserved as regions
2. configure the mesh plugin with `tool: gmsh` and `output_format: bdf`
3. run the workflow to generate a `.bdf` mesh artifact
4. use that exported BDF as downstream input for TACS / pyTACS, replacing the
   placeholder material and property cards as needed
