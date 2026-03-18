import shutil
from pathlib import Path

from mass_town.agents.mesh_agent import MeshAgent
from mass_town.config import WorkflowConfig
from mass_town.disciplines.meshing import resolve_meshing_backend
from mass_town.models.artifacts import ArtifactRecord
from mass_town.models.design_state import DesignState
from mass_town.storage.artifact_store import ArtifactStore


def _base_state() -> DesignState:
    return DesignState(
        run_id="mesh-run",
        problem_name="structural",
        design_variables={"thickness": 0.6, "length": 10.0, "width": 4.0},
        loads={"force": 120.0},
        constraints={"max_stress": 180.0},
    )


def test_config_preserves_legacy_target_mesh_quality() -> None:
    config = WorkflowConfig.model_validate({"target_mesh_quality": 0.82})
    assert config.meshing.target_quality == 0.82
    assert config.meshing.tool == "auto"


def test_resolve_meshing_backend_prefers_gmsh_when_available(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda executable: f"/usr/bin/{executable}")
    backend = resolve_meshing_backend("auto")
    assert backend.name == "gmsh"


def test_resolve_meshing_backend_falls_back_to_mock_when_gmsh_missing(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda executable: None)
    backend = resolve_meshing_backend("auto")
    assert backend.name == "mock"


def test_mesh_agent_uses_mock_backend(tmp_path: Path) -> None:
    config = WorkflowConfig.model_validate({"meshing": {"tool": "mock", "target_quality": 0.75}})
    result = MeshAgent().run(_base_state(), config, tmp_path)

    assert result.status == "success"
    assert result.updates["mesh_state"]["backend"] == "mock"
    mesh_path = tmp_path / result.updates["mesh_state"]["mesh_path"]
    assert mesh_path.exists()


def test_mesh_agent_reports_unavailable_gmsh_backend(tmp_path: Path) -> None:
    config = WorkflowConfig.model_validate({"meshing": {"tool": "gmsh"}})
    result = MeshAgent().run(_base_state(), config, tmp_path)

    assert result.status == "failure"
    assert result.diagnostics[0].code == "mesh.backend_unavailable"


def test_mesh_agent_rejects_unsupported_gmsh_geometry(tmp_path: Path) -> None:
    geometry_path = tmp_path / "shape.geo"
    geometry_path.write_text("dummy")
    true_executable = shutil.which("true")
    assert true_executable is not None
    config = WorkflowConfig.model_validate(
        {
            "meshing": {
                "tool": "gmsh",
                "geometry_input_path": "shape.geo",
                "gmsh_executable": true_executable,
            }
        }
    )

    result = MeshAgent().run(_base_state(), config, tmp_path)

    assert result.status == "failure"
    assert result.diagnostics[0].code == "mesh.unsupported_geometry_input"


def test_artifact_store_preserves_existing_mesh_files(tmp_path: Path) -> None:
    run_root = tmp_path
    state = _base_state()
    artifact_path = run_root / "artifacts" / state.run_id / "example.msh"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("mesh-data")
    artifact = ArtifactRecord(
        name="mesh-output",
        path=f"artifacts/{state.run_id}/example.msh",
        kind="mesh_file",
        metadata={"backend": "mock"},
    )

    ArtifactStore().record(run_root, state, [artifact])

    assert artifact_path.read_text() == "mesh-data"
    metadata_path = artifact_path.with_name(f"{artifact_path.name}.metadata.txt")
    assert metadata_path.exists()
