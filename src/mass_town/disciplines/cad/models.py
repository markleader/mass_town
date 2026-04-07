from pathlib import Path

from pydantic import BaseModel, Field

from mass_town.disciplines.contracts import (
    DisciplineArtifact,
    DisciplineDiagnostic,
    DisciplineTiming,
    MetadataValue,
    NamedRegion,
    SensitivityPayload,
)


class CADRequest(BaseModel):
    source_path: Path | None = None
    run_id: str
    output_directory: Path
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class CADResult(BaseModel):
    backend_name: str
    geometry_artifact: DisciplineArtifact | None = None
    regions: list[NamedRegion] = Field(default_factory=list)
    timing: DisciplineTiming = Field(default_factory=DisciplineTiming)
    diagnostics: list[DisciplineDiagnostic] = Field(default_factory=list)
    sensitivities: list[SensitivityPayload] = Field(default_factory=list)
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
