import shutil
import subprocess
from pathlib import Path

from mass_town.agents.mesh_agent import MeshAgent
from mass_town.config import WorkflowConfig
from mass_town.disciplines.meshing import MeshingRequest, resolve_meshing_backend
from mass_town.models.artifacts import ArtifactRecord
from mass_town.models.design_state import DesignState
from mass_town.storage.artifact_store import ArtifactStore
from plugins.gmsh.backend import GmshMeshingBackend
from plugins.gmsh.exporters.bdf import write_bdf
from plugins.gmsh.extraction import parse_gmsh_msh2


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
    assert config.meshing.mesh_dimension == 3
    assert config.meshing.output_format == "msh"


def test_config_parses_bdf_output_format() -> None:
    config = WorkflowConfig.model_validate(
        {
            "meshing": {
                "output_format": "bdf",
                "mesh_dimension": 2,
                "step_face_selector": "largest_planar",
            }
        }
    )

    assert config.meshing.output_format == "bdf"
    assert config.meshing.mesh_dimension == 2
    assert config.meshing.step_face_selector == "largest_planar"


def test_resolve_meshing_backend_prefers_gmsh_when_available(monkeypatch) -> None:
    monkeypatch.setattr("plugins.gmsh.backend.GmshMeshingBackend._python_api_available", lambda self: False)
    monkeypatch.setattr("plugins.gmsh.backend.GmshMeshingBackend._executable_available", lambda self: True)
    backend = resolve_meshing_backend("auto")
    assert backend.name == "gmsh"


def test_resolve_meshing_backend_falls_back_to_mock_when_gmsh_missing(monkeypatch) -> None:
    monkeypatch.setattr("plugins.gmsh.backend.GmshMeshingBackend._python_api_available", lambda self: False)
    monkeypatch.setattr("plugins.gmsh.backend.GmshMeshingBackend._executable_available", lambda self: False)
    backend = resolve_meshing_backend("auto")
    assert backend.name == "mock"


def test_mesh_agent_uses_mock_backend(tmp_path: Path) -> None:
    config = WorkflowConfig.model_validate({"meshing": {"tool": "mock", "target_quality": 0.75}})
    result = MeshAgent().run(_base_state(), config, tmp_path)

    assert result.status == "success"
    assert result.updates["mesh_state"]["backend"] == "mock"
    mesh_path = tmp_path / result.updates["mesh_state"]["mesh_path"]
    assert mesh_path.exists()


def test_mesh_agent_reports_unavailable_gmsh_backend(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("plugins.gmsh.backend.GmshMeshingBackend._python_api_available", lambda self: False)
    monkeypatch.setattr("plugins.gmsh.backend.GmshMeshingBackend._executable_available", lambda self: False)
    config = WorkflowConfig.model_validate({"meshing": {"tool": "gmsh"}})
    result = MeshAgent().run(_base_state(), config, tmp_path)

    assert result.status == "failure"
    assert result.diagnostics[0].code == "mesh.backend_unavailable"


def test_mesh_agent_rejects_unsupported_gmsh_geometry(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("plugins.gmsh.backend.GmshMeshingBackend._python_api_available", lambda self: True)
    monkeypatch.setattr("plugins.gmsh.backend.GmshMeshingBackend._executable_available", lambda self: False)
    geometry_path = tmp_path / "shape.geo"
    geometry_path.write_text("dummy")
    config = WorkflowConfig.model_validate(
        {
            "meshing": {
                "tool": "gmsh",
                "geometry_input_path": "shape.geo",
            }
        }
    )

    result = MeshAgent().run(_base_state(), config, tmp_path)

    assert result.status == "failure"
    assert result.diagnostics[0].code == "mesh.unsupported_geometry_input"


def test_artifact_store_preserves_existing_mesh_files(tmp_path: Path) -> None:
    run_root = tmp_path
    state = _base_state()
    artifact_path = run_root / "results" / state.run_id / "mesh" / "example.msh"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("mesh-data")
    artifact = ArtifactRecord(
        name="mesh-output",
        path=f"results/{state.run_id}/mesh/example.msh",
        kind="mesh_file",
        metadata={"backend": "mock"},
    )

    ArtifactStore().record(run_root, state, [artifact])

    assert artifact_path.read_text() == "mesh-data"
    metadata_path = artifact_path.with_name(f"{artifact_path.name}.metadata.txt")
    assert metadata_path.exists()


def test_parse_and_write_bdf_for_simple_shell_mesh(tmp_path: Path) -> None:
    mesh_path = tmp_path / "shell.msh"
    mesh_path.write_text(
        _msh_text(
            physical_names=['2 10 "skin"'],
            nodes=[
                "1 0 0 0",
                "2 1 0 0",
                "3 1 1 0",
                "4 0 1 0",
            ],
            elements=[
                "1 2 2 10 100 1 2 3",
                "2 3 2 10 100 1 3 4 2",
            ],
        )
    )

    mesh = parse_gmsh_msh2(mesh_path)
    bdf_path = write_bdf(mesh, tmp_path / "shell.bdf")
    text = bdf_path.read_text()

    assert "$ REGION pid=1 gmsh_id=10 kind=shell name=skin" in text
    assert "MAT1,1,1.0,0.3,0.0" in text
    assert "PSHELL,1,1,1.0" in text
    assert "GRID,1,,0.0,0.0,0.0" in text
    assert "CTRIA3,1,1,1,2,3" in text
    assert "CQUAD4,2,1,1,3,4,2" in text


def test_parse_and_write_bdf_for_simple_solid_mesh(tmp_path: Path) -> None:
    mesh_path = tmp_path / "solid.msh"
    mesh_path.write_text(
        _msh_text(
            physical_names=['3 20 "block"'],
            nodes=[
                "1 0 0 0",
                "2 1 0 0",
                "3 1 1 0",
                "4 0 1 0",
                "5 0 0 1",
                "6 1 0 1",
                "7 1 1 1",
                "8 0 1 1",
            ],
            elements=[
                "1 4 2 20 200 1 2 3 5",
                "2 5 2 20 200 1 2 3 4 5 6 7 8",
            ],
        )
    )

    mesh = parse_gmsh_msh2(mesh_path)
    bdf_path = write_bdf(mesh, tmp_path / "solid.bdf")
    text = bdf_path.read_text()

    assert "$ REGION pid=1 gmsh_id=20 kind=solid name=block" in text
    assert "PSOLID,1,1" in text
    assert "CTETRA,1,1,1,2,3,5" in text
    assert "CHEXA,2,1,1,2,3,4,5,6,7,8" in text


def test_multiple_physical_groups_get_deterministic_pid_assignment(tmp_path: Path) -> None:
    mesh_path = tmp_path / "regions.msh"
    mesh_path.write_text(
        _msh_text(
            physical_names=['2 20 "spar"', '2 10 "skin"'],
            nodes=[
                "1 0 0 0",
                "2 1 0 0",
                "3 1 1 0",
                "4 0 1 0",
                "5 2 0 0",
            ],
            elements=[
                "2 2 2 20 200 2 5 3",
                "1 2 2 10 100 1 2 3",
            ],
        )
    )

    mesh = parse_gmsh_msh2(mesh_path)
    bdf_path = write_bdf(mesh, tmp_path / "regions.bdf")
    text = bdf_path.read_text()

    assert "$ REGION pid=1 gmsh_id=10 kind=shell name=skin" in text
    assert "$ REGION pid=2 gmsh_id=20 kind=shell name=spar" in text
    assert "CTRIA3,1,1,1,2,3" in text
    assert "CTRIA3,2,2,2,5,3" in text


def test_unsupported_element_type_fails_clearly(tmp_path: Path) -> None:
    mesh_path = tmp_path / "unsupported.msh"
    mesh_path.write_text(
        _msh_text(
            physical_names=[],
            nodes=[
                "1 0 0 0",
                "2 1 0 0",
                "3 1 1 0",
                "4 0 1 0",
                "5 0 0 1",
                "6 1 0 1",
            ],
            elements=["1 6 2 30 300 1 2 3 4 5 6"],
        )
    )

    try:
        parse_gmsh_msh2(mesh_path)
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected unsupported element type failure")

    assert "Unsupported gmsh element types for BDF export" in message
    assert "type 6 (1 elements)" in message


def test_unassigned_elements_export_to_unassigned_region(tmp_path: Path) -> None:
    mesh_path = tmp_path / "unassigned.msh"
    mesh_path.write_text(
        _msh_text(
            physical_names=[],
            nodes=[
                "1 0 0 0",
                "2 1 0 0",
                "3 1 1 0",
            ],
            elements=["1 2 2 0 100 1 2 3"],
        )
    )

    mesh = parse_gmsh_msh2(mesh_path)
    bdf_path = write_bdf(mesh, tmp_path / "unassigned.bdf")
    text = bdf_path.read_text()

    assert "$ REGION pid=1 gmsh_id=none kind=shell name=UNASSIGNED" in text
    assert "PSHELL,1,1,1.0" in text
    assert "CTRIA3,1,1,1,2,3" in text


def test_mixed_shell_and_solid_regions_export_successfully(tmp_path: Path) -> None:
    mesh_path = tmp_path / "mixed.msh"
    mesh_path.write_text(
        _msh_text(
            physical_names=['2 10 "skin"', '3 20 "core"'],
            nodes=[
                "1 0 0 0",
                "2 1 0 0",
                "3 1 1 0",
                "4 0 1 0",
                "5 0 0 1",
                "6 1 0 1",
                "7 1 1 1",
                "8 0 1 1",
            ],
            elements=[
                "1 2 2 10 100 1 2 3",
                "2 5 2 20 200 1 2 3 4 5 6 7 8",
            ],
        )
    )

    mesh = parse_gmsh_msh2(mesh_path)
    bdf_path = write_bdf(mesh, tmp_path / "mixed.bdf")
    text = bdf_path.read_text()

    assert "PSOLID,1,1" in text
    assert "PSHELL,2,1,1.0" in text
    assert "CTRIA3,1,2,1,2,3" in text
    assert "CHEXA,2,1,1,2,3,4,5,6,7,8" in text


def test_mixed_shell_and_solid_elements_in_one_group_fail(tmp_path: Path) -> None:
    mesh_path = tmp_path / "bad-mixed.msh"
    mesh_path.write_text(
        _msh_text(
            physical_names=['2 10 "wing_skin"'],
            nodes=[
                "1 0 0 0",
                "2 1 0 0",
                "3 1 1 0",
                "4 0 1 0",
                "5 0 0 1",
                "6 1 0 1",
                "7 1 1 1",
                "8 0 1 1",
            ],
            elements=[
                "1 2 2 10 100 1 2 3",
                "2 5 2 10 200 1 2 3 4 5 6 7 8",
            ],
        )
    )

    try:
        parse_gmsh_msh2(mesh_path)
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected mixed-region failure")

    assert "Physical group 'wing_skin' mixes shell and solid elements" in message


def test_gmsh_backend_preserves_existing_msh_export(tmp_path: Path, monkeypatch) -> None:
    geometry_path = tmp_path / "shape.step"
    geometry_path.write_text("dummy")
    backend = GmshMeshingBackend(executable="/usr/bin/true")

    def fake_run(command: list[str], capture_output: bool, text: bool, check: bool) -> subprocess.CompletedProcess[str]:
        assert command[-2] == "-o"
        output_path = Path(command[-1])
        output_path.write_text(
            _msh_text(
                physical_names=['2 10 "skin"'],
                nodes=["1 0 0 0", "2 1 0 0", "3 1 1 0"],
                elements=["1 2 2 10 100 1 2 3"],
            )
        )
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr("plugins.gmsh.backend.subprocess.run", fake_run)

    result = backend.generate_mesh(
        MeshingRequest(
            geometry_input_path=geometry_path,
            mesh_directory=tmp_path,
            log_directory=tmp_path,
            run_id="mesh-run",
            output_format="msh",
            target_quality=0.75,
        )
    )

    assert result.mesh_path == tmp_path / "shape.msh"
    assert result.mesh_path.read_text().startswith("$MeshFormat")
    assert result.metadata["mesh_format"] == "msh"
    assert result.element_count == 0


def test_gmsh_backend_meshes_largest_planar_face_via_python_api(
    tmp_path: Path,
    monkeypatch,
) -> None:
    geometry_path = tmp_path / "shape.stp"
    geometry_path.write_text("dummy")
    backend = GmshMeshingBackend()
    fake_gmsh = _FakeGmsh(tmp_path)
    monkeypatch.setattr(backend, "_load_gmsh_python_module", lambda: fake_gmsh)

    result = backend.generate_mesh(
        MeshingRequest(
            geometry_input_path=geometry_path,
            mesh_directory=tmp_path,
            log_directory=tmp_path,
            run_id="mesh-run",
            mesh_dimension=2,
            step_face_selector="largest_planar",
            output_format="bdf",
            target_quality=0.75,
        )
    )

    assert result.mesh_path == tmp_path / "shape.bdf"
    assert (tmp_path / "shape.msh").exists()
    assert result.metadata["meshing_dimension"] == 2
    assert result.metadata["step_face_selector"] == "largest_planar"
    assert fake_gmsh.model.selected_physical_tags == [10]
    assert fake_gmsh.model.mesh.generated_dimension == 2


def _msh_text(
    *,
    physical_names: list[str],
    nodes: list[str],
    elements: list[str],
) -> str:
    lines = [
        "$MeshFormat",
        "2.2 0 8",
        "$EndMeshFormat",
    ]
    if physical_names:
        lines.extend(
            [
                "$PhysicalNames",
                str(len(physical_names)),
                *physical_names,
                "$EndPhysicalNames",
            ]
        )
    lines.extend(
        [
            "$Nodes",
            str(len(nodes)),
            *nodes,
            "$EndNodes",
            "$Elements",
            str(len(elements)),
            *elements,
            "$EndElements",
            "",
        ]
    )
    return "\n".join(lines)


class _FakeGmsh:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.option = _FakeOption()
        self.model = _FakeModel()

    def initialize(self) -> None:
        return None

    def finalize(self) -> None:
        return None

    def clear(self) -> None:
        return None

    def write(self, path: str) -> None:
        Path(path).write_text(
            _msh_text(
                physical_names=['2 1 "selected_face"'],
                nodes=[
                    "1 0 0 0",
                    "2 1 0 0",
                    "3 0 1 0",
                ],
                elements=["1 2 2 1 100 1 2 3"],
            )
        )


class _FakeOption:
    def setNumber(self, name: str, value: float) -> None:
        del name, value


class _FakeMesh:
    def __init__(self) -> None:
        self.generated_dimension: int | None = None

    def generate(self, dimension: int) -> None:
        self.generated_dimension = dimension


class _FakeOcc:
    def importShapes(self, path: str) -> None:
        del path

    def synchronize(self) -> None:
        return None

    def getMass(self, dim: int, tag: int) -> float:
        del dim
        return {10: 8.0, 11: 5.0}[tag]


class _FakeModel:
    def __init__(self) -> None:
        self.occ = _FakeOcc()
        self.mesh = _FakeMesh()
        self.selected_physical_tags: list[int] | None = None

    def add(self, name: str) -> None:
        del name

    def getEntities(self, dim: int | None = None) -> list[tuple[int, int]]:
        if dim == 2:
            return [(2, 10), (2, 11), (2, 12)]
        return [(0, 1), (0, 2), (1, 3), (1, 4), (2, 10), (2, 11), (2, 12), (3, 13)]

    def getType(self, dim: int, tag: int) -> str:
        del dim
        return {10: "Plane Surface", 11: "Plane Surface", 12: "BSpline Surface"}[tag]

    def addPhysicalGroup(self, dim: int, tags: list[int], physical_id: int) -> int:
        del dim
        self.selected_physical_tags = list(tags)
        return physical_id

    def setPhysicalName(self, dim: int, physical_id: int, name: str) -> None:
        del dim, physical_id, name

    def getBoundary(
        self,
        dim_tags: list[tuple[int, int]],
        *,
        combined: bool,
        oriented: bool,
        recursive: bool,
    ) -> list[tuple[int, int]]:
        del dim_tags, combined, oriented, recursive
        return [(1, 3), (1, 4), (0, 1), (0, 2)]

    def setVisibility(
        self,
        dim_tags: list[tuple[int, int]],
        value: int,
        *,
        recursive: bool = False,
    ) -> None:
        del dim_tags, value, recursive
