from mass_town.agents.base_agent import BaseAgent
from mass_town.adapters.fea_adapter import FEAAdapter
from mass_town.config import WorkflowConfig
from mass_town.models.artifacts import ArtifactRecord
from mass_town.models.design_state import DesignState
from mass_town.models.result import AgentResult, Diagnostic


class FEAAgent(BaseAgent):
    name = "fea_agent"
    task_name = "fea"

    def __init__(self) -> None:
        self.adapter = FEAAdapter()

    def run(self, state: DesignState, config: WorkflowConfig) -> AgentResult:
        stress = self.adapter.compute_max_stress(
            force=state.loads.get("force", 0.0),
            thickness=state.design_variables.get("thickness", 0.1),
            mesh_quality=state.mesh_state.quality,
        )
        artifact = ArtifactRecord(
            name="fea-summary",
            path=f"artifacts/{state.run_id}/fea.txt",
            kind="analysis_report",
            metadata={"max_stress": round(stress, 3)},
        )
        if stress > config.allowable_stress:
            diagnostic = Diagnostic(
                code="analysis.stress_exceeded",
                message="Stress exceeds allowable limit.",
                task=self.task_name,
                details={"max_stress": round(stress, 3), "allowable": config.allowable_stress},
            )
            return AgentResult(
                status="failure",
                task=self.task_name,
                message=diagnostic.message,
                diagnostics=[diagnostic],
                artifacts=[artifact],
                updates={"analysis_state": {"max_stress": stress, "passed": False}},
            )

        return AgentResult(
            status="success",
            task=self.task_name,
            message="Structural analysis passed.",
            artifacts=[artifact],
            updates={"analysis_state": {"max_stress": stress, "passed": True}},
        )
