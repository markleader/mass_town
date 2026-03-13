from pathlib import Path

from mass_town.models.design_state import DesignState
from mass_town.orchestration.state_manager import StateManager


def test_state_manager_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "design_state.yaml"
    state = DesignState(
        run_id="demo",
        problem_name="demo-problem",
        design_variables={"thickness": 1.0},
        loads={"force": 100.0},
        constraints={"max_stress": 180.0},
    )

    manager = StateManager()
    manager.save(state, path)
    loaded = manager.load(path)

    assert loaded.run_id == "demo"
    assert loaded.design_variables["thickness"] == 1.0
