import json
import shutil
from pathlib import Path

import pytest

from mass_town.config import WorkflowConfig
from mass_town.disciplines.topology import TopologyBackend, TopologyRequest, TopologyResult
from mass_town.disciplines.topology.registry import BACKEND_LOADERS as TOPOLOGY_BACKEND_LOADERS
from mass_town.llm import (
    LLMBackend,
    LLMBackendError,
    LLMRequest,
    OllamaLLMBackend,
    apply_rerun_decision,
)
from mass_town.models.outer_loop import AttemptSummary, DisciplineAssessment, RerunDecision
from mass_town.runtime.outer_loop_runtime import OuterLoopRuntime


class MalformedLLMBackend(LLMBackend):
    def ensure_available(self, config: object) -> None:
        del config

    def generate_text(self, config: object, request: LLMRequest) -> str:
        del config, request
        return "not-json"


class RepeatingLLMBackend(LLMBackend):
    def ensure_available(self, config: object) -> None:
        del config

    def generate_text(self, config: object, request: LLMRequest) -> str:
        del config
        if request.response_model is DisciplineAssessment:
            return json.dumps(
                {
                    "discipline": request.role,
                    "status": "warning",
                    "summary": "No strong conclusion.",
                    "confidence": 0.7,
                    "evidence": [],
                    "diagnostic_codes": [],
                }
            )
        return json.dumps(
            {
                "decision": "rerun",
                "confidence": 0.9,
                "summary": "Repeat the same override.",
                "discipline_findings": [],
                "overrides": [
                    {
                        "discipline": "chief_engineer",
                        "path": "max_iterations",
                        "value": 8,
                        "reason": "Repeat for validator coverage.",
                    }
                ],
            }
        )


class ConvergingTopologyBackend(TopologyBackend):
    name = "structured_plane_stress"

    def is_available(self) -> bool:
        return True

    def availability_reason(self) -> str | None:
        return None

    def run_optimization(self, request: TopologyRequest) -> TopologyResult:
        summary_path = request.report_directory / "topology-summary.json"
        converged = request.config.optimizer.max_iterations >= 10
        summary_path.write_text(
            json.dumps(
                {
                    "max_iterations": request.config.optimizer.max_iterations,
                    "converged": converged,
                }
            )
            + "\n"
        )
        return TopologyResult(
            backend_name=self.name,
            converged=converged,
            objective=1.2 if converged else 2.0,
            volume_fraction=request.config.volume_fraction,
            max_density_change=0.01 if converged else 0.2,
            beta=request.config.projection.beta,
            iteration_count=request.config.optimizer.max_iterations,
            result_files=[summary_path],
            summary_path=summary_path,
            failure_reason=None if converged else "Iteration limit reached before convergence.",
        )


class _FakeHTTPResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb


def _write_structural_project(project_dir: Path, *, llm_backend: str = "mock") -> None:
    project_dir.mkdir()
    (project_dir / "config.yaml").write_text(
        "\n".join(
            [
                "max_iterations: 3",
                "allowable_stress: 180.0",
                "llm:",
                "  enabled: true",
                f"  backend: {llm_backend}",
                "  model: mock-local",
                "meshing:",
                "  tool: mock",
                "  target_quality: 0.75",
                "fea:",
                "  tool: mock",
                "  model_input_path: analysis/model.bdf",
                "initial_tasks:",
                "  - geometry",
                "  - mesh",
                "  - fea",
                "  - optimizer",
                "",
            ]
        )
    )
    (project_dir / "design_state.yaml").write_text(
        "\n".join(
            [
                "run_id: llm-outer-loop",
                "problem_name: llm_outer_loop_problem",
                "status: pending",
                "iteration: 0",
                "design_variables:",
                "  thickness: 0.6",
                "  length: 10.0",
                "  width: 4.0",
                "loads:",
                "  force: 120.0",
                "constraints:",
                "  max_stress: 180.0",
                "diagnostics: []",
                "decision_history: []",
                "artifacts: []",
                "task_history: []",
                "",
            ]
        )
    )
    analysis_dir = project_dir / "analysis"
    analysis_dir.mkdir()
    (analysis_dir / "model.bdf").write_text("CEND\nBEGIN BULK\nENDDATA\n")


def test_workflow_config_requires_llm_model_when_enabled() -> None:
    with pytest.raises(ValueError, match="llm.model is required"):
        WorkflowConfig.model_validate({"llm": {"enabled": True}})


def test_workflow_config_rejects_invalid_allowed_override_paths() -> None:
    with pytest.raises(ValueError, match="Unsupported llm.allowed_override_paths"):
        WorkflowConfig.model_validate(
            {
                "llm": {
                    "enabled": True,
                    "backend": "mock",
                    "model": "mock-local",
                    "allowed_override_paths": ["fea.model_input_path"],
                }
            }
        )


def test_ollama_backend_parses_valid_structured_response(monkeypatch) -> None:
    responses = iter(
        [
            {"models": [{"name": "llama3.1:8b"}]},
            {
                "response": json.dumps(
                    {
                        "discipline": "structures",
                        "status": "success",
                        "summary": "Analysis converged cleanly.",
                        "confidence": 0.9,
                        "evidence": ["analysis passed"],
                        "diagnostic_codes": [],
                    }
                )
            },
        ]
    )

    def _fake_urlopen(req: object) -> _FakeHTTPResponse:
        del req
        return _FakeHTTPResponse(next(responses))

    monkeypatch.setattr("mass_town.llm.backends.request.urlopen", _fake_urlopen)
    config = WorkflowConfig.model_validate(
        {"llm": {"enabled": True, "backend": "ollama", "model": "llama3.1:8b"}}
    )
    backend = OllamaLLMBackend()
    backend.ensure_available(config.llm)

    result = backend.generate_structured(
        config.llm,
        LLMRequest(
            role="structures",
            prompt="return json",
            payload={},
            response_model=DisciplineAssessment,
        ),
        DisciplineAssessment,
    )

    assert result.status == "success"
    assert result.confidence == pytest.approx(0.9)


def test_ollama_backend_reports_missing_model(monkeypatch) -> None:
    def _fake_urlopen(req: object) -> _FakeHTTPResponse:
        del req
        return _FakeHTTPResponse({"models": [{"name": "other-model"}]})

    monkeypatch.setattr("mass_town.llm.backends.request.urlopen", _fake_urlopen)
    config = WorkflowConfig.model_validate(
        {"llm": {"enabled": True, "backend": "ollama", "model": "llama3.1:8b"}}
    )

    with pytest.raises(LLMBackendError, match="is not available"):
        OllamaLLMBackend().ensure_available(config.llm)


def test_apply_rerun_decision_rejects_repeated_override_set() -> None:
    config = WorkflowConfig.model_validate(
        {
            "llm": {
                "enabled": True,
                "backend": "mock",
                "model": "mock-local",
                "max_repeat_action_count": 2,
            }
        }
    )
    summary = AttemptSummary(
        base_run_id="base",
        attempt_index=2,
        attempt_run_id="base-attempt-02",
        inner_status="failed",
        feasible=False,
        iteration_count=3,
        config_snapshot=config.model_dump(mode="json"),
    )
    decision = RerunDecision.model_validate(
        {
            "decision": "rerun",
            "confidence": 0.9,
            "summary": "Increase max iterations.",
            "discipline_findings": [],
            "overrides": [
                {
                    "discipline": "chief_engineer",
                    "path": "max_iterations",
                    "value": 8,
                    "reason": "Need more iterations.",
                }
            ],
        }
    )

    try:
        apply_rerun_decision(
            config,
            summary,
            decision,
            [
                (("chief_engineer", "max_iterations", "8"),),
                (("chief_engineer", "max_iterations", "8"),),
            ],
        )
    except Exception as exc:  # noqa: BLE001
        assert "too many times" in str(exc)
    else:
        raise AssertionError("Expected repeated override validation to fail.")


def test_outer_loop_runtime_reruns_and_preserves_checked_in_inputs(tmp_path: Path) -> None:
    project_dir = tmp_path / "outer-loop-project"
    _write_structural_project(project_dir)

    original_state = (project_dir / "design_state.yaml").read_text()
    original_config = (project_dir / "config.yaml").read_text()

    runtime = OuterLoopRuntime(WorkflowConfig.from_file(project_dir / "config.yaml"))
    state = runtime.run(project_dir / "design_state.yaml", project_dir)

    assert state.run_id == "llm-outer-loop"
    assert state.status == "recovered"
    assert (project_dir / "config.yaml").read_text() == original_config
    assert (project_dir / "design_state.yaml").read_text() == original_state
    assert (
        project_dir
        / "results"
        / "llm-outer-loop"
        / "outer_loop"
        / "attempts"
        / "attempt-001"
        / "design_state.yaml"
    ).exists()
    session_summary = json.loads(
        (project_dir / "results" / "llm-outer-loop" / "outer_loop" / "outer_loop_summary.json").read_text()
    )
    assert session_summary["status"] == "recovered"
    assert session_summary["total_attempts"] == 2


def test_checked_in_llm_example_runs_end_to_end(tmp_path: Path) -> None:
    source = Path("examples/llm_outer_loop_mock_problem")
    project_dir = tmp_path / "llm_outer_loop_mock_problem"
    shutil.copytree(source, project_dir)

    runtime = OuterLoopRuntime(WorkflowConfig.from_file(project_dir / "config.yaml"))
    state = runtime.run(project_dir / "design_state.yaml", project_dir)

    assert state.status == "recovered"
    session_summary = json.loads(
        (project_dir / "results" / "llm-outer-loop" / "outer_loop" / "outer_loop_summary.json").read_text()
    )
    assert session_summary["total_attempts"] == 2


def test_outer_loop_runtime_escalates_on_malformed_llm_output(tmp_path: Path) -> None:
    project_dir = tmp_path / "malformed-project"
    _write_structural_project(project_dir, llm_backend="mock")

    runtime = OuterLoopRuntime(
        WorkflowConfig.from_file(project_dir / "config.yaml"),
        llm_backend=MalformedLLMBackend(),
    )
    state = runtime.run(project_dir / "design_state.yaml", project_dir)

    assert state.status == "escalated"
    decision_data = json.loads(
        (
            project_dir
            / "results"
            / "llm-outer-loop"
            / "outer_loop"
            / "attempts"
            / "attempt-001"
            / "chief_decision.json"
        ).read_text()
    )
    assert decision_data["valid"] is False


def test_outer_loop_runtime_escalates_after_repeating_same_override(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "repeat-project"
    _write_structural_project(project_dir, llm_backend="mock")

    runtime = OuterLoopRuntime(
        WorkflowConfig.from_file(project_dir / "config.yaml"),
        llm_backend=RepeatingLLMBackend(),
    )
    state = runtime.run(project_dir / "design_state.yaml", project_dir)

    assert state.status == "escalated"


def test_outer_loop_runtime_can_rerun_topology(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(
        TOPOLOGY_BACKEND_LOADERS,
        "structured_plane_stress",
        lambda: ConvergingTopologyBackend(),
    )
    project_dir = tmp_path / "topology-project"
    project_dir.mkdir()
    (project_dir / "config.yaml").write_text(
        "\n".join(
            [
                "llm:",
                "  enabled: true",
                "  backend: mock",
                "  model: mock-local",
                "topology:",
                "  tool: structured_plane_stress",
                "  optimizer:",
                "    max_iterations: 2",
                "initial_tasks:",
                "  - topology",
                "",
            ]
        )
    )
    (project_dir / "design_state.yaml").write_text(
        "\n".join(
            [
                "run_id: topology-outer-loop",
                "problem_name: topology_outer_loop_problem",
                "status: pending",
                "iteration: 0",
                "design_variables: {}",
                "diagnostics: []",
                "decision_history: []",
                "artifacts: []",
                "task_history: []",
                "",
            ]
        )
    )

    runtime = OuterLoopRuntime(WorkflowConfig.from_file(project_dir / "config.yaml"))
    state = runtime.run(project_dir / "design_state.yaml", project_dir)

    assert state.status == "recovered"
    session_summary = json.loads(
        (
            project_dir
            / "results"
            / "topology-outer-loop"
            / "outer_loop"
            / "outer_loop_summary.json"
        ).read_text()
    )
    assert session_summary["total_attempts"] == 2
