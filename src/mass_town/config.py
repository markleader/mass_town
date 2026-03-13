from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class WorkflowConfig(BaseModel):
    max_iterations: int = 8
    allowable_stress: float = 180.0
    target_mesh_quality: float = 0.75
    initial_tasks: list[str] = Field(
        default_factory=lambda: ["geometry", "mesh", "fea", "optimizer"]
    )

    @classmethod
    def from_file(cls, path: Path) -> "WorkflowConfig":
        data = yaml.safe_load(path.read_text()) or {}
        return cls.model_validate(data)
