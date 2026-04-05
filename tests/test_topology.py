import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

pytest.importorskip("numpy")
pytest.importorskip("scipy")
pytest.importorskip("matplotlib")

import numpy as np

from mass_town.cli import app
from mass_town.config import WorkflowConfig
from mass_town.disciplines.topology import TopologyConfig, TopologyRequest
from mass_town.orchestration.workflow_engine import WorkflowEngine
from plugins.topopt.backend import (
    StructuredPlaneStressTopologyBackend,
    _DensityFilter,
    _HeavisideProjection,
    _StructuredQuadMesh,
    _optimality_criteria_update,
)


def _request_from_config(tmp_path: Path, config_data: dict) -> TopologyRequest:
    run_root = tmp_path / "results_root"
    reports = run_root / "reports"
    logs = run_root / "logs"
    mesh = run_root / "mesh"
    solver = run_root / "solver"
    reports.mkdir(parents=True)
    logs.mkdir()
    mesh.mkdir()
    solver.mkdir()
    return TopologyRequest(
        report_directory=reports,
        log_directory=logs,
        mesh_directory=mesh,
        solution_directory=solver,
        run_id="topology-test",
        config=TopologyConfig.model_validate(config_data),
    )


def test_density_filter_preserves_uniform_field_and_maps_sensitivities() -> None:
    filter_operator = _DensityFilter(
        nelx=5,
        nely=4,
        radius=1.5,
        np=np,
        scipy_sparse=pytest.importorskip("scipy.sparse"),
    )
    uniform = np.full(20, 0.4)
    filtered = filter_operator.apply(uniform)
    mapped = filter_operator.apply_transpose(np.ones(20))

    assert np.allclose(filtered, uniform)
    assert mapped.shape == (20,)
    assert np.all(mapped > 0.0)


def test_heaviside_projection_derivative_matches_finite_difference() -> None:
    projector = _HeavisideProjection(
        enabled=True,
        beta=2.0,
        beta_max=8.0,
        eta=0.5,
        beta_scale=1.2,
        update_interval=10,
        np=np,
    )
    values = np.linspace(0.15, 0.85, 6)
    analytic = projector.derivative(values)
    epsilon = 1e-6
    finite_difference = (projector.apply(values + epsilon) - projector.apply(values - epsilon)) / (
        2.0 * epsilon
    )

    assert np.allclose(analytic, finite_difference, atol=1e-5, rtol=1e-4)


def test_oc_update_respects_move_limits_bounds_and_target_volume() -> None:
    current = np.full(12, 0.4)
    objective_gradient = -np.linspace(1.0, 2.0, 12)
    volume_gradient = np.full(12, 1.0 / 12.0)

    updated = _optimality_criteria_update(
        densities=current,
        objective_gradient=objective_gradient,
        volume_gradient=volume_gradient,
        target_volume_fraction=0.5,
        move_limit=0.1,
        density_min=1e-3,
        np=np,
    )

    assert np.all(updated >= 1e-3)
    assert np.all(updated <= 1.0)
    assert np.all(updated <= current + 0.1 + 1e-12)
    assert np.all(updated >= current - 0.1 - 1e-12)
    assert updated.mean() == pytest.approx(0.5, abs=1e-4)


def test_topology_chain_sensitivity_matches_finite_difference() -> None:
    scipy_sparse = pytest.importorskip("scipy.sparse")
    scipy_splinalg = pytest.importorskip("scipy.sparse.linalg")
    mesh = _StructuredQuadMesh(6, 3, 2.0, 1.0, np=np)
    filter_operator = _DensityFilter(
        nelx=6,
        nely=3,
        radius=1.5,
        np=np,
        scipy_sparse=scipy_sparse,
    )
    projector = _HeavisideProjection(
        enabled=True,
        beta=1.5,
        beta_max=8.0,
        eta=0.5,
        beta_scale=1.2,
        update_interval=5,
        np=np,
    )
    design = np.full(mesh.num_elements, 0.5)
    force, fixed = mesh.load_and_boundary(
        node_selector="max_x_mid",
        dof="y",
        magnitude=-1.0,
        fixed_boundary="min_x",
    )

    filtered = filter_operator.apply(design)
    physical = projector.apply(filtered)
    _, dc_phys = mesh.compliance_and_sensitivity(
        densities=physical,
        youngs_modulus=1.0,
        poisson_ratio=0.3,
        penal=3.0,
        density_min=1e-3,
        force_vector=force,
        fixed_dofs=fixed,
        scipy_sparse=scipy_sparse,
        scipy_splinalg=scipy_splinalg,
        warnings_module=__import__("warnings"),
        np=np,
    )
    analytic = filter_operator.apply_transpose(dc_phys * projector.derivative(filtered))

    epsilon = 1e-5
    index = 4
    delta = np.zeros_like(design)
    delta[index] = epsilon

    def objective(design_values: np.ndarray) -> float:
        filtered_local = filter_operator.apply(design_values)
        physical_local = projector.apply(filtered_local)
        value, _ = mesh.compliance_and_sensitivity(
            densities=physical_local,
            youngs_modulus=1.0,
            poisson_ratio=0.3,
            penal=3.0,
            density_min=1e-3,
            force_vector=force,
            fixed_dofs=fixed,
            scipy_sparse=scipy_sparse,
            scipy_splinalg=scipy_splinalg,
            warnings_module=__import__("warnings"),
            np=np,
        )
        return value

    finite_difference = (objective(design + delta) - objective(design - delta)) / (2.0 * epsilon)
    assert analytic[index] == pytest.approx(finite_difference, rel=3e-2, abs=5e-3)


def test_backend_runs_with_projection_continuation(tmp_path: Path) -> None:
    backend = StructuredPlaneStressTopologyBackend()
    request = _request_from_config(
        tmp_path,
        {
            "volume_fraction": 0.45,
            "domain": {"nelx": 12, "nely": 4, "lx": 2.0, "ly": 1.0},
            "filter": {"radius": 1.5},
            "projection": {
                "enabled": True,
                "beta": 1.0,
                "beta_max": 4.0,
                "eta": 0.5,
                "beta_scale": 2.0,
                "update_interval": 3,
            },
            "optimizer": {"max_iterations": 12, "change_tolerance": 0.05, "move_limit": 0.2},
        },
    )

    result = backend.run_optimization(request)
    history = json.loads(result.history_path.read_text())

    assert result.iteration_count >= 1
    assert result.timing.mesh_seconds is not None
    assert result.timing.solve_seconds is not None
    assert result.timing.optimization_seconds is not None
    assert result.beta is not None and result.beta >= 1.0
    assert history["beta"][0] == pytest.approx(1.0)
    assert result.summary_path.exists()
    assert result.density_path.exists()


def test_topology_config_rejects_invalid_filter_and_volume_fraction() -> None:
    with pytest.raises(ValueError):
        TopologyConfig.model_validate({"volume_fraction": 1.2})
    with pytest.raises(ValueError):
        TopologyConfig.model_validate({"filter": {"radius": 0.0}})


def test_backend_rejects_load_on_fixed_boundary(tmp_path: Path) -> None:
    backend = StructuredPlaneStressTopologyBackend()
    request = _request_from_config(
        tmp_path,
        {
            "domain": {"nelx": 10, "nely": 4, "lx": 2.0, "ly": 1.0},
            "load": {"node_selector": "max_x_mid", "dof": "y", "magnitude": -1.0},
            "boundary": {"fixed_boundary": "max_x"},
        },
    )

    with pytest.raises(ValueError, match="constrained by topology.boundary"):
        backend.run_optimization(request)


def test_topology_example_runs_end_to_end_and_status_is_topology_aware(tmp_path: Path) -> None:
    source = Path("examples/topology_cantilever_problem")
    project_dir = tmp_path / "topology_cantilever_problem"
    shutil.copytree(
        source,
        project_dir,
        ignore=shutil.ignore_patterns("results", "__pycache__"),
    )

    engine = WorkflowEngine(config=WorkflowConfig.from_file(project_dir / "config.yaml"))
    state = engine.run(project_dir / "design_state.yaml", project_dir)

    summary_path = (
        project_dir / "results" / "topology-cantilever-problem" / "reports" / "run_summary.json"
    )
    summary = json.loads(summary_path.read_text())

    assert state.status == "recovered"
    assert state.topology_state.converged is True
    assert state.topology_state.objective is not None
    assert state.topology_state.volume_fraction is not None
    assert state.topology_state.volume_fraction == pytest.approx(0.4, abs=0.03)
    assert summary["feasible"] is True
    assert summary["topology"]["converged"] is True
    assert summary["artifact_paths"]["topology_summary"] == (
        "results/topology-cantilever-problem/reports/topology_summary.json"
    )
    assert summary["artifact_paths"]["topology_density"] == (
        "results/topology-cantilever-problem/reports/final_density.json"
    )
    assert (
        project_dir / "results" / "topology-cantilever-problem" / "reports" / "final_density.png"
    ).exists()

    runner = CliRunner()
    status_result = runner.invoke(app, ["status", str(project_dir / "design_state.yaml")])
    assert status_result.exit_code == 0
    assert "objective=" in status_result.stdout
    assert "converged=True" in status_result.stdout
