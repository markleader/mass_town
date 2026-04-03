from pathlib import Path

from pydantic import BaseModel, Field

from mass_town.constraints import ConstraintSet
from mass_town.design_variables import DesignVariableAssignments
from mass_town.disciplines.fea.shell_setup import FEAShellSetup
from mass_town.disciplines.fea.solid_setup import FEASolidSetup


class FEALoadCase(BaseModel):
    loads: dict[str, float] = Field(default_factory=dict)


class FEALoadCaseResult(BaseModel):
    passed: bool
    result_files: list[Path] = Field(default_factory=list)
    mass: float | None = None
    max_stress: float | None = None
    displacement_norm: float | None = None
    metadata: dict[str, str | float | int | bool] = Field(default_factory=dict)
    log_path: Path | None = None
    analysis_seconds: float | None = None


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
    constraints: ConstraintSet = Field(default_factory=ConstraintSet)
    allowable_stress: float
    case_name: str = "static"
    load_cases: dict[str, FEALoadCase] = Field(default_factory=dict)
    write_solution: bool = True
    shell_setup: FEAShellSetup | None = None
    solid_setup: FEASolidSetup | None = None


class FEAResult(BaseModel):
    backend_name: str
    passed: bool
    mass: float | None = None
    max_stress: float | None = None
    displacement_norm: float | None = None
    result_files: list[Path] = Field(default_factory=list)
    metadata: dict[str, str | float | int | bool] = Field(default_factory=dict)
    log_path: Path | None = None
    load_cases: dict[str, FEALoadCaseResult] = Field(default_factory=dict)
    worst_case_name: str | None = None
    aggregation_quality_summary_path: Path | None = None
    analysis_seconds: float | None = None
