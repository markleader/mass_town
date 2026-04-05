from math import pi

import pytest

from mass_town.constraints import (
    ConstraintSet,
    aggregate_case_stresses,
    evaluate_minimum_buckling_load_factor_constraint,
    evaluate_minimum_natural_frequency_constraint,
    modal_eigenvalue_to_frequency_hz,
)


def test_ks_aggregation_is_at_least_the_max_case_stress() -> None:
    result = aggregate_case_stresses(
        {"gust": 120.0, "maneuver": 150.0},
        ConstraintSet.model_validate(
            {
                "aggregated_stress": {
                    "method": "ks",
                    "ks_weight": 25.0,
                }
            }
        ),
        180.0,
    )

    assert result is not None
    assert result.value is not None
    assert result.value >= 150.0
    assert result.controlling_case == "maneuver"


def test_pnorm_aggregation_is_monotone_with_increasing_case_stress() -> None:
    constraints = ConstraintSet.model_validate(
        {
            "aggregated_stress": {
                "method": "pnorm",
                "p": 8.0,
            }
        }
    )

    low_result = aggregate_case_stresses(
        {"gust": 100.0, "maneuver": 120.0},
        constraints,
        180.0,
    )
    high_result = aggregate_case_stresses(
        {"gust": 100.0, "maneuver": 140.0},
        constraints,
        180.0,
    )

    assert low_result is not None
    assert high_result is not None
    assert low_result.value is not None
    assert high_result.value is not None
    assert high_result.value > low_result.value


@pytest.mark.parametrize(
    ("constraints", "expected_allowable"),
    [
        (
            {
                "max_stress": 170.0,
                "aggregated_stress": {"method": "ks", "allowable": 160.0},
            },
            160.0,
        ),
        (
            {
                "max_stress": 170.0,
                "aggregated_stress": {"method": "ks"},
            },
            170.0,
        ),
        (
            {
                "aggregated_stress": {"method": "ks"},
            },
            180.0,
        ),
    ],
)
def test_aggregated_stress_allowable_precedence(
    constraints: dict[str, object],
    expected_allowable: float,
) -> None:
    result = aggregate_case_stresses(
        {"gust": 120.0, "maneuver": 150.0},
        ConstraintSet.model_validate(constraints),
        180.0,
    )

    assert result is not None
    assert result.allowable == expected_allowable


def test_minimum_buckling_load_factor_uses_requested_mode_and_controlling_case() -> None:
    result = evaluate_minimum_buckling_load_factor_constraint(
        {
            "gust": [4.0, 7.0],
            "maneuver": [2.5, 6.0],
        },
        ConstraintSet.model_validate(
            {
                "minimum_buckling_load_factor": {
                    "mode": 0,
                    "minimum": 3.0,
                }
            }
        ).minimum_buckling_load_factor,
    )

    assert result is not None
    assert result.quantity == "buckling_load_factor"
    assert result.value == pytest.approx(2.5)
    assert result.controlling_case == "maneuver"
    assert result.passed is False


def test_minimum_buckling_load_factor_can_pass_on_higher_mode() -> None:
    result = evaluate_minimum_buckling_load_factor_constraint(
        {
            "gust": [2.0, 5.5],
            "maneuver": [1.8, 4.2],
        },
        ConstraintSet.model_validate(
            {
                "minimum_buckling_load_factor": {
                    "mode": 1,
                    "minimum": 4.0,
                }
            }
        ).minimum_buckling_load_factor,
    )

    assert result is not None
    assert result.value == pytest.approx(4.2)
    assert result.controlling_case == "maneuver"
    assert result.passed is True


def test_modal_eigenvalue_to_frequency_hz_converts_from_radians_per_second() -> None:
    assert modal_eigenvalue_to_frequency_hz((2.0 * pi * 5.0) ** 2) == pytest.approx(5.0)


def test_minimum_natural_frequency_uses_requested_mode_and_controlling_case() -> None:
    result = evaluate_minimum_natural_frequency_constraint(
        {
            "gust": [(2.0 * pi * 12.0) ** 2, (2.0 * pi * 18.0) ** 2],
            "maneuver": [(2.0 * pi * 8.0) ** 2, (2.0 * pi * 16.0) ** 2],
        },
        ConstraintSet.model_validate(
            {
                "minimum_natural_frequency_hz": {
                    "mode": 0,
                    "minimum": 10.0,
                }
            }
        ).minimum_natural_frequency_hz,
    )

    assert result is not None
    assert result.quantity == "natural_frequency_hz"
    assert result.value == pytest.approx(8.0)
    assert result.controlling_case == "maneuver"
    assert result.passed is False
