from pathlib import Path

from pydantic import BaseModel, Field


class FEARequest(BaseModel):
    model_input_path: Path | None = None
    mesh_input_path: Path | None = None
    output_directory: Path
    run_id: str
    loads: dict[str, float] = Field(default_factory=dict)
    design_variables: dict[str, float] = Field(default_factory=dict)
    constraints: dict[str, float] = Field(default_factory=dict)
    allowable_stress: float
    case_name: str = "static"
    write_solution: bool = True


class FEAResult(BaseModel):
    backend_name: str
    passed: bool
    max_stress: float | None = None
    displacement_norm: float | None = None
    result_files: list[Path] = Field(default_factory=list)
    metadata: dict[str, str | float | int | bool] = Field(default_factory=dict)
    log_path: Path | None = None
