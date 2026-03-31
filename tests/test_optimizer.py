from pathlib import Path

from mass_town.agents.optimizer_agent import OptimizerAgent
from mass_town.config import WorkflowConfig
from mass_town.models.design_state import DesignState


def test_optimizer_updates_active_region_and_element_thickness_variables(tmp_path: Path) -> None:
    config = WorkflowConfig.model_validate(
        {
            "design_variables": [
                {
                    "id": "skin_t",
                    "name": "Skin Thickness",
                    "type": "region_thickness",
                    "initial_value": 0.5,
                    "bounds": {"lower": 0.1, "upper": 1.0},
                    "region": "pid_1",
                    "active": True,
                },
                {
                    "id": "local_t",
                    "name": "Local Thickness",
                    "type": "element_thickness",
                    "initial_value": 0.4,
                    "bounds": {"lower": 0.1, "upper": 1.0},
                    "element_ids": [10],
                    "active": True,
                },
            ]
        }
    )
    state = DesignState(
        run_id="opt-run",
        problem_name="optimizer",
        design_variables={"skin_t": 0.5, "local_t": 0.4},
        analysis_state={"passed": False},
    )

    result = OptimizerAgent().run(state, config, tmp_path)

    assert result.status == "success"
    assert result.updates["design_variables"]["skin_t"] == 0.7
    assert result.updates["design_variables"]["local_t"] == 0.6
