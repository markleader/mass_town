from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class MeshingRequest(BaseModel):
    geometry_input_path: Path | None = None
    output_directory: Path
    run_id: str
    mesh_dimension: Literal[2, 3] = 3
    step_face_selector: Literal["largest_planar"] | None = None
    output_format: Literal["msh", "bdf"] = "msh"
    target_quality: float


class MeshingResult(BaseModel):
    backend_name: str
    mesh_path: Path | None
    quality: float
    element_count: int
    metadata: dict[str, str | float | int | bool] = Field(default_factory=dict)
    log_path: Path | None = None
