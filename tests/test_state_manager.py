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
    assert loaded.load_cases == {}
    assert loaded.constraints["max_stress"] == 180.0


def test_state_manager_round_trip_preserves_load_cases(tmp_path: Path) -> None:
    path = tmp_path / "design_state.yaml"
    state = DesignState(
        run_id="demo-multi-case",
        problem_name="demo-problem",
        design_variables={"thickness": 1.0},
        load_cases={
            "center_bending": {"loads": {"force_z": 120.0}},
            "center_shear": {"loads": {"force_x": 60.0}},
        },
        constraints={"max_stress": 180.0},
    )

    manager = StateManager()
    manager.save(state, path)
    loaded = manager.load(path)

    assert loaded.load_cases["center_bending"].loads == {"force_z": 120.0}
    assert loaded.load_cases["center_shear"].loads == {"force_x": 60.0}


def test_state_manager_round_trip_preserves_aggregated_constraints(tmp_path: Path) -> None:
    path = tmp_path / "design_state.yaml"
    state = DesignState(
        run_id="demo-aggregated",
        problem_name="demo-problem",
        constraints={
            "max_stress": 180.0,
            "aggregated_stress": {
                "method": "ks",
                "source": "load_cases",
                "allowable": 175.0,
                "ks_weight": 40.0,
            },
        },
    )

    manager = StateManager()
    manager.save(state, path)
    loaded = manager.load(path)

    assert loaded.constraints.aggregated_stress is not None
    assert loaded.constraints.aggregated_stress.method == "ks"
    assert loaded.constraints.aggregated_stress.allowable == 175.0
    assert loaded.constraints.aggregated_stress.ks_weight == 40.0
