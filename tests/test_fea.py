from pathlib import Path

from mass_town.agents.fea_agent import FEAAgent
from mass_town.config import WorkflowConfig
from mass_town.disciplines.fea import FEABackend, FEABackendError, FEARequest, FEAResult
from mass_town.disciplines.fea.registry import BACKEND_LOADERS, resolve_fea_backend
from mass_town.models.design_state import DesignState
from plugins.tacs.shell_model import classify_boundary_loops, distribute_force_to_nodes, find_boundary_loops


class StubFEABackend(FEABackend):
    name = "tacs"

    def __init__(self, available: bool = True, result_path: Path | None = None) -> None:
        self.available = available
        self.result_path = result_path
        self.last_request: FEARequest | None = None

    def is_available(self) -> bool:
        return self.available

    def availability_reason(self) -> str | None:
        if self.available:
            return None
        return "stub backend unavailable"

    def run_analysis(self, request: FEARequest) -> FEAResult:
        self.last_request = request
        if request.model_input_path is None:
            raise ValueError("The tacs backend requires a BDF model input path.")
        if not request.model_input_path.exists():
            raise FileNotFoundError(f"FEA model input does not exist: {request.model_input_path}")

        summary_path = self.result_path or request.output_directory / "stub-fea.json"
        summary_path.write_text('{"max_stress": 120.0}\n')
        return FEAResult(
            backend_name=self.name,
            passed=True,
            max_stress=120.0,
            displacement_norm=0.0125,
            result_files=[summary_path],
            metadata={"case_name": request.case_name, "failure_index": 2.0 / 3.0},
        )


def _base_state() -> DesignState:
    return DesignState(
        run_id="fea-run",
        problem_name="structural",
        design_variables={"thickness": 0.8},
        loads={"force": 120.0},
        constraints={"max_stress": 180.0},
        mesh_state={"backend": "mock", "mesh_path": "artifacts/fea-run/mesh.msh", "quality": 0.9},
    )


def test_config_parses_fea_settings() -> None:
    config = WorkflowConfig.model_validate(
        {"fea": {"tool": "tacs", "model_input_path": "analysis/model.bdf", "case_name": "wing"}}
    )

    assert config.fea.tool == "tacs"
    assert config.fea.model_input_path == "analysis/model.bdf"
    assert config.fea.case_name == "wing"
    assert config.fea.write_solution is True


def test_resolve_fea_backend_prefers_tacs_when_available(monkeypatch) -> None:
    monkeypatch.setitem(BACKEND_LOADERS, "tacs", lambda: StubFEABackend())

    backend = resolve_fea_backend("auto")

    assert backend.name == "tacs"


def test_resolve_fea_backend_reports_unavailable_backend(monkeypatch) -> None:
    monkeypatch.setitem(BACKEND_LOADERS, "tacs", lambda: StubFEABackend(available=False))

    try:
        resolve_fea_backend("tacs")
    except FEABackendError as exc:
        assert "stub backend unavailable" in str(exc)
    else:
        raise AssertionError("Expected FEABackendError")


def test_fea_agent_reports_unavailable_backend(tmp_path: Path) -> None:
    config = WorkflowConfig.model_validate({"fea": {"tool": "tacs"}})

    result = FEAAgent().run(_base_state(), config, tmp_path)

    assert result.status == "failure"
    assert result.diagnostics[0].code == "analysis.backend_unavailable"


def test_fea_agent_reports_missing_model_input(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(BACKEND_LOADERS, "tacs", lambda: StubFEABackend())
    config = WorkflowConfig.model_validate(
        {"fea": {"tool": "tacs", "model_input_path": "analysis/missing.bdf"}}
    )

    result = FEAAgent().run(_base_state(), config, tmp_path)

    assert result.status == "failure"
    assert result.diagnostics[0].code == "analysis.model_input_missing"


def test_fea_agent_normalizes_backend_result(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "analysis" / "model.bdf"
    model_path.parent.mkdir(parents=True)
    model_path.write_text("CEND\nBEGIN BULK\nENDDATA\n")
    backend = StubFEABackend()
    monkeypatch.setitem(BACKEND_LOADERS, "tacs", lambda: backend)
    config = WorkflowConfig.model_validate(
        {"fea": {"tool": "tacs", "model_input_path": "analysis/model.bdf"}}
    )

    result = FEAAgent().run(_base_state(), config, tmp_path)

    assert result.status == "success"
    assert result.updates["analysis_state"]["backend"] == "tacs"
    assert result.updates["analysis_state"]["max_stress"] == 120.0
    assert result.updates["analysis_state"]["displacement_norm"] == 0.0125
    assert result.updates["analysis_state"]["result_path"] == "artifacts/fea-run/stub-fea.json"
    assert result.artifacts[0].metadata["backend"] == "tacs"
    assert result.artifacts[0].metadata["failure_index"] == 2.0 / 3.0


def test_fea_agent_uses_generated_bdf_when_model_path_is_omitted(monkeypatch, tmp_path: Path) -> None:
    mesh_bdf = tmp_path / "artifacts" / "fea-run" / "mesh.bdf"
    mesh_bdf.parent.mkdir(parents=True)
    mesh_bdf.write_text("CEND\nBEGIN BULK\nENDDATA\n")
    backend = StubFEABackend()
    monkeypatch.setitem(BACKEND_LOADERS, "tacs", lambda: backend)
    config = WorkflowConfig.model_validate({"fea": {"tool": "tacs"}})
    state = DesignState(
        run_id="fea-run",
        problem_name="structural",
        design_variables={"thickness": 0.8},
        loads={"force": 120.0},
        constraints={"max_stress": 180.0},
        mesh_state={"backend": "gmsh", "mesh_path": "artifacts/fea-run/mesh.bdf", "quality": 0.9},
    )

    result = FEAAgent().run(state, config, tmp_path)

    assert result.status == "success"
    assert backend.last_request is not None
    assert backend.last_request.model_input_path == mesh_bdf


def test_shell_boundary_loop_detection_and_classification() -> None:
    node_positions = {
        node_id: (float(x), float(y), 0.0)
        for node_id, (x, y) in {
            1: (0, 0),
            2: (1, 0),
            3: (2, 0),
            4: (3, 0),
            5: (4, 0),
            6: (5, 0),
            7: (6, 0),
            8: (0, 1),
            9: (1, 1),
            10: (2, 1),
            11: (3, 1),
            12: (4, 1),
            13: (5, 1),
            14: (6, 1),
            15: (0, 2),
            16: (1, 2),
            17: (2, 2),
            18: (3, 2),
            19: (4, 2),
            20: (5, 2),
            21: (6, 2),
            22: (0, 3),
            23: (1, 3),
            24: (2, 3),
            25: (3, 3),
            26: (4, 3),
            27: (5, 3),
            28: (6, 3),
            29: (0, 4),
            30: (1, 4),
            31: (2, 4),
            32: (3, 4),
            33: (4, 4),
            34: (5, 4),
            35: (6, 4),
        }.items()
    }
    elements = []
    for y in range(4):
        for x in range(6):
            if (x, y) in {(1, 1), (4, 1)}:
                continue
            lower_left = y * 7 + x + 1
            elements.append(
                (
                    "CQUAD4",
                    (
                        lower_left,
                        lower_left + 1,
                        lower_left + 8,
                        lower_left + 7,
                    ),
                )
            )

    loops = find_boundary_loops(node_positions, elements)
    classified = classify_boundary_loops(node_positions, loops)

    assert len(loops) == 3
    assert len(classified["outer"]) > len(classified["left_bore"])
    assert set(classified["left_bore"]) == {9, 10, 17, 16}
    assert set(classified["right_bore"]) == {12, 13, 20, 19}


def test_distribute_force_to_nodes_preserves_total_force() -> None:
    loads = distribute_force_to_nodes([10, 20, 30], 120.0)

    assert len(loads) == 3
    assert sum(load[1] for load in loads) == -120.0
    assert all(load[0] == 0.0 for load in loads)
