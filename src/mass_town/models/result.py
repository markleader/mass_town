from typing import Literal

from pydantic import BaseModel, Field

from .artifacts import ArtifactRecord

ResultStatus = Literal["success", "failure"]


class Diagnostic(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "error"
    task: str
    details: dict[str, str | float | int | bool] = Field(default_factory=dict)


class AgentResult(BaseModel):
    status: ResultStatus
    task: str
    message: str
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    updates: dict[str, object] = Field(default_factory=dict)
