# ROADMAP

## Vision

MassTown is a framework for orchestrating engineering design workflows across multiple disciplines, solvers, and modeling fidelities. It is intended to enable structured, repeatable, and extensible design studies while gradually incorporating higher-level automation, including LLM-assisted planning and decision-making.

The long-term goal is not just to automate individual analyses, but to manage the full lifecycle of design iteration: setup, execution, diagnosis, recovery, and improvement.

---

## Intended future use-cases

* Tune optimizer settings between optimization runs using diagnostics from prior runs
* Update geometry and re-mesh between optimization cycles
  * Handle shape optimization that hits geometric bounds
  * Recover from mesh-quality failures caused by mesh morphing
* Automatically select analysis types (static, buckling, modal) based on problem definition
* Switch between modeling fidelities (shell vs solid, coarse vs refined mesh)
* Coordinate multi-load-case and multi-scenario optimization studies
* Perform multidisciplinary design studies with structured data flow between disciplines
* Perform failure detection, triage, and recovery across the workflow
* Generate reproducible design studies from structured or natural-language input

---

## What MassTown is

* A workflow orchestration layer for engineering design and analysis
* A system that connects CAD, meshing, FEA, optimization, and eventually CFD and trajectory tools
* A framework built around explicit data flow between well-defined components (plugins)
* A platform for building increasingly complex design examples in a controlled and testable way
* A system that separates problem definition from execution
* A foundation for integrating deterministic solvers with higher-level planning logic
* A platform for experimenting with LLM-assisted planning in engineering workflows

---

## What MassTown is not

* Not a replacement for physics solvers (e.g., TACS, CFD codes)
* Not an optimizer implementation from scratch
* Not a black-box “AI designs everything” system
* Not a system where LLMs directly control numerical solve loops
* Not tightly coupled to any single external tool (e.g., Gmsh should not become a hard dependency)

---

## Core principles

### 1. Deterministic foundation first

All workflows must be executable deterministically without LLM involvement. LLMs are layered on top, not embedded in core numerical logic.

### 2. Explicit data flow

All data passed between disciplines must be explicit, structured, and inspectable. Hidden state should be avoided.

### 3. Plugin-based architecture

Each discipline (CAD, meshing, FEA, optimization, CFD, etc.) is implemented as a plugin with a well-defined interface.

### 4. Problem-definition driven

Workflows should be generated from a structured problem description rather than hard-coded scripts.

### 5. Reproducibility

Every run should be reproducible with:

* input definition
* solver settings
* mesh and model metadata
* recorded outputs and logs

### 6. Incremental capability growth

New features should build on previous layers rather than introducing entirely new paradigms prematurely.

### 7. Failure-aware design

Failures (mesh issues, solver divergence, infeasible constraints) are expected and must be first-class citizens in the workflow.

---

## Architecture overview

### Layers

1. Problem Definition Layer

   * Structured description of geometry, physics, objectives, constraints, and design variables

2. Workflow Execution Layer

   * Deterministic orchestration of CAD → meshing → analysis → post-processing → optimization

3. Plugin Layer

   * CAD
   * Meshing
   * FEA
   * Optimization
   * (Future) CFD, trajectory, thermal

4. Planning Layer (future)

   * LLM-assisted planning and decision-making
   * Converts user intent into structured execution plans

---

## Capability roadmap

### Phase 0 — Baseline (complete)

* 2D plane stress example
* Single thickness design variable
* Single constraint (max stress)
* Deterministic optimization loop

### Phase 1 — Structural sizing (near-term priority)

* Shell element support
* Multiple design variables (region-wise or element-wise thickness)
* Multiple load cases
* Constraint aggregation (KS or p-norm)

**Outcome:** A realistic structural sizing optimization problem

---

### Phase 2 — Expanded structural physics

* Solid element support
* Buckling analysis
* Modal/frequency analysis

**Outcome:** Multiple physics modes using a shared infrastructure

---

### Phase 3 — Topology optimization

* Element-wise density variables
* Filtering and projection
* Compliance and volume constraints

**Outcome:** High-dimensional design problems with field variables

---

### Phase 4 — Model abstraction and mixed modeling

* Support for multiple model types (shell, solid, mixed)
* Named-region propagation from CAD → mesh → FEA
* Model comparison workflows

**Outcome:** Ability to switch modeling fidelity without rewriting workflows

---

### Phase 5 — MDAO structure

* Canonical problem schema
* Graph-based workflow execution (e.g., OpenMDAO or equivalent)
* Discipline-level separation with clean interfaces

**Outcome:** True workflow composition and multi-scenario optimization

---

### Phase 6 — Multidisciplinary coupling

* Introduce a second discipline (thermal or CFD-lite)
* Define data exchange between disciplines
* Add coupled optimization example

**Outcome:** First true MDAO use-case

---

### Phase 7 — LLM-assisted planning

#### Entry criteria

* Multiple analysis types exist
* Multiple model choices exist
* Multiple optimization formulations exist
* Workflow branching and failure handling become nontrivial

#### Initial capabilities

* Convert user intent into structured problem definitions
* Select among existing workflows
* Suggest recovery strategies after failures

#### Constraints

* LLM does not control solver loops
* All plans must be validated before execution

**Outcome:** LLM acts as a planner, not a numerical controller

---

## Near-term focus (next milestones)

1. Shell sizing with multiple design variables
2. Multiple load case support
3. Constraint aggregation
4. Buckling-constrained example

These steps provide the minimum complexity needed before introducing higher-level orchestration.

---

## Long-term direction

MassTown evolves from:

1. Scripted deterministic workflows
2. Structured workflow graphs
3. Failure-aware orchestration
4. LLM-assisted planning and adaptation

The end state is a system that can:

* interpret a design objective
* construct an appropriate workflow
* execute it robustly
* diagnose issues
* iterate intelligently

---

## Open questions

* When should OpenMDAO be introduced relative to topology optimization?
* What is the first coupled discipline to implement (thermal vs CFD-lite vs full CFD)?
* What metadata must persist across CAD, meshing, and FEA for robust workflows?
* What is the minimal structured schema required for LLM-generated plans?
* How should failure-recovery strategies be represented and validated?

---

## Bottom line

MassTown should first become a robust, extensible, deterministic workflow engine for structural optimization problems. Only after that foundation is solid should LLM-based planning be introduced. The value of the system comes from combining strong physics-based tools with structured orchestration, not from replacing them.
