# Agent Notes

## Pixi environment model

This repository uses three named Pixi environments:

- `default`: lightweight core development and tests
- `mdao`: extends `default` with OpenMDAO-focused dependencies
- `fea`: extends `mdao` with FEA/TACS workflow support

Environments are selected one at a time (`pixi run -e <env> ...` or
`pixi shell -e <env>`). Do not describe them as stacked or mixed in a single
runtime session.

## Dependency placement rules

- Keep `default` minimal and fast to install.
- Put OpenMDAO-like tooling in `mdao`, not `default`.
- Put TACS/FEA-specific tooling in `fea`, not `default`.
- Do not promote heavy optional dependencies into `default`.
- Prefer the lightest environment that can run a new example or task.

## TACS local setup expectations

- TACS is optional and local setup is still required.
- Avoid hard-coding machine-specific absolute paths in `pixi.toml`.
- Use documented local hooks (`../tacs` comment placeholder and
  `install-local-tacs` task with optional `TACS_DIR`) for local development.

## Docs and task consistency

- Keep README/docs Pixi command examples aligned with actual environment names
  and tasks defined in `pixi.toml`.
- When adding or renaming a Pixi task, update all user-facing examples in the
  same change.

## Current repo commands

- Core validation uses `pixi run -e default test`.
- OpenMDAO checks belong in `mdao`, for example
  `pixi run -e mdao python -c "import openmdao.api as om; print(om.__version__)"`.
- The checked-in structural baseline is TACS-backed; run it from `fea` with
  `pixi run -e fea run-fea-example`.
- The baseline regression check is `pixi run -e fea test-fea-baseline`.
- Use `pixi run -e fea install-local-tacs` for local TACS wiring, with optional
  `TACS_DIR` when the checkout is not under `~/git/tacs`.
- Direct CLI entry points currently documented in the repo are
  `pixi run -e fea mass-town run examples/simple_structural_problem` and
  `pixi run -e fea mass-town status examples/simple_structural_problem/design_state.yaml`.

## Current workflow outputs

- Example runs write generated artifacts under `results/<run_id>/`.
- Keep the standardized subdirectories consistent: `logs/`, `mesh/`,
  `solver/`, and `reports/`.
- Baseline regressions use `reports/run_summary.json` as the normalized summary
  artifact and regression contract.


## Engineering Hygiene & Infrastructure (Always-On Requirements)

These rules apply to **every feature, example, and plugin update**. Do not defer them.

---

### 1. Testing requirements

For any new capability:
- Add at least one **minimal working example**
- Add at least one **regression check**:
  - does not need exact numerical match
  - must verify key metrics (e.g., convergence, feasibility, trends)

Always:
- Ensure existing examples still run

Do not merge features that break existing examples.

---

### 4. Problem definition consistency

All examples must:
- Follow a **consistent problem-definition structure**
- Explicitly define:
  - geometry source
  - meshing settings
  - analysis type
  - boundary conditions and loads
  - design variables
  - objectives and constraints

Avoid hard-coded logic that bypasses this structure.

---

### 5. Plugin boundaries must remain clean

When adding or modifying functionality:
- Do not introduce cross-dependencies between plugins
- Do not place tool-specific logic outside its plugin

Maintain clear interfaces between:
- meshing ↔ FEA
- FEA ↔ optimization

If tool-specific assumptions leak into core code, refactor.

---

### 6. Named regions and metadata must persist

Across CAD → mesh → FEA:
- Preserve named regions or groups whenever possible
- Ensure they are queryable downstream

Do not discard metadata needed for:
- boundary conditions
- loads
- design variable assignment

---

### 7. Failure handling is required

For every workflow step:
- Anticipate common failures:
  - meshing failure
  - invalid geometry
  - solver divergence
  - infeasible constraints

Provide:
- explicit error messages
- structured failure outputs

Do not rely on uncaught exceptions as the primary failure mechanism.

---

### 8. Performance awareness

For new features:
- Add basic timing for:
  - meshing
  - analysis
  - optimization loop

Identify obvious bottlenecks early.

Do not optimize prematurely, but do not ignore scaling behavior.

---

### 9. Documentation expectations

For any new capability:
- Update or add:
  - example usage
  - assumptions and limitations
  - `TODO.md`
  - `ROADMAP.md`

Keep documentation in the same PR as the code.

If a feature cannot be understood from the example and docs, it is incomplete.

---

### 10. LLM integration constraints (when applicable)

LLMs may:
- generate plans
- suggest workflow configurations
- steer problems based on failure output

LLMs must NOT:
- modify numerical state directly

---

## Summary rule

Every contribution must leave the system:
- reproducible
- debuggable
- architecturally consistent
- extensible for future workflows

If a change improves capability but degrades one of the above, revise before merging.
