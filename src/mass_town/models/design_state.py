from typing import Literal

from pydantic import BaseModel, Field

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


class AnalysisState(BaseModel):
    max_stress: float | None = None
    passed: bool = False


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
    constraints: dict[str, float] = Field(default_factory=dict)
    geometry_state: GeometryState = Field(default_factory=GeometryState)
    mesh_state: MeshState = Field(default_factory=MeshState)
    analysis_state: AnalysisState = Field(default_factory=AnalysisState)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    decision_history: list[DecisionRecord] = Field(default_factory=list)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    task_history: list[TaskRecord] = Field(default_factory=list)
