import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from mass_town.orchestration.state_manager import StateManager

pytest.importorskip("tacs")


def _run_with_uniform_pid_thickness(tmp_path: Path, thickness: float):
    source = Path("examples/shell_sizing_bdf_multi_case_problem")
    base_dir = Path(
        tempfile.mkdtemp(
            prefix=f"mass_town_shell_sizing_bdf_multi_case_{str(thickness).replace('.', '_')}_"
        )
    )
    project_dir = base_dir / "project"
    shutil.copytree(
        source,
        project_dir,
        ignore=shutil.ignore_patterns("results", "__pycache__"),
    )

    state_path = project_dir / "design_state.yaml"
    state = StateManager().load(state_path)
    state.run_id = f"shell-sizing-bdf-multi-case-{str(thickness).replace('.', '-')}"
    for key in [f"pid{i}_t" for i in range(1, 10)]:
        state.design_variables[key] = thickness
    state.constraints["max_stress"] = 3.0e9
    StateManager().save(state, state_path)

    child_env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PYTEST_")
    }
    subprocess.run(
        [sys.executable, "-m", "mass_town.cli", "run", str(project_dir)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=child_env,
        start_new_session=True,
    )
    final_state = StateManager().load(state_path)
    return final_state, project_dir


def test_shell_sizing_bdf_multi_case_example_runs_and_reports_aggregation(tmp_path: Path) -> None:
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

    assert set(thin_state.analysis_state.load_cases) == {"center_bending", "center_shear"}
    assert set(thick_state.analysis_state.load_cases) == {"center_bending", "center_shear"}
    assert thin_state.analysis_state.worst_case_name in thin_state.analysis_state.load_cases
    assert thick_state.analysis_state.worst_case_name in thick_state.analysis_state.load_cases
    assert thin_state.analysis_state.aggregated_stress is not None
    assert thick_state.analysis_state.aggregated_stress is not None
    assert thin_state.analysis_state.aggregated_stress.value is not None
    assert thick_state.analysis_state.aggregated_stress.value is not None
    assert (
        thick_state.analysis_state.aggregated_stress.value
        < thin_state.analysis_state.aggregated_stress.value
    )

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
    thin_quality_summary = (
        thin_project
        / thin_state.analysis_state.aggregated_stress.quality_summary_path
    )
    thick_quality_summary = (
        thick_project
        / thick_state.analysis_state.aggregated_stress.quality_summary_path
    )
    assert thin_quality_summary.exists()
    assert thick_quality_summary.exists()

    thin_summary_data = json.loads(thin_summary.read_text())
    thick_summary_data = json.loads(thick_summary.read_text())
    thin_quality_summary_data = json.loads(thin_quality_summary.read_text())
    thick_quality_summary_data = json.loads(thick_quality_summary.read_text())

    assert thin_summary_data["worst_case_name"] in thin_summary_data["load_case_results"]
    assert thick_summary_data["worst_case_name"] in thick_summary_data["load_case_results"]
    assert thin_summary_data["max_stress"] == pytest.approx(
        thin_summary_data["load_case_results"][thin_summary_data["worst_case_name"]]["max_stress"]
    )
    assert thick_summary_data["max_stress"] == pytest.approx(
        thick_summary_data["load_case_results"][thick_summary_data["worst_case_name"]]["max_stress"]
    )
    assert set(thin_summary_data["load_case_results"]) == {"center_bending", "center_shear"}
    assert set(thick_summary_data["load_case_results"]) == {"center_bending", "center_shear"}
    assert thin_summary_data["aggregated_stress"]["method"] == "ks"
    assert thick_summary_data["aggregated_stress"]["method"] == "ks"
    assert thin_summary_data["aggregated_stress"]["quality_summary_path"] == (
        thin_state.analysis_state.aggregated_stress.quality_summary_path
    )
    assert thick_summary_data["aggregated_stress"]["quality_summary_path"] == (
        thick_state.analysis_state.aggregated_stress.quality_summary_path
    )
    assert thin_quality_summary_data["raw_global_max_stress"] is not None
    assert thick_quality_summary_data["raw_global_max_stress"] is not None
