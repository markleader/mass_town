from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TypeVar
from urllib import error, parse, request

from pydantic import BaseModel

from mass_town.config import LLMConfig
from mass_town.models.outer_loop import AttemptSummary, DisciplineAssessment, RerunDecision

ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMBackendError(RuntimeError):
    """Raised when the configured LLM backend is unavailable or returns invalid output."""


@dataclass(frozen=True)
class LLMRequest:
    role: str
    prompt: str
    payload: dict[str, object]
    response_model: type[BaseModel]


class LLMBackend(ABC):
    @abstractmethod
    def ensure_available(self, config: LLMConfig) -> None:
        raise NotImplementedError

    @abstractmethod
    def generate_text(self, config: LLMConfig, request: LLMRequest) -> str:
        raise NotImplementedError

    def generate_structured(self, config: LLMConfig, request_obj: LLMRequest, response_model: type[ModelT]) -> ModelT:
        raw_text = self.generate_text(config, request_obj)
        try:
            return response_model.model_validate_json(_extract_json(raw_text))
        except Exception as exc:  # noqa: BLE001
            raise LLMBackendError(f"LLM returned invalid structured output: {exc}") from exc


def _extract_json(raw_text: str) -> str:
    stripped = raw_text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()
    return stripped


class OllamaLLMBackend(LLMBackend):
    def ensure_available(self, config: LLMConfig) -> None:
        url = parse.urljoin(_endpoint_base(config.endpoint), "api/tags")
        try:
            payload = _post_json(url, None)
        except LLMBackendError:
            payload = _get_json(url)

        model_names = {model.get("name") for model in payload.get("models", []) if model.get("name")}
        if config.model not in model_names:
            available = ", ".join(sorted(model_names)) or "none"
            raise LLMBackendError(
                f"Ollama model {config.model!r} is not available at {config.endpoint}. Available models: {available}."
            )

    def generate_text(self, config: LLMConfig, request_obj: LLMRequest) -> str:
        url = parse.urljoin(_endpoint_base(config.endpoint), "api/generate")
        payload = _post_json(
            url,
            {
                "model": config.model,
                "prompt": request_obj.prompt,
                "stream": False,
            },
        )
        response_text = payload.get("response")
        if not isinstance(response_text, str):
            raise LLMBackendError("Ollama response did not contain a text completion.")
        return response_text


class MockLLMBackend(LLMBackend):
    def ensure_available(self, config: LLMConfig) -> None:
        del config

    def generate_text(self, config: LLMConfig, request_obj: LLMRequest) -> str:
        del config
        payload = request_obj.payload
        if request_obj.response_model is DisciplineAssessment:
            attempt = AttemptSummary.model_validate(payload["attempt_summary"])
            assessment = _mock_assessment(request_obj.role, attempt)
            return json.dumps(assessment.model_dump(mode="json"), indent=2, sort_keys=True)
        if request_obj.response_model is RerunDecision:
            attempt = AttemptSummary.model_validate(payload["attempt_summary"])
            findings = [
                DisciplineAssessment.model_validate(item)
                for item in payload.get("discipline_findings", [])
            ]
            decision = _mock_decision(attempt, findings)
            return json.dumps(decision.model_dump(mode="json"), indent=2, sort_keys=True)
        raise LLMBackendError(f"Mock backend does not support response model {request_obj.response_model!r}.")


def _mock_assessment(role: str, attempt: AttemptSummary) -> DisciplineAssessment:
    task_map = {
        "geometry": "geometry",
        "meshing": "mesh",
        "structures": "fea",
        "optimizer": "optimizer",
        "topology": "topology",
    }
    task_name = task_map.get(role)
    diagnostics = attempt.diagnostics_by_task.get(task_name or "", [])
    if task_name is None:
        return DisciplineAssessment(
            discipline=role,
            status="not_applicable",
            summary="Role is not applicable for this attempt.",
            confidence=1.0,
        )
    if diagnostics:
        return DisciplineAssessment(
            discipline=role,
            status="failure",
            summary=diagnostics[0].message,
            confidence=0.92,
            evidence=[diagnostic.message for diagnostic in diagnostics[:3]],
            diagnostic_codes=[diagnostic.code for diagnostic in diagnostics],
        )
    status = "success" if attempt.inner_status == "recovered" else "warning"
    return DisciplineAssessment(
        discipline=role,
        status=status,
        summary=f"No blocking {role} diagnostics detected.",
        confidence=0.85 if status == "success" else 0.7,
    )


def _mock_decision(
    attempt: AttemptSummary,
    findings: list[DisciplineAssessment],
) -> RerunDecision:
    if attempt.feasible and attempt.inner_status == "recovered":
        return RerunDecision(
            decision="accept",
            confidence=0.95,
            summary="Attempt recovered and met the deterministic feasibility contract.",
            discipline_findings=findings,
            overrides=[],
        )

    all_codes = {
        code
        for diagnostics in attempt.diagnostics_by_task.values()
        for code in (diagnostic.code for diagnostic in diagnostics)
    }
    config_snapshot = attempt.config_snapshot
    max_iterations = int(config_snapshot.get("max_iterations", 0) or 0)
    if "runtime.max_iterations_exceeded" in all_codes and max_iterations < 8:
        return RerunDecision(
            decision="rerun",
            confidence=0.9,
            summary="Increase max_iterations so the deterministic workflow can complete its requeue cycle.",
            discipline_findings=findings,
            overrides=[
                {
                    "discipline": "chief_engineer",
                    "path": "max_iterations",
                    "value": max(8, max_iterations + 4),
                    "reason": "The previous attempt stopped at the configured iteration limit.",
                }
            ],
        )

    topology = config_snapshot.get("topology")
    topology_iterations = attempt.key_metrics.get("topology_iteration_count")
    if isinstance(topology, dict) and isinstance(topology_iterations, (int, float)):
        optimizer = topology.get("optimizer") or {}
        current_limit = int(optimizer.get("max_iterations", 0) or 0)
        if attempt.inner_status != "recovered" and current_limit and topology_iterations >= current_limit:
            return RerunDecision(
                decision="rerun",
                confidence=0.88,
                summary="Increase topology max_iterations to allow additional optimization steps.",
                discipline_findings=findings,
                overrides=[
                    {
                        "discipline": "topology",
                        "path": "topology.optimizer.max_iterations",
                        "value": current_limit + 20,
                        "reason": "Topology optimization hit the configured iteration limit before converging.",
                    }
                ],
            )

    if "mesh.poor_quality" in all_codes:
        meshing = config_snapshot.get("meshing") or {}
        target_quality = float(meshing.get("target_quality", 0.75))
        return RerunDecision(
            decision="rerun",
            confidence=0.85,
            summary="Relax the meshing target quality to a validated lower threshold.",
            discipline_findings=findings,
            overrides=[
                {
                    "discipline": "meshing",
                    "path": "meshing.target_quality",
                    "value": max(0.1, round(target_quality - 0.1, 3)),
                    "reason": "The last mesh missed the requested quality threshold.",
                }
            ],
        )

    return RerunDecision(
        decision="escalate",
        confidence=0.8,
        summary="No safe bounded override was identified automatically.",
        discipline_findings=findings,
        overrides=[],
    )


def resolve_llm_backend(name: str) -> LLMBackend:
    normalized = name.strip().lower()
    if normalized == "ollama":
        return OllamaLLMBackend()
    if normalized == "mock":
        return MockLLMBackend()
    raise LLMBackendError(f"Unknown LLM backend {name!r}.")


def _endpoint_base(endpoint: str) -> str:
    return endpoint.rstrip("/") + "/"


def _get_json(url: str) -> dict[str, object]:
    try:
        with request.urlopen(url) as response:
            return json.loads(response.read().decode("utf-8"))
    except (error.URLError, json.JSONDecodeError) as exc:
        raise LLMBackendError(str(exc)) from exc


def _post_json(url: str, payload: dict[str, object] | None) -> dict[str, object]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data is not None else {}
    try:
        with request.urlopen(request.Request(url, data=data, headers=headers, method="POST")) as response:
            return json.loads(response.read().decode("utf-8"))
    except (error.URLError, json.JSONDecodeError) as exc:
        raise LLMBackendError(str(exc)) from exc
