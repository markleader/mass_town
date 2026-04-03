import json
from pathlib import Path

from mass_town.config import WorkflowConfig
from mass_town.disciplines.fea import FEABackend, FEARequest, FEAResult
from mass_town.disciplines.fea.registry import BACKEND_LOADERS
from mass_town.orchestration.workflow_engine import WorkflowEngine
from tests.test_fea import StubFEABackend


class TrendFEABackend(FEABackend):
    name = "tacs"

    def __init__(self) -> None:
        self.observed_stresses: list[float] = []

    def is_available(self) -> bool:
        return True

    def availability_reason(self) -> str | None:
        return None

    def run_analysis(self, request: FEARequest) -> FEAResult:
        thickness = request.design_variable_assignments.global_values.get("thickness", 1.0)
        skin_thickness = request.design_variable_assignments.region_values.get("skin", thickness)
        max_stress = 220.0 / max(thickness + 0.25 * skin_thickness, 1e-6)
        self.observed_stresses.append(max_stress)
        summary_path = request.report_directory / "trend-fea.json"
        summary_path.write_text(f'{{"max_stress": {max_stress:.6f}}}\n')
        return FEAResult(
            backend_name=self.name,
            passed=max_stress <= request.allowable_stress,
            mass=30.0 + thickness,
            max_stress=max_stress,
            displacement_norm=0.01,
            result_files=[summary_path],
            metadata={"trend": "thickness_inverse_stress"},
        )


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


def test_workflow_engine_multi_dv_fixture_shows_expected_stress_trend(monkeypatch, tmp_path: Path) -> None:
    backend = TrendFEABackend()
    monkeypatch.setitem(BACKEND_LOADERS, "tacs", lambda: backend)
    project_dir = tmp_path / "multi-dv-example"
    project_dir.mkdir()
    (project_dir / "config.yaml").write_text(
        "\n".join(
            [
                "max_iterations: 20",
                "allowable_stress: 180.0",
                "meshing:",
                "  tool: mock",
                "  target_quality: 0.75",
                "fea:",
                "  tool: tacs",
                "  model_input_path: analysis/model.bdf",
                "design_variables:",
                "  - id: thickness",
                "    name: Global Thickness",
                "    type: scalar_thickness",
                "    initial_value: 0.6",
                "    bounds:",
                "      lower: 0.1",
                "      upper: 2.0",
                "    active: true",
                "  - id: skin_t",
                "    name: Skin Thickness",
                "    type: region_thickness",
                "    region: skin",
                "    initial_value: 0.8",
                "    bounds:",
                "      lower: 0.1",
                "      upper: 2.0",
                "    active: true",
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
                "run_id: multi-dv-run",
                "problem_name: structural",
                "status: pending",
                "iteration: 0",
                "design_variables:",
                "  thickness: 0.6",
                "  skin_t: 0.8",
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
    (analysis_dir / "model.bdf").write_text(
        "\n".join(
            [
                "$ REGION pid=1 gmsh_id=10 kind=shell name=skin",
                "CEND",
                "BEGIN BULK",
                "CTRIA3,10,1,1,2,3",
                "ENDDATA",
                "",
            ]
        )
    )

    engine = WorkflowEngine(config=WorkflowConfig.from_file(project_dir / "config.yaml"))
    state = engine.run(project_dir / "design_state.yaml", project_dir)

    assert state.status == "recovered"
    assert state.analysis_state.max_stress is not None
    assert state.analysis_state.max_stress <= 180.0
    assert state.design_variables["thickness"] > 0.6
    assert len(backend.observed_stresses) >= 2
    assert backend.observed_stresses[-1] < backend.observed_stresses[0]

    summary_path = project_dir / "results" / "multi-dv-run" / "reports" / "run_summary.json"
    summary = json.loads(summary_path.read_text())
    assert summary["active_design_variables"]["thickness"] == state.design_variables["thickness"]
    assert summary["active_design_variables"]["skin_t"] == state.design_variables["skin_t"]
