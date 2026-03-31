from __future__ import annotations

from enum import Enum
from pathlib import Path
import re
from typing import Mapping

from pydantic import BaseModel, Field, model_validator


class DesignVariableType(str, Enum):
    scalar_thickness = "scalar_thickness"
    region_thickness = "region_thickness"
    element_thickness = "element_thickness"


class DesignVariableBounds(BaseModel):
    lower: float
    upper: float

    @model_validator(mode="after")
    def _validate_bound_order(self) -> "DesignVariableBounds":
        if self.lower > self.upper:
            raise ValueError("Design variable bounds must satisfy lower <= upper.")
        return self


class DesignVariableDefinition(BaseModel):
    id: str
    name: str
    type: DesignVariableType
    initial_value: float
    bounds: DesignVariableBounds
    units: str = "model_unit"
    active: bool = True
    region: str | None = None
    element_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_definition(self) -> "DesignVariableDefinition":
        if self.bounds.lower > self.initial_value or self.initial_value > self.bounds.upper:
            raise ValueError(
                f"Initial value for design variable '{self.id}' must satisfy "
                "lower <= initial_value <= upper."
            )
        if self.type == DesignVariableType.scalar_thickness:
            if self.region is not None:
                raise ValueError("Scalar thickness design variables cannot define a region selector.")
            if self.element_ids:
                raise ValueError("Scalar thickness design variables cannot define element selectors.")
        elif self.type == DesignVariableType.region_thickness:
            if not self.region:
                raise ValueError("Region thickness design variables must define a region selector.")
            if self.element_ids:
                raise ValueError("Region thickness design variables cannot define element selectors.")
        elif self.type == DesignVariableType.element_thickness:
            if self.region is not None:
                raise ValueError("Element thickness design variables cannot define a region selector.")
            if not self.element_ids:
                raise ValueError("Element thickness design variables must define element selectors.")
            deduplicated = sorted({int(element_id) for element_id in self.element_ids})
            if any(element_id <= 0 for element_id in deduplicated):
                raise ValueError("Element thickness selectors must contain positive integer element IDs.")
            self.element_ids = deduplicated
        return self


class DesignVariableMappingError(ValueError):
    pass


class DesignVariableContext(BaseModel):
    region_names: set[str] = Field(default_factory=set)
    element_ids: set[int] = Field(default_factory=set)


class DesignVariableAssignments(BaseModel):
    global_values: dict[str, float] = Field(default_factory=dict)
    region_values: dict[str, float] = Field(default_factory=dict)
    element_values: dict[int, float] = Field(default_factory=dict)
    active_values: dict[str, float] = Field(default_factory=dict)


_REGION_COMMENT_PATTERN = re.compile(r"^\$\s+REGION\s+pid=(?P<pid>\d+).*\sname=(?P<name>\S+)\s*$")
_ELEMENT_CARD_PREFIXES = {"CTRIA3", "CTRIAR", "CQUAD4", "CQUADR", "CTETRA", "CHEXA"}


def ensure_unique_design_variable_definitions(
    definitions: list[DesignVariableDefinition],
) -> list[DesignVariableDefinition]:
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for definition in definitions:
        if definition.id in seen_ids:
            raise ValueError(f"Duplicate design variable id: '{definition.id}'.")
        if definition.name in seen_names:
            raise ValueError(f"Duplicate design variable name: '{definition.name}'.")
        seen_ids.add(definition.id)
        seen_names.add(definition.name)
    return definitions


def resolved_design_variable_definitions(
    configured: list[DesignVariableDefinition],
    current_values: Mapping[str, float],
) -> list[DesignVariableDefinition]:
    if configured:
        return configured

    legacy_initial = float(current_values.get("thickness", 1.0))
    return [
        DesignVariableDefinition(
            id="thickness",
            name="thickness",
            type=DesignVariableType.scalar_thickness,
            initial_value=legacy_initial,
            bounds=DesignVariableBounds(lower=1e-6, upper=1_000.0),
            units="model_unit",
            active=True,
        )
    ]


def resolved_design_variable_values(
    definitions: list[DesignVariableDefinition],
    current_values: Mapping[str, float],
) -> dict[str, float]:
    resolved: dict[str, float] = {}
    for definition in definitions:
        value = float(current_values.get(definition.id, definition.initial_value))
        resolved[definition.id] = clamp_design_variable_value(definition, value)
    return resolved


def clamp_design_variable_value(definition: DesignVariableDefinition, value: float) -> float:
    return max(definition.bounds.lower, min(definition.bounds.upper, float(value)))


def map_design_variables_to_analysis(
    definitions: list[DesignVariableDefinition],
    current_values: Mapping[str, float],
    context: DesignVariableContext,
) -> DesignVariableAssignments:
    values = resolved_design_variable_values(definitions, current_values)
    mapped = DesignVariableAssignments()

    for definition in definitions:
        value = values[definition.id]
        if not definition.active:
            continue

        mapped.active_values[definition.id] = value
        if definition.type == DesignVariableType.scalar_thickness:
            if "thickness" in mapped.global_values:
                raise DesignVariableMappingError(
                    "Only one active scalar_thickness design variable is currently supported."
                )
            mapped.global_values["thickness"] = value
            continue

        if definition.type == DesignVariableType.region_thickness:
            region_name = str(definition.region)
            if region_name not in context.region_names:
                available_regions = ", ".join(sorted(context.region_names)) or "none"
                raise DesignVariableMappingError(
                    f"Region-thickness design variable '{definition.id}' targets unknown region "
                    f"'{region_name}'. Available regions: {available_regions}."
                )
            mapped.region_values[region_name] = value
            continue

        missing_elements = sorted(
            element_id for element_id in definition.element_ids if element_id not in context.element_ids
        )
        if missing_elements:
            preview = ",".join(str(element_id) for element_id in missing_elements[:10])
            raise DesignVariableMappingError(
                f"Element-thickness design variable '{definition.id}' references unknown element IDs: {preview}."
            )
        for element_id in definition.element_ids:
            mapped.element_values[element_id] = value

    return mapped


def bdf_design_variable_context(path: Path) -> DesignVariableContext:
    if not path.exists():
        return DesignVariableContext()

    region_names: set[str] = set()
    element_ids: set[int] = set()
    pid_ids: set[int] = set()
    for line in path.read_text().splitlines():
        normalized = line.strip()
        if not normalized:
            continue
        match = _REGION_COMMENT_PATTERN.match(normalized)
        if match:
            region_names.add(match.group("name"))
            continue
        if normalized.startswith("$"):
            continue
        parts = _split_bdf_fields(normalized)
        if len(parts) < 2:
            continue
        if parts[0].upper() not in _ELEMENT_CARD_PREFIXES:
            continue
        try:
            element_ids.add(int(parts[1]))
        except ValueError:
            continue
        if len(parts) > 2:
            try:
                pid_ids.add(int(parts[2]))
            except ValueError:
                pass

    if not region_names:
        region_names = {f"pid_{pid}" for pid in sorted(pid_ids)}

    return DesignVariableContext(region_names=region_names, element_ids=element_ids)


def _split_bdf_fields(line: str) -> list[str]:
    if "," in line:
        return [part.strip() for part in line.split(",") if part.strip()]
    return [part for part in line.split() if part]
