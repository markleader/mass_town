import json

import pytest

from mass_town.config import WorkflowConfig
from mass_town.orchestration.workflow_engine import WorkflowEngine
from tests.cantilever_example_utils import copy_cantilever_examples

pytest.importorskip("gmsh")
pytest.importorskip("tacs")


def test_shell_and_solid_cantilever_examples_track_same_envelope_trends(tmp_path) -> None:
    solid_project_dir, shell_project_dir = copy_cantilever_examples(tmp_path)

    solid_state = WorkflowEngine(
        config=WorkflowConfig.from_file(solid_project_dir / "config.yaml")
    ).run(solid_project_dir / "design_state.yaml", solid_project_dir)
    shell_state = WorkflowEngine(
        config=WorkflowConfig.from_file(shell_project_dir / "config.yaml")
    ).run(shell_project_dir / "design_state.yaml", shell_project_dir)

    solid_summary = json.loads(
        (
            solid_project_dir
            / "results"
            / "solid-cantilever-problem"
            / "reports"
            / "run_summary.json"
        ).read_text()
    )
    shell_summary = json.loads(
        (
            shell_project_dir
            / "results"
            / "shell-cantilever-problem"
            / "reports"
            / "run_summary.json"
        ).read_text()
    )

    assert solid_state.analysis_state.passed is True
    assert shell_state.analysis_state.passed is True
    assert solid_summary["mass"] is not None
    assert shell_summary["mass"] is not None
    assert solid_summary["max_stress"] is not None
    assert shell_summary["max_stress"] is not None

    mass_ratio = shell_summary["mass"] / solid_summary["mass"]
    stress_ratio = shell_summary["max_stress"] / solid_summary["max_stress"]

    assert 0.75 <= mass_ratio <= 1.25
    assert 0.1 <= stress_ratio <= 10.0
    if (
        solid_summary.get("displacement_norm") is not None
        and shell_summary.get("displacement_norm") is not None
    ):
        displacement_ratio = (
            shell_summary["displacement_norm"] / solid_summary["displacement_norm"]
        )
        assert 0.1 <= displacement_ratio <= 10.0
