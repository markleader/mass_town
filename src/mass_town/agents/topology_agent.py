from pathlib import Path

from mass_town.agents.base_agent import BaseAgent
from mass_town.config import WorkflowConfig
from mass_town.disciplines.topology import (
    TopologyBackendError,
    resolve_topology_backend,
)
from mass_town.models.artifacts import ArtifactRecord
from mass_town.models.design_state import DesignState
from mass_town.models.result import AgentResult, Diagnostic
from mass_town.problem_schema import ProblemSchemaResolver
from mass_town.storage.filesystem import ensure_run_layout


class TopologyAgent(BaseAgent):
    name = "topology_agent"
    task_name = "topology"

    def __init__(self) -> None:
        self.schema_resolver = ProblemSchemaResolver()

    def run(self, state: DesignState, config: WorkflowConfig, run_root: Path) -> AgentResult:
        if config.topology is None:
            diagnostic = Diagnostic(
                code="topology.config_missing",
                message="The topology task requires a topology configuration block.",
                task=self.task_name,
            )
            return AgentResult(
                status="failure",
                task=self.task_name,
                message=diagnostic.message,
                diagnostics=[diagnostic],
            )

        layout = ensure_run_layout(run_root, state.run_id)
        problem = self.schema_resolver.resolve(config, state, run_root)
        request = self.schema_resolver.build_topology_request(
            problem,
            state,
            report_directory=layout.reports_dir,
            log_directory=layout.logs_dir,
            mesh_directory=layout.mesh_dir,
            solution_directory=layout.solver_dir,
        )

        try:
            backend = resolve_topology_backend(config.topology.tool)
        except TopologyBackendError as exc:
            diagnostic = Diagnostic(
                code="topology.backend_unavailable",
                message=str(exc),
                task=self.task_name,
                details={"backend": config.topology.tool},
            )
            return AgentResult(
                status="failure",
                task=self.task_name,
                message=diagnostic.message,
                diagnostics=[diagnostic],
            )

        try:
            result = backend.run_optimization(request)
        except ValueError as exc:
            diagnostic = Diagnostic(
                code="topology.invalid_config",
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
                code="topology.backend_failed",
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

        summary_metadata = {
            "backend": result.backend_name,
            "converged": result.converged,
            "objective": result.objective if result.objective is not None else "",
            "volume_fraction": result.volume_fraction if result.volume_fraction is not None else "",
            "max_density_change": (
                result.max_density_change if result.max_density_change is not None else ""
            ),
            "beta": result.beta if result.beta is not None else "",
        }
        if result.log_path is not None:
            summary_metadata["log_path"] = str(result.log_path.relative_to(run_root))
        if result.history_path is not None:
            summary_metadata["history_path"] = str(result.history_path.relative_to(run_root))
        if result.density_path is not None:
            summary_metadata["density_path"] = str(result.density_path.relative_to(run_root))
        if result.plot_path is not None:
            summary_metadata["plot_path"] = str(result.plot_path.relative_to(run_root))

        artifacts = [
            ArtifactRecord(
                name="topology-summary",
                path=(
                    str(result.summary_path.relative_to(run_root))
                    if result.summary_path is not None
                    else f"results/{state.run_id}/reports/topology_summary.json"
                ),
                kind="topology_report",
                metadata=summary_metadata,
            )
        ]
        for path in result.result_files:
            if result.summary_path is not None and path == result.summary_path:
                continue
            artifacts.append(
                ArtifactRecord(
                    name=path.name,
                    path=str(path.relative_to(run_root)),
                    kind="topology_artifact",
                    metadata={"backend": result.backend_name},
                )
            )

        updates = {
            "topology_state": {
                "backend": result.backend_name,
                "result_path": (
                    str(result.summary_path.relative_to(run_root))
                    if result.summary_path is not None
                    else None
                ),
                "objective": result.objective,
                "volume_fraction": result.volume_fraction,
                "max_density_change": result.max_density_change,
                "beta": result.beta,
                "converged": result.converged,
                "iteration_count": result.iteration_count,
                "timing": result.timing.model_dump(mode="json"),
                "failure_reason": result.failure_reason,
            }
        }

        if result.converged:
            return AgentResult(
                status="success",
                task=self.task_name,
                message="Topology optimization converged.",
                artifacts=artifacts,
                updates=updates,
            )

        diagnostic = Diagnostic(
            code="topology.nonconverged",
            message=result.failure_reason or "Topology optimization did not converge.",
            task=self.task_name,
            details={"backend": result.backend_name},
        )
        return AgentResult(
            status="failure",
            task=self.task_name,
            message=diagnostic.message,
            diagnostics=[diagnostic],
            artifacts=artifacts,
            updates=updates,
        )
