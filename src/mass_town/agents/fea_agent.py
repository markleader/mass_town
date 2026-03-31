from pathlib import Path

from mass_town.agents.base_agent import BaseAgent
from mass_town.config import WorkflowConfig
from mass_town.design_variables import (
    DesignVariableContext,
    DesignVariableMappingError,
    bdf_design_variable_context,
    map_design_variables_to_analysis,
    resolved_design_variable_definitions,
    resolved_design_variable_values,
)
from mass_town.disciplines.fea import FEABackendError, FEARequest, resolve_fea_backend
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
            write_solution=config.fea.write_solution,
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

        metadata = dict(fea_result.metadata)
        metadata.update(
            {
                "backend": fea_result.backend_name,
                "passed": fea_result.passed,
            }
        )
        if fea_result.mass is not None:
            metadata["mass"] = round(fea_result.mass, 6)
        if fea_result.max_stress is not None:
            metadata["max_stress"] = round(fea_result.max_stress, 6)
        if fea_result.displacement_norm is not None:
            metadata["displacement_norm"] = round(fea_result.displacement_norm, 6)
        if fea_result.log_path is not None:
            metadata["log_path"] = str(fea_result.log_path.relative_to(run_root))

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

        passed = fea_result.passed
        if fea_result.max_stress is not None:
            passed = passed and fea_result.max_stress <= config.allowable_stress

        updates = {
            "analysis_state": {
                "backend": fea_result.backend_name,
                "result_path": primary_result_path,
                "mass": fea_result.mass,
                "max_stress": fea_result.max_stress,
                "displacement_norm": fea_result.displacement_norm,
                "passed": passed,
            }
        }

        if not passed and fea_result.max_stress is not None:
            diagnostic = Diagnostic(
                code="analysis.stress_exceeded",
                message="Stress exceeds allowable limit.",
                task=self.task_name,
                details={
                    "max_stress": round(fea_result.max_stress, 3),
                    "allowable": config.allowable_stress,
                    "backend": fea_result.backend_name,
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
