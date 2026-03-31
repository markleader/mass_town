import json
from pathlib import Path

from mass_town.agents.base_agent import BaseAgent
from mass_town.adapters.optimizer_adapter import OptimizerAdapter
from mass_town.config import WorkflowConfig
from mass_town.design_variables import (
    DesignVariableType,
    clamp_design_variable_value,
    resolved_design_variable_definitions,
    resolved_design_variable_values,
)
from mass_town.models.artifacts import ArtifactRecord
from mass_town.models.design_state import DesignState
from mass_town.models.result import AgentResult


class OptimizerAgent(BaseAgent):
    name = "optimizer_agent"
    task_name = "optimizer"

    def __init__(self) -> None:
        self.adapter = OptimizerAdapter()

    def run(self, state: DesignState, config: WorkflowConfig, run_root: Path) -> AgentResult:
        definitions = resolved_design_variable_definitions(
            config.design_variables,
            state.design_variables,
        )
        values = resolved_design_variable_values(definitions, state.design_variables)
        next_values = dict(values)

        for definition in definitions:
            if not definition.active:
                continue
            current = values[definition.id]
            next_value = current
            if definition.type == DesignVariableType.scalar_thickness:
                next_value = max(current, 0.8)
            if not state.analysis_state.passed:
                next_value = self.adapter.increase_thickness(current)
            next_values[definition.id] = clamp_design_variable_value(definition, next_value)

        persisted_values = {
            key: value
            for key, value in state.design_variables.items()
            if key not in {definition.id for definition in definitions}
        }
        persisted_values.update(next_values)

        artifact = ArtifactRecord(
            name="optimizer-summary",
            path=f"results/{state.run_id}/reports/optimizer_summary.txt",
            kind="optimizer_report",
            metadata={
                "design_variables": ",".join(sorted(next_values)),
                "design_variable_snapshot": json.dumps(next_values, sort_keys=True),
            },
        )
        return AgentResult(
            status="success",
            task=self.task_name,
            message="Design variables updated.",
            artifacts=[artifact],
            updates={"design_variables": persisted_values},
        )
