import shutil
from pathlib import Path

import pytest

from mass_town.config import WorkflowConfig
from mass_town.orchestration.state_manager import StateManager
from mass_town.orchestration.workflow_engine import WorkflowEngine

pytest.importorskip("tacs")


def _run_with_uniform_pid_thickness(tmp_path: Path, thickness: float):
    source = Path("examples/shell_sizing_bdf_problem")
    project_dir = tmp_path / f"shell_sizing_bdf_problem_{str(thickness).replace('.', '_')}"
    shutil.copytree(
        source,
        project_dir,
        ignore=shutil.ignore_patterns("results", "__pycache__"),
    )

    state_path = project_dir / "design_state.yaml"
    state = StateManager().load(state_path)
    state.run_id = f"shell-sizing-bdf-{str(thickness).replace('.', '-') }"
    for key in [f"pid{i}_t" for i in range(1, 10)]:
        state.design_variables[key] = thickness
    state.constraints["max_stress"] = 3.0e9
    StateManager().save(state, state_path)

    config = WorkflowConfig.from_file(project_dir / "config.yaml")
    config.allowable_stress = 3.0e9
    engine = WorkflowEngine(config=config)
    final_state = engine.run(state_path, project_dir)
    return final_state, project_dir


def test_shell_sizing_bdf_example_runs_and_reports_trends(tmp_path: Path) -> None:
    thin_state, thin_project = _run_with_uniform_pid_thickness(tmp_path, 0.003)
    thick_state, thick_project = _run_with_uniform_pid_thickness(tmp_path, 0.009)

    assert thin_state.analysis_state.passed is True
    assert thick_state.analysis_state.passed is True

    assert thin_state.analysis_state.mass is not None
    assert thick_state.analysis_state.mass is not None
    assert thick_state.analysis_state.mass > thin_state.analysis_state.mass

    assert thin_state.analysis_state.max_stress is not None
    assert thick_state.analysis_state.max_stress is not None
    assert thick_state.analysis_state.max_stress < thin_state.analysis_state.max_stress

    thin_summary = (
        thin_project
        / "results"
        / thin_state.run_id
        / "reports"
        / "run_summary.json"
    )
    thick_summary = (
        thick_project
        / "results"
        / thick_state.run_id
        / "reports"
        / "run_summary.json"
    )

    assert thin_summary.exists()
    assert thick_summary.exists()
