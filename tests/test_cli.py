from pathlib import Path

from typer.testing import CliRunner

from mass_town.cli import app


def test_cli_run_and_status(tmp_path: Path) -> None:
    project_dir = tmp_path / "example"
    project_dir.mkdir()
    (project_dir / "config.yaml").write_text(
        "max_iterations: 8\nallowable_stress: 180.0\ntarget_mesh_quality: 0.75\ninitial_tasks:\n  - geometry\n  - mesh\n  - fea\n  - optimizer\n"
    )
    (project_dir / "design_state.yaml").write_text(
        "run_id: cli-run\nproblem_name: structural\nstatus: pending\niteration: 0\ndesign_variables:\n  thickness: 0.6\n  length: 10.0\n  width: 4.0\nloads:\n  force: 120.0\nconstraints:\n  max_stress: 180.0\ngeometry_state:\n  valid: true\n  notes: seed\nmesh_state:\n  quality: 0.5\n  elements: 0\nanalysis_state:\n  max_stress: null\n  passed: false\ndiagnostics: []\ndecision_history: []\nartifacts: []\ntask_history: []\n"
    )

    runner = CliRunner()
    run_result = runner.invoke(app, ["run", str(project_dir)])
    status_result = runner.invoke(app, ["status", str(project_dir / "design_state.yaml")])

    assert run_result.exit_code == 0
    assert "status=recovered" in run_result.stdout
    assert status_result.exit_code == 0
    assert "run_id=cli-run" in status_result.stdout
