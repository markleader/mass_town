from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class TopologyDomainConfig(BaseModel):
    nelx: int = 60
    nely: int = 20
    lx: float = 3.0
    ly: float = 1.0

    @model_validator(mode="after")
    def _validate_domain(self) -> "TopologyDomainConfig":
        if self.nelx <= 0 or self.nely <= 0:
            raise ValueError("topology.domain must define positive nelx and nely.")
        if self.lx <= 0.0 or self.ly <= 0.0:
            raise ValueError("topology.domain must define positive lx and ly.")
        return self


class TopologyMaterialConfig(BaseModel):
    youngs_modulus: float = 1.0
    poisson_ratio: float = 0.3
    simp_penalization: float = 3.0
    density_min: float = 1e-3

    @model_validator(mode="after")
    def _validate_material(self) -> "TopologyMaterialConfig":
        if self.youngs_modulus <= 0.0:
            raise ValueError("topology.material.youngs_modulus must be positive.")
        if not (-0.99 < self.poisson_ratio < 0.49):
            raise ValueError("topology.material.poisson_ratio must be between -0.99 and 0.49.")
        if self.simp_penalization < 1.0:
            raise ValueError("topology.material.simp_penalization must be at least 1.0.")
        if not (0.0 < self.density_min <= 1.0):
            raise ValueError("topology.material.density_min must satisfy 0 < density_min <= 1.")
        return self


class TopologyLoadConfig(BaseModel):
    node_selector: Literal["max_x_mid", "max_x_min_y", "max_x_max_y"] = "max_x_mid"
    dof: Literal["x", "y"] = "y"
    magnitude: float = -1.0

    @model_validator(mode="after")
    def _validate_load(self) -> "TopologyLoadConfig":
        if self.magnitude == 0.0:
            raise ValueError("topology.load.magnitude must be non-zero.")
        return self


class TopologyBoundaryConfig(BaseModel):
    fixed_boundary: Literal["min_x", "max_x", "min_y", "max_y"] = "min_x"


class TopologyFilterConfig(BaseModel):
    radius: float = 1.5

    @model_validator(mode="after")
    def _validate_filter(self) -> "TopologyFilterConfig":
        if self.radius <= 0.0:
            raise ValueError("topology.filter.radius must be positive.")
        return self


class TopologyProjectionConfig(BaseModel):
    enabled: bool = True
    beta: float = 1.0
    beta_max: float = 8.0
    eta: float = 0.5
    beta_scale: float = 1.2
    update_interval: int = 10

    @model_validator(mode="after")
    def _validate_projection(self) -> "TopologyProjectionConfig":
        if self.beta <= 0.0:
            raise ValueError("topology.projection.beta must be positive.")
        if self.beta_max < self.beta:
            raise ValueError("topology.projection.beta_max must be >= beta.")
        if not (0.0 < self.eta < 1.0):
            raise ValueError("topology.projection.eta must satisfy 0 < eta < 1.")
        if self.beta_scale < 1.0:
            raise ValueError("topology.projection.beta_scale must be >= 1.")
        if self.update_interval <= 0:
            raise ValueError("topology.projection.update_interval must be positive.")
        return self


class TopologyOptimizerConfig(BaseModel):
    max_iterations: int = 80
    change_tolerance: float = 1e-3
    move_limit: float = 0.2

    @model_validator(mode="after")
    def _validate_optimizer(self) -> "TopologyOptimizerConfig":
        if self.max_iterations <= 0:
            raise ValueError("topology.optimizer.max_iterations must be positive.")
        if self.change_tolerance <= 0.0:
            raise ValueError("topology.optimizer.change_tolerance must be positive.")
        if not (0.0 < self.move_limit <= 1.0):
            raise ValueError("topology.optimizer.move_limit must satisfy 0 < move_limit <= 1.")
        return self


class TopologyConfig(BaseModel):
    tool: str = "auto"
    volume_fraction: float = 0.4
    domain: TopologyDomainConfig = Field(default_factory=TopologyDomainConfig)
    material: TopologyMaterialConfig = Field(default_factory=TopologyMaterialConfig)
    load: TopologyLoadConfig = Field(default_factory=TopologyLoadConfig)
    boundary: TopologyBoundaryConfig = Field(default_factory=TopologyBoundaryConfig)
    filter: TopologyFilterConfig = Field(default_factory=TopologyFilterConfig)
    projection: TopologyProjectionConfig = Field(default_factory=TopologyProjectionConfig)
    optimizer: TopologyOptimizerConfig = Field(default_factory=TopologyOptimizerConfig)
    write_density_plot: bool = True

    @model_validator(mode="after")
    def _validate_config(self) -> "TopologyConfig":
        if not (0.0 < self.volume_fraction <= 1.0):
            raise ValueError("topology.volume_fraction must satisfy 0 < volume_fraction <= 1.")
        return self


class TopologyTimingResult(BaseModel):
    mesh_seconds: float | None = None
    solve_seconds: float | None = None
    optimization_seconds: float | None = None


class TopologyRequest(BaseModel):
    report_directory: Path
    log_directory: Path
    mesh_directory: Path
    solution_directory: Path
    run_id: str
    config: TopologyConfig


class TopologyResult(BaseModel):
    backend_name: str
    converged: bool
    objective: float | None = None
    volume_fraction: float | None = None
    max_density_change: float | None = None
    beta: float | None = None
    iteration_count: int = 0
    timing: TopologyTimingResult = Field(default_factory=TopologyTimingResult)
    result_files: list[Path] = Field(default_factory=list)
    metadata: dict[str, str | float | int | bool] = Field(default_factory=dict)
    log_path: Path | None = None
    history_path: Path | None = None
    density_path: Path | None = None
    plot_path: Path | None = None
    summary_path: Path | None = None
    failure_reason: str | None = None
