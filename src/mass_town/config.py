from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class MeshingConfig(BaseModel):
    tool: str = "auto"
    geometry_input_path: str | None = None
    gmsh_executable: str = "gmsh"
    target_quality: float = 0.75


class WorkflowConfig(BaseModel):
    max_iterations: int = 8
    allowable_stress: float = 180.0
    meshing: MeshingConfig = Field(default_factory=MeshingConfig)
    initial_tasks: list[str] = Field(
        default_factory=lambda: ["geometry", "mesh", "fea", "optimizer"]
    )

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_meshing_config(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data

        meshing = dict(data.get("meshing") or {})
        legacy_target = data.pop("target_mesh_quality", None)
        if legacy_target is not None and "target_quality" not in meshing:
            meshing["target_quality"] = legacy_target
        if meshing:
            data["meshing"] = meshing
        return data

    @classmethod
    def from_file(cls, path: Path) -> "WorkflowConfig":
        data = yaml.safe_load(path.read_text()) or {}
        return cls.model_validate(data)
