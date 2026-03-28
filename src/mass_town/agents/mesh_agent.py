import logging
from pathlib import Path

from mass_town.agents.base_agent import BaseAgent
from mass_town.config import WorkflowConfig
from mass_town.disciplines.meshing import (
    MeshingBackendError,
    MeshingRequest,
    resolve_meshing_backend,
)
from mass_town.models.artifacts import ArtifactRecord
from mass_town.models.design_state import DesignState
from mass_town.models.result import AgentResult, Diagnostic
from mass_town.storage.filesystem import ensure_run_layout

logger = logging.getLogger(__name__)


class MeshAgent(BaseAgent):
    name = "mesh_agent"
    task_name = "mesh"

    def run(self, state: DesignState, config: WorkflowConfig, run_root: Path) -> AgentResult:
        layout = ensure_run_layout(run_root, state.run_id)
        request = MeshingRequest(
            geometry_input_path=(
                run_root / config.meshing.geometry_input_path
                if config.meshing.geometry_input_path
                else None
            ),
            mesh_directory=layout.mesh_dir,
            log_directory=layout.logs_dir,
            run_id=state.run_id,
            mesh_dimension=config.meshing.mesh_dimension,
            step_face_selector=config.meshing.step_face_selector,
            output_format=config.meshing.output_format,
            target_quality=config.meshing.target_quality,
        )

        try:
            backend = resolve_meshing_backend(config.meshing.tool, config.meshing.gmsh_executable)
        except MeshingBackendError as exc:
            diagnostic = Diagnostic(
                code="mesh.backend_unavailable",
                message=str(exc),
                task=self.task_name,
                details={"backend": config.meshing.tool},
            )
            return AgentResult(
                status="failure",
                task=self.task_name,
                message=diagnostic.message,
                diagnostics=[diagnostic],
            )

        try:
            meshing_result = backend.generate_mesh(request)
        except FileNotFoundError as exc:
            diagnostic = Diagnostic(
                code="mesh.geometry_input_missing",
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
                code="mesh.unsupported_geometry_input",
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
            logger.exception("Meshing backend %s failed.", backend.name)
            diagnostic = Diagnostic(
                code="mesh.backend_failed",
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

        metadata = dict(meshing_result.metadata)
        metadata.update(
            {
                "quality": meshing_result.quality,
                "elements": meshing_result.element_count,
                "backend": meshing_result.backend_name,
            }
        )
        if meshing_result.log_path is not None:
            metadata["log_path"] = str(meshing_result.log_path.relative_to(run_root))

        artifacts = [
            ArtifactRecord(
                name="mesh-output",
                path=str(meshing_result.mesh_path.relative_to(run_root))
                if meshing_result.mesh_path is not None
                else f"results/{state.run_id}/mesh/mesh-output.txt",
                kind="mesh_file",
                metadata=metadata,
            )
        ]

        if meshing_result.quality < config.meshing.target_quality:
            diagnostic = Diagnostic(
                code="mesh.poor_quality",
                message="Mesh quality is below the configured threshold.",
                task=self.task_name,
                details={
                    "quality": meshing_result.quality,
                    "target": config.meshing.target_quality,
                    "backend": meshing_result.backend_name,
                },
            )
            return AgentResult(
                status="failure",
                task=self.task_name,
                message=diagnostic.message,
                diagnostics=[diagnostic],
                artifacts=artifacts,
                updates={
                    "mesh_state": {
                        "backend": meshing_result.backend_name,
                        "mesh_path": (
                            str(meshing_result.mesh_path.relative_to(run_root))
                            if meshing_result.mesh_path is not None
                            else None
                        ),
                        "quality": meshing_result.quality,
                        "elements": meshing_result.element_count,
                    }
                },
            )

        return AgentResult(
            status="success",
            task=self.task_name,
            message="Mesh generated.",
            artifacts=artifacts,
            updates={
                "mesh_state": {
                    "backend": meshing_result.backend_name,
                    "mesh_path": (
                        str(meshing_result.mesh_path.relative_to(run_root))
                        if meshing_result.mesh_path is not None
                        else None
                    ),
                    "quality": meshing_result.quality,
                    "elements": meshing_result.element_count,
                }
            },
        )
