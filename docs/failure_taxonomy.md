# Failure Taxonomy

The initial taxonomy is small and deterministic:

- `geometry.invalid`
  Raised when dimensions are non-physical or violate simple geometry rules.
- `mesh.poor_quality`
  Raised when mesh quality falls below the configured threshold.
- `analysis.stress_exceeded`
  Raised when computed stress is above the allowable limit.
- `optimization.stalled`
  Reserved for future optimizer convergence handling.
- `workflow.unknown`
  Fallback category for unexpected failures.

Each failure maps to a triage action such as `repair_geometry`,
`refine_mesh`, or `increase_thickness`.
