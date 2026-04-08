import json
from pathlib import Path

from mass_town.config import WorkflowConfig
from mass_town.models.artifacts import ArtifactRecord
from mass_town.models.design_state import DesignState
from mass_town.problem_schema import ProblemSchema, ProblemSchemaResolver
from mass_town.storage.filesystem import ensure_run_layout


class RunReporter:
    def __init__(
        self,
        config: WorkflowConfig,
        schema_resolver: ProblemSchemaResolver | None = None,
    ) -> None:
        self.config = config
        self.schema_resolver = schema_resolver or ProblemSchemaResolver()

    def append_workflow_log(self, path: Path, line: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def write_problem_schema(
        self,
        problem_schema: ProblemSchema,
        run_root: Path,
        state: DesignState,
    ) -> None:
        layout = ensure_run_layout(run_root, state.run_id)
        schema_path = layout.reports_dir / "problem_schema.json"
        schema_path.write_text(
            json.dumps(problem_schema.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        )

    def write_run_summary(
        self,
        state: DesignState,
        run_root: Path,
        problem_schema: ProblemSchema,
    ) -> Path:
        layout = ensure_run_layout(run_root, state.run_id)
        summary_path = layout.reports_dir / "run_summary.json"
        topology_mode = problem_schema.model.type == "topology"
        feasible = (
            state.status == "recovered" and state.topology_state.converged
            if topology_mode
            else state.status == "recovered" and state.analysis_state.passed
        )
        definitions = self.schema_resolver.design_variable_definitions(problem_schema)
        active_design_variables = {
            definition.id: state.design_variables.get(definition.id, definition.initial_value)
            for definition in definitions
            if definition.active
        }
        latest_mesh_path = state.mesh_state.mesh_path
        analysis_log_path = self._latest_artifact_metadata_value(state, "fea-summary", "log_path")
        mesh_log_path = self._latest_artifact_metadata_value(state, "mesh-output", "log_path")
        topology_log_path = self._latest_artifact_metadata_value(state, "topology-summary", "log_path")
        topology_history_path = self._latest_artifact_metadata_value(
            state, "topology-summary", "history_path"
        )
        topology_density_path = self._latest_artifact_metadata_value(
            state, "topology-summary", "density_path"
        )
        topology_plot_path = self._latest_artifact_metadata_value(
            state, "topology-summary", "plot_path"
        )
        load_case_results = {
            case_name: case_state.model_dump(mode="json")
            for case_name, case_state in state.analysis_state.load_cases.items()
        }
        summary = {
            "run_id": state.run_id,
            "problem_name": state.problem_name,
            "status": state.status,
            "feasible": feasible,
            "iteration_count": state.iteration,
            "final_thickness": state.design_variables.get("thickness"),
            "design_variables": state.design_variables,
            "active_design_variables": active_design_variables,
            "mass": state.analysis_state.mass,
            "max_stress": state.analysis_state.max_stress,
            "displacement_norm": state.analysis_state.displacement_norm,
            "analysis_type": state.analysis_state.analysis_type,
            "eigenvalues": state.analysis_state.eigenvalues,
            "critical_eigenvalue": state.analysis_state.critical_eigenvalue,
            "frequencies_hz": state.analysis_state.frequencies_hz,
            "critical_frequency_hz": state.analysis_state.critical_frequency_hz,
            "critical_buckling_load_factor": (
                state.analysis_state.critical_eigenvalue
                if state.analysis_state.analysis_type == "buckling"
                else None
            ),
            "buckling_load_factors": (
                state.analysis_state.eigenvalues
                if state.analysis_state.analysis_type == "buckling"
                else []
            ),
            "critical_natural_frequency_hz": (
                state.analysis_state.critical_frequency_hz
                if state.analysis_state.analysis_type == "modal"
                else None
            ),
            "natural_frequencies_hz": (
                state.analysis_state.frequencies_hz
                if state.analysis_state.analysis_type == "modal"
                else []
            ),
            "worst_case_name": state.analysis_state.worst_case_name,
            "aggregated_stress": (
                state.analysis_state.aggregated_stress.model_dump(mode="json")
                if state.analysis_state.aggregated_stress is not None
                else None
            ),
            "eigenvalue_constraints": {
                name: result.model_dump(mode="json")
                for name, result in state.analysis_state.eigenvalue_constraints.items()
            },
            "analysis_seconds": state.analysis_state.analysis_seconds,
            "load_case_results": load_case_results,
            "allowable_stress": self.schema_resolver.allowable_stress(problem_schema),
            "problem_model_type": problem_schema.model.type,
            "artifact_paths": {
                "workflow_log": str((layout.logs_dir / "workflow.log").relative_to(run_root)),
                "mesh_model": latest_mesh_path,
                "mesh_log": mesh_log_path,
                "analysis_summary": state.analysis_state.result_path,
                "analysis_log": analysis_log_path,
                "topology_summary": state.topology_state.result_path,
                "topology_log": topology_log_path,
                "topology_history": topology_history_path,
                "topology_density": topology_density_path,
                "topology_plot": topology_plot_path,
                "problem_schema": str(
                    (layout.reports_dir / "problem_schema.json").relative_to(run_root)
                ),
                "aggregation_quality_summary": (
                    state.analysis_state.aggregated_stress.quality_summary_path
                    if state.analysis_state.aggregated_stress is not None
                    else None
                ),
                "solver_directory": str(layout.solver_dir.relative_to(run_root)),
            },
            "topology": {
                "backend": state.topology_state.backend,
                "result_path": state.topology_state.result_path,
                "objective": state.topology_state.objective,
                "volume_fraction": state.topology_state.volume_fraction,
                "max_density_change": state.topology_state.max_density_change,
                "beta": state.topology_state.beta,
                "converged": state.topology_state.converged,
                "iteration_count": state.topology_state.iteration_count,
                "timing": state.topology_state.timing.model_dump(mode="json"),
                "failure_reason": state.topology_state.failure_reason,
            },
        }
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        return summary_path

    def record_run_summary_artifact(
        self,
        state: DesignState,
        summary_path: Path,
        run_root: Path,
    ) -> None:
        state.artifacts = [artifact for artifact in state.artifacts if artifact.kind != "run_summary"]
        state.artifacts.append(
            ArtifactRecord(
                name="run-summary",
                path=str(summary_path.relative_to(run_root)),
                kind="run_summary",
                metadata={
                    "status": state.status,
                    "iteration_count": state.iteration,
                    "feasible": (
                        state.status == "recovered" and state.topology_state.converged
                        if self.config.topology is not None
                        else state.status == "recovered" and state.analysis_state.passed
                    ),
                    "topology_converged": state.topology_state.converged,
                    "worst_case_name": state.analysis_state.worst_case_name or "",
                },
            )
        )

    def _latest_artifact_metadata_value(
        self, state: DesignState, artifact_name: str, key: str
    ) -> str | None:
        for artifact in reversed(state.artifacts):
            if artifact.name == artifact_name:
                value = artifact.metadata.get(key)
                if value is not None:
                    return str(value)
        return None
