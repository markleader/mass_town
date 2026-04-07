from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from mass_town.constraints import ConstraintSet
from mass_town.design_variables import DesignVariableAssignments
from mass_town.disciplines.contracts import MeshToFEAManifest, SensitivityPayload
from mass_town.disciplines.fea.shell_setup import FEAShellSetup
from mass_town.disciplines.fea.solid_setup import FEASolidSetup


class FEALoadCase(BaseModel):
    loads: dict[str, float] = Field(default_factory=dict)


class FEABucklingSetup(BaseModel):
    sigma: float = 10.0
    num_eigenvalues: int = 5

    @model_validator(mode="after")
    def _validate_parameters(self) -> "FEABucklingSetup":
        if self.sigma <= 0.0:
            raise ValueError("buckling setup sigma must be positive.")
        if self.num_eigenvalues <= 0:
            raise ValueError("buckling setup num_eigenvalues must be positive.")
        return self


class FEAModalSetup(BaseModel):
    sigma: float = 100.0
    num_eigenvalues: int = 5

    @model_validator(mode="after")
    def _validate_parameters(self) -> "FEAModalSetup":
        if self.sigma <= 0.0:
            raise ValueError("modal setup sigma must be positive.")
        if self.num_eigenvalues <= 0:
            raise ValueError("modal setup num_eigenvalues must be positive.")
        return self


class FEALoadCaseResult(BaseModel):
    passed: bool
    result_files: list[Path] = Field(default_factory=list)
    mass: float | None = None
    max_stress: float | None = None
    displacement_norm: float | None = None
    analysis_type: Literal["static", "buckling", "modal"] = "static"
    eigenvalues: list[float] = Field(default_factory=list)
    critical_eigenvalue: float | None = None
    frequencies_hz: list[float] = Field(default_factory=list)
    critical_frequency_hz: float | None = None
    metadata: dict[str, str | float | int | bool] = Field(default_factory=dict)
    log_path: Path | None = None
    analysis_seconds: float | None = None


class FEARequest(BaseModel):
    model_input_path: Path | None = None
    mesh_input_path: Path | None = None
    mesh_manifest_path: Path | None = None
    mesh_manifest: MeshToFEAManifest | None = None
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
    analysis_type: Literal["static", "buckling", "modal"] = "static"
    load_cases: dict[str, FEALoadCase] = Field(default_factory=dict)
    write_solution: bool = True
    buckling_setup: FEABucklingSetup | None = None
    modal_setup: FEAModalSetup | None = None
    shell_setup: FEAShellSetup | None = None
    solid_setup: FEASolidSetup | None = None
    sensitivities: list[SensitivityPayload] = Field(default_factory=list)


class FEAResult(BaseModel):
    backend_name: str
    passed: bool
    mass: float | None = None
    max_stress: float | None = None
    displacement_norm: float | None = None
    analysis_type: Literal["static", "buckling", "modal"] = "static"
    eigenvalues: list[float] = Field(default_factory=list)
    critical_eigenvalue: float | None = None
    frequencies_hz: list[float] = Field(default_factory=list)
    critical_frequency_hz: float | None = None
    result_files: list[Path] = Field(default_factory=list)
    metadata: dict[str, str | float | int | bool] = Field(default_factory=dict)
    log_path: Path | None = None
    load_cases: dict[str, FEALoadCaseResult] = Field(default_factory=dict)
    worst_case_name: str | None = None
    aggregation_quality_summary_path: Path | None = None
    analysis_seconds: float | None = None
    sensitivities: list[SensitivityPayload] = Field(default_factory=list)
