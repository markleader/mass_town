import json
from pathlib import Path

from mass_town.config import WorkflowConfig
from mass_town.disciplines.fea.registry import BACKEND_LOADERS
from mass_town.orchestration.workflow_engine import WorkflowEngine
from tests.test_fea import StubFEABackend


def test_workflow_engine_recovers_example(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(BACKEND_LOADERS, "tacs", lambda: StubFEABackend())
    project_dir = tmp_path / "example"
    project_dir.mkdir()
    (project_dir / "config.yaml").write_text(
        "\n".join(
            [
                "max_iterations: 8",
                "allowable_stress: 180.0",
                "meshing:",
                "  tool: mock",
                "  target_quality: 0.75",
                "fea:",
                "  tool: tacs",
                "  model_input_path: analysis/model.bdf",
                "initial_tasks:",
                "  - geometry",
                "  - mesh",
                "  - fea",
                "  - optimizer",
                "",
            ]
        )
    )
    (project_dir / "design_state.yaml").write_text(
        "\n".join(
            [
                "run_id: test-run",
                "problem_name: structural",
                "status: pending",
                "iteration: 0",
                "design_variables:",
                "  thickness: 0.6",
                "  length: 10.0",
                "  width: 4.0",
                "loads:",
                "  force: 120.0",
                "constraints:",
                "  max_stress: 180.0",
                "geometry_state:",
                "  valid: true",
                "  notes: seed",
                "mesh_state:",
                "  quality: 0.5",
                "  elements: 0",
                "analysis_state:",
                "  mass: null",
                "  max_stress: null",
                "  passed: false",
                "diagnostics: []",
                "decision_history: []",
                "artifacts: []",
                "task_history: []",
                "",
            ]
        )
    )
    analysis_dir = project_dir / "analysis"
    analysis_dir.mkdir()
    (analysis_dir / "model.bdf").write_text("CEND\nBEGIN BULK\nENDDATA\n")

    engine = WorkflowEngine(config=WorkflowConfig.from_file(project_dir / "config.yaml"))
    state = engine.run(project_dir / "design_state.yaml", project_dir)

    assert state.status == "recovered"
    assert state.analysis_state.passed is True
    assert state.analysis_state.mass == 24.0
    assert state.design_variables["thickness"] >= 0.8
    summary_path = project_dir / "results" / "test-run" / "reports" / "run_summary.json"
    summary = json.loads(summary_path.read_text())
    assert summary["status"] == "recovered"
    assert summary["feasible"] is True
    assert summary["mass"] == 24.0
    assert summary["artifact_paths"]["analysis_summary"] == "results/test-run/reports/stub-fea.json"
