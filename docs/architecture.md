# Architecture

`mass_town` models an engineering organization in software:

- `ChiefEngineer` supervises execution and chooses the next action.
- `TriageEngine` classifies failures and recommends bounded recovery steps.
- Discipline agents execute narrow tasks and return structured results.
- Discipline interfaces define stable request/result contracts.
- Tool plugins implement concrete backends behind those discipline contracts.
- Filesystem-backed storage persists state, diagnostics, history, and artifacts.

The design keeps workflow knowledge outside model context so the same run can be
inspected, resumed, or handed to a future LLM controller.

## Plugin-based disciplines MVP

Meshing and FEA now use the plugin split directly.

- Core orchestration depends on a normalized `MeshingRequest`,
  `MeshingResult`, and `MeshingBackend` contract.
- Core orchestration depends on a normalized `FEARequest`, `FEAResult`, and
  `FEABackend` contract.
- Concrete tools are discovered through a lightweight lazy registry.
- `plugins/gmsh/` provides the first real backend and shells out to the
  external `gmsh` executable.
- The gmsh plugin now separates mesh extraction from export writers, so the
  same gmsh-generated mesh can be emitted as `.msh` or normalized into a
  deterministic TACS-friendly `.bdf`.
- `plugins/tacs/` provides the first real FEA backend and keeps all TACS
  imports isolated from core code.
- `plugins/mock/` provides a deterministic meshing fallback so the repo remains
  runnable without optional meshing tool installation.

The core package never imports `gmsh` or `tacs` eagerly, so MassTown imports
cleanly even when optional tools are absent.
