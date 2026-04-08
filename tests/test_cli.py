from pathlib import Path

import json
import sys
import types

from typer.testing import CliRunner

from mass_town.cli import app
from mass_town.disciplines.fea.registry import BACKEND_LOADERS
from mass_town.models.design_state import DesignState
from tests.test_fea import StubFEABackend


def test_cli_run_and_status(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(BACKEND_LOADERS, "tacs", lambda: StubFEABackend())
    project_dir = tmp_path / "example"
    project_dir.mkdir()
    (project_dir / "config.yaml").write_text(
        "max_iterations: 8\nallowable_stress: 180.0\nmeshing:\n  tool: mock\n  target_quality: 0.75\nfea:\n  tool: tacs\n  model_input_path: analysis/model.bdf\ninitial_tasks:\n  - geometry\n  - mesh\n  - fea\n  - optimizer\n"
    )
    (project_dir / "design_state.yaml").write_text(
        "run_id: cli-run\nproblem_name: structural\nstatus: pending\niteration: 0\ndesign_variables:\n  thickness: 0.6\n  length: 10.0\n  width: 4.0\nloads:\n  force: 120.0\nconstraints:\n  max_stress: 180.0\ngeometry_state:\n  valid: true\n  notes: seed\nmesh_state:\n  quality: 0.5\n  elements: 0\nanalysis_state:\n  mass: null\n  max_stress: null\n  passed: false\ndiagnostics: []\ndecision_history: []\nartifacts: []\ntask_history: []\n"
    )
    analysis_dir = project_dir / "analysis"
    analysis_dir.mkdir()
    (analysis_dir / "model.bdf").write_text("CEND\nBEGIN BULK\nENDDATA\n")

    runner = CliRunner()
    run_result = runner.invoke(app, ["run", str(project_dir)])
    status_result = runner.invoke(app, ["status", str(project_dir / "design_state.yaml")])

    assert run_result.exit_code == 0
    assert "status=recovered" in run_result.stdout
    assert status_result.exit_code == 0
    assert "run_id=cli-run" in status_result.stdout
    summary = json.loads((project_dir / "results" / "cli-run" / "reports" / "run_summary.json").read_text())
    assert (project_dir / "results" / "cli-run" / "reports" / "problem_schema.json").exists()
    assert summary["artifact_paths"]["problem_schema"] == "results/cli-run/reports/problem_schema.json"


def test_cli_openmdao_runtime_option_selects_openmdao_runtime(tmp_path: Path) -> None:
    project_dir = tmp_path / "openmdao-project"
    project_dir.mkdir()
    (project_dir / "config.yaml").write_text(
        "max_iterations: 4\nallowable_stress: 180.0\nfea:\n  tool: mock\n  model_input_path: inputs/model.bdf\ninitial_tasks:\n  - fea\n"
    )
    (project_dir / "design_state.yaml").write_text(
        "run_id: cli-openmdao\nproblem_name: openmdao\nstatus: pending\niteration: 0\ndesign_variables: {}\nconstraints:\n  max_stress: 180.0\nanalysis_state:\n  passed: false\ndiagnostics: []\ndecision_history: []\nartifacts: []\ntask_history: []\n"
    )
    (project_dir / "inputs").mkdir()
    (project_dir / "inputs" / "model.bdf").write_text("ENDDATA\n")

    calls: list[str] = []

    class FakeOpenMDAORuntime:
        def __init__(self, config: object) -> None:
            del config

        def run(self, state_path: Path, run_root: Path) -> DesignState:
            del state_path, run_root
            calls.append("openmdao")
            return DesignState(run_id="cli-openmdao", problem_name="openmdao", status="recovered")

    fake_module = types.ModuleType("mass_town.runtime.openmdao_runtime")
    fake_module.OpenMDAORuntime = FakeOpenMDAORuntime
    sys.modules["mass_town.runtime.openmdao_runtime"] = fake_module
    try:
        runner = CliRunner()
        result = runner.invoke(app, ["run", str(project_dir), "--runtime", "openmdao"])
    finally:
        sys.modules.pop("mass_town.runtime.openmdao_runtime", None)

    assert result.exit_code == 0
    assert "status=recovered" in result.stdout
    assert calls == ["openmdao"]
