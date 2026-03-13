from mass_town.agents.base_agent import BaseAgent
from mass_town.adapters.mesh_adapter import MeshAdapter
from mass_town.config import WorkflowConfig
from mass_town.models.artifacts import ArtifactRecord
from mass_town.models.design_state import DesignState
from mass_town.models.result import AgentResult, Diagnostic


class MeshAgent(BaseAgent):
    name = "mesh_agent"
    task_name = "mesh"

    def __init__(self) -> None:
        self.adapter = MeshAdapter()

    def run(self, state: DesignState, config: WorkflowConfig) -> AgentResult:
        quality = self.adapter.generate_quality(state.mesh_state.quality)
        elements = self.adapter.estimate_elements(quality)
        artifact = ArtifactRecord(
            name="mesh-summary",
            path=f"artifacts/{state.run_id}/mesh.txt",
            kind="mesh_report",
            metadata={"quality": quality, "elements": elements},
        )
        if quality < config.target_mesh_quality:
            diagnostic = Diagnostic(
                code="mesh.poor_quality",
                message="Mesh quality is below the configured threshold.",
                task=self.task_name,
                details={"quality": quality, "target": config.target_mesh_quality},
            )
            return AgentResult(
                status="failure",
                task=self.task_name,
                message=diagnostic.message,
                diagnostics=[diagnostic],
                artifacts=[artifact],
                updates={"mesh_state": {"quality": quality, "elements": elements}},
            )

        return AgentResult(
            status="success",
            task=self.task_name,
            message="Mesh generated.",
            artifacts=[artifact],
            updates={"mesh_state": {"quality": quality, "elements": elements}},
        )
