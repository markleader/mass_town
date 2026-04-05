from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from mass_town.design_variables import (
    DesignVariableDefinition,
    ensure_unique_design_variable_definitions,
)
from mass_town.disciplines.fea.models import FEABucklingSetup, FEAModalSetup
from mass_town.disciplines.fea.shell_setup import FEAShellSetup
from mass_town.disciplines.fea.solid_setup import FEASolidSetup
from mass_town.disciplines.topology import TopologyConfig


class MeshingConfig(BaseModel):
    tool: str = "auto"
    geometry_input_path: str | None = None
    gmsh_executable: str = "gmsh"
    mesh_dimension: Literal[2, 3] = 3
    step_face_selector: (
        Literal["largest_planar", "min_x", "max_x", "min_y", "max_y", "min_z", "max_z"] | None
    ) = None
    volume_element_preference: Literal["hex_preferred", "tet_only"] = "hex_preferred"
    output_format: Literal["msh", "bdf"] = "msh"
    target_quality: float = 0.75


class FEAConfig(BaseModel):
    tool: str = "auto"
    model_input_path: str | None = None
    case_name: str = "static"
    analysis_type: Literal["static", "buckling", "modal"] = "static"
    write_solution: bool = True
    buckling_setup: FEABucklingSetup | None = None
    modal_setup: FEAModalSetup | None = None
    shell_setup: FEAShellSetup | None = None
    solid_setup: FEASolidSetup | None = None


class WorkflowConfig(BaseModel):
    max_iterations: int = 8
    allowable_stress: float = 180.0
    meshing: MeshingConfig = Field(default_factory=MeshingConfig)
    fea: FEAConfig = Field(default_factory=FEAConfig)
    topology: TopologyConfig | None = None
    design_variables: list[DesignVariableDefinition] = Field(default_factory=list)
    initial_tasks: list[str] = Field(
        default_factory=lambda: ["geometry", "mesh", "fea", "optimizer"]
    )

    @field_validator("design_variables")
    @classmethod
    def _validate_design_variables(
        cls, value: list[DesignVariableDefinition]
    ) -> list[DesignVariableDefinition]:
        return ensure_unique_design_variable_definitions(value)

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
