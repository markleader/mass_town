from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


ShellNodeSelectorType = Literal["boundary_loop", "closest_node_to_centroid"]
ShellBoundaryLoopFamily = Literal["outer", "inner"]
ShellBoundaryLoopOrder = Literal["area", "centroid_x", "centroid_y"]
ShellLoadDistribution = Literal["equal"]


class FEAShellNodeSet(BaseModel):
    selector: ShellNodeSelectorType
    family: ShellBoundaryLoopFamily | None = None
    order_by: ShellBoundaryLoopOrder | None = None
    index: int | None = None

    @field_validator("index")
    @classmethod
    def _validate_index(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("Shell node-set selector index must be non-negative.")
        return value

    @model_validator(mode="after")
    def _validate_selector_fields(self) -> "FEAShellNodeSet":
        if self.selector == "boundary_loop":
            missing = [
                field_name
                for field_name in ("family", "order_by", "index")
                if getattr(self, field_name) is None
            ]
            if missing:
                missing_fields = ", ".join(missing)
                raise ValueError(
                    "Boundary-loop shell node sets require the fields: "
                    f"{missing_fields}."
                )
            return self

        extra_fields = [
            field_name
            for field_name in ("family", "order_by", "index")
            if getattr(self, field_name) is not None
        ]
        if extra_fields:
            extras = ", ".join(extra_fields)
            raise ValueError(
                "Closest-node shell node sets do not accept boundary-loop fields: "
                f"{extras}."
            )
        return self


class FEAShellBoundaryCondition(BaseModel):
    node_set: str
    dof: str

    @field_validator("node_set", "dof")
    @classmethod
    def _require_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Shell setup values must not be empty.")
        return stripped

    @field_validator("dof")
    @classmethod
    def _validate_dof(cls, value: str) -> str:
        if any(character not in "123456" for character in value):
            raise ValueError("Boundary-condition DOF strings may only contain digits 1-6.")
        return value


class FEAShellLoad(BaseModel):
    node_set: str
    load_key: str
    direction: tuple[float, float, float]
    distribution: ShellLoadDistribution = "equal"

    @field_validator("node_set", "load_key")
    @classmethod
    def _require_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Shell setup values must not be empty.")
        return stripped

    @field_validator("direction")
    @classmethod
    def _validate_direction(
        cls,
        value: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        if len(value) != 3:
            raise ValueError("Shell load directions must contain exactly three components.")
        if all(abs(float(component)) <= 1e-12 for component in value):
            raise ValueError("Shell load directions must not be the zero vector.")
        return tuple(float(component) for component in value)


class FEAShellSetup(BaseModel):
    node_sets: dict[str, FEAShellNodeSet] = Field(default_factory=dict)
    boundary_conditions: list[FEAShellBoundaryCondition] = Field(default_factory=list)
    loads: list[FEAShellLoad] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_references(self) -> "FEAShellSetup":
        available_node_sets = set(self.node_sets)
        referenced_node_sets = {
            item.node_set for item in [*self.boundary_conditions, *self.loads]
        }
        missing = sorted(referenced_node_sets - available_node_sets)
        if missing:
            missing_names = ", ".join(missing)
            raise ValueError(
                "Shell setup references unknown node sets: "
                f"{missing_names}."
            )
        return self
