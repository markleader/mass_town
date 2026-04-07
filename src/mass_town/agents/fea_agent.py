from pathlib import Path

from mass_town.agents.base_agent import BaseAgent
from mass_town.config import WorkflowConfig
from mass_town.design_variables import DesignVariableMappingError
from mass_town.disciplines.contracts import read_mesh_to_fea_manifest
from mass_town.disciplines.fea import (
    FEABackendError,
    FEALoadCase,
    FEALoadCaseResult,
    resolve_fea_backend,
)
from mass_town.disciplines.postprocessing import (
    PostProcessingRequest,
    StructuralPostProcessingBackend,
)
from mass_town.models.artifacts import ArtifactRecord
from mass_town.models.design_state import DesignState
from mass_town.models.result import AgentResult, Diagnostic
from mass_town.problem_schema import ProblemSchemaResolver
from mass_town.storage.filesystem import ensure_run_layout


class FEAAgent(BaseAgent):
    name = "fea_agent"
    task_name = "fea"

    def __init__(self) -> None:
        self.schema_resolver = ProblemSchemaResolver()
        self.postprocessor = StructuralPostProcessingBackend()

    def run(self, state: DesignState, config: WorkflowConfig, run_root: Path) -> AgentResult:
        layout = ensure_run_layout(run_root, state.run_id)
        problem = self.schema_resolver.resolve(config, state, run_root)
        mesh_input_path = run_root / state.mesh_state.mesh_path if state.mesh_state.mesh_path else None
        mesh_manifest_path = (
            run_root / state.mesh_state.mesh_manifest_path
            if state.mesh_state.mesh_manifest_path
            else None
        )
        mesh_manifest = None
        if mesh_manifest_path is not None and mesh_manifest_path.exists():
            try:
                mesh_manifest = read_mesh_to_fea_manifest(mesh_manifest_path)
            except ValueError as exc:
                diagnostic = Diagnostic(
                    code="analysis.mesh_manifest_invalid",
                    message=f"Mesh-to-FEA manifest is invalid: {exc}",
                    task=self.task_name,
                    details={"mesh_manifest_path": str(mesh_manifest_path)},
                )
                return AgentResult(
                    status="failure",
                    task=self.task_name,
                    message=diagnostic.message,
                    diagnostics=[diagnostic],
                )
        try:
            request = self.schema_resolver.build_fea_request(
                problem,
                state,
                run_root,
                report_directory=layout.reports_dir,
                log_directory=layout.logs_dir,
                solution_directory=layout.solver_dir,
                mesh_input_path=mesh_input_path,
                mesh_manifest_path=mesh_manifest_path,
                mesh_manifest=mesh_manifest,
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

        aggregation_quality_summary_path = self._relative_quality_summary_path(
            fea_result.aggregation_quality_summary_path,
            run_root,
        )
        postprocessing_result = self.postprocessor.process(
            PostProcessingRequest(
                fea_request=request,
                fea_result=fea_result,
                aggregation_quality_summary_path=aggregation_quality_summary_path,
            )
        )
        normalized_case_results = postprocessing_result.normalized_case_results
        minimum_buckling_load_factor = postprocessing_result.minimum_buckling_load_factor
        minimum_natural_frequency = postprocessing_result.minimum_natural_frequency_hz
        worst_case_name = postprocessing_result.worst_case_name
        worst_case_result = (
            normalized_case_results[worst_case_name]
            if worst_case_name is not None and worst_case_name in normalized_case_results
            else None
        )
        analysis_seconds = postprocessing_result.analysis_seconds
        aggregated_stress = postprocessing_result.aggregated_stress

        metadata = dict(fea_result.metadata)
        passed = postprocessing_result.passed
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
        if worst_case_result is not None and worst_case_result.critical_frequency_hz is not None:
            metadata["critical_frequency_hz"] = round(
                worst_case_result.critical_frequency_hz,
                6,
            )
        elif fea_result.critical_frequency_hz is not None:
            metadata["critical_frequency_hz"] = round(fea_result.critical_frequency_hz, 6)
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
        if minimum_natural_frequency is not None:
            metadata["minimum_natural_frequency_hz_mode"] = minimum_natural_frequency.mode
            metadata["minimum_natural_frequency_hz_minimum"] = round(
                minimum_natural_frequency.minimum,
                6,
            )
            metadata["minimum_natural_frequency_hz_passed"] = minimum_natural_frequency.passed
            if minimum_natural_frequency.value is not None:
                metadata["minimum_natural_frequency_hz_value"] = round(
                    minimum_natural_frequency.value,
                    6,
                )
            if minimum_natural_frequency.controlling_case is not None:
                metadata["minimum_natural_frequency_hz_controlling_case"] = (
                    minimum_natural_frequency.controlling_case
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
                "frequencies_hz": list(case_result.frequencies_hz),
                "critical_frequency_hz": case_result.critical_frequency_hz,
                "passed": (
                    self._case_passed(case_result, request.allowable_stress)
                    and self._case_satisfies_minimum_buckling_load_factor(
                        case_result,
                        request.constraints.minimum_buckling_load_factor,
                    )
                    and self._case_satisfies_minimum_natural_frequency(
                        case_result,
                        request.constraints.minimum_natural_frequency_hz,
                    )
                ),
                "analysis_seconds": case_result.analysis_seconds,
            }
            for case_name, case_result in normalized_case_results.items()
        }
        eigenvalue_constraints = {
            name: value
            for name, value in {
                "minimum_buckling_load_factor": (
                    minimum_buckling_load_factor.model_dump(mode="python")
                    if minimum_buckling_load_factor is not None
                    else None
                ),
                "minimum_natural_frequency_hz": (
                    minimum_natural_frequency.model_dump(mode="python")
                    if minimum_natural_frequency is not None
                    else None
                ),
            }.items()
            if value is not None
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
                "frequencies_hz": (
                    list(worst_case_result.frequencies_hz)
                    if worst_case_result is not None and worst_case_result.frequencies_hz
                    else list(fea_result.frequencies_hz)
                ),
                "critical_frequency_hz": (
                    worst_case_result.critical_frequency_hz
                    if worst_case_result is not None
                    and worst_case_result.critical_frequency_hz is not None
                    else fea_result.critical_frequency_hz
                ),
                "passed": passed,
                "load_cases": analysis_state_load_cases,
                "worst_case_name": worst_case_name,
                "aggregated_stress": (
                    aggregated_stress.model_dump(mode="python")
                    if aggregated_stress is not None
                    else None
                ),
                "eigenvalue_constraints": eigenvalue_constraints,
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

        if (
            minimum_natural_frequency is not None
            and not minimum_natural_frequency.passed
            and minimum_natural_frequency.value is not None
        ):
            diagnostic = Diagnostic(
                code="analysis.minimum_natural_frequency_not_met",
                message="Minimum natural frequency constraint is not satisfied.",
                task=self.task_name,
                details={
                    "natural_frequency_hz": round(minimum_natural_frequency.value, 3),
                    "minimum": minimum_natural_frequency.minimum,
                    "mode": minimum_natural_frequency.mode,
                    "backend": fea_result.backend_name,
                    "controlling_case": minimum_natural_frequency.controlling_case or "",
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
                    "allowable": request.allowable_stress,
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

    def _case_satisfies_minimum_natural_frequency(
        self,
        case_result: FEALoadCaseResult,
        constraint: object,
    ) -> bool:
        if constraint is None:
            return True
        if len(case_result.frequencies_hz) <= constraint.mode:
            return False
        return float(case_result.frequencies_hz[constraint.mode]) >= float(constraint.minimum)

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
