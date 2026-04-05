# Topology Cantilever Problem

This example is the Phase 3.1 topology baseline for MassTown. It runs a
dedicated topology workflow with an internal structured rectangular mesh, a
single plane-stress load case, density filtering, Heaviside projection, and an
optimality-criteria update loop.

- Inputs live directly in the example directory:
  - [`config.yaml`](/Users/markleader/git/mass_town/examples/topology_cantilever_problem/config.yaml): topology workflow definition
  - [`design_state.yaml`](/Users/markleader/git/mass_town/examples/topology_cantilever_problem/design_state.yaml): seed run state
- Geometry source and meshing assumptions:
  - the geometry is an internal `lx` by `ly` rectangle defined in `topology.domain`
  - the mesh is a structured `nelx` by `nely` quadrilateral grid generated inside the topology backend
  - the backend supports only this structured 2D plane-stress topology formulation in Phase 3.1
- Analysis and optimization assumptions:
  - the left boundary (`min_x`) is fixed in both translational DOFs
  - a single vertical point load is applied at the mid-height node on the right boundary
  - the objective is compliance minimization
  - the constraint is target volume fraction
  - densities are regularized with a radius-based density filter and smooth Heaviside projection

Generated outputs are standardized under `results/topology-cantilever-problem/`:

- `logs/`: workflow and topology iteration logs
- `mesh/`: structured mesh metadata
- `reports/`: topology history, final density field, final density image, topology summary, and `run_summary.json`

Run it with:

```bash
pixi install -e topopt
pixi run -e topopt run-topology-example
```

The regression summary is written to
`results/topology-cantilever-problem/reports/run_summary.json`.
