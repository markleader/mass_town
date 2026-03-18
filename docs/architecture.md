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

## Meshing discipline MVP

Meshing is the first discipline that uses the plugin split directly.

- Core orchestration depends on a normalized `MeshingRequest`,
  `MeshingResult`, and `MeshingBackend` contract.
- Concrete tools are discovered through a lightweight lazy registry.
- `plugins/gmsh/` provides the first real backend and shells out to the
  external `gmsh` executable.
- `plugins/mock/` provides a deterministic fallback so the repo remains
  runnable without optional tool installation.

The core package never imports `gmsh` eagerly, so MassTown imports cleanly even
when the tool is absent.
