from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ConfigScalar = str | float | int | bool

DecisionKind = Literal["accept", "rerun", "escalate"]
AssessmentStatus = Literal["success", "warning", "failure", "substandard", "not_applicable"]


class DiagnosticSummary(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning", "error"]
    task: str
    details: dict[str, ConfigScalar] = Field(default_factory=dict)


class LogExcerpt(BaseModel):
    task: str
    path: str
    excerpt: str


class AttemptDelta(BaseModel):
    mass: float | None = None
    max_stress: float | None = None
    objective: float | None = None
    analysis_seconds: float | None = None
    converged: bool | None = None


class AttemptSummary(BaseModel):
    base_run_id: str
    attempt_index: int
    attempt_run_id: str
    inner_status: str
    feasible: bool
    iteration_count: int
    analysis_type: str | None = None
    problem_model_type: str | None = None
    diagnostics_by_task: dict[str, list[DiagnosticSummary]] = Field(default_factory=dict)
    key_metrics: dict[str, ConfigScalar | None] = Field(default_factory=dict)
    artifact_paths: dict[str, str | None] = Field(default_factory=dict)
    config_snapshot: dict[str, object] = Field(default_factory=dict)
    previous_attempt_delta: AttemptDelta | None = None
    history: list[dict[str, ConfigScalar | None]] = Field(default_factory=list)
    log_excerpts: list[LogExcerpt] = Field(default_factory=list)


class DisciplineAssessment(BaseModel):
    discipline: str
    status: AssessmentStatus
    summary: str
    confidence: float
    evidence: list[str] = Field(default_factory=list)
    diagnostic_codes: list[str] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: float) -> float:
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ValueError("Assessment confidence must be between 0.0 and 1.0.")
        return numeric


class OverrideProposal(BaseModel):
    discipline: str
    path: str
    value: ConfigScalar
    reason: str


class RerunDecision(BaseModel):
    decision: DecisionKind
    confidence: float
    summary: str
    discipline_findings: list[DisciplineAssessment] = Field(default_factory=list)
    overrides: list[OverrideProposal] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: float) -> float:
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ValueError("Decision confidence must be between 0.0 and 1.0.")
        return numeric


class AttemptRecord(BaseModel):
    attempt_index: int
    attempt_run_id: str
    status: str
    feasible: bool
    summary_path: str
    assessments_path: str
    decision_path: str


class OuterLoopSessionSummary(BaseModel):
    base_run_id: str
    status: str
    total_attempts: int
    final_attempt_run_id: str | None = None
    session_seconds: float | None = None
    attempts: list[AttemptRecord] = Field(default_factory=list)
    stop_reason: str | None = None
