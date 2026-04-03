from collections.abc import Mapping
from math import exp, log
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AggregatedStressConstraint(BaseModel):
    method: Literal["ks", "pnorm"] = "ks"
    source: Literal["load_cases"] = "load_cases"
    allowable: float | None = None
    ks_weight: float = 50.0
    p: float = 8.0

    @model_validator(mode="after")
    def _validate_parameters(self) -> "AggregatedStressConstraint":
        if self.ks_weight <= 0.0:
            raise ValueError("aggregated_stress.ks_weight must be positive.")
        if self.p <= 0.0:
            raise ValueError("aggregated_stress.p must be positive.")
        return self


class ConstraintSet(BaseModel):
    model_config = ConfigDict(extra="allow")

    max_stress: float | None = None
    aggregated_stress: AggregatedStressConstraint | None = None

    def __getitem__(self, key: str) -> object:
        return getattr(self, key)

    def __setitem__(self, key: str, value: object) -> None:
        if key == "aggregated_stress" and value is not None:
            value = AggregatedStressConstraint.model_validate(value)
        setattr(self, key, value)

    def get(self, key: str, default: object = None) -> object:
        return getattr(self, key, default)

    def items(self) -> list[tuple[str, object]]:
        return list(self.model_dump(mode="python", exclude_none=True).items())


class ResolvedAggregatedStressConstraint(BaseModel):
    method: Literal["ks", "pnorm"]
    source: Literal["load_cases"]
    allowable: float
    ks_weight: float = 50.0
    p: float = 8.0


class AggregatedStressResult(BaseModel):
    method: Literal["ks", "pnorm"]
    source: Literal["load_cases"]
    allowable: float
    value: float | None = None
    passed: bool = False
    controlling_case: str | None = None
    quality_summary_path: str | None = None


def resolve_aggregated_stress_constraint(
    constraints: ConstraintSet,
    default_allowable: float,
) -> ResolvedAggregatedStressConstraint | None:
    aggregated = constraints.aggregated_stress
    if aggregated is None:
        return None

    allowable = aggregated.allowable
    if allowable is None:
        allowable = constraints.max_stress
    if allowable is None:
        allowable = default_allowable

    return ResolvedAggregatedStressConstraint(
        method=aggregated.method,
        source=aggregated.source,
        allowable=float(allowable),
        ks_weight=aggregated.ks_weight,
        p=aggregated.p,
    )


def aggregate_case_stresses(
    case_stresses: Mapping[str, float | None],
    constraints: ConstraintSet,
    default_allowable: float,
    *,
    quality_summary_path: str | None = None,
) -> AggregatedStressResult | None:
    resolved = resolve_aggregated_stress_constraint(constraints, default_allowable)
    if resolved is None:
        return None

    valid_case_stresses = {
        case_name: float(stress)
        for case_name, stress in case_stresses.items()
        if stress is not None
    }
    controlling_case = (
        max(valid_case_stresses, key=valid_case_stresses.get)
        if valid_case_stresses
        else None
    )
    value = None
    if valid_case_stresses:
        value = _aggregate_stress_values(valid_case_stresses.values(), resolved)

    return AggregatedStressResult(
        method=resolved.method,
        source=resolved.source,
        allowable=resolved.allowable,
        value=value,
        passed=value is not None and value <= resolved.allowable,
        controlling_case=controlling_case,
        quality_summary_path=quality_summary_path,
    )


def _aggregate_stress_values(
    stress_values: Mapping[str, float] | list[float] | tuple[float, ...] | set[float],
    constraint: ResolvedAggregatedStressConstraint,
) -> float:
    if isinstance(stress_values, Mapping):
        values = [float(value) for value in stress_values.values()]
    else:
        values = [float(value) for value in stress_values]

    if not values:
        raise ValueError("At least one stress value is required for aggregation.")

    if constraint.method == "ks":
        max_value = max(values)
        return max_value + log(sum(exp(constraint.ks_weight * (value - max_value)) for value in values)) / constraint.ks_weight

    return sum(value**constraint.p for value in values) ** (1.0 / constraint.p)
