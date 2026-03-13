from pathlib import Path

from mass_town.config import WorkflowConfig
from mass_town.orchestration.workflow_engine import WorkflowEngine


def test_workflow_engine_recovers_example(tmp_path: Path) -> None:
    project_dir = tmp_path / "example"
    project_dir.mkdir()
    (project_dir / "config.yaml").write_text(
        "\n".join(
            [
                "max_iterations: 8",
                "allowable_stress: 180.0",
                "target_mesh_quality: 0.75",
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

    engine = WorkflowEngine(config=WorkflowConfig.from_file(project_dir / "config.yaml"))
    state = engine.run(project_dir / "design_state.yaml", project_dir)

    assert state.status == "recovered"
    assert state.analysis_state.passed is True
    assert state.design_variables["thickness"] >= 0.8
