import json
import os
import shutil
import warnings
from pathlib import Path

import pytest

os.environ.setdefault("OPENMDAO_REPORTS", "0")
om = pytest.importorskip("openmdao.api")

from mass_town.config import WorkflowConfig
from mass_town.disciplines import SensitivityPayload
from mass_town.disciplines.fea import FEABackend, FEARequest, FEAResult
from mass_town.orchestration.state_manager import StateManager
from mass_town.problem_schema import ProblemSchemaResolver
from mass_town.runtime.local_runtime import LocalRuntime
from mass_town.runtime.openmdao_components import StructuralAnalysisComp, StructuralPostprocessingComp
from mass_town.runtime.openmdao_runtime import OpenMDAORuntime
from mass_town.storage.filesystem import ensure_run_layout
from plugins.mock.backend import MockFEABackend


class PartialSensitivityMockBackend(FEABackend):
    name = "partial-mock"

    def is_available(self) -> bool:
        return True

    def availability_reason(self) -> str | None:
        return None

    def run_analysis(self, request: FEARequest) -> FEAResult:
        del request
        return FEAResult(
            backend_name=self.name,
            passed=True,
            mass=2.4,
            max_stress=150.0,
            displacement_norm=0.1,
            sensitivities=[
                SensitivityPayload(response="mass", with_respect_to="skin_t", values=[2.0]),
                SensitivityPayload(response="mass", with_respect_to="web_t", values=[3.0]),
            ],
        )


def _example_project(name: str) -> Path:
    return Path("examples") / name


def _copy_example(tmp_path: Path, name: str) -> Path:
    source = _example_project(name)
    destination = tmp_path / name
    shutil.copytree(source, destination)
    return destination


def test_openmdao_mock_example_runs_and_writes_standard_artifacts(tmp_path: Path) -> None:
    project_dir = _copy_example(tmp_path, "openmdao_mock_structural_problem")
    config = WorkflowConfig.from_file(project_dir / "config.yaml")
    runtime = OpenMDAORuntime(config=config)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        final_state = runtime.run(project_dir / "design_state.yaml", project_dir)

    assert final_state.status == "recovered"
    assert not [warning for warning in caught if "finite-difference fallback" in str(warning.message)]
    summary_path = project_dir / "results" / final_state.run_id / "reports" / "run_summary.json"
    summary = json.loads(summary_path.read_text())
    assert (project_dir / "results" / final_state.run_id / "reports" / "problem_schema.json").exists()
    assert summary["artifact_paths"]["problem_schema"] == (
        f"results/{final_state.run_id}/reports/problem_schema.json"
    )
    assert summary["design_variables"]["skin_t"] != pytest.approx(0.7)
    assert summary["design_variables"]["web_t"] != pytest.approx(0.7)
    assert summary["mass"] < (2.0 * 0.7) + (3.0 * 0.7)
    assert summary["max_stress"] <= 180.0 + 1.0e-4


def test_openmdao_analysis_component_uses_backend_sensitivities(tmp_path: Path) -> None:
    project_dir = _copy_example(tmp_path, "openmdao_mock_structural_problem")
    config = WorkflowConfig.from_file(project_dir / "config.yaml")
    state = StateManager().load(project_dir / "design_state.yaml")
    problem = ProblemSchemaResolver().resolve(config, state, project_dir)
    layout = ensure_run_layout(project_dir, state.run_id)

    prob = om.Problem(reports=False)
    ivc = om.IndepVarComp()
    ivc.add_output("skin_t", val=0.7)
    ivc.add_output("web_t", val=0.7)
    prob.model.add_subsystem("design_vars", ivc, promotes=["*"])
    analysis = StructuralAnalysisComp(
        config=config,
        problem=problem,
        state=state,
        run_root=project_dir,
        layout=layout,
        backend=MockFEABackend(),
        schema_resolver=ProblemSchemaResolver(),
        fallback_reporter=lambda *args: (_ for _ in ()).throw(
            AssertionError(f"unexpected fallback: {args}")
        ),
    )
    prob.model.add_subsystem("analysis", analysis)
    prob.model.connect("skin_t", "analysis.skin_t")
    prob.model.connect("web_t", "analysis.web_t")
    prob.setup()
    prob.run_model()

    partials = prob.check_partials(out_stream=None, compact_print=True)
    assert analysis.latest_result is not None
    assert analysis.latest_result.sensitivities
    assert partials["analysis"][("mass", "skin_t")]["J_fwd"][0][0] == pytest.approx(2.0)
    assert partials["analysis"][("mass", "web_t")]["J_fwd"][0][0] == pytest.approx(3.0)


def test_openmdao_postprocessing_component_exposes_objective_and_constraint(tmp_path: Path) -> None:
    project_dir = _copy_example(tmp_path, "openmdao_mock_structural_problem")
    config = WorkflowConfig.from_file(project_dir / "config.yaml")
    state = StateManager().load(project_dir / "design_state.yaml")
    problem = ProblemSchemaResolver().resolve(config, state, project_dir)
    layout = ensure_run_layout(project_dir, state.run_id)

    prob = om.Problem(reports=False)
    ivc = om.IndepVarComp()
    ivc.add_output("mass", val=2.5)
    ivc.add_output("max_stress", val=175.0)
    ivc.add_output("displacement_norm", val=0.2)
    prob.model.add_subsystem("analysis_outputs", ivc, promotes=["*"])
    postprocess = StructuralPostprocessingComp(
        config=config,
        problem=problem,
        state=state,
        run_root=project_dir,
        layout=layout,
        objective_kind="minimize_mass",
        include_max_stress_constraint=True,
    )
    prob.model.add_subsystem("postprocess", postprocess)
    prob.model.connect("mass", "postprocess.mass")
    prob.model.connect("max_stress", "postprocess.max_stress")
    prob.model.connect("displacement_norm", "postprocess.displacement_norm")
    prob.setup()
    prob.run_model()

    assert float(prob.get_val("postprocess.objective")[0]) == pytest.approx(2.5)
    assert float(prob.get_val("postprocess.max_stress_margin")[0]) == pytest.approx(-5.0)


def test_openmdao_analysis_component_reports_fd_fallback_for_missing_pairs(tmp_path: Path) -> None:
    project_dir = _copy_example(tmp_path, "openmdao_mock_structural_problem")
    config = WorkflowConfig.from_file(project_dir / "config.yaml")
    state = StateManager().load(project_dir / "design_state.yaml")
    problem = ProblemSchemaResolver().resolve(config, state, project_dir)
    layout = ensure_run_layout(project_dir, state.run_id)
    fallback_calls: list[tuple[str, str, str, list[str]]] = []

    prob = om.Problem(reports=False)
    ivc = om.IndepVarComp()
    ivc.add_output("skin_t", val=0.7)
    ivc.add_output("web_t", val=0.7)
    prob.model.add_subsystem("design_vars", ivc, promotes=["*"])
    analysis = StructuralAnalysisComp(
        config=config,
        problem=problem,
        state=state,
        run_root=project_dir,
        layout=layout,
        backend=PartialSensitivityMockBackend(),
        schema_resolver=ProblemSchemaResolver(),
        fallback_reporter=lambda *args: fallback_calls.append(args),
    )
    prob.model.add_subsystem("analysis", analysis)
    prob.model.connect("skin_t", "analysis.skin_t")
    prob.model.connect("web_t", "analysis.web_t")
    prob.setup()
    prob.run_model()

    assert fallback_calls
    assert fallback_calls[0][0] == "analysis"
    assert "max_stress<-skin_t" in fallback_calls[0][3]
    assert any(
        key[0].endswith("max_stress") and key[1].endswith("skin_t") and value.get("method") == "fd"
        for key, value in analysis._subjacs_info.items()
    )


def test_local_runtime_path_still_works_for_mock_structural_problem(tmp_path: Path) -> None:
    project_dir = _copy_example(tmp_path, "openmdao_mock_structural_problem")
    config = WorkflowConfig.from_file(project_dir / "config.yaml")
    local_runtime = LocalRuntime(config=config)

    final_state = local_runtime.run(project_dir / "design_state.yaml", project_dir)

    assert final_state.status in {"recovered", "failed"}
    assert final_state.analysis_state.backend == "mock"
