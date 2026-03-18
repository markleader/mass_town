from pathlib import Path

from mass_town.agents.base_agent import BaseAgent
from mass_town.adapters.optimizer_adapter import OptimizerAdapter
from mass_town.config import WorkflowConfig
from mass_town.models.artifacts import ArtifactRecord
from mass_town.models.design_state import DesignState
from mass_town.models.result import AgentResult


class OptimizerAgent(BaseAgent):
    name = "optimizer_agent"
    task_name = "optimizer"

    def __init__(self) -> None:
        self.adapter = OptimizerAdapter()

    def run(self, state: DesignState, config: WorkflowConfig, run_root: Path) -> AgentResult:
        current = state.design_variables.get("thickness", 0.0)
        next_thickness = max(current, 0.8)
        if not state.analysis_state.passed:
            next_thickness = self.adapter.increase_thickness(current)
        artifact = ArtifactRecord(
            name="optimizer-summary",
            path=f"artifacts/{state.run_id}/optimizer.txt",
            kind="optimizer_report",
            metadata={"thickness": next_thickness},
        )
        return AgentResult(
            status="success",
            task=self.task_name,
            message="Design variables updated.",
            artifacts=[artifact],
            updates={"design_variables": {**state.design_variables, "thickness": next_thickness}},
        )
