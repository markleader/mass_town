import json
from pathlib import Path

import pytest

from mass_town.config import WorkflowConfig
from mass_town.orchestration.workflow_engine import WorkflowEngine
from tests.cantilever_example_utils import copy_cantilever_examples

pytest.importorskip("gmsh")
pytest.importorskip("tacs")


def test_solid_cantilever_example_runs_end_to_end(tmp_path: Path) -> None:
    solid_project_dir, _ = copy_cantilever_examples(tmp_path)

    engine = WorkflowEngine(config=WorkflowConfig.from_file(solid_project_dir / "config.yaml"))
    state = engine.run(solid_project_dir / "design_state.yaml", solid_project_dir)

    summary_path = solid_project_dir / "results" / "solid-cantilever-problem" / "reports" / "run_summary.json"
    mesh_path = solid_project_dir / "results" / "solid-cantilever-problem" / "mesh" / "cantilever.bdf"
    gmsh_log_path = solid_project_dir / "results" / "solid-cantilever-problem" / "logs" / "cantilever.gmsh.log"
    tacs_log_path = solid_project_dir / "results" / "solid-cantilever-problem" / "logs" / "cantilever.tacs.log"
    solver_dir = solid_project_dir / "results" / "solid-cantilever-problem" / "solver"

    summary = json.loads(summary_path.read_text())

    assert state.status == "recovered"
    assert state.analysis_state.passed is True
    assert mesh_path.exists()
    assert gmsh_log_path.exists()
    assert tacs_log_path.exists()
    assert summary["feasible"] is True
    assert summary["artifact_paths"]["mesh_model"] == "results/solid-cantilever-problem/mesh/cantilever.bdf"
    assert summary["artifact_paths"]["analysis_summary"] == (
        "results/solid-cantilever-problem/reports/cantilever.tacs.summary.json"
    )
    assert summary["iteration_count"] == 3
    assert summary["max_stress"] is not None
    assert summary["max_stress"] <= 180.0
    assert summary["mass"] is not None
    assert summary["mass"] > 0.0
    assert any(solver_dir.rglob("*.f5"))
