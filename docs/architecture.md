# Architecture

`mass_town` models an engineering organization in software:

- `ChiefEngineer` supervises execution and chooses the next action.
- `TriageEngine` classifies failures and recommends bounded recovery steps.
- Discipline agents execute narrow tasks and return structured results.
- Deterministic adapters emulate physics and geometry tools.
- Filesystem-backed storage persists state, diagnostics, history, and artifacts.

The design keeps workflow knowledge outside model context so the same run can be
inspected, resumed, or handed to a future LLM controller.
