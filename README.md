# mass_town

`mass_town` is a prototype engineering workflow supervision system for brittle
pipelines such as `CAD -> mesh -> solver -> postprocess -> optimization`.

The project focuses on failure triage and recovery rather than replacing
deterministic engineering tools. A Chief Engineer observes workflow state,
classifies anomalies, selects corrective actions, dispatches bounded discipline
agents, and persists the evolving design state to disk.

## Features

- Deterministic workflow supervision loop
- Structured design state and artifact tracking with `pydantic`
- Failure taxonomy and rule-based triage engine
- Bounded geometry, mesh, FEA, and optimizer agents
- Filesystem-backed state and artifact storage
- Typer-based CLI
- Example structural problem and unit tests

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
mass-town run examples/simple_structural_problem
mass-town status examples/simple_structural_problem/design_state.yaml
pytest
```

## Repository layout

- `src/mass_town/`: application package
- `docs/`: architecture, workflow, taxonomy, and roadmap notes
- `examples/simple_structural_problem/`: runnable example input
- `tests/`: unit tests for the core orchestration and CLI

## What the prototype does

The included workflow runs four bounded tasks:

1. geometry validation and sizing
2. mesh generation or repair
3. simplified structural analysis
4. design variable update

Failures are persisted as diagnostics, then triaged into corrective actions such
as repairing geometry, refining mesh quality, or increasing thickness to satisfy
stress constraints.
