# mass_town: initialize repository

## Project overview

Initialize a new repository for **mass_town**, an experimental engineering workflow supervision system.

The goal of this project is to build a prototype system that manages engineering simulation pipelines and can:

- detect failures
- diagnose likely causes
- select corrective actions
- dispatch discipline agents to execute those actions
- resume the workflow

The architecture is inspired by real engineering organizations:

- **Chief Engineer** supervises the workflow
- **Discipline agents** execute bounded engineering tasks
- **Deterministic tools** perform physics computation
- **Structured state** persists workflow knowledge

This system is **not a swarm of chatting agents**.

Instead, it is an **engineering workflow supervisor** designed to manage brittle pipelines such as:
CAD → mesh → solver → postprocess → optimization

The core value of the system is **failure triage and recovery**, not just task execution.

---

# Core design principles

## 1. Agents orchestrate, tools compute

The system must never attempt to replace engineering solvers.

Agents should:

- inspect workflow state
- interpret diagnostics
- select corrective actions
- dispatch deterministic tools

Tools perform:

- geometry generation
- mesh generation
- structural analysis
- optimization updates

Concrete tools can be split behind discipline-specific plugin backends so core
orchestration remains tool-agnostic. Meshing and FEA now follow this pattern.

---

## 2. State must live outside model context

All persistent information must be stored in files, not only in LLM context.

Persist:

- design variables
- geometry state
- mesh state
- analysis results
- failure diagnostics
- decision history
- artifact paths

---

## 3. Structured workflow supervision

The core system is a **triage loop** rather than a static pipeline.
observe workflow state
↓
detect anomaly or failure
↓
classify failure type
↓
triage root cause
↓
select corrective action
↓
dispatch discipline agent
↓
update design state
↓
repeat

---

## 4. Bounded discipline agents

Each discipline agent performs a **narrow task** and returns structured diagnostics.

Examples:

- geometry agent
- mesh agent
- FEA agent
- optimizer agent

Agents do not coordinate with each other directly.

The **Chief Engineer** manages coordination.

---

## 5. Deterministic first, AI later

The initial prototype should implement deterministic logic for triage and recovery.

The architecture should allow replacing the triage engine with an LLM controller later.

---

# Initial repository requirements

Create a functional Python repository with:

- workflow orchestration engine
- structured design state
- failure taxonomy
- triage engine
- discipline agents
- artifact storage
- CLI interface
- example problem
- unit tests
- documentation

The goal is a **working engineering workflow prototype**.

---

# Recommended tech stack

Use the following tools unless there is a strong reason otherwise.

Python 3.11+

Libraries:

- `pydantic` for structured models
- `typer` for CLI
- `pytest` for testing
- `yaml` or `json` for state persistence
- Python standard library logging

Avoid heavy dependencies.

---

# Repository structure

Create the following repository layout.

mass_town/
├── README.md
├── LICENSE
├── pyproject.toml
├── .gitignore
│
├── docs/
│ ├── architecture.md
│ ├── workflow.md
│ ├── failure_taxonomy.md
│ └── roadmap.md
│
├── examples/
│ └── simple_structural_problem/
│ ├── design_state.yaml
│ ├── config.yaml
│ └── README.md
│├── src/
│ └── mass_town/
│ | ├── init.py
│ | ├── cli.py
│ | ├── config.py
│ | ├── logging_utils.py
│ │
│ ├── disciplines/
│ │ ├── meshing/
│ │ │ ├── base.py
│ │ │ ├── models.py
│ │ │ └── registry.py
│ │ └── fea/
│ │   ├── base.py
│ │   ├── models.py
│ │   └── registry.py
│ │
│ ├── models/
│ │ ├── design_state.py
│ │ ├── task.py
│ │ ├── result.py
│ │ └── artifacts.py
│ │
│ ├── orchestration/
│ │ ├── workflow_engine.py
│ │ ├── chief_engineer.py
│ │ ├── triage_engine.py
│ │ ├── task_queue.py
│ │ └── state_manager.py
│ │
│ ├── agents/
│ │ ├── base_agent.py
│ │ ├── geometry_agent.py
│ │ ├── mesh_agent.py
│ │ ├── fea_agent.py
│ │ └── optimizer_agent.py
│ │
│ ├── adapters/
│ │ ├── geometry_adapter.py
│ │ ├── fea_adapter.py
│ │ └── optimizer_adapter.py
│ │
│ ├── runtime/
│ │ ├── runtime_interface.py
│ │ └── local_runtime.py
│ │
│ └── storage/
│ ├── artifact_store.py
│ ├── filesystem.py
│ └── run_registry.py
│
├── plugins/
│ ├── gmsh/
│ ├── mock/
│ └── tacs/
│
└── tests/
├── test_state_manager.py
├── test_triage_engine.py
├── test_workflow_engine.py
└── test_cli.py


---

# Core data models

Use `pydantic` to define structured models.

## DesignState

Fields should include:

- problem_name
- design_id
- revision
- design_variables
- objectives
- constraints
- geometry_state
- mesh_state
- analysis_state
- optimizer_state
- artifacts
- decision_history

---

## Task

Represents work dispatched to discipline agents.

Fields:

- task_id
- role
- task_type
- status
- input_payload
- output_payload
- timestamps

---

## Result

Each agent returns a structured result.

Fields:

- status: success or failure
- failure_type (optional)
- message
- metrics
- suggested_actions
- artifacts

---

# Failure taxonomy

Implement a structured failure classification system.

Possible failure types:

GEOMETRY_INVALID
MESH_FAILED
MESH_POOR_QUALITY
SOLVER_DIVERGED
SOLVER_UNSTABLE
CONSTRAINT_VIOLATED
OPTIMIZER_STEP_TOO_LARGE
UNKNOWN_FAILURE

Discipline agents must return one of these when failures occur.

---

# Recovery action system

Define a finite set of corrective actions.

Example actions:

UPDATE_GEOMETRY
REGENERATE_MESH
COARSEN_MESH
REFINE_MESH
ADJUST_DESIGN_VARIABLE
REDUCE_OPTIMIZATION_STEP
RETRY_ANALYSIS
REVERT_TO_PREVIOUS_DESIGN
ABORT_WORKFLOW

The Chief Engineer selects actions based on triage results.

---

# Triage engine

Create module:

triage_engine.py

Responsibilities:

- inspect latest task result
- classify failure
- determine likely cause
- select corrective action
- generate decision explanation

The initial implementation should use deterministic rules.

Future versions may replace this with an LLM.

---

# Chief Engineer

The Chief Engineer coordinates the workflow.

Responsibilities:

- monitor design state
- detect failures or anomalies
- call triage engine
- dispatch discipline agents
- update state
- record decisions

Pseudo-logic:

if last task failed:
triage failure
select recovery action
elif workflow incomplete:
dispatch next analysis task
else:
mark workflow complete

---

# Discipline agents

Each agent must implement:

`run(task, state) -> TaskResult`

Agents required for MVP:

### Geometry agent

Responsibilities:

- generate geometry from design variables
- detect invalid geometry
- write geometry artifact

---

### Mesh agent

Responsibilities:

- generate mesh
- detect mesh failures or poor quality
- return mesh metrics

---

### FEA agent

Responsibilities:

- run structural analysis
- return stress/displacement metrics
- detect solver divergence

For MVP this may use a **mock or analytic structural model**.

---

### Optimizer agent

Responsibilities:

- update design variables
- detect infeasible steps
- mark geometry stale

---

# Artifact storage

All workflow artifacts should be stored on disk.

Suggested layout:

runs/
run_0001/
geometry/
mesh/
fea/
optimizer/
decisions/
state/
design_state.yaml
logs/

---

# Decision logging

Maintain a decision log describing workflow reasoning.

Example entry:

iteration 8
mesh failure detected
triage: geometry thickness below threshold
action: increase thickness 5%
result: mesh success

This log is a key artifact of the system.

---

# CLI interface

Provide a simple CLI.

Commands:

mt init <example_dir>
mt run <example_dir>
mt step <example_dir>
mt status <example_dir>

Behavior:

- `init`: initialize workspace
- `run`: run full workflow
- `step`: execute one iteration
- `status`: print summary

---

# Example problem

Provide a minimal structural example:

examples/simple_structural_problem

Design variables:

- thickness
- width
- height

Objective:

- minimize mass

Constraint:

- maximum stress below allowable

---

# Testing requirements

Implement tests for:

- state persistence
- triage logic
- workflow execution
- CLI commands

---

# Documentation

Provide documentation for:

### README

Explain:

- what mass_town is
- architecture
- quickstart
- limitations

### docs/architecture.md

Explain:

- Chief Engineer
- discipline agents
- triage system
- artifact storage

### docs/workflow.md

Explain the supervisory loop.

### docs/failure_taxonomy.md

Describe failure types and recovery actions.

### docs/roadmap.md

Outline future directions.

---

# Future directions

Possible future work:

- LLM-powered triage engine
- integration with real CAD/mesh/FEA tools
- additional disciplines (aero, controls, propulsion, thermal, etc.)
- adaptive fidelity management
- design exploration automation
- distributed workflow execution

---

# Implementation order

Implement in this order:

1. repository skeleton
2. state models
3. artifact storage
4. triage engine
5. discipline agents
6. workflow engine
7. CLI
8. example problem
9. tests
10. documentation

---

# Final instruction

Initialize the repository as a **serious engineering workflow prototype**.

Prioritize:

- clarity
- robustness
- structured state
- deterministic behavior
- extensibility

Avoid unnecessary complexity.

The initial goal is a **working failure-aware engineering workflow supervisor**.
