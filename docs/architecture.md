# Architecture

`mass_town` models an engineering organization in software:

- `ChiefEngineer` supervises execution and chooses the next action.
- `TriageEngine` classifies failures and recommends bounded recovery steps.
- Discipline agents execute narrow tasks and return structured results.
- Discipline interfaces define stable request/result contracts.
- Tool plugins implement concrete backends behind those discipline contracts.
- Filesystem-backed storage persists state, diagnostics, history, and artifacts.

The design keeps workflow knowledge outside model context so the same run can be
inspected, resumed, or handed to a future LLM outer-loop controller.

## LLM outer-loop direction

The planned LLM layer is an outer-loop orchestration system around deterministic
optimization runs.

- Users still kick off an optimization manually from a fully specified problem definition.
- Deterministic code still owns the inner execution loop, solver calls, and optimization iterations.
- The LLM layer inspects structured run summaries, diagnostics, and logs after a run or discipline step completes.
- The LLM layer may propose bounded rerun actions such as solver tolerance changes, iteration-limit changes, meshing adjustments, or optimizer-setting changes.
- The LLM layer may automatically trigger a restart only within explicit retry budgets, time budgets, and permitted action classes.
- The LLM layer must not directly modify numerical state inside solver loops.
- The LLM layer must not silently change loads, boundary conditions, objectives, constraints, or design intent.
- CAD or geometry edits are future work and remain out of scope for the first LLM phase.

This direction treats the LLM as a guarded chief engineer for reruns and
recovery, not as a replacement for deterministic discipline execution.

## Knowledge boundaries for LLM roles

Future LLM roles should follow the same separation principles as the codebase.

- Each role may have a curated, version-controlled markdown knowledge file for discipline-level guidance.
- Tool-specific knowledge should live with the relevant plugin boundary rather than in shared core prompts.
- Persistent run observations should be stored as artifacts or history, not silently folded into permanent knowledge.
- Promotion of a "lesson learned" into permanent knowledge should happen through an intentional repo change.

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
