from __future__ import annotations

import json
import warnings
from pathlib import Path

import openmdao.api as om

from mass_town.agents.fea_agent import FEAAgent
from mass_town.config import WorkflowConfig
from mass_town.models.artifacts import ArtifactRecord
from mass_town.models.design_state import DesignState, TaskRecord
from mass_town.models.result import Diagnostic
from mass_town.orchestration.run_reporter import RunReporter
from mass_town.orchestration.state_manager import StateManager
from mass_town.problem_schema import ProblemSchemaResolver
from mass_town.runtime.openmdao_components import (
    StructuralAnalysisComp,
    StructuralPostprocessingComp,
)
from mass_town.runtime.runtime_interface import RuntimeInterface
from mass_town.storage.artifact_store import ArtifactStore
from mass_town.storage.filesystem import ensure_run_layout
from mass_town.storage.run_registry import RunRegistry
from mass_town.disciplines.fea import FEABackendError, resolve_fea_backend


class OpenMDAORuntime(RuntimeInterface):
    def __init__(
        self,
        config: WorkflowConfig,
        state_manager: StateManager | None = None,
        artifact_store: ArtifactStore | None = None,
        run_registry: RunRegistry | None = None,
    ) -> None:
        self.config = config
        self.state_manager = state_manager or StateManager()
        self.artifact_store = artifact_store or ArtifactStore()
        self.run_registry = run_registry or RunRegistry()
        self.schema_resolver = ProblemSchemaResolver()
        self.reporter = RunReporter(config=config, schema_resolver=self.schema_resolver)
        self.fea_agent = FEAAgent()
        self._deferred_diagnostics: list[Diagnostic] = []
        self._current_log_path: Path | None = None

    def run(self, state_path: Path, run_root: Path) -> DesignState:
        state = self.state_manager.load(state_path)
        problem = self.schema_resolver.resolve(self.config, state, run_root)
        layout = ensure_run_layout(run_root, state.run_id)
        self._deferred_diagnostics = []
        state.status = "running"
        self.run_registry.start_run(state.run_id, run_root)
        self.reporter.write_problem_schema(problem, run_root, state)
        log_path = layout.logs_dir / "workflow.log"
        self._current_log_path = log_path
        self.reporter.append_workflow_log(log_path, f"run_started run_id={state.run_id} runtime=openmdao")

        validation_diagnostic = self._validate_problem(problem)
        if validation_diagnostic is not None:
            state.diagnostics.append(validation_diagnostic)
            state.status = "failed"
            return self._finish_run(state, state_path, run_root, problem)

        try:
            backend = resolve_fea_backend(self.config.fea.tool)
        except FEABackendError as exc:
            state.diagnostics.append(
                Diagnostic(
                    code="analysis.backend_unavailable",
                    message=str(exc),
                    task="fea",
                    details={"backend": self.config.fea.tool},
                )
            )
            state.status = "failed"
            return self._finish_run(state, state_path, run_root, problem)

        objective_kind = next(
            (objective.kind for objective in problem.objectives if objective.enabled),
            "feasibility",
        )
        include_optimizer = "optimizer" in self.config.initial_tasks
        include_stress_constraint = any(
            constraint.kind == "max_stress" for constraint in problem.constraints
        )
        optimization_failed = False

        try:
            problem_driver = om.Problem(reports=False)
            design_var_group = om.IndepVarComp()
            active_definitions = [
                definition
                for definition in self.schema_resolver.design_variable_definitions(problem)
                if definition.active
            ]
            for definition in active_definitions:
                design_var_group.add_output(
                    definition.id,
                    val=float(state.design_variables.get(definition.id, definition.initial_value)),
                )
            problem_driver.model.add_subsystem("design_vars", design_var_group, promotes=["*"])

            analysis = StructuralAnalysisComp(
                config=self.config,
                problem=problem,
                state=state,
                run_root=run_root,
                layout=layout,
                backend=backend,
                schema_resolver=self.schema_resolver,
                fallback_reporter=self._report_fd_fallback,
            )
            postprocess = StructuralPostprocessingComp(
                config=self.config,
                problem=problem,
                state=state,
                run_root=run_root,
                layout=layout,
                objective_kind=objective_kind,
                include_max_stress_constraint=include_stress_constraint,
            )
            problem_driver.model.add_subsystem("analysis", analysis)
            problem_driver.model.add_subsystem("postprocess", postprocess)
            for definition in active_definitions:
                problem_driver.model.connect(definition.id, f"analysis.{definition.id}")
            problem_driver.model.connect("analysis.mass", "postprocess.mass")
            problem_driver.model.connect("analysis.max_stress", "postprocess.max_stress")
            problem_driver.model.connect("analysis.displacement_norm", "postprocess.displacement_norm")

            if include_optimizer:
                problem_driver.driver = om.ScipyOptimizeDriver()
                problem_driver.driver.options["optimizer"] = "SLSQP"
                problem_driver.driver.options["disp"] = False
                problem_driver.driver.options["maxiter"] = int(problem.optimizer.max_iterations or self.config.max_iterations)
                tolerance = float(problem.optimizer.settings.get("tol", 1e-6)) if problem.optimizer else 1e-6
                problem_driver.driver.opt_settings["ftol"] = tolerance
                for definition in active_definitions:
                    problem_driver.model.add_design_var(
                        definition.id,
                        lower=definition.bounds.lower,
                        upper=definition.bounds.upper,
                    )
                problem_driver.model.add_objective("postprocess.objective")
                if include_stress_constraint:
                    # Keep a tiny feasibility buffer so the final persisted FEA pass
                    # stays strictly below the allowable stress threshold.
                    problem_driver.model.add_constraint("postprocess.max_stress_margin", upper=-1.0e-6)

            problem_driver.setup()
            if include_optimizer:
                problem_driver.run_driver()
                if getattr(problem_driver.driver, "fail", False):
                    optimization_failed = True
                    state.diagnostics.append(
                        Diagnostic(
                            code="optimization.openmdao_driver_failed",
                            message="OpenMDAO driver did not converge successfully.",
                            task="optimizer",
                            details={
                                "runtime": "openmdao",
                                "driver": type(problem_driver.driver).__name__,
                                "exit_status": getattr(problem_driver.driver.result, "exit_status", "unknown"),
                            },
                        )
                    )
            else:
                problem_driver.run_model()
        except Exception as exc:
            state.diagnostics.append(
                Diagnostic(
                    code="runtime.openmdao_failed",
                    message=str(exc),
                    task="optimizer" if include_optimizer else "fea",
                    details={"runtime": "openmdao"},
                )
            )
            state.status = "failed"
            return self._finish_run(state, state_path, run_root, problem)

        if self._deferred_diagnostics:
            state.diagnostics.extend(self._deferred_diagnostics)

        optimized_values = {
            definition.id: self._scalar_value(problem_driver.get_val(definition.id))
            for definition in active_definitions
        }
        persisted_values = {
            key: value
            for key, value in state.design_variables.items()
            if key not in optimized_values
        }
        persisted_values.update(optimized_values)
        state.design_variables = persisted_values

        if include_optimizer:
            state.iteration += 1
            objective_value = self._scalar_value(problem_driver.get_val("postprocess.objective"))
            optimizer_summary_path = layout.reports_dir / "openmdao_summary.json"
            optimizer_summary_path.write_text(
                json.dumps(
                    {
                        "runtime": "openmdao",
                        "driver": "ScipyOptimizeDriver",
                        "optimizer": "SLSQP",
                        "objective": objective_value,
                        "design_variables": optimized_values,
                        "constraint_max_stress_margin": (
                            self._scalar_value(problem_driver.get_val("postprocess.max_stress_margin"))
                            if include_stress_constraint
                            else None
                        ),
                        "iterations": getattr(problem_driver.driver.result, "iter_count", None),
                        "success": getattr(problem_driver.driver.result, "success", None),
                        "exit_status": getattr(problem_driver.driver.result, "exit_status", None),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
            optimizer_artifact = ArtifactRecord(
                name="openmdao-summary",
                path=str(optimizer_summary_path.relative_to(run_root)),
                kind="optimization_report",
                metadata={
                    "runtime": "openmdao",
                    "driver": "ScipyOptimizeDriver",
                    "optimizer": "SLSQP",
                    "objective": round(objective_value, 6),
                },
            )
            state.artifacts.append(optimizer_artifact)
            state.task_history.append(
                TaskRecord(
                    iteration=state.iteration,
                    task="optimizer",
                    status="success",
                    message="OpenMDAO optimization completed.",
                )
            )
            self.artifact_store.record(run_root, state, [optimizer_artifact])
            self.reporter.append_workflow_log(
                log_path,
                f"iteration={state.iteration} task=optimizer status=success runtime=openmdao",
            )

        state.iteration += 1
        self.reporter.append_workflow_log(
            log_path,
            f"iteration={state.iteration} task=fea event=start runtime=openmdao",
        )
        fea_result = self.fea_agent.run(state, self.config, run_root)
        self._apply_agent_result(state, fea_result)
        self.artifact_store.record(run_root, state, fea_result.artifacts)
        self.reporter.append_workflow_log(
            log_path,
            f"iteration={state.iteration} task=fea status={fea_result.status} runtime=openmdao",
        )
        state.status = (
            "recovered"
            if (not optimization_failed) and fea_result.status == "success" and state.analysis_state.passed
            else "failed"
        )
        return self._finish_run(state, state_path, run_root, problem)

    def _finish_run(
        self,
        state: DesignState,
        state_path: Path,
        run_root: Path,
        problem: object,
    ) -> DesignState:
        layout = ensure_run_layout(run_root, state.run_id)
        summary_path = self.reporter.write_run_summary(state, run_root, problem)
        self.reporter.record_run_summary_artifact(state, summary_path, run_root)
        self.artifact_store.record(run_root, state, [state.artifacts[-1]])
        self.state_manager.save(state, state_path)
        self.reporter.append_workflow_log(
            layout.logs_dir / "workflow.log",
            f"run_finished status={state.status} iteration_count={state.iteration} runtime=openmdao",
        )
        self.run_registry.finish_run(
            state.run_id,
            run_root,
            state.status,
            iteration_count=state.iteration,
            summary_path=str(summary_path.relative_to(run_root)),
        )
        return state

    def _validate_problem(self, problem: object) -> Diagnostic | None:
        if self.config.topology is not None:
            return Diagnostic(
                code="runtime.openmdao_unsupported_topology",
                message="OpenMDAO runtime does not support topology workflows yet.",
                task="optimizer",
                details={"runtime": "openmdao"},
            )
        if self.config.fea.analysis_type != "static":
            return Diagnostic(
                code="runtime.openmdao_unsupported_analysis_type",
                message="OpenMDAO runtime currently supports only structural static analysis.",
                task="optimizer",
                details={"runtime": "openmdao", "analysis_type": self.config.fea.analysis_type},
            )
        if self.config.meshing.geometry_input_path is not None or "geometry" in self.config.initial_tasks or "mesh" in self.config.initial_tasks:
            return Diagnostic(
                code="runtime.openmdao_unsupported_meshing",
                message="OpenMDAO runtime requires direct model input and excludes geometry/mesh tasks.",
                task="optimizer",
                details={"runtime": "openmdao"},
            )
        if self.config.fea.model_input_path is None:
            return Diagnostic(
                code="runtime.openmdao_missing_model_input",
                message="OpenMDAO runtime requires fea.model_input_path.",
                task="optimizer",
                details={"runtime": "openmdao"},
            )
        if self.config.initial_tasks not in (["fea"], ["fea", "optimizer"]):
            return Diagnostic(
                code="runtime.openmdao_unsupported_task_shape",
                message="OpenMDAO runtime supports only initial_tasks of [fea] or [fea, optimizer].",
                task="optimizer",
                details={"runtime": "openmdao", "initial_tasks": ",".join(self.config.initial_tasks)},
            )
        if "optimizer" in self.config.initial_tasks:
            objective_kind = next(
                (objective.kind for objective in problem.objectives if objective.enabled),
                "feasibility",
            )
            if objective_kind != "minimize_mass":
                return Diagnostic(
                    code="runtime.openmdao_unsupported_objective",
                    message="OpenMDAO runtime currently supports only the minimize_mass structural objective.",
                    task="optimizer",
                    details={"runtime": "openmdao", "objective": objective_kind},
                )
        return None

    def _report_fd_fallback(
        self,
        component_name: str,
        backend_name: str,
        model_name: str,
        missing_pairs: list[str],
    ) -> None:
        message = (
            "OpenMDAO finite-difference fallback enabled for "
            f"{component_name} using backend={backend_name} model={model_name}: "
            + ", ".join(missing_pairs)
        )
        warnings.warn(message, RuntimeWarning, stacklevel=3)
        if self._current_log_path is not None:
            self.reporter.append_workflow_log(self._current_log_path, f"warning {message}")
        self._deferred_diagnostics.append(
            Diagnostic(
                code="runtime.openmdao_fd_fallback",
                message=message,
                severity="warning",
                task="optimizer",
                details={
                    "runtime": "openmdao",
                    "component": component_name,
                    "backend": backend_name,
                    "model": model_name,
                    "missing_pairs": ",".join(missing_pairs),
                },
            )
        )

    def _apply_agent_result(self, state: DesignState, result: object) -> None:
        if "geometry_state" in result.updates:
            state.geometry_state = state.geometry_state.model_copy(
                update=result.updates["geometry_state"]
            )
        if "mesh_state" in result.updates:
            state.mesh_state = state.mesh_state.model_copy(update=result.updates["mesh_state"])
        if "analysis_state" in result.updates:
            merged_analysis_state = state.analysis_state.model_dump(mode="python")
            merged_analysis_state.update(result.updates["analysis_state"])
            state.analysis_state = state.analysis_state.__class__.model_validate(
                merged_analysis_state
            )
        if "topology_state" in result.updates:
            merged_topology_state = state.topology_state.model_dump(mode="python")
            merged_topology_state.update(result.updates["topology_state"])
            state.topology_state = state.topology_state.__class__.model_validate(
                merged_topology_state
            )
        if "design_variables" in result.updates:
            state.design_variables = dict(result.updates["design_variables"])

        state.artifacts.extend(result.artifacts)
        state.diagnostics.extend(result.diagnostics)
        state.task_history.append(
            TaskRecord(
                iteration=state.iteration,
                task=result.task,
                status=result.status,
                message=result.message,
            )
        )

    def _scalar_value(self, value: object) -> float:
        if isinstance(value, (float, int)):
            return float(value)
        return float(value[0])
