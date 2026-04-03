# TODO

## Guiding principle

Build capability in layers. Prioritize deterministic solver and optimization infrastructure first. Introduce an LLM-based driver only after there are enough modeling choices, physics branches, and failure-recovery paths that rule-based orchestration becomes difficult to maintain.

---

## Phase 0 — Stabilize the current baseline

### Goals

* Keep one simple, always-working reference example.
* Make the CAD → mesh → BDF → TACS → update loop easy to run and debug.
* Ensure future examples do not break the current plane-stress path.

### Tasks

* [x] Preserve the current 2D plane-stress thickness-sizing example as the baseline regression case.
* [x] Document the exact assumptions of the baseline example:
  * STEP input requirements
  * Gmsh meshing assumptions
  * BDF export assumptions
  * TACS-side BC and load application
  * objective / constraint definitions

* [x] Add a simple regression test that checks:
  * mesh generation succeeds
  * BDF export succeeds
  * TACS solve succeeds
  * optimization loop converges to a feasible design

* [x] Save key outputs for regression comparison:
  * mass
  * max stress
  * final thickness
  * iteration count
  
* [x] Define a standard example folder layout for all future problems.
* [x] Define a standard result folder layout for logs, meshes, plots, and solution summaries.

### Deliverables

* One stable baseline example
* One regression test
* Minimal documentation for reproducing the run

Phase 0 is complete. The checked-in baseline example now defines the canonical
example layout and emits a normalized `run_summary.json` for regression checks.

---

## Phase 1 — Generalize single-discipline structural optimization

### Goals

* Move from a trivial scalar design variable problem to a real sizing-optimization framework.
* Build the abstraction needed for vector design variables and multiple constraints.

### Tasks

#### 1.1 Design variable abstraction

* [x] Create a generic design-variable interface independent of any one example.
* [x] Support at least these DV types:
  * scalar thickness
  * region-wise thickness
  * element-wise thickness

* [x] Define a DV-to-analysis mapping layer so the optimizer does not directly manipulate solver internals.
* [x] Add bounds and initial values handling.
* [x] Add per-DV metadata such as name, region, units, and active/inactive status.

#### 1.2 Shell sizing example

* [x] Add a shell-element structural example.
* [ ] Define a shell meshing path in the meshing plugin.
* [x] Define shell property assignment in the FEA plugin.
* [x] Use multiple thickness design variables, not just one scalar thickness.
* [x] Verify stresses and mass trends behave as expected.

#### 1.3 Multiple load cases

* [x] Add support for multiple static load cases in one problem.
* [x] Decide how shared design variables are handled across cases.
* [x] Add problem definitions for:
  * single load case
  * multiple load cases with shared constraints
* [x] Document a future multiple load case problem definition for aggregated constraints (implementation deferred to 1.4).

* [x] Add reporting for worst-case load case.

#### 1.4 Constraint aggregation

* [x] Implement KS aggregation or p-norm aggregation for stress constraints.
* [x] Make the aggregation method configurable.
* [x] Validate aggregation behavior against raw element stresses.
* [x] Add plots or summaries showing constraint aggregation quality.

### Deliverables

* Shell sizing example with multiple DVs
* Multiple load case support
* Aggregated stress constraint support

---

## Phase 2 — Expand structural physics coverage

### Goals

* Add new analysis types while keeping the same optimization and orchestration interfaces.
* Test whether the solver/plugin abstraction is actually general enough.

### Tasks

#### 2.1 Solid-element example

* [x] Add a 3D solid mesh path.
* [x] Add a solid-element TACS example.
* [x] Define how BCs and loads are specified for solid problems.
* [x] Compare shell vs solid behavior on a simple benchmark geometry.

#### 2.2 Buckling analysis

* [ ] Add linear buckling analysis support.
* [ ] Define a common interface for eigenvalue-based constraints.
* [ ] Create a buckling-constrained sizing example.
* [ ] Verify feasibility logic for minimum buckling load factor constraints.

#### 2.3 Modal / dynamic analysis

* [ ] Add modal analysis support.
* [ ] Define frequency constraints in the optimization interface.
* [ ] Create a frequency-constrained structural example.
* [ ] Decide whether transient dynamics belongs in the initial roadmap or should wait.

### Deliverables

* Solid example
* Buckling-constrained example
* Frequency-constrained example

---

## Phase 3 — Introduce topology optimization

### Goals

* Add field-based structural design capability.
* Force the framework to handle high-dimensional design spaces.

### Tasks

#### 3.1 Core topology optimization infrastructure

* [ ] Define topology design variables at the element level.
* [ ] Add density filtering.
* [ ] Add projection / continuation support.
* [ ] Define volume-fraction constraints.
* [ ] Add compliance objective support.

#### 3.2 Example problems

* [ ] Add a 2D compliance-minimization example.
* [ ] Add a stress-constrained topology example if practical.
* [ ] Add plots for density field evolution over iterations.
* [ ] Add convergence summaries and final-design visualization.

#### 3.3 Numerical robustness

* [ ] Define continuation schedules for projection parameters.
* [ ] Check mesh sensitivity behavior.
* [ ] Check consistency of gradients under filtering and projection.

### Deliverables

* Working 2D topology optimization example
* Visualization and regression outputs

---

## Phase 4 — Improve model abstraction and mixed modeling

### Goals

* Support multiple model types without rewriting the whole workflow.
* Prepare for realistic structural assemblies.

### Tasks

* [ ] Define a model-type abstraction for:
  * plane stress
  * shell
  * solid
  * mixed element

* [ ] Add mixed shell/solid example support.
* [ ] Define how element groups and named regions are preserved from CAD/mesh to analysis.
* [ ] Add mesh and property queries by named region.
* [ ] Decide what metadata must survive the Gmsh → BDF path.
* [ ] Add a benchmark problem comparing shell and solid models for the same structure.

### Deliverables

* Mixed-model capability plan
* At least one mixed shell/solid example or a clearly documented placeholder

---

## Phase 5 — Formalize optimization and MDAO structure

### Goals

* Separate problem definition from execution logic.
* Make the workflow ready for OpenMDAO or a similar graph-based framework.

### Tasks

#### 5.1 Problem schema

* [ ] Define a canonical problem description format containing:
  * geometry source
  * meshing settings
  * analysis type
  * material definitions
  * BCs and loads
  * design variables
  * objectives
  * constraints
  * optimizer settings

* [ ] Ensure the same schema can represent the current baseline example and future problems.

#### 5.2 Discipline interfaces

* [ ] Standardize plugin interfaces for:
  * CAD
  * meshing
  * FEA
  * post-processing
  * optimization

* [ ] Separate data-transfer objects from solver-specific implementations.
* [ ] Define a clean handoff between meshing and FEA, especially around region naming and properties.

#### 5.3 MDAO integration

* [ ] Decide when to integrate OpenMDAO directly versus maintaining a lightweight custom graph first.
* [ ] Build a minimal MDAO-style example with at least:
  * one geometry/mesh component
  * one FEA component
  * one post-processing component
  * one optimizer
* [ ] Ensure derivatives can be propagated through the workflow if available.

### Deliverables

* Canonical problem schema
* Stable plugin interfaces
* First graph-based workflow example

---

## Phase 6 — Add discipline coupling beyond structures

### Goals

* Move from single-discipline structural optimization to real multi-discipline workflows.
* Start with simple or surrogate coupling before full CFD.

### Tasks

#### 6.1 Coupling candidates

* [ ] Choose the first coupled example. Candidate options:
  * thermal load → structural response
  * pressure field proxy → structural response
  * simple aerodynamic load model → structural response

* [ ] Prefer a coupling path that is simple enough to debug but rich enough to justify MDAO.

#### 6.2 CFD-lite / surrogate path

* [ ] Add a placeholder CFD discipline or load surrogate.
* [ ] Define data exchange requirements between CFD and structures.
* [ ] Add one coupled example with deterministic data transfer.

#### 6.3 Real CFD path

* [ ] Decide the first real CFD tool and coupling fidelity.
* [ ] Add a plugin interface that does not force CFD as a core repo dependency.
* [ ] Define whether coupling is one-way or two-way for the first example.

### Deliverables

* First coupled multidisciplinary example
* CFD plugin plan

---

## Phase 7 — Introduce the LLM-based driver

### Guiding rule

Do not use the LLM as the numerical controller. Use it first as a planner that emits a structured execution plan which is then run by deterministic code.

### Start only after these conditions are met

* [ ] At least 3 structural analysis modes exist, for example:
  * static
  * buckling
  * modal

* [ ] At least 2 model choices exist, for example:
  * shell
  * solid

* [ ] At least 2 optimization formulations exist, for example:
  * sizing
  * topology

* [ ] There are enough branching and failure-recovery cases that rule-based orchestration is becoming cumbersome.

### First LLM-driver tasks

* [ ] Use the LLM to map a user request into a structured problem specification.
* [ ] Use the LLM to choose among existing deterministic workflows.
* [ ] Use the LLM to propose recovery actions after failures, but require deterministic validation before execution.
* [ ] Log all LLM decisions and the exact structured plan they produced.

### Later LLM-driver tasks

* [ ] Add multi-step planning across disciplines.
* [ ] Add failure triage and rerun strategies.
* [ ] Add design-study setup generation from natural language requests.
* [ ] Add model-form selection recommendations, with explicit confidence and fallback rules.

### Non-goals for the first LLM phase

* [ ] Do not let the LLM directly update numerical states inside the solve loop.
* [ ] Do not let the LLM replace the optimizer.
* [ ] Do not let the LLM make irreversible changes without validation.

### Deliverables

* LLM planner prototype
* Structured plan schema
* Deterministic executor for LLM-generated plans

---

## Cross-cutting infrastructure tasks

### Documentation

* [ ] Write a short architecture overview for the repo.
* [ ] Document plugin boundaries and responsibilities.
* [ ] Document example maturity levels:
  * baseline
  * experimental
  * advanced

* [ ] Add one page describing the roadmap from deterministic driver to LLM planner.

### Testing

* [ ] Add regression tests for every released example.
* [ ] Add schema validation tests for problem definitions.
* [ ] Add interface tests for each plugin type.
* [ ] Add smoke tests that confirm external-tool handoffs work.

### Logging and reproducibility

* [ ] Log all solver inputs and key outputs per run.
* [ ] Save optimization histories in a consistent format.
* [ ] Save mesh and model metadata for postmortem debugging.
* [ ] Add a run manifest capturing code version, plugin versions, and example settings.

### Performance and robustness

* [ ] Add timing summaries for CAD, meshing, FEA, and optimization phases.
* [ ] Identify the slowest steps in the current loop.
* [ ] Add failure handling for common issues:
  * meshing failure
  * missing named region
  * infeasible load or BC setup
  * optimization divergence

* [ ] Define standardized recovery messages and fallback actions.

---

## Recommended task priority

### Immediate next tasks

* [ ] Preserve and document the current baseline example.
* [ ] Build DV abstraction for scalar and vector thickness variables.
* [ ] Add shell sizing example.
* [ ] Add multiple load case support.
* [ ] Add KS or p-norm stress aggregation.

### Next wave

* [ ] Add buckling analysis and a buckling-constrained sizing example.
* [ ] Add a solid-element example.
* [ ] Define the canonical problem schema.
* [ ] Standardize plugin interfaces.

### After that

* [ ] Add 2D topology optimization.
* [ ] Build the first graph-based MDAO workflow.
* [ ] Add a simple coupled multidisciplinary example.

### Only after the above

* [ ] Start the first LLM-planner prototype.

---

## Suggested milestone sequence

### Milestone 1

* Stable baseline example
* DV abstraction
* Shell sizing

### Milestone 2

* Multiple load cases
* Constraint aggregation
* Better reporting and regression tests

### Milestone 3

* Buckling example
* Solid example
* Common problem schema

### Milestone 4

* Topology optimization
* Graph-based MDAO workflow

### Milestone 5

* First multidisciplinary coupled example
* LLM planner prototype

---

## Open questions to resolve

* [ ] Should OpenMDAO be introduced before or after topology optimization?
* [ ] Should the first coupled discipline be thermal, CFD-lite, or true CFD?
* [ ] How much solver-specific logic should live inside plugins versus shared core abstractions?
* [ ] What metadata must survive from CAD through meshing into FEA for robust named-region workflows?
* [ ] What is the minimum reliable structured schema for an LLM-generated execution plan?

---

## Bottom line

Near-term effort should focus on strengthening deterministic structural analysis and optimization infrastructure. The best next example is not a fully coupled LLM-orchestrated workflow. It is a shell-sizing problem with multiple design variables, multiple load cases, and aggregated constraints. Once that exists, buckling and topology optimization become much more natural extensions. The LLM driver should come after the deterministic workflow graph is rich enough that orchestration choices are genuinely nontrivial.
