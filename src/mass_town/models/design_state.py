from typing import Literal

from pydantic import BaseModel, Field

from mass_town.constraints import (
    AggregatedStressResult,
    ConstraintSet,
    EigenvalueConstraintResult,
)

from .artifacts import ArtifactRecord
from .result import Diagnostic

WorkflowStatus = Literal["pending", "running", "recovered", "failed"]


class GeometryState(BaseModel):
    valid: bool = True
    notes: str = ""


class MeshState(BaseModel):
    backend: str | None = None
    mesh_path: str | None = None
    quality: float = 0.0
    elements: int = 0


class LoadCaseState(BaseModel):
    loads: dict[str, float] = Field(default_factory=dict)


class LoadCaseAnalysisState(BaseModel):
    backend: str | None = None
    result_path: str | None = None
    mass: float | None = None
    max_stress: float | None = None
    displacement_norm: float | None = None
    analysis_type: Literal["static", "buckling"] = "static"
    eigenvalues: list[float] = Field(default_factory=list)
    critical_eigenvalue: float | None = None
    passed: bool = False
    analysis_seconds: float | None = None


class AnalysisState(BaseModel):
    backend: str | None = None
    result_path: str | None = None
    mass: float | None = None
    max_stress: float | None = None
    displacement_norm: float | None = None
    analysis_type: Literal["static", "buckling"] = "static"
    eigenvalues: list[float] = Field(default_factory=list)
    critical_eigenvalue: float | None = None
    passed: bool = False
    load_cases: dict[str, LoadCaseAnalysisState] = Field(default_factory=dict)
    worst_case_name: str | None = None
    aggregated_stress: AggregatedStressResult | None = None
    eigenvalue_constraints: dict[str, EigenvalueConstraintResult] = Field(default_factory=dict)
    analysis_seconds: float | None = None


class DecisionRecord(BaseModel):
    iteration: int
    action: str
    reason: str


class TaskRecord(BaseModel):
    iteration: int
    task: str
    status: str
    message: str


class DesignState(BaseModel):
    run_id: str
    problem_name: str
    status: WorkflowStatus = "pending"
    iteration: int = 0
    design_variables: dict[str, float] = Field(default_factory=dict)
    loads: dict[str, float] = Field(default_factory=dict)
    load_cases: dict[str, LoadCaseState] = Field(default_factory=dict)
    constraints: ConstraintSet = Field(default_factory=ConstraintSet)
    geometry_state: GeometryState = Field(default_factory=GeometryState)
    mesh_state: MeshState = Field(default_factory=MeshState)
    analysis_state: AnalysisState = Field(default_factory=AnalysisState)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    decision_history: list[DecisionRecord] = Field(default_factory=list)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    task_history: list[TaskRecord] = Field(default_factory=list)
