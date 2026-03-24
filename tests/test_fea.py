from pathlib import Path

from mass_town.agents.fea_agent import FEAAgent
from mass_town.config import WorkflowConfig
from mass_town.disciplines.fea import FEABackend, FEABackendError, FEARequest, FEAResult
from mass_town.disciplines.fea.registry import BACKEND_LOADERS, resolve_fea_backend
from mass_town.models.design_state import DesignState


class StubFEABackend(FEABackend):
    name = "tacs"

    def __init__(self, available: bool = True, result_path: Path | None = None) -> None:
        self.available = available
        self.result_path = result_path

    def is_available(self) -> bool:
        return self.available

    def availability_reason(self) -> str | None:
        if self.available:
            return None
        return "stub backend unavailable"

    def run_analysis(self, request: FEARequest) -> FEAResult:
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
            metadata={"case_name": request.case_name},
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
    monkeypatch.setitem(BACKEND_LOADERS, "tacs", lambda: StubFEABackend())
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
