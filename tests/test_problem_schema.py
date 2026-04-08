import json
from pathlib import Path

import pytest

from mass_town.config import WorkflowConfig
from mass_town.orchestration.state_manager import StateManager
from mass_town.problem_schema import ProblemSchema, ProblemSchemaResolver


def _resolve_example(name: str):
    project_dir = Path("examples") / name
    config = WorkflowConfig.from_file(project_dir / "config.yaml")
    state = StateManager().load(project_dir / "design_state.yaml")
    schema = ProblemSchemaResolver().resolve(config, state, project_dir)
    return project_dir, schema


def _fixture(name: str) -> dict:
    path = Path("tests/fixtures/problem_schema") / name
    return json.loads(path.read_text())


def _subset(schema: ProblemSchema) -> dict:
    return {
        "problem": {"id": schema.problem.id, "name": schema.problem.name},
        "model": {
            "type": schema.model.type,
            "input_source": schema.model.input_source,
        },
        "analysis": {
            "discipline": schema.analysis.discipline,
            "analysis_type": schema.analysis.analysis_type,
            "case_name": schema.analysis.case_name,
        },
        "objectives": [objective.model_dump(mode="json") for objective in schema.objectives],
        "constraints": [constraint.model_dump(mode="json") for constraint in schema.constraints],
        "execution": {"initial_tasks": schema.execution.initial_tasks},
    }


def test_baseline_example_converts_to_problem_schema_snapshot() -> None:
    _, schema = _resolve_example("simple_structural_problem")

    assert _subset(schema) == _fixture("simple_structural_problem.json")
    assert schema.geometry is not None
    assert schema.meshing is not None
    assert sorted(node_set.name for node_set in schema.node_sets) == ["left_bore", "right_bore"]
    assert [design_variable.kind for design_variable in schema.design_variables] == ["scalar_thickness"]


def test_shell_sizing_bdf_example_converts_with_region_design_variables() -> None:
    _, schema = _resolve_example("shell_sizing_bdf_problem")

    assert schema.model.type == "shell"
    assert schema.meshing is not None
    assert schema.meshing.tool == "auto"
    assert schema.geometry is not None
    assert schema.geometry.file_format == "bdf"
    assert len(schema.design_variables) == 9
    assert {design_variable.kind for design_variable in schema.design_variables} == {"region_thickness"}
    assert {design_variable.target.name for design_variable in schema.design_variables if design_variable.target} == {
        f"pid_{index}" for index in range(1, 10)
    }


def test_multi_case_shell_problem_preserves_load_cases_and_aggregation() -> None:
    _, schema = _resolve_example("shell_sizing_bdf_multi_case_problem")

    assert [load_case.name for load_case in schema.analysis.load_cases] == [
        "center_bending",
        "center_shear",
    ]
    aggregated = next(
        constraint for constraint in schema.constraints if constraint.kind == "aggregated_stress"
    )
    assert aggregated.method == "ks"
    assert aggregated.source == "load_cases"
    assert aggregated.limit == pytest.approx(3.0e9)


def test_solid_cantilever_problem_converts_with_solid_model_type() -> None:
    _, schema = _resolve_example("solid_cantilever_problem")

    assert schema.model.type == "solid"
    assert schema.meshing is not None
    assert schema.analysis.analysis_type == "static"


def test_buckling_and_modal_examples_preserve_eigenvalue_constraints() -> None:
    _, buckling_schema = _resolve_example("shell_buckling_bdf_problem")
    _, modal_schema = _resolve_example("shell_modal_bdf_problem")

    buckling_constraint = next(
        constraint
        for constraint in buckling_schema.constraints
        if constraint.kind == "minimum_buckling_load_factor"
    )
    modal_constraint = next(
        constraint
        for constraint in modal_schema.constraints
        if constraint.kind == "minimum_natural_frequency_hz"
    )

    assert buckling_schema.analysis.analysis_type == "buckling"
    assert buckling_constraint.mode == 0
    assert buckling_constraint.limit == pytest.approx(0.005)
    assert modal_schema.analysis.analysis_type == "modal"
    assert modal_constraint.mode == 0
    assert modal_constraint.limit == pytest.approx(0.25)


def test_openmdao_mock_example_converts_with_mass_objective() -> None:
    _, schema = _resolve_example("openmdao_mock_structural_problem")

    assert _subset(schema) == _fixture("openmdao_mock_structural_problem.json")
    assert schema.model.model_input_path == "inputs/model/mock_panel.bdf"
    assert [design_variable.id for design_variable in schema.design_variables] == ["skin_t", "web_t"]
    assert schema.optimizer is not None
    assert schema.optimizer.backend == "openmdao_slsqp"
    assert schema.optimizer.strategy == "scipy_slsqp"


def test_topology_example_converts_to_problem_schema_snapshot() -> None:
    _, schema = _resolve_example("topology_cantilever_problem")

    assert _subset(schema) == _fixture("topology_cantilever_problem.json")
    assert schema.geometry is not None
    assert schema.geometry.domain is not None
    assert schema.model.type == "topology"
    assert schema.optimizer is not None
    assert schema.optimizer.backend == "optimality_criteria"
    assert [design_variable.kind for design_variable in schema.design_variables] == ["density_field"]


def test_problem_schema_rejects_structural_problem_without_meshing_or_model_input() -> None:
    with pytest.raises(
        ValueError,
        match="require either meshing settings or a model_input_path",
    ):
        ProblemSchema.model_validate(
            {
                "problem": {"id": "broken", "name": "broken"},
                "model": {"type": "shell", "input_source": "meshed_geometry"},
                "analysis": {
                    "discipline": "structural",
                    "analysis_type": "static",
                },
            }
        )


def test_problem_schema_rejects_unknown_node_set_references() -> None:
    with pytest.raises(ValueError, match="unknown node set 'missing_set'"):
        ProblemSchema.model_validate(
            {
                "problem": {"id": "broken", "name": "broken"},
                "geometry": {
                    "source_type": "file",
                    "path": "inputs/model.bdf",
                    "file_format": "bdf",
                },
                "model": {
                    "type": "shell",
                    "input_source": "model_file",
                    "model_input_path": "inputs/model.bdf",
                },
                "analysis": {
                    "discipline": "structural",
                    "analysis_type": "static",
                },
                "boundary_conditions": [
                    {
                        "kind": "displacement_fixed",
                        "target": {"kind": "node_set", "name": "missing_set"},
                        "dof": "123456",
                    }
                ],
            }
        )


def test_problem_schema_rejects_optimizer_task_without_objective_or_optimizer() -> None:
    with pytest.raises(ValueError, match="require an enabled optimizer specification"):
        ProblemSchema.model_validate(
            {
                "problem": {"id": "broken", "name": "broken"},
                "geometry": {
                    "source_type": "file",
                    "path": "inputs/model.bdf",
                    "file_format": "bdf",
                },
                "model": {
                    "type": "shell",
                    "input_source": "model_file",
                    "model_input_path": "inputs/model.bdf",
                },
                "analysis": {
                    "discipline": "structural",
                    "analysis_type": "static",
                },
                "execution": {"initial_tasks": ["fea", "optimizer"]},
                "constraints": [{"kind": "max_stress", "limit": 180.0}],
            }
        )
