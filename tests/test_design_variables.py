from pathlib import Path

import pytest
from pydantic import ValidationError

from mass_town.design_variables import (
    DesignVariableAssignments,
    DesignVariableBounds,
    DesignVariableContext,
    DesignVariableDefinition,
    DesignVariableMappingError,
    DesignVariableType,
    bdf_design_variable_context,
    ensure_unique_design_variable_definitions,
    map_design_variables_to_analysis,
    resolved_design_variable_definitions,
    resolved_design_variable_values,
)


def _scalar_definition() -> DesignVariableDefinition:
    return DesignVariableDefinition(
        id="thickness",
        name="Global Thickness",
        type=DesignVariableType.scalar_thickness,
        initial_value=0.8,
        bounds=DesignVariableBounds(lower=0.1, upper=2.0),
    )


def test_design_variable_definition_validates_scalar_region_and_element_modes() -> None:
    scalar = _scalar_definition()
    region = DesignVariableDefinition(
        id="skin_t",
        name="Skin Thickness",
        type=DesignVariableType.region_thickness,
        initial_value=0.6,
        bounds=DesignVariableBounds(lower=0.1, upper=1.2),
        region="skin",
    )
    element = DesignVariableDefinition(
        id="local_t",
        name="Local Thickness",
        type=DesignVariableType.element_thickness,
        initial_value=0.5,
        bounds=DesignVariableBounds(lower=0.1, upper=1.0),
        element_ids=[4, 2, 2, 3],
    )

    assert scalar.type == DesignVariableType.scalar_thickness
    assert region.region == "skin"
    assert element.element_ids == [2, 3, 4]


def test_design_variable_definition_rejects_invalid_bounds_and_missing_selectors() -> None:
    with pytest.raises(ValidationError):
        DesignVariableDefinition(
            id="bad_bounds",
            name="Bad Bounds",
            type=DesignVariableType.scalar_thickness,
            initial_value=3.0,
            bounds=DesignVariableBounds(lower=0.1, upper=2.0),
        )

    with pytest.raises(ValidationError):
        DesignVariableDefinition(
            id="missing_region",
            name="Missing Region",
            type=DesignVariableType.region_thickness,
            initial_value=0.5,
            bounds=DesignVariableBounds(lower=0.1, upper=1.0),
        )

    with pytest.raises(ValidationError):
        DesignVariableDefinition(
            id="missing_elements",
            name="Missing Elements",
            type=DesignVariableType.element_thickness,
            initial_value=0.5,
            bounds=DesignVariableBounds(lower=0.1, upper=1.0),
        )


def test_ensure_unique_design_variable_definitions_rejects_duplicate_ids_and_names() -> None:
    first = _scalar_definition()
    duplicate_id = DesignVariableDefinition(
        id="thickness",
        name="Regional",
        type=DesignVariableType.region_thickness,
        initial_value=0.5,
        bounds=DesignVariableBounds(lower=0.1, upper=1.0),
        region="skin",
    )
    with pytest.raises(ValueError):
        ensure_unique_design_variable_definitions([first, duplicate_id])

    duplicate_name = DesignVariableDefinition(
        id="other_id",
        name="Global Thickness",
        type=DesignVariableType.region_thickness,
        initial_value=0.5,
        bounds=DesignVariableBounds(lower=0.1, upper=1.0),
        region="skin",
    )
    with pytest.raises(ValueError):
        ensure_unique_design_variable_definitions([first, duplicate_name])


def test_mapping_layer_groups_assignments_by_scope() -> None:
    definitions = [
        _scalar_definition(),
        DesignVariableDefinition(
            id="skin_t",
            name="Skin Thickness",
            type=DesignVariableType.region_thickness,
            initial_value=0.6,
            bounds=DesignVariableBounds(lower=0.1, upper=2.0),
            region="skin",
        ),
        DesignVariableDefinition(
            id="elem_t",
            name="Element Thickness",
            type=DesignVariableType.element_thickness,
            initial_value=0.7,
            bounds=DesignVariableBounds(lower=0.1, upper=2.0),
            element_ids=[10, 11],
        ),
    ]
    context = DesignVariableContext(region_names={"skin", "spar"}, element_ids={10, 11, 12})
    mapped = map_design_variables_to_analysis(
        definitions,
        {"thickness": 0.9, "skin_t": 0.65, "elem_t": 0.55},
        context,
    )

    assert isinstance(mapped, DesignVariableAssignments)
    assert mapped.global_values == {"thickness": 0.9}
    assert mapped.region_values == {"skin": 0.65}
    assert mapped.element_values == {10: 0.55, 11: 0.55}
    assert mapped.active_values == {"thickness": 0.9, "skin_t": 0.65, "elem_t": 0.55}


def test_mapping_layer_reports_unknown_regions_and_elements() -> None:
    region_definition = DesignVariableDefinition(
        id="skin_t",
        name="Skin Thickness",
        type=DesignVariableType.region_thickness,
        initial_value=0.6,
        bounds=DesignVariableBounds(lower=0.1, upper=2.0),
        region="skin",
    )
    with pytest.raises(DesignVariableMappingError):
        map_design_variables_to_analysis(
            [region_definition],
            {"skin_t": 0.7},
            DesignVariableContext(region_names={"spar"}, element_ids=set()),
        )

    element_definition = DesignVariableDefinition(
        id="elem_t",
        name="Element Thickness",
        type=DesignVariableType.element_thickness,
        initial_value=0.6,
        bounds=DesignVariableBounds(lower=0.1, upper=2.0),
        element_ids=[1, 2],
    )
    with pytest.raises(DesignVariableMappingError):
        map_design_variables_to_analysis(
            [element_definition],
            {"elem_t": 0.7},
            DesignVariableContext(region_names=set(), element_ids={1}),
        )


def test_resolve_definitions_falls_back_to_legacy_thickness() -> None:
    definitions = resolved_design_variable_definitions([], {"thickness": 1.25})
    values = resolved_design_variable_values(definitions, {"thickness": 1.25})

    assert len(definitions) == 1
    assert definitions[0].id == "thickness"
    assert definitions[0].type == DesignVariableType.scalar_thickness
    assert values["thickness"] == 1.25


def test_bdf_design_variable_context_extracts_regions_and_elements(tmp_path: Path) -> None:
    bdf_path = tmp_path / "model.bdf"
    bdf_path.write_text(
        "\n".join(
            [
                "$ REGION pid=1 gmsh_id=10 kind=shell name=skin",
                "$ REGION pid=2 gmsh_id=20 kind=shell name=spar",
                "CEND",
                "BEGIN BULK",
                "CTRIA3,10,1,1,2,3",
                "CQUAD4,11,2,1,2,3,4",
                "ENDDATA",
            ]
        )
        + "\n"
    )

    context = bdf_design_variable_context(bdf_path)
    assert context.region_names == {"skin", "spar"}
    assert context.element_ids == {10, 11}


def test_bdf_design_variable_context_handles_fixed_width_cards_and_pid_regions(tmp_path: Path) -> None:
    bdf_path = tmp_path / "model.bdf"
    bdf_path.write_text(
        "\n".join(
            [
                "CEND",
                "BEGIN BULK",
                "CQUAD4         1       7       1       2      33      32",
                "CQUAD4         2       8       2       3      34      33",
                "ENDDATA",
            ]
        )
        + "\n"
    )

    context = bdf_design_variable_context(bdf_path)
    assert context.region_names == {"pid_7", "pid_8"}
    assert context.element_ids == {1, 2}
