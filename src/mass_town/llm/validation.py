from __future__ import annotations

import json
from collections import Counter

from mass_town.config import WorkflowConfig
from mass_town.models.outer_loop import AttemptSummary, OverrideProposal, RerunDecision


class OuterLoopValidationError(RuntimeError):
    """Raised when an LLM rerun decision is invalid or unsafe."""


def _path_is_allowed(path: str, allowed_patterns: list[str]) -> bool:
    for pattern in allowed_patterns:
        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            if path.startswith(prefix + ".") and len(path) > len(prefix) + 1:
                return True
            continue
        if path == pattern:
            return True
    return False


def _assert_path_applicable(config: WorkflowConfig, path: str) -> None:
    if path.startswith("topology.") and config.topology is None:
        raise OuterLoopValidationError("Topology overrides require a topology configuration.")
    if path.startswith("optimizer.settings.") and config.optimizer is None:
        raise OuterLoopValidationError("Optimizer overrides require an optimizer configuration.")
    if path.startswith("fea.buckling_setup.") and config.fea.analysis_type != "buckling":
        raise OuterLoopValidationError("Buckling overrides require buckling analysis_type.")
    if path.startswith("fea.modal_setup.") and config.fea.analysis_type != "modal":
        raise OuterLoopValidationError("Modal overrides require modal analysis_type.")


def _set_nested_value(data: dict[str, object], path: str, value: object) -> None:
    parts = path.split(".")
    cursor: dict[str, object] = data
    for part in parts[:-1]:
        next_value = cursor.get(part)
        if next_value is None:
            next_value = {}
            cursor[part] = next_value
        if not isinstance(next_value, dict):
            raise OuterLoopValidationError(f"Override path {path!r} does not address a mapping.")
        cursor = next_value
    cursor[parts[-1]] = value


def _normalized_signature(overrides: list[OverrideProposal]) -> tuple[tuple[str, str, str], ...]:
    normalized = [
        (override.discipline, override.path, json.dumps(override.value, sort_keys=True))
        for override in overrides
    ]
    return tuple(sorted(normalized))


def apply_rerun_decision(
    config: WorkflowConfig,
    summary: AttemptSummary,
    decision: RerunDecision,
    prior_override_signatures: list[tuple[tuple[str, str, str], ...]],
) -> tuple[WorkflowConfig | None, tuple[tuple[str, str, str], ...] | None]:
    if decision.confidence < config.llm.min_confidence:
        raise OuterLoopValidationError(
            f"Decision confidence {decision.confidence:.2f} is below min_confidence {config.llm.min_confidence:.2f}."
        )

    if decision.decision == "accept":
        if decision.overrides:
            raise OuterLoopValidationError("Accept decisions must not include overrides.")
        if summary.inner_status != "recovered":
            raise OuterLoopValidationError("Only recovered attempts may be accepted.")
        return None, None

    if decision.decision == "escalate":
        if decision.overrides:
            raise OuterLoopValidationError("Escalate decisions must not include overrides.")
        return None, None

    if not decision.overrides:
        raise OuterLoopValidationError("Rerun decisions must include at least one override.")

    for override in decision.overrides:
        if not _path_is_allowed(override.path, config.llm.allowed_override_paths):
            raise OuterLoopValidationError(f"Override path {override.path!r} is not allowed.")
        _assert_path_applicable(config, override.path)

    signature = _normalized_signature(decision.overrides)
    seen = Counter(prior_override_signatures)
    if seen[signature] >= config.llm.max_repeat_action_count:
        raise OuterLoopValidationError("The same override set has already been used too many times.")

    data = config.model_dump(mode="json")
    for override in decision.overrides:
        _set_nested_value(data, override.path, override.value)
    try:
        updated = WorkflowConfig.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        raise OuterLoopValidationError(str(exc)) from exc
    return updated, signature
