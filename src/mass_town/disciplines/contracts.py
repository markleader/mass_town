from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


MetadataValue = str | float | int | bool
ElementKind = Literal["shell", "solid", "mixed", "unknown"]


class DisciplineTiming(BaseModel):
    mesh_seconds: float | None = None
    analysis_seconds: float | None = None
    postprocessing_seconds: float | None = None
    optimization_seconds: float | None = None


class DisciplineDiagnostic(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "error"
    details: dict[str, MetadataValue] = Field(default_factory=dict)


class SensitivityPayload(BaseModel):
    response: str
    with_respect_to: str
    values: list[float] = Field(default_factory=list)
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class DisciplineArtifact(BaseModel):
    path: Path
    kind: str
    format: str | None = None
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class NamedRegion(BaseModel):
    id: str
    name: str
    element_kind: ElementKind = "unknown"
    source: str = "unknown"
    source_id: str | None = None
    export_pid: int | None = None
    entity_dimension: int | None = None
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class MaterialReference(BaseModel):
    id: str
    name: str
    model: str = "unspecified"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class PropertyAssignment(BaseModel):
    id: str
    region_id: str
    element_kind: ElementKind = "unknown"
    material_id: str
    thickness: float | None = None
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class MeshToFEAManifest(BaseModel):
    schema_version: str = "mass_town.mesh_to_fea_manifest.v1"
    mesh_path: Path
    source_mesh_path: Path | None = None
    regions: list[NamedRegion] = Field(default_factory=list)
    materials: list[MaterialReference] = Field(default_factory=list)
    property_assignments: list[PropertyAssignment] = Field(default_factory=list)
    timing: DisciplineTiming = Field(default_factory=DisciplineTiming)
    diagnostics: list[DisciplineDiagnostic] = Field(default_factory=list)
    sensitivities: list[SensitivityPayload] = Field(default_factory=list)
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


def read_mesh_to_fea_manifest(path: Path) -> MeshToFEAManifest:
    return MeshToFEAManifest.model_validate_json(path.read_text())


def write_mesh_to_fea_manifest(manifest: MeshToFEAManifest, path: Path) -> Path:
    path.write_text(manifest.model_dump_json(indent=2) + "\n")
    return path
