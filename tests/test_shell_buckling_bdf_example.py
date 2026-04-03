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


def _run_with_thickness(tmp_path: Path, thickness: float):
    source = Path("examples/shell_buckling_bdf_problem")
    base_dir = Path(
        tempfile.mkdtemp(
            prefix=f"mass_town_shell_buckling_bdf_{str(thickness).replace('.', '_')}_"
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
    state.run_id = f"shell-buckling-bdf-{str(thickness).replace('.', '-')}"
    state.design_variables["thickness"] = thickness
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
    summary_path = project_dir / "results" / final_state.run_id / "reports" / "run_summary.json"
    summary = json.loads(summary_path.read_text())
    return final_state, summary, summary_path


def test_shell_buckling_bdf_example_reports_feasibility_and_trend(tmp_path: Path) -> None:
    thin_state, thin_summary, thin_summary_path = _run_with_thickness(tmp_path, 0.005)
    thick_state, thick_summary, thick_summary_path = _run_with_thickness(tmp_path, 0.01)

    assert thin_state.status == "failed"
    assert thick_state.status == "recovered"

    assert thin_state.analysis_state.critical_eigenvalue is not None
    assert thick_state.analysis_state.critical_eigenvalue is not None
    assert (
        thick_state.analysis_state.critical_eigenvalue
        > thin_state.analysis_state.critical_eigenvalue
    )

    assert thin_state.analysis_state.mass is not None
    assert thick_state.analysis_state.mass is not None
    assert thick_state.analysis_state.mass > thin_state.analysis_state.mass

    assert thin_summary_path.exists()
    assert thick_summary_path.exists()
    assert thin_summary["analysis_type"] == "buckling"
    assert thick_summary["analysis_type"] == "buckling"
    assert thin_summary["critical_buckling_load_factor"] == pytest.approx(
        thin_state.analysis_state.critical_eigenvalue
    )
    assert thick_summary["critical_buckling_load_factor"] == pytest.approx(
        thick_state.analysis_state.critical_eigenvalue
    )
    assert thin_summary["eigenvalue_constraints"]["minimum_buckling_load_factor"]["passed"] is False
    assert thick_summary["eigenvalue_constraints"]["minimum_buckling_load_factor"]["passed"] is True
