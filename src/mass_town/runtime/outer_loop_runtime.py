from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

import yaml

from mass_town.config import WorkflowConfig
from mass_town.llm import (
    LLMBackend,
    LLMBackendError,
    LLMRequest,
    OuterLoopValidationError,
    apply_rerun_decision,
    resolve_llm_backend,
)
from mass_town.llm.prompts import build_role_prompt
from mass_town.models.design_state import AnalysisState, DesignState, GeometryState, MeshState, TopologyState
from mass_town.models.outer_loop import (
    AttemptDelta,
    AttemptRecord,
    AttemptSummary,
    DiagnosticSummary,
    DisciplineAssessment,
    LogExcerpt,
    OuterLoopSessionSummary,
    RerunDecision,
)
from mass_town.runtime.local_runtime import LocalRuntime
from mass_town.runtime.runtime_interface import RuntimeInterface
from mass_town.storage.filesystem import ensure_directory
from mass_town.storage.run_registry import RunRegistry


class OuterLoopRuntime(RuntimeInterface):
    def __init__(
        self,
        config: WorkflowConfig,
        llm_backend: LLMBackend | None = None,
        run_registry: RunRegistry | None = None,
    ) -> None:
        self.config = config
        self.llm_backend = llm_backend or resolve_llm_backend(config.llm.backend)
        self.run_registry = run_registry or RunRegistry()

    def run(self, state_path: Path, run_root: Path) -> DesignState:
        base_state = DesignState.model_validate(yaml.safe_load(state_path.read_text()) or {})
        base_run_id = base_state.run_id
        outer_loop_dir = ensure_directory(run_root / "results" / base_run_id / "outer_loop")
        attempts_root = ensure_directory(outer_loop_dir / "attempts")
        outer_loop_log = outer_loop_dir / "outer_loop.log"
        self.run_registry.start_run(base_run_id, run_root)

        attempt_records: list[AttemptRecord] = []
        attempt_history: list[dict[str, str | int | float | bool | None]] = []
        prior_signatures: list[tuple[tuple[str, str, str], ...]] = []
        current_config = self.config
        current_seed_state = base_state
        final_attempt_state: DesignState | None = None
        final_status = "failed"
        stop_reason: str | None = None
        session_start = time.monotonic()

        try:
            self.llm_backend.ensure_available(current_config.llm)
        except LLMBackendError as exc:
            stop_reason = f"LLM backend unavailable: {exc}"
            final_status = "failed"
            session_summary = self._write_session_summary(
                outer_loop_dir=outer_loop_dir,
                base_run_id=base_run_id,
                status=final_status,
                attempt_records=attempt_records,
                final_attempt_state=final_attempt_state,
                session_seconds=time.monotonic() - session_start,
                stop_reason=stop_reason,
            )
            self.run_registry.finish_run(
                base_run_id,
                run_root,
                final_status,
                iteration_count=0,
                summary_path=str(session_summary.relative_to(run_root)),
            )
            self._append_log(outer_loop_log, stop_reason)
            return base_state.model_copy(update={"status": final_status})

        previous_summary: AttemptSummary | None = None
        for attempt_index in range(1, current_config.llm.max_attempts + 1):
            if time.monotonic() - session_start > current_config.llm.max_total_runtime_seconds:
                final_status = "failed"
                stop_reason = "Outer-loop runtime budget exhausted."
                break

            attempt_run_id = f"{base_run_id}-attempt-{attempt_index:02d}"
            attempt_dir = ensure_directory(attempts_root / f"attempt-{attempt_index:03d}")
            attempt_state_path = attempt_dir / "design_state.yaml"
            attempt_state = self._prepare_attempt_state(current_seed_state, attempt_run_id)
            self._write_state(attempt_state, attempt_state_path)
            self._append_log(outer_loop_log, f"attempt={attempt_index} run_id={attempt_run_id} event=start")

            final_attempt_state = LocalRuntime(current_config).run(attempt_state_path, run_root)
            attempt_summary = self._build_attempt_summary(
                base_run_id=base_run_id,
                attempt_index=attempt_index,
                attempt_run_id=attempt_run_id,
                config=current_config,
                state=final_attempt_state,
                run_root=run_root,
                history=attempt_history,
                previous_summary=previous_summary,
            )
            summary_path = attempt_dir / "attempt_summary.json"
            summary_path.write_text(json.dumps(attempt_summary.model_dump(mode="json"), indent=2, sort_keys=True) + "\n")

            assessments_path = attempt_dir / "discipline_assessments.json"
            decision_path = attempt_dir / "chief_decision.json"
            raw_decision: dict[str, object] | None = None
            try:
                assessments = self._run_assessments(
                    config=current_config,
                    summary=attempt_summary,
                )
                assessments_path.write_text(
                    json.dumps(
                        [assessment.model_dump(mode="json") for assessment in assessments],
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                )
                decision = self._run_chief_engineer(
                    config=current_config,
                    summary=attempt_summary,
                    assessments=assessments,
                )
                raw_decision = decision.model_dump(mode="json")
                updated_config, signature = apply_rerun_decision(
                    current_config,
                    attempt_summary,
                    decision,
                    prior_signatures,
                )
                decision_path.write_text(json.dumps(raw_decision, indent=2, sort_keys=True) + "\n")
            except (LLMBackendError, OuterLoopValidationError) as exc:
                final_status = "escalated"
                stop_reason = str(exc)
                if not assessments_path.exists():
                    assessments_path.write_text("[]\n")
                decision_path.write_text(
                    json.dumps(
                        {
                            "valid": False,
                            "error": str(exc),
                            "decision": raw_decision,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                )
                attempt_records.append(
                    AttemptRecord(
                        attempt_index=attempt_index,
                        attempt_run_id=attempt_run_id,
                        status=final_attempt_state.status,
                        feasible=attempt_summary.feasible,
                        summary_path=str(summary_path.relative_to(run_root)),
                        assessments_path=str(assessments_path.relative_to(run_root)),
                        decision_path=str(decision_path.relative_to(run_root)),
                    )
                )
                self._append_log(
                    outer_loop_log,
                    f"attempt={attempt_index} run_id={attempt_run_id} event=validation_failed reason={stop_reason}",
                )
                break

            attempt_records.append(
                AttemptRecord(
                    attempt_index=attempt_index,
                    attempt_run_id=attempt_run_id,
                    status=final_attempt_state.status,
                    feasible=attempt_summary.feasible,
                    summary_path=str(summary_path.relative_to(run_root)),
                    assessments_path=str(assessments_path.relative_to(run_root)),
                    decision_path=str(decision_path.relative_to(run_root)),
                )
            )
            attempt_history.append(
                {
                    "attempt_index": attempt_index,
                    "attempt_run_id": attempt_run_id,
                    "status": final_attempt_state.status,
                    "feasible": attempt_summary.feasible,
                    "decision": decision.decision,
                    "summary": decision.summary,
                }
            )
            previous_summary = attempt_summary

            if decision.decision == "accept":
                final_status = final_attempt_state.status
                stop_reason = decision.summary
                self._append_log(
                    outer_loop_log,
                    f"attempt={attempt_index} run_id={attempt_run_id} event=accepted",
                )
                break
            if decision.decision == "escalate":
                final_status = "escalated"
                stop_reason = decision.summary
                self._append_log(
                    outer_loop_log,
                    f"attempt={attempt_index} run_id={attempt_run_id} event=escalated",
                )
                break

            if updated_config is None or signature is None:
                final_status = "escalated"
                stop_reason = "Rerun decision did not produce an updated configuration."
                break

            current_config = updated_config
            prior_signatures.append(signature)
            current_seed_state = final_attempt_state
            self._append_log(
                outer_loop_log,
                f"attempt={attempt_index} run_id={attempt_run_id} event=rerun",
            )
        else:
            final_status = "failed"
            stop_reason = "Outer-loop max_attempts exhausted."

        if final_attempt_state is None:
            final_attempt_state = base_state.model_copy(update={"status": final_status})
        session_summary = self._write_session_summary(
            outer_loop_dir=outer_loop_dir,
            base_run_id=base_run_id,
            status=final_status,
            attempt_records=attempt_records,
            final_attempt_state=final_attempt_state,
            session_seconds=time.monotonic() - session_start,
            stop_reason=stop_reason,
        )
        self.run_registry.finish_run(
            base_run_id,
            run_root,
            final_status,
            iteration_count=len(attempt_records),
            summary_path=str(session_summary.relative_to(run_root)),
        )
        if stop_reason is not None:
            self._append_log(outer_loop_log, f"event=finished status={final_status} reason={stop_reason}")
        return final_attempt_state.model_copy(update={"run_id": base_run_id, "status": final_status})

    def _prepare_attempt_state(self, seed_state: DesignState, attempt_run_id: str) -> DesignState:
        prepared = seed_state.model_copy(deep=True)
        prepared.run_id = attempt_run_id
        prepared.status = "pending"
        prepared.iteration = 0
        prepared.geometry_state = GeometryState()
        prepared.mesh_state = MeshState()
        prepared.analysis_state = AnalysisState()
        prepared.topology_state = TopologyState()
        prepared.diagnostics = []
        prepared.decision_history = []
        prepared.artifacts = []
        prepared.task_history = []
        return prepared

    def _run_assessments(
        self,
        config: WorkflowConfig,
        summary: AttemptSummary,
    ) -> list[DisciplineAssessment]:
        roles = ["chief_engineer"]
        if config.topology is not None or "topology" in config.initial_tasks:
            roles.extend(["topology"])
        else:
            if "geometry" in config.initial_tasks:
                roles.append("geometry")
            if "mesh" in config.initial_tasks:
                roles.append("meshing")
            if "fea" in config.initial_tasks:
                roles.append("structures")
            if "optimizer" in config.initial_tasks:
                roles.append("optimizer")

        assessments: list[DisciplineAssessment] = []
        for role in roles:
            if role == "chief_engineer":
                continue
            payload = {"attempt_summary": summary.model_dump(mode="json")}
            prompt = build_role_prompt(role, payload, DisciplineAssessment, config)
            request_obj = LLMRequest(
                role=role,
                prompt=prompt,
                payload=payload,
                response_model=DisciplineAssessment,
            )
            assessments.append(self.llm_backend.generate_structured(config.llm, request_obj, DisciplineAssessment))
        return assessments

    def _run_chief_engineer(
        self,
        config: WorkflowConfig,
        summary: AttemptSummary,
        assessments: list[DisciplineAssessment],
    ) -> RerunDecision:
        payload = {
            "attempt_summary": summary.model_dump(mode="json"),
            "discipline_findings": [assessment.model_dump(mode="json") for assessment in assessments],
        }
        prompt = build_role_prompt("chief_engineer", payload, RerunDecision, config)
        request_obj = LLMRequest(
            role="chief_engineer",
            prompt=prompt,
            payload=payload,
            response_model=RerunDecision,
        )
        return self.llm_backend.generate_structured(config.llm, request_obj, RerunDecision)

    def _build_attempt_summary(
        self,
        *,
        base_run_id: str,
        attempt_index: int,
        attempt_run_id: str,
        config: WorkflowConfig,
        state: DesignState,
        run_root: Path,
        history: list[dict[str, str | int | float | bool | None]],
        previous_summary: AttemptSummary | None,
    ) -> AttemptSummary:
        run_summary_path = run_root / "results" / attempt_run_id / "reports" / "run_summary.json"
        run_summary = json.loads(run_summary_path.read_text()) if run_summary_path.exists() else {}
        diagnostics_by_task: dict[str, list[DiagnosticSummary]] = defaultdict(list)
        for diagnostic in state.diagnostics:
            diagnostics_by_task[diagnostic.task].append(
                DiagnosticSummary(
                    code=diagnostic.code,
                    message=diagnostic.message,
                    severity=diagnostic.severity,
                    task=diagnostic.task,
                    details=dict(diagnostic.details),
                )
            )

        key_metrics: dict[str, object] = {
            "mass": run_summary.get("mass"),
            "max_stress": run_summary.get("max_stress"),
            "displacement_norm": run_summary.get("displacement_norm"),
            "analysis_seconds": run_summary.get("analysis_seconds"),
            "objective": (run_summary.get("topology") or {}).get("objective"),
            "topology_iteration_count": (run_summary.get("topology") or {}).get("iteration_count"),
            "critical_eigenvalue": run_summary.get("critical_eigenvalue"),
            "critical_frequency_hz": run_summary.get("critical_frequency_hz"),
        }
        previous_delta = self._attempt_delta(previous_summary, key_metrics)
        log_excerpts = self._collect_log_excerpts(run_root, run_summary.get("artifact_paths") or {}, diagnostics_by_task)
        return AttemptSummary(
            base_run_id=base_run_id,
            attempt_index=attempt_index,
            attempt_run_id=attempt_run_id,
            inner_status=state.status,
            feasible=bool(run_summary.get("feasible")),
            iteration_count=state.iteration,
            analysis_type=run_summary.get("analysis_type"),
            problem_model_type=run_summary.get("problem_model_type"),
            diagnostics_by_task=dict(diagnostics_by_task),
            key_metrics=key_metrics,
            artifact_paths=dict(run_summary.get("artifact_paths") or {}),
            config_snapshot=config.model_dump(mode="json"),
            previous_attempt_delta=previous_delta,
            history=list(history),
            log_excerpts=log_excerpts,
        )

    def _attempt_delta(
        self,
        previous_summary: AttemptSummary | None,
        key_metrics: dict[str, object],
    ) -> AttemptDelta | None:
        if previous_summary is None:
            return None

        def _delta(key: str) -> float | None:
            current = key_metrics.get(key)
            previous = previous_summary.key_metrics.get(key)
            if isinstance(current, (int, float)) and isinstance(previous, (int, float)):
                return float(current) - float(previous)
            return None

        current_converged = key_metrics.get("objective") is not None
        previous_converged = previous_summary.key_metrics.get("objective") is not None
        return AttemptDelta(
            mass=_delta("mass"),
            max_stress=_delta("max_stress"),
            objective=_delta("objective"),
            analysis_seconds=_delta("analysis_seconds"),
            converged=current_converged if current_converged != previous_converged else None,
        )

    def _collect_log_excerpts(
        self,
        run_root: Path,
        artifact_paths: dict[str, str | None],
        diagnostics_by_task: dict[str, list[DiagnosticSummary]],
    ) -> list[LogExcerpt]:
        excerpts: list[LogExcerpt] = []
        task_to_artifact_key = {
            "mesh": "mesh_log",
            "fea": "analysis_log",
            "topology": "topology_log",
            "optimizer": "workflow_log",
            "runtime": "workflow_log",
            "geometry": "workflow_log",
        }
        for task, diagnostics in diagnostics_by_task.items():
            if not diagnostics:
                continue
            artifact_key = task_to_artifact_key.get(task)
            if artifact_key is None:
                continue
            relative_path = artifact_paths.get(artifact_key)
            if not relative_path:
                continue
            path = run_root / relative_path
            if not path.exists():
                continue
            lines = path.read_text().splitlines()
            excerpt = "\n".join(lines[-8:]).strip()
            if excerpt:
                excerpts.append(LogExcerpt(task=task, path=relative_path, excerpt=excerpt))
        return excerpts

    def _write_session_summary(
        self,
        *,
        outer_loop_dir: Path,
        base_run_id: str,
        status: str,
        attempt_records: list[AttemptRecord],
        final_attempt_state: DesignState | None,
        session_seconds: float,
        stop_reason: str | None,
    ) -> Path:
        summary = OuterLoopSessionSummary(
            base_run_id=base_run_id,
            status=status,
            total_attempts=len(attempt_records),
            final_attempt_run_id=final_attempt_state.run_id if final_attempt_state is not None else None,
            session_seconds=round(session_seconds, 6),
            attempts=attempt_records,
            stop_reason=stop_reason,
        )
        path = outer_loop_dir / "outer_loop_summary.json"
        path.write_text(json.dumps(summary.model_dump(mode="json"), indent=2, sort_keys=True) + "\n")
        return path

    def _write_state(self, state: DesignState, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(state.model_dump(mode="json"), sort_keys=False))

    def _append_log(self, path: Path, message: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
