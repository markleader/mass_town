import json
from math import pi
from pathlib import Path
from types import SimpleNamespace

import pytest

from mass_town.agents.fea_agent import FEAAgent
from mass_town.config import WorkflowConfig
from mass_town.design_variables import DesignVariableType
from mass_town.disciplines.fea import (
    FEABackend,
    FEABackendError,
    FEALoadCaseResult,
    FEARequest,
    FEAResult,
)
from mass_town.disciplines.fea.registry import BACKEND_LOADERS, resolve_fea_backend
from mass_town.models.design_state import DesignState
from plugins.tacs.backend import TacsFEABackend
from plugins.tacs.shell_model import (
    describe_boundary_loops,
    distribute_force_to_nodes,
    find_boundary_loops,
    select_boundary_loop,
)


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

        summary_path = self.result_path or request.report_directory / "stub-fea.json"
        summary_path.write_text('{"max_stress": 120.0}\n')
        load_cases: dict[str, FEALoadCaseResult] = {}
        case_result_files: list[Path] = []
        requested_case_names = list(request.load_cases) or [request.case_name]
        for case_name in requested_case_names:
            case_summary_path = (
                summary_path
                if len(requested_case_names) == 1
                else request.report_directory / f"stub-fea-{case_name}.json"
            )
            if case_summary_path != summary_path:
                case_summary_path.write_text(f'{{"case_name": "{case_name}", "max_stress": 120.0}}\n')
            load_cases[case_name] = FEALoadCaseResult(
                passed=True,
                result_files=[case_summary_path],
                mass=24.0,
                max_stress=120.0,
                displacement_norm=0.0125,
                metadata={"case_name": case_name, "failure_index": 2.0 / 3.0},
                analysis_seconds=0.25,
            )
            case_result_files.append(case_summary_path)
        return FEAResult(
            backend_name=self.name,
            passed=True,
            mass=24.0,
            max_stress=120.0,
            displacement_norm=0.0125,
            result_files=[summary_path, *case_result_files] if len(load_cases) > 1 else [summary_path],
            metadata={"case_name": request.case_name, "failure_index": 2.0 / 3.0},
            load_cases=load_cases,
            worst_case_name=request.case_name,
            analysis_seconds=0.25 * len(load_cases),
        )


class MultiCaseStubFEABackend(FEABackend):
    name = "tacs"

    def __init__(self) -> None:
        self.last_request: FEARequest | None = None

    def is_available(self) -> bool:
        return True

    def availability_reason(self) -> str | None:
        return None

    def run_analysis(self, request: FEARequest) -> FEAResult:
        self.last_request = request
        if request.model_input_path is None:
            raise ValueError("The tacs backend requires a BDF model input path.")

        overall_summary_path = request.report_directory / "multi-case-fea.json"
        overall_summary_path.write_text('{"worst_case_name": "center_bending"}\n')

        load_cases: dict[str, FEALoadCaseResult] = {}
        stresses = {
            "center_shear": 90.0,
            "center_bending": 150.0,
        }
        for case_name in request.load_cases:
            summary_path = request.report_directory / f"multi-case-{case_name}.json"
            summary_path.write_text(
                f'{{"case_name": "{case_name}", "max_stress": {stresses[case_name]:.1f}}}\n'
            )
            load_cases[case_name] = FEALoadCaseResult(
                passed=True,
                result_files=[summary_path],
                mass=24.0,
                max_stress=stresses[case_name],
                displacement_norm=0.01 if case_name == "center_shear" else 0.02,
                metadata={"case_name": case_name},
                analysis_seconds=0.4 if case_name == "center_shear" else 0.6,
            )

        return FEAResult(
            backend_name=self.name,
            passed=True,
            mass=24.0,
            max_stress=150.0,
            displacement_norm=0.02,
            result_files=[overall_summary_path, *(case.result_files[0] for case in load_cases.values())],
            metadata={"case_name": "center_bending"},
            load_cases=load_cases,
            worst_case_name="center_bending",
            analysis_seconds=1.0,
        )


class FakeProblem:
    def __init__(self) -> None:
        self.added_loads: list[tuple[list[int], list[list[float]], bool]] = []
        self.function_registrations: list[tuple[str, object, dict[str, float]]] = []
        self.solved = False

    def addFunction(self, name: str, function: object, **kwargs: float) -> None:
        self.function_registrations.append((name, function, kwargs))

    def addLoadToNodes(
        self,
        node_ids: list[int],
        load_vectors: list[list[float]],
        *,
        nastranOrdering: bool,
    ) -> None:
        self.added_loads.append((list(node_ids), load_vectors, nastranOrdering))

    def solve(self) -> None:
        self.solved = True

    def evalFunctions(self, values: dict[str, float]) -> None:
        values["mass"] = 24.0
        values["ks_vmfailure"] = 0.5


class FakeBucklingProblem(FakeProblem):
    def __init__(self, case_name: str, eigenvalues: list[float] | None = None) -> None:
        super().__init__()
        self.case_name = case_name
        self.eigenvalues = list(eigenvalues or [3.0, 7.5, 10.0])

    def evalFunctions(self, values: dict[str, float]) -> None:
        for mode, value in enumerate(self.eigenvalues):
            values[f"{self.case_name}_eigsb.{mode}"] = value


class FakeModalProblem(FakeProblem):
    def __init__(self, case_name: str, eigenvalues: list[float] | None = None) -> None:
        super().__init__()
        self.case_name = case_name
        self.eigenvalues = list(eigenvalues or [(2.0 * pi * 8.0) ** 2, (2.0 * pi * 12.0) ** 2])

    def evalFunctions(self, values: dict[str, float]) -> None:
        for mode, value in enumerate(self.eigenvalues):
            values[f"{self.case_name}_eigsm.{mode}"] = value


class FakeAssembler:
    def __init__(self, bdf_info: object) -> None:
        self.bdf_info = bdf_info
        self.problem = FakeProblem()
        self.problems: dict[str, FakeProblem] = {}
        self.buckling_problems: dict[str, FakeBucklingProblem] = {}
        self.modal_problems: dict[str, FakeModalProblem] = {}
        self.initialized = False

    def initialize(self, callback: object | None = None) -> None:
        self.initialized = True
        self.callback = callback

    def createStaticProblem(self, case_name: str) -> FakeProblem:
        self.case_name = case_name
        problem = FakeProblem()
        self.problems[case_name] = problem
        if len(self.problems) == 1:
            self.problem = problem
        return problem

    def createBucklingProblem(
        self,
        case_name: str,
        sigma: float,
        numEigs: int,
    ) -> FakeBucklingProblem:
        del sigma
        problem = FakeBucklingProblem(case_name, [float(index + 1) for index in range(numEigs)])
        self.buckling_problems[case_name] = problem
        return problem

    def createModalProblem(
        self,
        case_name: str,
        sigma: float,
        numEigs: int,
    ) -> FakeModalProblem:
        del sigma
        problem = FakeModalProblem(
            case_name,
            [(2.0 * pi * float(index + 1)) ** 2 for index in range(numEigs)],
        )
        self.modal_problems[case_name] = problem
        return problem


class FakeBDFInfo:
    def __init__(
        self,
        node_positions: dict[int, tuple[float, float, float]],
        elements: list[tuple[str, tuple[int, ...]]],
        *,
        spcs: dict[int, object] | None = None,
    ) -> None:
        self.nodes = {
            node_id: SimpleNamespace(xyz=position) for node_id, position in node_positions.items()
        }
        self.elements = {
            element_id: SimpleNamespace(type=kind, nodes=node_ids, pid=1)
            for element_id, (kind, node_ids) in enumerate(elements, start=1)
        }
        self.spcs = spcs or {}
        self.spcadds = {}
        self.added_spcs: list[tuple[int, str, list[int]]] = []

    def add_spc1(self, sid: int, dof: str, node_ids: list[int]) -> None:
        self.added_spcs.append((sid, dof, list(node_ids)))


def _shell_node_positions_and_elements() -> tuple[
    dict[int, tuple[float, float, float]],
    list[tuple[str, tuple[int, ...]]],
]:
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
    return node_positions, elements


def _shell_request(
    tmp_path: Path,
    *,
    shell_setup: dict[str, object] | None = None,
    loads: dict[str, float] | None = None,
) -> FEARequest:
    model_path = tmp_path / "shell_model.bdf"
    model_path.write_text("CEND\nBEGIN BULK\nENDDATA\n")
    return FEARequest(
        model_input_path=model_path,
        report_directory=tmp_path,
        log_directory=tmp_path,
        solution_directory=tmp_path,
        run_id="shell-run",
        design_variables={"thickness": 0.8},
        loads=loads or {"force": 120.0},
        allowable_stress=180.0,
        shell_setup=shell_setup,
    )


def _solid_node_positions_and_elements() -> tuple[
    dict[int, tuple[float, float, float]],
    list[tuple[str, tuple[int, ...]]],
]:
    node_positions = {
        1: (0.0, 0.0, 0.0),
        2: (1.0, 0.0, 0.0),
        3: (1.0, 1.0, 0.0),
        4: (0.0, 1.0, 0.0),
        5: (0.0, 0.0, 1.0),
        6: (1.0, 0.0, 1.0),
        7: (1.0, 1.0, 1.0),
        8: (0.0, 1.0, 1.0),
    }
    return node_positions, [("CHEXA", (1, 2, 3, 4, 5, 6, 7, 8))]


def _solid_request(
    tmp_path: Path,
    *,
    solid_setup: dict[str, object] | None = None,
    loads: dict[str, float] | None = None,
) -> FEARequest:
    model_path = tmp_path / "solid_model.bdf"
    model_path.write_text("CEND\nBEGIN BULK\nENDDATA\n")
    return FEARequest(
        model_input_path=model_path,
        report_directory=tmp_path,
        log_directory=tmp_path,
        solution_directory=tmp_path,
        run_id="solid-run",
        loads=loads or {"force": 120.0},
        allowable_stress=180.0,
        solid_setup=solid_setup,
    )


def _base_state() -> DesignState:
    return DesignState(
        run_id="fea-run",
        problem_name="structural",
        design_variables={"thickness": 0.8},
        loads={"force": 120.0},
        constraints={"max_stress": 180.0},
        mesh_state={"backend": "mock", "mesh_path": "results/fea-run/mesh/mesh.msh", "quality": 0.9},
    )


def test_config_parses_fea_settings() -> None:
    config = WorkflowConfig.model_validate(
        {
            "fea": {
                "tool": "tacs",
                "model_input_path": "analysis/model.bdf",
                "case_name": "wing",
                "settings": {"tol": 1e-6, "solver": "gmres"},
            }
        }
    )

    assert config.fea.tool == "tacs"
    assert config.fea.model_input_path == "analysis/model.bdf"
    assert config.fea.case_name == "wing"
    assert config.fea.write_solution is True
    assert config.fea.settings == {"tol": 1e-06, "solver": "gmres"}


def test_config_parses_buckling_settings() -> None:
    config = WorkflowConfig.model_validate(
        {
            "fea": {
                "tool": "tacs",
                "model_input_path": "analysis/model.bdf",
                "analysis_type": "buckling",
                "buckling_setup": {
                    "sigma": 5.0,
                    "num_eigenvalues": 4,
                },
            }
        }
    )

    assert config.fea.analysis_type == "buckling"
    assert config.fea.buckling_setup is not None
    assert config.fea.buckling_setup.sigma == 5.0
    assert config.fea.buckling_setup.num_eigenvalues == 4


def test_config_parses_modal_settings() -> None:
    config = WorkflowConfig.model_validate(
        {
            "fea": {
                "tool": "tacs",
                "model_input_path": "analysis/model.bdf",
                "analysis_type": "modal",
                "modal_setup": {
                    "sigma": 20.0,
                    "num_eigenvalues": 6,
                },
            }
        }
    )

    assert config.fea.analysis_type == "modal"
    assert config.fea.modal_setup is not None
    assert config.fea.modal_setup.sigma == 20.0
    assert config.fea.modal_setup.num_eigenvalues == 6


def test_config_parses_shell_setup_settings() -> None:
    config = WorkflowConfig.model_validate(
        {
            "fea": {
                "tool": "tacs",
                "shell_setup": {
                    "node_sets": {
                        "left_bore": {
                            "selector": "boundary_loop",
                            "family": "inner",
                            "order_by": "centroid_x",
                            "index": 0,
                        }
                    },
                    "boundary_conditions": [{"node_set": "left_bore", "dof": "123456"}],
                    "loads": [
                        {
                            "node_set": "left_bore",
                            "load_key": "force",
                            "direction": [0.0, -1.0, 0.0],
                            "distribution": "equal",
                        }
                    ],
                },
            }
        }
    )

    assert config.fea.shell_setup is not None
    assert config.fea.shell_setup.node_sets["left_bore"].selector == "boundary_loop"
    assert config.fea.shell_setup.loads[0].direction == (0.0, -1.0, 0.0)


def test_config_parses_solid_setup_settings() -> None:
    config = WorkflowConfig.model_validate(
        {
            "fea": {
                "tool": "tacs",
                "solid_setup": {
                    "node_sets": {
                        "fixed_face": {
                            "selector": "bounding_box_extreme",
                            "axis": "x",
                            "extreme": "min",
                        }
                    },
                    "boundary_conditions": [{"node_set": "fixed_face", "dof": "123456"}],
                    "loads": [
                        {
                            "node_set": "fixed_face",
                            "load_key": "force",
                            "direction": [0.0, -1.0, 0.0],
                            "distribution": "equal",
                        }
                    ],
                },
            }
        }
    )

    assert config.fea.solid_setup is not None
    assert config.fea.solid_setup.node_sets["fixed_face"].axis == "x"
    assert config.fea.solid_setup.node_sets["fixed_face"].extreme == "min"


def test_config_parses_design_variable_settings() -> None:
    config = WorkflowConfig.model_validate(
        {
            "design_variables": [
                {
                    "id": "thickness",
                    "name": "Global Thickness",
                    "type": "scalar_thickness",
                    "initial_value": 0.8,
                    "bounds": {"lower": 0.1, "upper": 2.0},
                    "active": True,
                }
            ]
        }
    )

    assert len(config.design_variables) == 1
    assert config.design_variables[0].id == "thickness"
    assert config.design_variables[0].type == DesignVariableType.scalar_thickness


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
    assert result.updates["analysis_state"]["mass"] == 24.0
    assert result.updates["analysis_state"]["max_stress"] == 120.0
    assert result.updates["analysis_state"]["displacement_norm"] == 0.0125
    assert result.updates["analysis_state"]["result_path"] == "results/fea-run/reports/stub-fea.json"
    assert result.updates["analysis_state"]["worst_case_name"] == "static"
    assert "static" in result.updates["analysis_state"]["load_cases"]
    assert result.artifacts[0].metadata["backend"] == "tacs"
    assert result.artifacts[0].metadata["mass"] == 24.0
    assert result.artifacts[0].metadata["failure_index"] == 2.0 / 3.0
    assert backend.last_request is not None
    assert list(backend.last_request.load_cases) == ["static"]
    assert backend.last_request.load_cases["static"].loads == {"force": 120.0}


def test_fea_agent_builds_multi_case_request_and_rolls_up_worst_case(
    monkeypatch,
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "analysis" / "model.bdf"
    model_path.parent.mkdir(parents=True)
    model_path.write_text("CEND\nBEGIN BULK\nENDDATA\n")
    backend = MultiCaseStubFEABackend()
    monkeypatch.setitem(BACKEND_LOADERS, "tacs", lambda: backend)
    config = WorkflowConfig.model_validate(
        {"fea": {"tool": "tacs", "model_input_path": "analysis/model.bdf"}}
    )
    state = DesignState(
        run_id="multi-case-run",
        problem_name="structural",
        design_variables={"thickness": 0.8},
        load_cases={
            "center_shear": {"loads": {"force_x": 60.0}},
            "center_bending": {"loads": {"force_z": 120.0}},
        },
        constraints={"max_stress": 180.0},
    )

    result = FEAAgent().run(state, config, tmp_path)

    assert result.status == "success"
    assert backend.last_request is not None
    assert list(backend.last_request.load_cases) == ["center_shear", "center_bending"]
    assert backend.last_request.load_cases["center_shear"].loads == {"force_x": 60.0}
    assert backend.last_request.load_cases["center_bending"].loads == {"force_z": 120.0}
    assert backend.last_request.design_variables == {"thickness": 0.8}
    assert result.updates["analysis_state"]["worst_case_name"] == "center_bending"
    assert result.updates["analysis_state"]["max_stress"] == 150.0
    assert result.updates["analysis_state"]["analysis_seconds"] == 1.0
    assert result.updates["analysis_state"]["load_cases"]["center_shear"]["max_stress"] == 90.0
    assert result.updates["analysis_state"]["load_cases"]["center_bending"]["max_stress"] == 150.0
    assert result.artifacts[0].metadata["worst_case_name"] == "center_bending"


def test_fea_agent_uses_aggregated_stress_for_pass_fail(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "analysis" / "model.bdf"
    model_path.parent.mkdir(parents=True)
    model_path.write_text("CEND\nBEGIN BULK\nENDDATA\n")

    class AggregatedStressStubFEABackend(FEABackend):
        name = "tacs"

        def is_available(self) -> bool:
            return True

        def availability_reason(self) -> str | None:
            return None

        def run_analysis(self, request: FEARequest) -> FEAResult:
            quality_summary_path = request.report_directory / "stress_aggregation_summary.json"
            quality_summary_path.write_text('{"aggregated_stress_value": 170.0}\n')
            load_cases = {
                "center_shear": FEALoadCaseResult(
                    passed=True,
                    result_files=[request.report_directory / "center-shear.json"],
                    mass=24.0,
                    max_stress=150.0,
                    displacement_norm=0.01,
                    analysis_seconds=0.4,
                ),
                "center_bending": FEALoadCaseResult(
                    passed=True,
                    result_files=[request.report_directory / "center-bending.json"],
                    mass=24.0,
                    max_stress=170.0,
                    displacement_norm=0.02,
                    analysis_seconds=0.6,
                ),
            }
            for case_result in load_cases.values():
                case_result.result_files[0].write_text('{"ok": true}\n')

            overall_summary_path = request.report_directory / "multi-case-fea.json"
            overall_summary_path.write_text('{"worst_case_name": "center_bending"}\n')
            return FEAResult(
                backend_name=self.name,
                passed=True,
                mass=24.0,
                max_stress=170.0,
                displacement_norm=0.02,
                result_files=[
                    overall_summary_path,
                    *(case.result_files[0] for case in load_cases.values()),
                    quality_summary_path,
                ],
                load_cases=load_cases,
                worst_case_name="center_bending",
                aggregation_quality_summary_path=quality_summary_path,
                analysis_seconds=1.0,
            )

    backend = AggregatedStressStubFEABackend()
    monkeypatch.setitem(BACKEND_LOADERS, "tacs", lambda: backend)
    config = WorkflowConfig.model_validate(
        {"fea": {"tool": "tacs", "model_input_path": "analysis/model.bdf"}}
    )
    state = DesignState(
        run_id="aggregated-run",
        problem_name="structural",
        design_variables={"thickness": 0.8},
        load_cases={
            "center_shear": {"loads": {"force_x": 60.0}},
            "center_bending": {"loads": {"force_z": 120.0}},
        },
        constraints={
            "max_stress": 180.0,
            "aggregated_stress": {
                "method": "ks",
                "allowable": 165.0,
            },
        },
    )

    result = FEAAgent().run(state, config, tmp_path)

    assert result.status == "failure"
    assert result.diagnostics[0].code == "analysis.aggregated_stress_exceeded"
    aggregated_stress = result.updates["analysis_state"]["aggregated_stress"]
    assert aggregated_stress["method"] == "ks"
    assert aggregated_stress["allowable"] == 165.0
    assert aggregated_stress["value"] == pytest.approx(170.0)
    assert aggregated_stress["controlling_case"] == "center_bending"
    assert (
        aggregated_stress["quality_summary_path"]
        == "results/aggregated-run/reports/stress_aggregation_summary.json"
    )
    assert result.updates["analysis_state"]["worst_case_name"] == "center_bending"
    assert result.updates["analysis_state"]["max_stress"] == 170.0


def test_fea_agent_uses_minimum_buckling_load_factor_for_pass_fail(
    monkeypatch,
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "analysis" / "model.bdf"
    model_path.parent.mkdir(parents=True)
    model_path.write_text("CEND\nBEGIN BULK\nENDDATA\n")

    class BucklingStubFEABackend(FEABackend):
        name = "tacs"

        def is_available(self) -> bool:
            return True

        def availability_reason(self) -> str | None:
            return None

        def run_analysis(self, request: FEARequest) -> FEAResult:
            summary_path = request.report_directory / "buckling-fea.json"
            summary_path.write_text('{"worst_case_name": "maneuver"}\n')
            load_cases = {
                "gust": FEALoadCaseResult(
                    passed=True,
                    result_files=[request.report_directory / "gust.json"],
                    mass=20.0,
                    max_stress=90.0,
                    displacement_norm=0.01,
                    analysis_type="buckling",
                    eigenvalues=[3.2, 5.4],
                    critical_eigenvalue=3.2,
                    analysis_seconds=0.4,
                ),
                "maneuver": FEALoadCaseResult(
                    passed=True,
                    result_files=[request.report_directory / "maneuver.json"],
                    mass=20.0,
                    max_stress=110.0,
                    displacement_norm=0.02,
                    analysis_type="buckling",
                    eigenvalues=[2.1, 4.8],
                    critical_eigenvalue=2.1,
                    analysis_seconds=0.6,
                ),
            }
            for case_result in load_cases.values():
                case_result.result_files[0].write_text('{"ok": true}\n')
            return FEAResult(
                backend_name=self.name,
                passed=True,
                mass=20.0,
                max_stress=110.0,
                displacement_norm=0.02,
                analysis_type="buckling",
                eigenvalues=[2.1, 4.8],
                critical_eigenvalue=2.1,
                result_files=[summary_path, *(case.result_files[0] for case in load_cases.values())],
                load_cases=load_cases,
                worst_case_name="maneuver",
                analysis_seconds=1.0,
            )

    backend = BucklingStubFEABackend()
    monkeypatch.setitem(BACKEND_LOADERS, "tacs", lambda: backend)
    config = WorkflowConfig.model_validate(
        {
            "fea": {
                "tool": "tacs",
                "model_input_path": "analysis/model.bdf",
                "analysis_type": "buckling",
            }
        }
    )
    state = DesignState(
        run_id="buckling-run",
        problem_name="structural",
        design_variables={"thickness": 0.8},
        load_cases={
            "gust": {"loads": {"force_x": 60.0}},
            "maneuver": {"loads": {"force_x": 120.0}},
        },
        constraints={
            "max_stress": 180.0,
            "minimum_buckling_load_factor": {
                "mode": 0,
                "minimum": 2.5,
            },
        },
    )

    result = FEAAgent().run(state, config, tmp_path)

    assert result.status == "failure"
    assert result.diagnostics[0].code == "analysis.minimum_buckling_load_factor_not_met"
    assert result.updates["analysis_state"]["analysis_type"] == "buckling"
    assert result.updates["analysis_state"]["critical_eigenvalue"] == pytest.approx(2.1)
    assert result.updates["analysis_state"]["worst_case_name"] == "maneuver"
    minimum_buckling = result.updates["analysis_state"]["eigenvalue_constraints"][
        "minimum_buckling_load_factor"
    ]
    assert minimum_buckling["quantity"] == "buckling_load_factor"
    assert minimum_buckling["minimum"] == 2.5
    assert minimum_buckling["value"] == pytest.approx(2.1)
    assert minimum_buckling["controlling_case"] == "maneuver"


def test_fea_agent_uses_minimum_natural_frequency_for_pass_fail(
    monkeypatch,
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "analysis" / "model.bdf"
    model_path.parent.mkdir(parents=True)
    model_path.write_text("CEND\nBEGIN BULK\nENDDATA\n")

    class ModalStubFEABackend(FEABackend):
        name = "tacs"

        def is_available(self) -> bool:
            return True

        def availability_reason(self) -> str | None:
            return None

        def run_analysis(self, request: FEARequest) -> FEAResult:
            summary_path = request.report_directory / "modal-fea.json"
            summary_path.write_text('{"worst_case_name": "maneuver"}\n')
            load_cases = {
                "gust": FEALoadCaseResult(
                    passed=True,
                    result_files=[request.report_directory / "gust.json"],
                    mass=20.0,
                    analysis_type="modal",
                    eigenvalues=[(2.0 * pi * 12.0) ** 2, (2.0 * pi * 18.0) ** 2],
                    critical_eigenvalue=(2.0 * pi * 12.0) ** 2,
                    frequencies_hz=[12.0, 18.0],
                    critical_frequency_hz=12.0,
                    analysis_seconds=0.4,
                ),
                "maneuver": FEALoadCaseResult(
                    passed=True,
                    result_files=[request.report_directory / "maneuver.json"],
                    mass=20.0,
                    analysis_type="modal",
                    eigenvalues=[(2.0 * pi * 8.0) ** 2, (2.0 * pi * 16.0) ** 2],
                    critical_eigenvalue=(2.0 * pi * 8.0) ** 2,
                    frequencies_hz=[8.0, 16.0],
                    critical_frequency_hz=8.0,
                    analysis_seconds=0.6,
                ),
            }
            for case_result in load_cases.values():
                case_result.result_files[0].write_text('{"ok": true}\n')
            return FEAResult(
                backend_name=self.name,
                passed=True,
                mass=20.0,
                analysis_type="modal",
                eigenvalues=[(2.0 * pi * 8.0) ** 2, (2.0 * pi * 16.0) ** 2],
                critical_eigenvalue=(2.0 * pi * 8.0) ** 2,
                frequencies_hz=[8.0, 16.0],
                critical_frequency_hz=8.0,
                result_files=[summary_path, *(case.result_files[0] for case in load_cases.values())],
                load_cases=load_cases,
                worst_case_name="maneuver",
                analysis_seconds=1.0,
            )

    backend = ModalStubFEABackend()
    monkeypatch.setitem(BACKEND_LOADERS, "tacs", lambda: backend)
    config = WorkflowConfig.model_validate(
        {
            "fea": {
                "tool": "tacs",
                "model_input_path": "analysis/model.bdf",
                "analysis_type": "modal",
            }
        }
    )
    state = DesignState(
        run_id="modal-run",
        problem_name="structural",
        load_cases={
            "gust": {"loads": {}},
            "maneuver": {"loads": {}},
        },
        constraints={
            "minimum_natural_frequency_hz": {
                "mode": 0,
                "minimum": 10.0,
            },
        },
    )

    result = FEAAgent().run(state, config, tmp_path)

    assert result.status == "failure"
    assert result.diagnostics[0].code == "analysis.minimum_natural_frequency_not_met"
    assert result.updates["analysis_state"]["analysis_type"] == "modal"
    assert result.updates["analysis_state"]["critical_frequency_hz"] == pytest.approx(8.0)
    assert result.updates["analysis_state"]["frequencies_hz"] == pytest.approx([8.0, 16.0])
    assert result.updates["analysis_state"]["worst_case_name"] == "maneuver"
    minimum_frequency = result.updates["analysis_state"]["eigenvalue_constraints"][
        "minimum_natural_frequency_hz"
    ]
    assert minimum_frequency["quantity"] == "natural_frequency_hz"
    assert minimum_frequency["minimum"] == 10.0
    assert minimum_frequency["value"] == pytest.approx(8.0)
    assert minimum_frequency["controlling_case"] == "maneuver"


def test_fea_agent_forwards_shell_setup(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "analysis" / "model.bdf"
    model_path.parent.mkdir(parents=True)
    model_path.write_text("CEND\nBEGIN BULK\nENDDATA\n")
    backend = StubFEABackend()
    monkeypatch.setitem(BACKEND_LOADERS, "tacs", lambda: backend)
    config = WorkflowConfig.model_validate(
        {
            "fea": {
                "tool": "tacs",
                "model_input_path": "analysis/model.bdf",
                "shell_setup": {
                    "node_sets": {
                        "center_node": {
                            "selector": "closest_node_to_centroid",
                        }
                    },
                    "loads": [
                        {
                            "node_set": "center_node",
                            "load_key": "force",
                            "direction": [0.0, 0.0, 1.0],
                            "distribution": "equal",
                        }
                    ],
                },
            }
        }
    )

    result = FEAAgent().run(_base_state(), config, tmp_path)

    assert result.status == "success"
    assert backend.last_request is not None
    assert backend.last_request.shell_setup is not None
    assert backend.last_request.shell_setup.node_sets["center_node"].selector == (
        "closest_node_to_centroid"
    )


def test_fea_agent_forwards_buckling_settings(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "analysis" / "model.bdf"
    model_path.parent.mkdir(parents=True)
    model_path.write_text("CEND\nBEGIN BULK\nENDDATA\n")
    backend = StubFEABackend()
    monkeypatch.setitem(BACKEND_LOADERS, "tacs", lambda: backend)
    config = WorkflowConfig.model_validate(
        {
            "fea": {
                "tool": "tacs",
                "model_input_path": "analysis/model.bdf",
                "analysis_type": "buckling",
                "buckling_setup": {
                    "sigma": 6.0,
                    "num_eigenvalues": 3,
                },
            }
        }
    )

    result = FEAAgent().run(_base_state(), config, tmp_path)

    assert result.status == "success"
    assert backend.last_request is not None
    assert backend.last_request.analysis_type == "buckling"
    assert backend.last_request.buckling_setup is not None
    assert backend.last_request.buckling_setup.sigma == 6.0
    assert backend.last_request.buckling_setup.num_eigenvalues == 3


def test_fea_agent_forwards_modal_settings(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "analysis" / "model.bdf"
    model_path.parent.mkdir(parents=True)
    model_path.write_text("CEND\nBEGIN BULK\nENDDATA\n")
    backend = StubFEABackend()
    monkeypatch.setitem(BACKEND_LOADERS, "tacs", lambda: backend)
    config = WorkflowConfig.model_validate(
        {
            "fea": {
                "tool": "tacs",
                "model_input_path": "analysis/model.bdf",
                "analysis_type": "modal",
                "modal_setup": {
                    "sigma": 15.0,
                    "num_eigenvalues": 4,
                },
            }
        }
    )

    result = FEAAgent().run(_base_state(), config, tmp_path)

    assert result.status == "success"
    assert backend.last_request is not None
    assert backend.last_request.analysis_type == "modal"
    assert backend.last_request.modal_setup is not None
    assert backend.last_request.modal_setup.sigma == 15.0
    assert backend.last_request.modal_setup.num_eigenvalues == 4


def test_fea_agent_forwards_generic_solver_settings(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "analysis" / "model.bdf"
    model_path.parent.mkdir(parents=True)
    model_path.write_text("CEND\nBEGIN BULK\nENDDATA\n")
    backend = StubFEABackend()
    monkeypatch.setitem(BACKEND_LOADERS, "tacs", lambda: backend)
    config = WorkflowConfig.model_validate(
        {
            "fea": {
                "tool": "tacs",
                "model_input_path": "analysis/model.bdf",
                "settings": {
                    "tol": 1e-7,
                    "linear_solver": "gmres",
                },
            }
        }
    )

    result = FEAAgent().run(_base_state(), config, tmp_path)

    assert result.status == "success"
    assert backend.last_request is not None
    assert backend.last_request.settings == {"tol": 1e-07, "linear_solver": "gmres"}


def test_fea_agent_forwards_solid_setup(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "analysis" / "model.bdf"
    model_path.parent.mkdir(parents=True)
    model_path.write_text("CEND\nBEGIN BULK\nENDDATA\n")
    backend = StubFEABackend()
    monkeypatch.setitem(BACKEND_LOADERS, "tacs", lambda: backend)
    config = WorkflowConfig.model_validate(
        {
            "fea": {
                "tool": "tacs",
                "model_input_path": "analysis/model.bdf",
                "solid_setup": {
                    "node_sets": {
                        "fixed_face": {
                            "selector": "bounding_box_extreme",
                            "axis": "x",
                            "extreme": "min",
                        }
                    },
                    "boundary_conditions": [{"node_set": "fixed_face", "dof": "123456"}],
                },
            }
        }
    )

    result = FEAAgent().run(_base_state(), config, tmp_path)

    assert result.status == "success"
    assert backend.last_request is not None
    assert backend.last_request.solid_setup is not None
    assert backend.last_request.solid_setup.node_sets["fixed_face"].axis == "x"


def test_fea_agent_uses_generated_bdf_when_model_path_is_omitted(monkeypatch, tmp_path: Path) -> None:
    mesh_bdf = tmp_path / "results" / "fea-run" / "mesh" / "mesh.bdf"
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
        mesh_state={"backend": "gmsh", "mesh_path": "results/fea-run/mesh/mesh.bdf", "quality": 0.9},
    )

    result = FEAAgent().run(state, config, tmp_path)

    assert result.status == "success"
    assert backend.last_request is not None
    assert backend.last_request.model_input_path == mesh_bdf


def test_fea_agent_forwards_mapped_design_variables(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "analysis" / "model.bdf"
    model_path.parent.mkdir(parents=True)
    model_path.write_text(
        "\n".join(
            [
                "$ REGION pid=1 gmsh_id=10 kind=shell name=skin",
                "CEND",
                "BEGIN BULK",
                "CTRIA3,10,1,1,2,3",
                "ENDDATA",
            ]
        )
        + "\n"
    )
    backend = StubFEABackend()
    monkeypatch.setitem(BACKEND_LOADERS, "tacs", lambda: backend)
    config = WorkflowConfig.model_validate(
        {
            "fea": {"tool": "tacs", "model_input_path": "analysis/model.bdf"},
            "design_variables": [
                {
                    "id": "thickness",
                    "name": "Global Thickness",
                    "type": "scalar_thickness",
                    "initial_value": 0.8,
                    "bounds": {"lower": 0.1, "upper": 2.0},
                    "active": True,
                },
                {
                    "id": "skin_t",
                    "name": "Skin Thickness",
                    "type": "region_thickness",
                    "initial_value": 0.9,
                    "bounds": {"lower": 0.1, "upper": 2.0},
                    "region": "skin",
                    "active": True,
                },
            ],
        }
    )
    state = DesignState(
        run_id="fea-run",
        problem_name="structural",
        design_variables={"thickness": 0.85, "skin_t": 0.95},
        loads={"force": 120.0},
        constraints={"max_stress": 180.0},
        mesh_state={"backend": "gmsh", "mesh_path": "results/fea-run/mesh/mesh.bdf", "quality": 0.9},
    )

    result = FEAAgent().run(state, config, tmp_path)

    assert result.status == "success"
    assert backend.last_request is not None
    assert backend.last_request.design_variable_assignments.global_values == {"thickness": 0.85}
    assert backend.last_request.design_variable_assignments.region_values == {"skin": 0.95}


def test_fea_agent_reports_design_variable_mapping_failures(tmp_path: Path) -> None:
    model_path = tmp_path / "analysis" / "model.bdf"
    model_path.parent.mkdir(parents=True)
    model_path.write_text("CEND\nBEGIN BULK\nCTRIA3,10,1,1,2,3\nENDDATA\n")
    config = WorkflowConfig.model_validate(
        {
            "fea": {"tool": "mock", "model_input_path": "analysis/model.bdf"},
            "design_variables": [
                {
                    "id": "skin_t",
                    "name": "Skin Thickness",
                    "type": "region_thickness",
                    "initial_value": 0.9,
                    "bounds": {"lower": 0.1, "upper": 2.0},
                    "region": "skin",
                    "active": True,
                }
            ],
        }
    )
    state = DesignState(
        run_id="fea-run",
        problem_name="structural",
        design_variables={"skin_t": 0.95},
        loads={"force": 120.0},
        constraints={"max_stress": 180.0},
    )

    result = FEAAgent().run(state, config, tmp_path)

    assert result.status == "failure"
    assert result.diagnostics[0].code == "design_variables.mapping_failed"


def test_shell_boundary_loop_detection_and_classification() -> None:
    node_positions, elements = _shell_node_positions_and_elements()
    loops = find_boundary_loops(node_positions, elements)
    described = describe_boundary_loops(node_positions, loops)
    outer = select_boundary_loop(described, family="outer", order_by="area", index=0)
    left_inner = select_boundary_loop(described, family="inner", order_by="centroid_x", index=0)
    right_inner = select_boundary_loop(described, family="inner", order_by="centroid_x", index=1)

    assert len(loops) == 3
    assert len(outer) > len(left_inner)
    assert set(left_inner) == {9, 10, 17, 16}
    assert set(right_inner) == {12, 13, 20, 19}


def test_distribute_force_to_nodes_preserves_total_force() -> None:
    loads = distribute_force_to_nodes([10, 20, 30], 120.0, (0.0, -1.0, 0.0))

    assert len(loads) == 3
    assert sum(load[1] for load in loads) == -120.0
    assert all(load[0] == 0.0 for load in loads)


def test_tacs_backend_resolves_shell_node_sets(tmp_path: Path) -> None:
    backend = TacsFEABackend()
    node_positions, elements = _shell_node_positions_and_elements()
    request = _shell_request(
        tmp_path,
        shell_setup={
            "node_sets": {
                "left_bore": {
                    "selector": "boundary_loop",
                    "family": "inner",
                    "order_by": "centroid_x",
                    "index": 0,
                },
                "right_bore": {
                    "selector": "boundary_loop",
                    "family": "inner",
                    "order_by": "centroid_x",
                    "index": 1,
                },
                "center_node": {
                    "selector": "closest_node_to_centroid",
                },
            }
        },
    )

    resolved = backend._resolve_shell_node_sets(
        request=request,
        node_positions=node_positions,
        shell_elements=elements,
    )

    assert set(resolved["left_bore"]) == {9, 10, 17, 16}
    assert set(resolved["right_bore"]) == {12, 13, 20, 19}
    assert len(resolved["center_node"]) == 1
    assert resolved["center_node"][0] in node_positions


def test_tacs_backend_resolves_shell_bounding_box_node_sets(tmp_path: Path) -> None:
    backend = TacsFEABackend()
    node_positions, elements = _shell_node_positions_and_elements()
    request = _shell_request(
        tmp_path,
        shell_setup={
            "node_sets": {
                "left_edge": {
                    "selector": "bounding_box_extreme",
                    "axis": "x",
                    "extreme": "min",
                    "tolerance": 1e-6,
                }
            }
        },
    )

    resolved = backend._resolve_shell_node_sets(
        request=request,
        node_positions=node_positions,
        shell_elements=elements,
    )

    assert set(resolved["left_edge"]) == {1, 8, 15, 22, 29}


def test_tacs_backend_resolves_solid_node_sets(tmp_path: Path) -> None:
    backend = TacsFEABackend()
    node_positions, _ = _solid_node_positions_and_elements()
    request = _solid_request(
        tmp_path,
        solid_setup={
            "node_sets": {
                "fixed_face": {
                    "selector": "bounding_box_extreme",
                    "axis": "x",
                    "extreme": "min",
                },
                "loaded_face": {
                    "selector": "bounding_box_extreme",
                    "axis": "x",
                    "extreme": "max",
                },
            }
        },
    )

    resolved = backend._resolve_solid_node_sets(
        request=request,
        node_positions=node_positions,
    )

    assert set(resolved["fixed_face"]) == {1, 4, 5, 8}
    assert set(resolved["loaded_face"]) == {2, 3, 6, 7}


def test_tacs_backend_applies_explicit_shell_setup_boundary_conditions_and_loads(tmp_path: Path) -> None:
    backend = TacsFEABackend()
    node_positions, elements = _shell_node_positions_and_elements()
    bdf_info = FakeBDFInfo(node_positions, elements)
    assembler = FakeAssembler(bdf_info)
    request = _shell_request(
        tmp_path,
        shell_setup={
            "node_sets": {
                "left_bore": {
                    "selector": "boundary_loop",
                    "family": "inner",
                    "order_by": "centroid_x",
                    "index": 0,
                },
                "right_bore": {
                    "selector": "boundary_loop",
                    "family": "inner",
                    "order_by": "centroid_x",
                    "index": 1,
                },
            },
            "boundary_conditions": [{"node_set": "left_bore", "dof": "123456"}],
            "loads": [
                {
                    "node_set": "right_bore",
                    "load_key": "force",
                    "direction": [0.0, -1.0, 0.0],
                    "distribution": "equal",
                }
            ],
        },
    )

    result = backend._run_shell_analysis(
        request=request,
        bdf_info=bdf_info,
        pyTACS=lambda input_bdf: assembler,
        functions=SimpleNamespace(StructuralMass=object(), KSFailure=object()),
        constitutive=SimpleNamespace(),
        elements=SimpleNamespace(),
        output_directory=tmp_path,
    )

    assert result["boundary_conditions"]["bc_mode"] == "configured_shell_setup"
    assert result["boundary_conditions"]["load_mode"] == "configured_shell_setup"
    assert len(bdf_info.added_spcs) == 1
    assert bdf_info.added_spcs[0][1] == "123456"
    assert set(bdf_info.added_spcs[0][2]) == {9, 10, 17, 16}
    assert len(assembler.problem.added_loads) == 1
    node_ids, load_vectors, nastran_ordering = assembler.problem.added_loads[0]
    assert nastran_ordering is True
    assert set(node_ids) == {12, 13, 20, 19}
    assert sum(load[1] for load in load_vectors) == -120.0


def test_tacs_backend_applies_explicit_solid_setup_boundary_conditions_and_loads(tmp_path: Path) -> None:
    backend = TacsFEABackend()
    node_positions, elements = _solid_node_positions_and_elements()
    bdf_info = FakeBDFInfo(node_positions, elements)
    assembler = FakeAssembler(bdf_info)
    request = _solid_request(
        tmp_path,
        solid_setup={
            "node_sets": {
                "fixed_face": {
                    "selector": "bounding_box_extreme",
                    "axis": "x",
                    "extreme": "min",
                },
                "loaded_face": {
                    "selector": "bounding_box_extreme",
                    "axis": "x",
                    "extreme": "max",
                },
            },
            "boundary_conditions": [{"node_set": "fixed_face", "dof": "123456"}],
            "loads": [
                {
                    "node_set": "loaded_face",
                    "load_key": "force",
                    "direction": [0.0, -1.0, 0.0],
                    "distribution": "equal",
                }
            ],
        },
    )

    result = backend._run_solid_analysis(
        request=request,
        bdf_info=bdf_info,
        pyTACS=lambda input_bdf: assembler,
        functions=SimpleNamespace(StructuralMass=object(), KSFailure=object()),
        constitutive=SimpleNamespace(),
        elements=SimpleNamespace(),
        output_directory=tmp_path,
    )

    assert result["boundary_conditions"]["bc_mode"] == "configured_solid_setup"
    assert result["boundary_conditions"]["load_mode"] == "configured_solid_setup"
    assert len(bdf_info.added_spcs) == 1
    assert set(bdf_info.added_spcs[0][2]) == {1, 4, 5, 8}
    assert len(assembler.problem.added_loads) == 1
    node_ids, load_vectors, nastran_ordering = assembler.problem.added_loads[0]
    assert nastran_ordering is True
    assert set(node_ids) == {2, 3, 6, 7}
    assert sum(load[1] for load in load_vectors) == -120.0
    assert all(len(load) == 3 for load in load_vectors)


def test_tacs_backend_run_analysis_writes_multi_case_shell_summaries(tmp_path: Path) -> None:
    backend = TacsFEABackend()
    node_positions, elements = _shell_node_positions_and_elements()
    bdf_info = FakeBDFInfo(node_positions, elements, spcs={1: object()})

    class CaseAwareProblem(FakeProblem):
        def __init__(self, case_name: str) -> None:
            super().__init__()
            self.case_name = case_name

        def evalFunctions(self, values: dict[str, float]) -> None:
            values["mass"] = 24.0
            values["ks_vmfailure"] = 0.35 if self.case_name == "center_shear" else 0.9

    class CaseAwareAssembler(FakeAssembler):
        def createStaticProblem(self, case_name: str) -> FakeProblem:
            self.case_name = case_name
            problem = CaseAwareProblem(case_name)
            self.problems[case_name] = problem
            if len(self.problems) == 1:
                self.problem = problem
            return problem

    assembler = CaseAwareAssembler(bdf_info)
    model_path = tmp_path / "shell_model.bdf"
    model_path.write_text("CEND\nBEGIN BULK\nENDDATA\n")
    request = FEARequest(
        model_input_path=model_path,
        report_directory=tmp_path / "reports",
        log_directory=tmp_path / "logs",
        solution_directory=tmp_path / "solver",
        run_id="multi-case-shell",
        allowable_stress=180.0,
        load_cases={
            "center_shear": {"loads": {"force_x": 80.0}},
            "center_bending": {"loads": {"force_z": 120.0}},
        },
        shell_setup={
            "node_sets": {
                "center_node": {
                    "selector": "closest_node_to_centroid",
                }
            },
            "loads": [
                {
                    "node_set": "center_node",
                    "load_key": "force_x",
                    "direction": [1.0, 0.0, 0.0],
                    "distribution": "equal",
                },
                {
                    "node_set": "center_node",
                    "load_key": "force_z",
                    "direction": [0.0, 0.0, 1.0],
                    "distribution": "equal",
                },
            ],
        },
    )

    backend._load_tacs_modules = lambda: (
        lambda input_bdf: assembler,
        SimpleNamespace(StructuralMass=object(), KSFailure=object()),
        SimpleNamespace(),
        SimpleNamespace(),
        object,
    )
    backend._load_bdf = lambda model_path, bdf_class: bdf_info

    result = backend.run_analysis(request)

    assert result.worst_case_name == "center_bending"
    assert result.analysis_seconds is not None
    assert set(result.load_cases) == {"center_shear", "center_bending"}
    assert len(result.result_files) == 3
    overall_summary = json.loads(result.result_files[0].read_text())
    assert overall_summary["worst_case_name"] == "center_bending"
    assert set(overall_summary["load_cases"]) == {"center_shear", "center_bending"}
    bending_summary = json.loads((tmp_path / "reports" / "shell_model.center_bending.tacs.summary.json").read_text())
    assert bending_summary["case_name"] == "center_bending"
    assert bending_summary["max_stress"] == pytest.approx(162.0)
    assert bending_summary["loads"] == {"force_z": 120.0}
    assert "center_bending" in assembler.problems
    assert "center_shear" in assembler.problems


def test_tacs_backend_runs_shell_buckling_analysis_and_reports_eigenvalues(tmp_path: Path) -> None:
    backend = TacsFEABackend()
    node_positions, elements = _shell_node_positions_and_elements()
    bdf_info = FakeBDFInfo(node_positions, elements, spcs={1: object()})

    class BucklingAssembler(FakeAssembler):
        def createBucklingProblem(
            self,
            case_name: str,
            sigma: float,
            numEigs: int,
        ) -> FakeBucklingProblem:
            del sigma
            problem = FakeBucklingProblem(case_name, [2.4, 4.8, 8.2][:numEigs])
            self.buckling_problems[case_name] = problem
            return problem

    assembler = BucklingAssembler(bdf_info)
    model_path = tmp_path / "shell_model.bdf"
    model_path.write_text("CEND\nBEGIN BULK\nENDDATA\n")
    request = FEARequest(
        model_input_path=model_path,
        report_directory=tmp_path / "reports",
        log_directory=tmp_path / "logs",
        solution_directory=tmp_path / "solver",
        run_id="buckling-shell",
        allowable_stress=180.0,
        analysis_type="buckling",
        buckling_setup={
            "sigma": 5.0,
            "num_eigenvalues": 3,
        },
        load_cases={
            "compression": {"loads": {"force_x": 120.0}},
        },
        shell_setup={
            "node_sets": {
                "edge": {
                    "selector": "bounding_box_extreme",
                    "axis": "x",
                    "extreme": "max",
                }
            },
            "loads": [
                {
                    "node_set": "edge",
                    "load_key": "force_x",
                    "direction": [-1.0, 0.0, 0.0],
                    "distribution": "equal",
                }
            ],
        },
    )

    backend._load_tacs_modules = lambda: (
        lambda input_bdf: assembler,
        SimpleNamespace(StructuralMass=object(), KSFailure=object()),
        SimpleNamespace(),
        SimpleNamespace(),
        object,
    )
    backend._load_bdf = lambda model_path, bdf_class: bdf_info

    result = backend.run_analysis(request)

    assert result.analysis_type == "buckling"
    assert result.critical_eigenvalue == pytest.approx(2.4)
    assert result.eigenvalues == pytest.approx([2.4, 4.8, 8.2])
    assert result.load_cases["compression"].critical_eigenvalue == pytest.approx(2.4)
    summary = json.loads(result.result_files[0].read_text())
    assert summary["analysis_type"] == "buckling"
    assert summary["critical_buckling_load_factor"] == pytest.approx(2.4)
    assert summary["buckling_load_factors"] == pytest.approx([2.4, 4.8, 8.2])
    case_summary = json.loads(
        (tmp_path / "reports" / "shell_model.compression.tacs.summary.json").read_text()
    )
    assert case_summary["critical_buckling_load_factor"] == pytest.approx(2.4)
    assert "compression_buckling" in assembler.buckling_problems


def test_tacs_backend_runs_shell_modal_analysis_and_reports_frequencies(tmp_path: Path) -> None:
    backend = TacsFEABackend()
    node_positions, elements = _shell_node_positions_and_elements()
    bdf_info = FakeBDFInfo(node_positions, elements, spcs={1: object()})

    class ModalAssembler(FakeAssembler):
        def createModalProblem(
            self,
            case_name: str,
            sigma: float,
            numEigs: int,
        ) -> FakeModalProblem:
            del sigma
            problem = FakeModalProblem(
                case_name,
                [(2.0 * pi * value) ** 2 for value in [9.0, 15.0, 21.0][:numEigs]],
            )
            self.modal_problems[case_name] = problem
            return problem

    assembler = ModalAssembler(bdf_info)
    model_path = tmp_path / "shell_model.bdf"
    model_path.write_text("CEND\nBEGIN BULK\nENDDATA\n")
    request = FEARequest(
        model_input_path=model_path,
        report_directory=tmp_path / "reports",
        log_directory=tmp_path / "logs",
        solution_directory=tmp_path / "solver",
        run_id="modal-shell",
        allowable_stress=180.0,
        analysis_type="modal",
        modal_setup={
            "sigma": 25.0,
            "num_eigenvalues": 3,
        },
        load_cases={
            "cantilever": {"loads": {}},
        },
    )

    backend._load_tacs_modules = lambda: (
        lambda input_bdf: assembler,
        SimpleNamespace(StructuralMass=object(), KSFailure=object()),
        SimpleNamespace(),
        SimpleNamespace(),
        object,
    )
    backend._load_bdf = lambda model_path, bdf_class: bdf_info

    result = backend.run_analysis(request)

    assert result.analysis_type == "modal"
    assert result.critical_eigenvalue == pytest.approx((2.0 * pi * 9.0) ** 2)
    assert result.critical_frequency_hz == pytest.approx(9.0)
    assert result.frequencies_hz == pytest.approx([9.0, 15.0, 21.0])
    assert result.load_cases["cantilever"].critical_frequency_hz == pytest.approx(9.0)
    summary = json.loads(result.result_files[0].read_text())
    assert summary["analysis_type"] == "modal"
    assert summary["critical_natural_frequency_hz"] == pytest.approx(9.0)
    assert summary["natural_frequencies_hz"] == pytest.approx([9.0, 15.0, 21.0])
    case_summary = json.loads(
        (tmp_path / "reports" / "shell_model.cantilever.tacs.summary.json").read_text()
    )
    assert case_summary["critical_natural_frequency_hz"] == pytest.approx(9.0)
    assert "cantilever_modal" in assembler.modal_problems


def test_tacs_backend_writes_aggregation_quality_summary(tmp_path: Path) -> None:
    backend = TacsFEABackend()
    node_positions, elements = _shell_node_positions_and_elements()
    bdf_info = FakeBDFInfo(node_positions, elements, spcs={1: object()})

    class CaseAwareProblem(FakeProblem):
        def __init__(self, case_name: str) -> None:
            super().__init__()
            self.case_name = case_name

        def evalFunctions(self, values: dict[str, float]) -> None:
            values["mass"] = 24.0
            values["ks_vmfailure"] = 0.42 if self.case_name == "center_shear" else 0.88

        def getElementStresses(self) -> list[float]:
            if self.case_name == "center_shear":
                return [61.0, 70.0, 75.0]
            return [120.0, 150.0, 168.0]

    class CaseAwareAssembler(FakeAssembler):
        def createStaticProblem(self, case_name: str) -> FakeProblem:
            self.case_name = case_name
            problem = CaseAwareProblem(case_name)
            self.problems[case_name] = problem
            if len(self.problems) == 1:
                self.problem = problem
            return problem

    assembler = CaseAwareAssembler(bdf_info)
    model_path = tmp_path / "shell_model.bdf"
    model_path.write_text("CEND\nBEGIN BULK\nENDDATA\n")
    request = FEARequest(
        model_input_path=model_path,
        report_directory=tmp_path / "reports",
        log_directory=tmp_path / "logs",
        solution_directory=tmp_path / "solver",
        run_id="multi-case-shell-aggregated",
        allowable_stress=180.0,
        load_cases={
            "center_shear": {"loads": {"force_x": 80.0}},
            "center_bending": {"loads": {"force_z": 120.0}},
        },
        constraints={
            "max_stress": 180.0,
            "aggregated_stress": {
                "method": "ks",
                "allowable": 175.0,
            },
        },
        shell_setup={
            "node_sets": {
                "center_node": {
                    "selector": "closest_node_to_centroid",
                }
            },
            "loads": [
                {
                    "node_set": "center_node",
                    "load_key": "force_x",
                    "direction": [1.0, 0.0, 0.0],
                    "distribution": "equal",
                },
                {
                    "node_set": "center_node",
                    "load_key": "force_z",
                    "direction": [0.0, 0.0, 1.0],
                    "distribution": "equal",
                },
            ],
        },
    )

    backend._load_tacs_modules = lambda: (
        lambda input_bdf: assembler,
        SimpleNamespace(StructuralMass=object(), KSFailure=object()),
        SimpleNamespace(),
        SimpleNamespace(),
        object,
    )
    backend._load_bdf = lambda model_path, bdf_class: bdf_info

    result = backend.run_analysis(request)

    assert result.aggregation_quality_summary_path is not None
    quality_summary = json.loads(result.aggregation_quality_summary_path.read_text())
    assert quality_summary["load_cases"]["center_bending"]["aggregated_input_stress"] == pytest.approx(
        158.4
    )
    assert quality_summary["load_cases"]["center_bending"]["raw_max_stress"] == pytest.approx(168.0)
    assert quality_summary["raw_global_max_stress"] == pytest.approx(168.0)
    assert quality_summary["controlling_case_by_surrogate"] == "center_bending"
    assert quality_summary["controlling_case_by_raw_max"] == "center_bending"


def test_tacs_backend_uses_existing_spcs_with_explicit_shell_load_selector(tmp_path: Path) -> None:
    backend = TacsFEABackend()
    node_positions, elements = _shell_node_positions_and_elements()
    bdf_info = FakeBDFInfo(node_positions, elements, spcs={1: object()})
    assembler = FakeAssembler(bdf_info)
    request = _shell_request(
        tmp_path,
        shell_setup={
            "node_sets": {
                "center_node": {"selector": "closest_node_to_centroid"},
            },
            "loads": [
                {
                    "node_set": "center_node",
                    "load_key": "force",
                    "direction": [0.0, 0.0, 1.0],
                    "distribution": "equal",
                }
            ],
        },
    )

    result = backend._run_shell_analysis(
        request=request,
        bdf_info=bdf_info,
        pyTACS=lambda input_bdf: assembler,
        functions=SimpleNamespace(StructuralMass=object(), KSFailure=object()),
        constitutive=SimpleNamespace(),
        elements=SimpleNamespace(),
        output_directory=tmp_path,
    )

    assert result["boundary_conditions"]["bc_mode"] == "existing_spc"
    assert bdf_info.added_spcs == []
    assert len(assembler.problem.added_loads) == 1
    node_ids, load_vectors, _ = assembler.problem.added_loads[0]
    assert len(node_ids) == 1
    assert load_vectors == [[0.0, 0.0, 120.0, 0.0, 0.0, 0.0]]


def test_tacs_backend_requires_explicit_shell_load_configuration_for_scripted_loads(
    tmp_path: Path,
) -> None:
    backend = TacsFEABackend()
    node_positions, elements = _shell_node_positions_and_elements()
    bdf_info = FakeBDFInfo(node_positions, elements, spcs={1: object()})
    assembler = FakeAssembler(bdf_info)
    request = _shell_request(tmp_path, shell_setup=None)

    with pytest.raises(RuntimeError, match="fea\\.shell_setup\\.loads"):
        backend._run_shell_analysis(
            request=request,
            bdf_info=bdf_info,
            pyTACS=lambda input_bdf: assembler,
            functions=SimpleNamespace(StructuralMass=object(), KSFailure=object()),
            constitutive=SimpleNamespace(),
            elements=SimpleNamespace(),
            output_directory=tmp_path,
        )


def test_tacs_backend_maps_elementwise_thickness_assignments_to_component_thickness(tmp_path: Path) -> None:
    backend = TacsFEABackend()
    model_path = tmp_path / "model.bdf"
    model_path.write_text("CEND\nBEGIN BULK\nENDDATA\n")
    bdf_info = SimpleNamespace(
        elements={
            1: SimpleNamespace(pid=7),
            2: SimpleNamespace(pid=8),
        }
    )
    request = FEARequest(
        model_input_path=model_path,
        report_directory=tmp_path,
        log_directory=tmp_path,
        solution_directory=tmp_path,
        run_id="tacs-run",
        design_variables={"thickness": 0.8},
        design_variable_assignments={
            "element_values": {1: 0.9},
        },
        allowable_stress=180.0,
    )

    assignments = backend._resolve_shell_thickness_assignments(
        request,
        request.model_input_path,
        bdf_info,
    )
    assert assignments["component_thickness"] == {7: 0.9}


def test_tacs_backend_runs_multi_case_bdf_analysis() -> None:
    backend = TacsFEABackend()

    class NamedProblem(FakeProblem):
        def __init__(self, case_name: str, failure_index: float) -> None:
            super().__init__()
            self.case_name = case_name
            self.failure_index = failure_index

        def evalFunctions(self, values: dict[str, float]) -> None:
            values["mass"] = 30.0
            values["ks_vmfailure"] = self.failure_index

    class BdfAssembler:
        def initialize(self) -> None:
            return None

        def createTACSProbsFromBDF(self) -> dict[str, NamedProblem]:
            return {
                "gust": NamedProblem("gust", 0.8),
                "maneuver": NamedProblem("maneuver", 0.45),
            }

    request = FEARequest(
        model_input_path=Path("model.bdf"),
        report_directory=Path("reports"),
        log_directory=Path("logs"),
        solution_directory=Path("solver"),
        run_id="bdf-multi-case",
        allowable_stress=180.0,
        load_cases={
            "gust": {"loads": {}},
            "maneuver": {"loads": {}},
        },
    )

    result = backend._run_bdf_analysis(
        request=request,
        model_path=Path("model.bdf"),
        pyTACS=lambda model_path: BdfAssembler(),
        functions=SimpleNamespace(StructuralMass=object(), KSFailure=object()),
        output_directory=Path("solver"),
    )

    assert result["case_name"] == "gust"
    assert set(result["load_cases"]) == {"gust", "maneuver"}
    assert result["load_cases"]["gust"]["selected_case_name"] == "gust"
    assert result["load_cases"]["maneuver"]["selected_case_name"] == "maneuver"
    assert result["load_cases"]["gust"]["max_stress"] == pytest.approx(144.0)


def test_tacs_backend_reports_missing_named_bdf_case() -> None:
    backend = TacsFEABackend()

    class BdfAssembler:
        def initialize(self) -> None:
            return None

        def createTACSProbsFromBDF(self) -> dict[str, FakeProblem]:
            return {"gust": FakeProblem()}

    request = FEARequest(
        model_input_path=Path("model.bdf"),
        report_directory=Path("reports"),
        log_directory=Path("logs"),
        solution_directory=Path("solver"),
        run_id="bdf-missing-case",
        allowable_stress=180.0,
        load_cases={
            "gust": {"loads": {}},
            "maneuver": {"loads": {}},
        },
    )

    with pytest.raises(RuntimeError, match="Requested BDF load case 'maneuver'"):
        backend._run_bdf_analysis(
            request=request,
            model_path=Path("model.bdf"),
            pyTACS=lambda model_path: BdfAssembler(),
            functions=SimpleNamespace(StructuralMass=object(), KSFailure=object()),
            output_directory=Path("solver"),
        )
