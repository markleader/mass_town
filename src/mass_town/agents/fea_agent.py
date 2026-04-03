from pathlib import Path

from mass_town.agents.base_agent import BaseAgent
from mass_town.config import WorkflowConfig
from mass_town.constraints import (
    aggregate_case_stresses,
    evaluate_minimum_buckling_load_factor_constraint,
)
from mass_town.design_variables import (
    DesignVariableContext,
    DesignVariableMappingError,
    bdf_design_variable_context,
    map_design_variables_to_analysis,
    resolved_design_variable_definitions,
    resolved_design_variable_values,
)
from mass_town.disciplines.fea import (
    FEABackendError,
    FEALoadCase,
    FEALoadCaseResult,
    FEARequest,
    FEAResult,
    resolve_fea_backend,
)
from mass_town.models.artifacts import ArtifactRecord
from mass_town.models.design_state import DesignState
from mass_town.models.result import AgentResult, Diagnostic
from mass_town.storage.filesystem import ensure_run_layout


class FEAAgent(BaseAgent):
    name = "fea_agent"
    task_name = "fea"

    def run(self, state: DesignState, config: WorkflowConfig, run_root: Path) -> AgentResult:
        layout = ensure_run_layout(run_root, state.run_id)
        mesh_input_path = run_root / state.mesh_state.mesh_path if state.mesh_state.mesh_path else None
        model_input_path = (
            run_root / config.fea.model_input_path if config.fea.model_input_path else None
        )
        if model_input_path is None and mesh_input_path is not None and mesh_input_path.suffix.lower() == ".bdf":
            model_input_path = mesh_input_path

        definitions = resolved_design_variable_definitions(
            config.design_variables,
            state.design_variables,
        )
        resolved_values = resolved_design_variable_values(definitions, state.design_variables)
        mapping_context = (
            bdf_design_variable_context(model_input_path)
            if model_input_path is not None and model_input_path.suffix.lower() == ".bdf"
            else bdf_design_variable_context(mesh_input_path)
            if mesh_input_path is not None and mesh_input_path.suffix.lower() == ".bdf"
            else DesignVariableContext()
        )
        try:
            mapped_design_variables = map_design_variables_to_analysis(
                definitions,
                resolved_values,
                mapping_context,
            )
        except DesignVariableMappingError as exc:
            diagnostic = Diagnostic(
                code="design_variables.mapping_failed",
                message=str(exc),
                task=self.task_name,
            )
            return AgentResult(
                status="failure",
                task=self.task_name,
                message=diagnostic.message,
                diagnostics=[diagnostic],
            )

        load_cases = self._normalized_load_cases(state, config)
        request = FEARequest(
            model_input_path=model_input_path,
            mesh_input_path=mesh_input_path,
            report_directory=layout.reports_dir,
            log_directory=layout.logs_dir,
            solution_directory=layout.solver_dir,
            run_id=state.run_id,
            loads=state.loads,
            design_variables=resolved_values,
            design_variable_assignments=mapped_design_variables,
            constraints=state.constraints,
            allowable_stress=config.allowable_stress,
            case_name=config.fea.case_name,
            analysis_type=config.fea.analysis_type,
            load_cases=load_cases,
            write_solution=config.fea.write_solution,
            buckling_setup=config.fea.buckling_setup,
            shell_setup=config.fea.shell_setup,
            solid_setup=config.fea.solid_setup,
        )

        try:
            backend = resolve_fea_backend(config.fea.tool)
        except FEABackendError as exc:
            diagnostic = Diagnostic(
                code="analysis.backend_unavailable",
                message=str(exc),
                task=self.task_name,
                details={"backend": config.fea.tool},
            )
            return AgentResult(
                status="failure",
                task=self.task_name,
                message=diagnostic.message,
                diagnostics=[diagnostic],
            )

        try:
            fea_result = backend.run_analysis(request)
        except FileNotFoundError as exc:
            diagnostic = Diagnostic(
                code="analysis.model_input_missing",
                message=str(exc),
                task=self.task_name,
            )
            return AgentResult(
                status="failure",
                task=self.task_name,
                message=diagnostic.message,
                diagnostics=[diagnostic],
            )
        except ValueError as exc:
            diagnostic = Diagnostic(
                code="analysis.unsupported_input",
                message=str(exc),
                task=self.task_name,
            )
            return AgentResult(
                status="failure",
                task=self.task_name,
                message=diagnostic.message,
                diagnostics=[diagnostic],
            )
        except RuntimeError as exc:
            diagnostic = Diagnostic(
                code="analysis.backend_failed",
                message=str(exc),
                task=self.task_name,
                details={"backend": backend.name},
            )
            return AgentResult(
                status="failure",
                task=self.task_name,
                message=diagnostic.message,
                diagnostics=[diagnostic],
            )

        normalized_case_results = self._normalized_case_results(fea_result, request)
        ordered_case_names = list(load_cases)
        minimum_buckling_load_factor = evaluate_minimum_buckling_load_factor_constraint(
            {
                case_name: tuple(case_result.eigenvalues)
                for case_name, case_result in normalized_case_results.items()
            },
            request.constraints.minimum_buckling_load_factor,
        )
        worst_case_name = self._select_worst_case_name(
            normalized_case_results,
            ordered_case_names,
            analysis_type=request.analysis_type,
            minimum_buckling_load_factor_case=(
                minimum_buckling_load_factor.controlling_case
                if minimum_buckling_load_factor is not None
                else None
            ),
        )
        worst_case_result = (
            normalized_case_results[worst_case_name]
            if worst_case_name is not None and worst_case_name in normalized_case_results
            else None
        )
        analysis_seconds = fea_result.analysis_seconds
        if analysis_seconds is None:
            case_times = [
                case_result.analysis_seconds
                for case_result in normalized_case_results.values()
                if case_result.analysis_seconds is not None
            ]
            if case_times:
                analysis_seconds = sum(case_times)
        aggregation_quality_summary_path = self._relative_quality_summary_path(
            fea_result.aggregation_quality_summary_path,
            run_root,
        )
        aggregated_stress = aggregate_case_stresses(
            {
                case_name: case_result.max_stress
                for case_name, case_result in normalized_case_results.items()
            },
            request.constraints,
            config.allowable_stress,
            quality_summary_path=aggregation_quality_summary_path,
        )

        metadata = dict(fea_result.metadata)
        passed = self._all_cases_passed(normalized_case_results, config.allowable_stress)
        if not normalized_case_results and fea_result.max_stress is not None:
            passed = passed and fea_result.max_stress <= config.allowable_stress
        if aggregated_stress is not None:
            passed = passed and aggregated_stress.passed
        if minimum_buckling_load_factor is not None:
            passed = passed and minimum_buckling_load_factor.passed
        metadata.update(
            {
                "backend": fea_result.backend_name,
                "analysis_type": request.analysis_type,
                "passed": passed,
                "load_case_count": len(normalized_case_results),
                "load_case_names": ",".join(normalized_case_results),
            }
        )
        if worst_case_name is not None:
            metadata["worst_case_name"] = worst_case_name
        if analysis_seconds is not None:
            metadata["analysis_seconds"] = round(analysis_seconds, 6)
        if worst_case_result is not None and worst_case_result.mass is not None:
            metadata["mass"] = round(worst_case_result.mass, 6)
        elif fea_result.mass is not None:
            metadata["mass"] = round(fea_result.mass, 6)
        if worst_case_result is not None and worst_case_result.max_stress is not None:
            metadata["max_stress"] = round(worst_case_result.max_stress, 6)
        elif fea_result.max_stress is not None:
            metadata["max_stress"] = round(fea_result.max_stress, 6)
        if worst_case_result is not None and worst_case_result.displacement_norm is not None:
            metadata["displacement_norm"] = round(worst_case_result.displacement_norm, 6)
        elif fea_result.displacement_norm is not None:
            metadata["displacement_norm"] = round(fea_result.displacement_norm, 6)
        if worst_case_result is not None and worst_case_result.critical_eigenvalue is not None:
            metadata["critical_eigenvalue"] = round(worst_case_result.critical_eigenvalue, 6)
        elif fea_result.critical_eigenvalue is not None:
            metadata["critical_eigenvalue"] = round(fea_result.critical_eigenvalue, 6)
        if fea_result.log_path is not None:
            metadata["log_path"] = str(fea_result.log_path.relative_to(run_root))
        if aggregated_stress is not None:
            metadata["aggregated_stress_method"] = aggregated_stress.method
            metadata["aggregated_stress_allowable"] = round(aggregated_stress.allowable, 6)
            metadata["aggregated_stress_passed"] = aggregated_stress.passed
            if aggregated_stress.value is not None:
                metadata["aggregated_stress_value"] = round(aggregated_stress.value, 6)
            if aggregated_stress.controlling_case is not None:
                metadata["aggregated_stress_controlling_case"] = (
                    aggregated_stress.controlling_case
                )
            if aggregated_stress.quality_summary_path is not None:
                metadata["aggregated_stress_quality_summary_path"] = (
                    aggregated_stress.quality_summary_path
                )
        if minimum_buckling_load_factor is not None:
            metadata["minimum_buckling_load_factor_mode"] = minimum_buckling_load_factor.mode
            metadata["minimum_buckling_load_factor_minimum"] = round(
                minimum_buckling_load_factor.minimum,
                6,
            )
            metadata["minimum_buckling_load_factor_passed"] = (
                minimum_buckling_load_factor.passed
            )
            if minimum_buckling_load_factor.value is not None:
                metadata["minimum_buckling_load_factor_value"] = round(
                    minimum_buckling_load_factor.value,
                    6,
                )
            if minimum_buckling_load_factor.controlling_case is not None:
                metadata["minimum_buckling_load_factor_controlling_case"] = (
                    minimum_buckling_load_factor.controlling_case
                )

        result_files = list(fea_result.result_files)
        primary_result_path = (
            str(result_files[0].relative_to(run_root)) if result_files else None
        )
        artifacts: list[ArtifactRecord] = []
        for index, result_file in enumerate(result_files):
            artifacts.append(
                ArtifactRecord(
                    name="fea-summary" if index == 0 else f"fea-output-{index}",
                    path=str(result_file.relative_to(run_root)),
                    kind="analysis_report" if index == 0 else "analysis_output",
                    metadata=metadata,
                )
            )

        analysis_state_load_cases = {
            case_name: {
                "backend": fea_result.backend_name,
                "result_path": self._relative_case_result_path(case_result, run_root),
                "mass": case_result.mass,
                "max_stress": case_result.max_stress,
                "displacement_norm": case_result.displacement_norm,
                "analysis_type": case_result.analysis_type,
                "eigenvalues": list(case_result.eigenvalues),
                "critical_eigenvalue": case_result.critical_eigenvalue,
                "passed": (
                    self._case_passed(case_result, config.allowable_stress)
                    and self._case_satisfies_minimum_buckling_load_factor(
                        case_result,
                        request.constraints.minimum_buckling_load_factor,
                    )
                ),
                "analysis_seconds": case_result.analysis_seconds,
            }
            for case_name, case_result in normalized_case_results.items()
        }

        updates = {
            "analysis_state": {
                "backend": fea_result.backend_name,
                "result_path": primary_result_path,
                "mass": (
                    worst_case_result.mass
                    if worst_case_result is not None and worst_case_result.mass is not None
                    else fea_result.mass
                ),
                "max_stress": (
                    worst_case_result.max_stress
                    if worst_case_result is not None and worst_case_result.max_stress is not None
                    else fea_result.max_stress
                ),
                "displacement_norm": (
                    worst_case_result.displacement_norm
                    if worst_case_result is not None
                    and worst_case_result.displacement_norm is not None
                    else fea_result.displacement_norm
                ),
                "analysis_type": request.analysis_type,
                "eigenvalues": (
                    list(worst_case_result.eigenvalues)
                    if worst_case_result is not None and worst_case_result.eigenvalues
                    else list(fea_result.eigenvalues)
                ),
                "critical_eigenvalue": (
                    worst_case_result.critical_eigenvalue
                    if worst_case_result is not None
                    and worst_case_result.critical_eigenvalue is not None
                    else fea_result.critical_eigenvalue
                ),
                "passed": passed,
                "load_cases": analysis_state_load_cases,
                "worst_case_name": worst_case_name,
                "aggregated_stress": (
                    aggregated_stress.model_dump(mode="python")
                    if aggregated_stress is not None
                    else None
                ),
                "eigenvalue_constraints": {
                    "minimum_buckling_load_factor": (
                        minimum_buckling_load_factor.model_dump(mode="python")
                        if minimum_buckling_load_factor is not None
                        else None
                    )
                }
                if minimum_buckling_load_factor is not None
                else {},
                "analysis_seconds": analysis_seconds,
            }
        }

        if (
            aggregated_stress is not None
            and not aggregated_stress.passed
            and aggregated_stress.value is not None
        ):
            diagnostic = Diagnostic(
                code="analysis.aggregated_stress_exceeded",
                message="Aggregated stress exceeds allowable limit.",
                task=self.task_name,
                details={
                    "aggregated_stress": round(aggregated_stress.value, 3),
                    "allowable": aggregated_stress.allowable,
                    "method": aggregated_stress.method,
                    "backend": fea_result.backend_name,
                    "controlling_case": aggregated_stress.controlling_case or "",
                },
            )
            return AgentResult(
                status="failure",
                task=self.task_name,
                message=diagnostic.message,
                diagnostics=[diagnostic],
                artifacts=artifacts,
                updates=updates,
            )

        if (
            minimum_buckling_load_factor is not None
            and not minimum_buckling_load_factor.passed
            and minimum_buckling_load_factor.value is not None
        ):
            diagnostic = Diagnostic(
                code="analysis.minimum_buckling_load_factor_not_met",
                message="Minimum buckling load factor constraint is not satisfied.",
                task=self.task_name,
                details={
                    "buckling_load_factor": round(minimum_buckling_load_factor.value, 3),
                    "minimum": minimum_buckling_load_factor.minimum,
                    "mode": minimum_buckling_load_factor.mode,
                    "backend": fea_result.backend_name,
                    "controlling_case": minimum_buckling_load_factor.controlling_case or "",
                },
            )
            return AgentResult(
                status="failure",
                task=self.task_name,
                message=diagnostic.message,
                diagnostics=[diagnostic],
                artifacts=artifacts,
                updates=updates,
            )

        if not passed and worst_case_result is not None and worst_case_result.max_stress is not None:
            diagnostic = Diagnostic(
                code="analysis.stress_exceeded",
                message="Stress exceeds allowable limit.",
                task=self.task_name,
                details={
                    "max_stress": round(worst_case_result.max_stress, 3),
                    "allowable": config.allowable_stress,
                    "backend": fea_result.backend_name,
                    "worst_case_name": worst_case_name or request.case_name,
                },
            )
            return AgentResult(
                status="failure",
                task=self.task_name,
                message=diagnostic.message,
                diagnostics=[diagnostic],
                artifacts=artifacts,
                updates=updates,
            )

        return AgentResult(
            status="success",
            task=self.task_name,
            message="Structural analysis passed.",
            artifacts=artifacts,
            updates=updates,
        )

    def _normalized_load_cases(
        self,
        state: DesignState,
        config: WorkflowConfig,
    ) -> dict[str, FEALoadCase]:
        if state.load_cases:
            return {
                case_name: FEALoadCase(loads=dict(case_state.loads))
                for case_name, case_state in state.load_cases.items()
            }
        return {
            config.fea.case_name: FEALoadCase(loads=dict(state.loads)),
        }

    def _normalized_case_results(
        self,
        fea_result: FEAResult,
        request: FEARequest,
    ) -> dict[str, FEALoadCaseResult]:
        if fea_result.load_cases:
            return dict(fea_result.load_cases)
        fallback_case_name = next(iter(request.load_cases), request.case_name)
        return {
            fallback_case_name: FEALoadCaseResult(
                passed=fea_result.passed,
                result_files=list(fea_result.result_files),
                mass=fea_result.mass,
                max_stress=fea_result.max_stress,
                displacement_norm=fea_result.displacement_norm,
                analysis_type=fea_result.analysis_type,
                eigenvalues=list(fea_result.eigenvalues),
                critical_eigenvalue=fea_result.critical_eigenvalue,
                metadata=dict(fea_result.metadata),
                log_path=fea_result.log_path,
                analysis_seconds=fea_result.analysis_seconds,
            )
        }

    def _select_worst_case_name(
        self,
        case_results: dict[str, FEALoadCaseResult],
        ordered_case_names: list[str],
        *,
        analysis_type: str,
        minimum_buckling_load_factor_case: str | None = None,
    ) -> str | None:
        candidate_names = [name for name in ordered_case_names if name in case_results]
        if not candidate_names:
            candidate_names = list(case_results)
        if not candidate_names:
            return None

        if minimum_buckling_load_factor_case in candidate_names:
            return minimum_buckling_load_factor_case

        best_name: str | None = None
        if analysis_type == "buckling":
            best_eigenvalue: float | None = None
            for case_name in candidate_names:
                critical_eigenvalue = case_results[case_name].critical_eigenvalue
                if critical_eigenvalue is None:
                    if best_name is None:
                        best_name = case_name
                    continue
                if best_eigenvalue is None or critical_eigenvalue < best_eigenvalue:
                    best_name = case_name
                    best_eigenvalue = critical_eigenvalue
            return best_name or candidate_names[0]

        best_stress: float | None = None
        for case_name in candidate_names:
            max_stress = case_results[case_name].max_stress
            if max_stress is None:
                if best_name is None:
                    best_name = case_name
                continue
            if best_stress is None or max_stress > best_stress:
                best_name = case_name
                best_stress = max_stress
        return best_name or candidate_names[0]

    def _all_cases_passed(
        self,
        case_results: dict[str, FEALoadCaseResult],
        allowable_stress: float,
    ) -> bool:
        if not case_results:
            return True
        return all(
            self._case_passed(case_result, allowable_stress)
            for case_result in case_results.values()
        )

    def _case_passed(
        self,
        case_result: FEALoadCaseResult,
        allowable_stress: float,
    ) -> bool:
        if not case_result.passed:
            return False
        if case_result.max_stress is not None and case_result.max_stress > allowable_stress:
            return False
        return True

    def _case_satisfies_minimum_buckling_load_factor(
        self,
        case_result: FEALoadCaseResult,
        constraint: object,
    ) -> bool:
        if constraint is None:
            return True
        if len(case_result.eigenvalues) <= constraint.mode:
            return False
        return float(case_result.eigenvalues[constraint.mode]) >= float(constraint.minimum)

    def _relative_case_result_path(
        self,
        case_result: FEALoadCaseResult,
        run_root: Path,
    ) -> str | None:
        if not case_result.result_files:
            return None
        return str(case_result.result_files[0].relative_to(run_root))

    def _relative_quality_summary_path(
        self,
        quality_summary_path: Path | None,
        run_root: Path,
    ) -> str | None:
        if quality_summary_path is None:
            return None
        return str(quality_summary_path.relative_to(run_root))
