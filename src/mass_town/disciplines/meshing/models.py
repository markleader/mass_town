from pathlib import Path

from pydantic import BaseModel, Field


class MeshingRequest(BaseModel):
    geometry_input_path: Path | None = None
    output_directory: Path
    run_id: str
    target_quality: float


class MeshingResult(BaseModel):
    backend_name: str
    mesh_path: Path | None
    quality: float
    element_count: int
    metadata: dict[str, str | float | int | bool] = Field(default_factory=dict)
    log_path: Path | None = None

