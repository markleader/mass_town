from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .setup_common import (
    FEABoundaryCondition,
    FEALoad,
)

ShellNodeSelectorType = Literal[
    "boundary_loop",
    "closest_node_to_centroid",
    "bounding_box_extreme",
]
ShellBoundaryLoopFamily = Literal["outer", "inner"]
ShellBoundaryLoopOrder = Literal["area", "centroid_x", "centroid_y"]


class FEAShellNodeSet(BaseModel):
    selector: ShellNodeSelectorType
    family: ShellBoundaryLoopFamily | None = None
    order_by: ShellBoundaryLoopOrder | None = None
    index: int | None = None
    axis: Literal["x", "y", "z"] | None = None
    extreme: Literal["min", "max"] | None = None
    tolerance: float = 1e-6

    @field_validator("index")
    @classmethod
    def _validate_index(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("Shell node-set selector index must be non-negative.")
        return value

    @field_validator("tolerance")
    @classmethod
    def _validate_tolerance(cls, value: float) -> float:
        if float(value) <= 0.0:
            raise ValueError("Shell node-set selector tolerance must be positive.")
        return float(value)

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

        if self.selector == "bounding_box_extreme":
            missing = [
                field_name
                for field_name in ("axis", "extreme")
                if getattr(self, field_name) is None
            ]
            if missing:
                missing_fields = ", ".join(missing)
                raise ValueError(
                    "Bounding-box shell node sets require the fields: "
                    f"{missing_fields}."
                )
            extra_fields = [
                field_name
                for field_name in ("family", "order_by", "index")
                if getattr(self, field_name) is not None
            ]
            if extra_fields:
                extras = ", ".join(extra_fields)
                raise ValueError(
                    "Bounding-box shell node sets do not accept boundary-loop fields: "
                    f"{extras}."
                )
            return self

        extra_fields = [
            field_name
            for field_name in ("family", "order_by", "index", "axis", "extreme")
            if getattr(self, field_name) is not None and field_name != "tolerance"
        ]
        if extra_fields:
            extras = ", ".join(extra_fields)
            raise ValueError(
                "Closest-node shell node sets do not accept boundary-loop fields: "
                f"{extras}."
            )
        return self


class FEAShellSetup(BaseModel):
    node_sets: dict[str, FEAShellNodeSet] = Field(default_factory=dict)
    boundary_conditions: list[FEABoundaryCondition] = Field(default_factory=list)
    loads: list[FEALoad] = Field(default_factory=list)

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
