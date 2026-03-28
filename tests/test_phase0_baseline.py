import json
import shutil
from pathlib import Path

import pytest

from mass_town.config import WorkflowConfig
from mass_town.orchestration.workflow_engine import WorkflowEngine

pytest.importorskip("gmsh")
pytest.importorskip("tacs")


def test_phase0_baseline_example_runs_end_to_end(tmp_path: Path) -> None:
    source = Path("examples/simple_structural_problem")
    project_dir = tmp_path / "simple_structural_problem"
    shutil.copytree(
        source,
        project_dir,
        ignore=shutil.ignore_patterns("results", "__pycache__"),
    )

    engine = WorkflowEngine(config=WorkflowConfig.from_file(project_dir / "config.yaml"))
    state = engine.run(project_dir / "design_state.yaml", project_dir)

    summary_path = project_dir / "results" / "simple-structural-problem" / "reports" / "run_summary.json"
    mesh_path = project_dir / "results" / "simple-structural-problem" / "mesh" / "crank.bdf"
    gmsh_log_path = project_dir / "results" / "simple-structural-problem" / "logs" / "crank.gmsh.log"
    tacs_log_path = project_dir / "results" / "simple-structural-problem" / "logs" / "crank.tacs.log"
    solver_dir = project_dir / "results" / "simple-structural-problem" / "solver"

    summary = json.loads(summary_path.read_text())

    assert state.status == "recovered"
    assert state.analysis_state.passed is True
    assert mesh_path.exists()
    assert gmsh_log_path.exists()
    assert tacs_log_path.exists()
    assert summary["feasible"] is True
    assert summary["artifact_paths"]["mesh_model"] == "results/simple-structural-problem/mesh/crank.bdf"
    assert summary["artifact_paths"]["analysis_summary"] == (
        "results/simple-structural-problem/reports/crank.tacs.summary.json"
    )
    assert summary["artifact_paths"]["workflow_log"] == (
        "results/simple-structural-problem/logs/workflow.log"
    )
    assert summary["final_thickness"] >= 1.2
    assert summary["final_thickness"] <= 1.6
    assert summary["max_stress"] is not None
    assert summary["max_stress"] <= 180.0
    assert summary["max_stress"] >= 150.0
    assert summary["mass"] is not None
    assert summary["mass"] >= 30.0
    assert summary["mass"] <= 40.0
    assert summary["iteration_count"] >= 3
    assert summary["iteration_count"] <= 11
    assert any(solver_dir.glob("*.f5"))
