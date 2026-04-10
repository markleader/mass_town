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
    settings: dict[str, str | float | int | bool] = Field(default_factory=dict)
    buckling_setup: FEABucklingSetup | None = None
    modal_setup: FEAModalSetup | None = None
    shell_setup: FEAShellSetup | None = None
    solid_setup: FEASolidSetup | None = None


ConfigScalar = str | float | int | bool
SupportedLLMBackend = Literal["ollama", "mock"]
DEFAULT_ALLOWED_OVERRIDE_PATHS = [
    "max_iterations",
    "meshing.target_quality",
    "meshing.volume_element_preference",
    "fea.write_solution",
    "fea.settings.*",
    "fea.buckling_setup.sigma",
    "fea.buckling_setup.num_eigenvalues",
    "fea.modal_setup.sigma",
    "fea.modal_setup.num_eigenvalues",
    "optimizer.settings.*",
    "topology.filter.radius",
    "topology.projection.beta",
    "topology.projection.beta_max",
    "topology.projection.eta",
    "topology.projection.beta_scale",
    "topology.projection.update_interval",
    "topology.optimizer.max_iterations",
    "topology.optimizer.change_tolerance",
    "topology.optimizer.move_limit",
    "topology.write_density_plot",
]


def is_supported_override_path(path: str) -> bool:
    stripped = path.strip()
    return bool(stripped) and stripped in DEFAULT_ALLOWED_OVERRIDE_PATHS


class LLMConfig(BaseModel):
    enabled: bool = False
    backend: SupportedLLMBackend = "ollama"
    model: str | None = None
    endpoint: str = "http://127.0.0.1:11434"
    max_attempts: int = 3
    max_total_runtime_seconds: int = 3600
    min_confidence: float = 0.65
    max_repeat_action_count: int = 2
    allowed_override_paths: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ALLOWED_OVERRIDE_PATHS)
    )

    @field_validator("model")
    @classmethod
    def _validate_model(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("llm.model must not be empty when provided.")
        return stripped

    @field_validator("max_attempts", "max_total_runtime_seconds", "max_repeat_action_count")
    @classmethod
    def _validate_positive_ints(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("LLM runtime limits must be positive.")
        return value

    @field_validator("min_confidence")
    @classmethod
    def _validate_min_confidence(cls, value: float) -> float:
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ValueError("llm.min_confidence must be between 0.0 and 1.0.")
        return numeric

    @field_validator("allowed_override_paths")
    @classmethod
    def _validate_override_paths(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for path in value:
            stripped = path.strip()
            if not is_supported_override_path(stripped):
                raise ValueError(f"Unsupported llm.allowed_override_paths entry: {path!r}")
            normalized.append(stripped)
        return normalized

    @model_validator(mode="after")
    def _validate_enabled_model(self) -> "LLMConfig":
        if self.enabled and self.model is None:
            raise ValueError("llm.model is required when llm.enabled is true.")
        return self


class OptimizerConfig(BaseModel):
    enabled: bool = True
    backend: str = "mass_town_heuristic"
    strategy: str = "stress_recovery_thickness_update"
    objective: Literal["feasibility", "minimize_mass"] = "feasibility"
    settings: dict[str, ConfigScalar] = Field(default_factory=dict)


class WorkflowConfig(BaseModel):
    max_iterations: int = 8
    allowable_stress: float = 180.0
    meshing: MeshingConfig = Field(default_factory=MeshingConfig)
    fea: FEAConfig = Field(default_factory=FEAConfig)
    optimizer: OptimizerConfig | None = None
    topology: TopologyConfig | None = None
    llm: LLMConfig = Field(default_factory=LLMConfig)
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
