from pathlib import Path

from pydantic import BaseModel, Field

from mass_town.design_variables import DesignVariableAssignments
from mass_town.disciplines.fea.shell_setup import FEAShellSetup


class FEARequest(BaseModel):
    model_input_path: Path | None = None
    mesh_input_path: Path | None = None
    report_directory: Path
    log_directory: Path
    solution_directory: Path
    run_id: str
    loads: dict[str, float] = Field(default_factory=dict)
    design_variables: dict[str, float] = Field(default_factory=dict)
    design_variable_assignments: DesignVariableAssignments = Field(
        default_factory=DesignVariableAssignments
    )
    constraints: dict[str, float] = Field(default_factory=dict)
    allowable_stress: float
    case_name: str = "static"
    write_solution: bool = True
    shell_setup: FEAShellSetup | None = None


class FEAResult(BaseModel):
    backend_name: str
    passed: bool
    mass: float | None = None
    max_stress: float | None = None
    displacement_norm: float | None = None
    result_files: list[Path] = Field(default_factory=list)
    metadata: dict[str, str | float | int | bool] = Field(default_factory=dict)
    log_path: Path | None = None
