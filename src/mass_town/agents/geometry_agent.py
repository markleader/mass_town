from pathlib import Path

from mass_town.adapters.geometry_adapter import GeometryAdapter
from mass_town.agents.base_agent import BaseAgent
from mass_town.config import WorkflowConfig
from mass_town.models.artifacts import ArtifactRecord
from mass_town.models.design_state import DesignState
from mass_town.models.result import AgentResult


class GeometryAgent(BaseAgent):
    name = "geometry_agent"
    task_name = "geometry"

    def __init__(self) -> None:
        self.adapter = GeometryAdapter()

    def run(self, state: DesignState, config: WorkflowConfig, run_root: Path) -> AgentResult:
        valid, message = self.adapter.validate(state.design_variables)
        if not valid:
            diagnostic = self.adapter.failure(message or "Geometry validation failed.")
            return AgentResult(
                status="failure",
                task=self.task_name,
                message=diagnostic.message,
                diagnostics=[diagnostic],
            )

        artifact = ArtifactRecord(
            name="geometry-summary",
            path=f"results/{state.run_id}/reports/geometry_summary.txt",
            kind="geometry_report",
            metadata={"valid": True},
        )
        return AgentResult(
            status="success",
            task=self.task_name,
            message="Geometry validated.",
            artifacts=[artifact],
            updates={"geometry_state": {"valid": True, "notes": "validated"}},
        )
