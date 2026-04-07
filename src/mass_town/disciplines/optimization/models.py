from pathlib import Path

from pydantic import BaseModel, Field

from mass_town.disciplines.contracts import (
    DisciplineArtifact,
    DisciplineDiagnostic,
    DisciplineTiming,
    MetadataValue,
    SensitivityPayload,
)


class OptimizationRequest(BaseModel):
    run_id: str
    design_variables: dict[str, float] = Field(default_factory=dict)
    responses: dict[str, float] = Field(default_factory=dict)
    report_directory: Path
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class OptimizationResult(BaseModel):
    backend_name: str
    design_variables: dict[str, float] = Field(default_factory=dict)
    converged: bool = False
    iteration_count: int = 0
    result_files: list[DisciplineArtifact] = Field(default_factory=list)
    timing: DisciplineTiming = Field(default_factory=DisciplineTiming)
    diagnostics: list[DisciplineDiagnostic] = Field(default_factory=list)
    sensitivities: list[SensitivityPayload] = Field(default_factory=list)
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
