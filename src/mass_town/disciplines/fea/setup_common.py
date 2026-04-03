from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


NodeSelectorAxis = Literal["x", "y", "z"]
NodeSelectorExtreme = Literal["min", "max"]
LoadDistribution = Literal["equal"]


class FEABoundingBoxNodeSelector(BaseModel):
    axis: NodeSelectorAxis
    extreme: NodeSelectorExtreme
    tolerance: float = 1e-6

    @field_validator("tolerance")
    @classmethod
    def _validate_tolerance(cls, value: float) -> float:
        if float(value) <= 0.0:
            raise ValueError("Bounding-box selector tolerance must be positive.")
        return float(value)


class FEABoundaryCondition(BaseModel):
    node_set: str
    dof: str

    @field_validator("node_set", "dof")
    @classmethod
    def _require_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("FEA setup values must not be empty.")
        return stripped

    @field_validator("dof")
    @classmethod
    def _validate_dof(cls, value: str) -> str:
        if any(character not in "123456" for character in value):
            raise ValueError("Boundary-condition DOF strings may only contain digits 1-6.")
        return value


class FEALoad(BaseModel):
    node_set: str
    load_key: str
    direction: tuple[float, float, float]
    distribution: LoadDistribution = "equal"
    metadata: dict[str, str | float | int | bool] = Field(default_factory=dict)

    @field_validator("node_set", "load_key")
    @classmethod
    def _require_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("FEA setup values must not be empty.")
        return stripped

    @field_validator("direction")
    @classmethod
    def _validate_direction(
        cls,
        value: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        if len(value) != 3:
            raise ValueError("Load directions must contain exactly three components.")
        if all(abs(float(component)) <= 1e-12 for component in value):
            raise ValueError("Load directions must not be the zero vector.")
        return tuple(float(component) for component in value)
