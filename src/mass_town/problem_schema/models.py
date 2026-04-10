from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SchemaScalar = str | float | int | bool
ProblemModelType = Literal["plane_stress", "shell", "solid", "topology"]
TargetKind = Literal["node_set", "domain_boundary", "domain_selector", "named_region"]


class ProblemMetadata(BaseModel):
    id: str
    name: str
    version: str = "1.0"
    description: str | None = None

    @field_validator("id", "name", "version")
    @classmethod
    def _validate_text_fields(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Problem metadata fields must not be empty.")
        return stripped


class GeometryDomainSpec(BaseModel):
    kind: Literal["structured_2d"] = "structured_2d"
    nelx: int
    nely: int
    lx: float
    ly: float

    @model_validator(mode="after")
    def _validate_dimensions(self) -> "GeometryDomainSpec":
        if self.nelx <= 0 or self.nely <= 0:
            raise ValueError("Structured domains must define positive nelx and nely.")
        if self.lx <= 0.0 or self.ly <= 0.0:
            raise ValueError("Structured domains must define positive lx and ly.")
        return self


class GeometrySpec(BaseModel):
    source_type: Literal["file", "structured_domain"]
    path: str | None = None
    file_format: Literal["step", "stp", "bdf"] | None = None
    domain: GeometryDomainSpec | None = None

    @model_validator(mode="after")
    def _validate_geometry(self) -> "GeometrySpec":
        if self.source_type == "file":
            if not self.path:
                raise ValueError("File-backed geometry requires a path.")
            if self.file_format is None:
                raise ValueError("File-backed geometry requires a file_format.")
            if self.domain is not None:
                raise ValueError("File-backed geometry cannot define a structured domain.")
            return self

        if self.domain is None:
            raise ValueError("Structured-domain geometry requires a domain definition.")
        if self.path is not None or self.file_format is not None:
            raise ValueError("Structured-domain geometry cannot define a file path or file_format.")
        return self


class MeshingSpec(BaseModel):
    tool: str = "auto"
    gmsh_executable: str = "gmsh"
    mesh_dimension: Literal[2, 3] = 3
    step_face_selector: (
        Literal["largest_planar", "min_x", "max_x", "min_y", "max_y", "min_z", "max_z"] | None
    ) = None
    volume_element_preference: Literal["hex_preferred", "tet_only"] = "hex_preferred"
    output_format: Literal["msh", "bdf"] = "msh"
    target_quality: float

    @field_validator("target_quality")
    @classmethod
    def _validate_target_quality(cls, value: float) -> float:
        if float(value) <= 0.0:
            raise ValueError("Meshing target_quality must be positive.")
        return float(value)


class ModelSpec(BaseModel):
    type: ProblemModelType
    input_source: Literal["meshed_geometry", "model_file", "structured_domain"]
    model_input_path: str | None = None
    region_reference_mode: Literal["named_region", "pid_region", "not_applicable"] = "not_applicable"
    metadata_hooks: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_model(self) -> "ModelSpec":
        if self.input_source == "model_file" and not self.model_input_path:
            raise ValueError("Model input_source 'model_file' requires model_input_path.")
        if self.input_source != "model_file" and self.model_input_path is not None:
            raise ValueError("Only model_file inputs may define model_input_path.")
        if self.type == "topology" and self.input_source != "structured_domain":
            raise ValueError("Topology models must use the structured_domain input source.")
        return self


class MaterialSpec(BaseModel):
    id: str
    name: str
    model: Literal["implicit_solver_default", "isotropic_linear_elastic", "simp_isotropic"]
    youngs_modulus: float | None = None
    poisson_ratio: float | None = None
    density: float | None = None
    simp_penalization: float | None = None
    density_min: float | None = None
    metadata: dict[str, SchemaScalar] = Field(default_factory=dict)

    @field_validator("id", "name")
    @classmethod
    def _validate_names(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Material identifiers must not be empty.")
        return stripped

    @model_validator(mode="after")
    def _validate_material(self) -> "MaterialSpec":
        if self.model == "isotropic_linear_elastic":
            if self.youngs_modulus is None or self.poisson_ratio is None:
                raise ValueError(
                    "isotropic_linear_elastic materials require youngs_modulus and poisson_ratio."
                )
        if self.model == "simp_isotropic":
            missing = [
                field_name
                for field_name in (
                    "youngs_modulus",
                    "poisson_ratio",
                    "simp_penalization",
                    "density_min",
                )
                if getattr(self, field_name) is None
            ]
            if missing:
                missing_fields = ", ".join(missing)
                raise ValueError(f"simp_isotropic materials require: {missing_fields}.")
        return self


class SelectorSpec(BaseModel):
    kind: Literal[
        "boundary_loop",
        "closest_node_to_centroid",
        "bounding_box_extreme",
        "topology_load_node",
        "topology_fixed_boundary",
    ]
    parameters: dict[str, SchemaScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_selector(self) -> "SelectorSpec":
        if self.kind == "boundary_loop":
            missing = [name for name in ("family", "order_by", "index") if name not in self.parameters]
            if missing:
                raise ValueError(
                    "boundary_loop selectors require parameters: " + ", ".join(missing) + "."
                )
        elif self.kind == "bounding_box_extreme":
            missing = [name for name in ("axis", "extreme") if name not in self.parameters]
            if missing:
                raise ValueError(
                    "bounding_box_extreme selectors require parameters: "
                    + ", ".join(missing)
                    + "."
                )
        elif self.kind == "topology_load_node":
            missing = [name for name in ("node_selector",) if name not in self.parameters]
            if missing:
                raise ValueError(
                    "topology_load_node selectors require parameters: "
                    + ", ".join(missing)
                    + "."
                )
        elif self.kind == "topology_fixed_boundary":
            missing = [name for name in ("fixed_boundary",) if name not in self.parameters]
            if missing:
                raise ValueError(
                    "topology_fixed_boundary selectors require parameters: "
                    + ", ".join(missing)
                    + "."
                )
        return self


class NodeSetSpec(BaseModel):
    name: str
    selector: SelectorSpec

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Node-set names must not be empty.")
        return stripped


class TargetReference(BaseModel):
    kind: TargetKind
    name: str

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Target reference names must not be empty.")
        return stripped


class BoundaryConditionSpec(BaseModel):
    kind: Literal["displacement_fixed", "domain_fixed"] = "displacement_fixed"
    target: TargetReference
    dof: str | None = None
    metadata: dict[str, SchemaScalar] = Field(default_factory=dict)

    @field_validator("dof")
    @classmethod
    def _validate_dof(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if any(character not in "123456" for character in value):
            raise ValueError("Boundary-condition DOF strings may only contain digits 1-6.")
        return value

    @model_validator(mode="after")
    def _validate_boundary_condition(self) -> "BoundaryConditionSpec":
        if self.kind == "displacement_fixed":
            if self.target.kind != "node_set":
                raise ValueError("displacement_fixed boundary conditions must target a node_set.")
            if self.dof is None:
                raise ValueError("displacement_fixed boundary conditions require a dof string.")
            return self
        if self.target.kind != "domain_boundary":
            raise ValueError("domain_fixed boundary conditions must target a domain_boundary.")
        return self


class LoadSpec(BaseModel):
    kind: Literal["nodal_force", "domain_force"] = "nodal_force"
    target: TargetReference
    load_key: str | None = None
    direction: tuple[float, float, float] | None = None
    distribution: Literal["equal"] | None = None
    dof: Literal["x", "y"] | None = None
    magnitude: float | None = None
    metadata: dict[str, SchemaScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_load(self) -> "LoadSpec":
        if self.kind == "nodal_force":
            if self.target.kind != "node_set":
                raise ValueError("nodal_force loads must target a node_set.")
            if not self.load_key:
                raise ValueError("nodal_force loads require load_key.")
            if self.direction is None:
                raise ValueError("nodal_force loads require direction.")
            if all(abs(float(component)) <= 1e-12 for component in self.direction):
                raise ValueError("nodal_force directions must not be the zero vector.")
            if self.distribution is None:
                raise ValueError("nodal_force loads require distribution.")
            return self

        if self.target.kind != "domain_selector":
            raise ValueError("domain_force loads must target a domain_selector.")
        if self.dof is None or self.magnitude is None:
            raise ValueError("domain_force loads require dof and magnitude.")
        return self


class DesignVariableSpec(BaseModel):
    id: str
    name: str
    kind: Literal["scalar_thickness", "region_thickness", "element_thickness", "density_field"]
    initial_value: float
    bounds_lower: float
    bounds_upper: float
    units: str = "model_unit"
    active: bool = True
    target: TargetReference | None = None
    element_ids: list[int] = Field(default_factory=list)
    metadata: dict[str, SchemaScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_design_variable(self) -> "DesignVariableSpec":
        if self.bounds_lower > self.initial_value or self.initial_value > self.bounds_upper:
            raise ValueError(
                f"Initial value for design variable '{self.id}' must satisfy bounds_lower <= "
                "initial_value <= bounds_upper."
            )
        if self.kind == "scalar_thickness":
            if self.target is not None or self.element_ids:
                raise ValueError("scalar_thickness design variables cannot define explicit targets.")
        elif self.kind == "region_thickness":
            if self.target is None or self.target.kind != "named_region":
                raise ValueError("region_thickness design variables must target a named_region.")
            if self.element_ids:
                raise ValueError("region_thickness design variables cannot define element_ids.")
        elif self.kind == "element_thickness":
            if self.target is not None:
                raise ValueError("element_thickness design variables cannot define a target reference.")
            if not self.element_ids:
                raise ValueError("element_thickness design variables must define element_ids.")
        elif self.target is not None or self.element_ids:
            raise ValueError("density_field design variables cannot define discrete targets.")
        return self


class ObjectiveSpec(BaseModel):
    kind: Literal["feasibility", "minimize_mass", "minimize_compliance"]
    response: str
    enabled: bool = True
    metadata: dict[str, SchemaScalar] = Field(default_factory=dict)

    @field_validator("response")
    @classmethod
    def _validate_response(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Objective response identifiers must not be empty.")
        return stripped


class ConstraintSpec(BaseModel):
    kind: Literal[
        "max_stress",
        "aggregated_stress",
        "minimum_buckling_load_factor",
        "minimum_natural_frequency_hz",
        "volume_fraction",
    ]
    limit: float | None = None
    method: Literal["ks", "pnorm"] | None = None
    source: str | None = None
    mode: int | None = None
    metadata: dict[str, SchemaScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_constraint(self) -> "ConstraintSpec":
        if self.kind == "aggregated_stress":
            if self.limit is None or self.method is None or self.source is None:
                raise ValueError(
                    "aggregated_stress constraints require limit, method, and source."
                )
        elif self.kind in {"max_stress", "volume_fraction"}:
            if self.limit is None:
                raise ValueError(f"{self.kind} constraints require a limit.")
        elif self.kind in {
            "minimum_buckling_load_factor",
            "minimum_natural_frequency_hz",
        }:
            if self.limit is None or self.mode is None:
                raise ValueError(f"{self.kind} constraints require limit and mode.")
        return self


class OptimizerSpec(BaseModel):
    enabled: bool = True
    backend: str
    strategy: str
    max_iterations: int | None = None
    settings: dict[str, SchemaScalar] = Field(default_factory=dict)

    @field_validator("backend", "strategy")
    @classmethod
    def _validate_text_fields(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Optimizer text fields must not be empty.")
        return stripped

    @field_validator("max_iterations")
    @classmethod
    def _validate_max_iterations(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("Optimizer max_iterations must be positive when provided.")
        return value


class LoadCaseSpec(BaseModel):
    name: str
    loads: dict[str, float] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Load-case names must not be empty.")
        return stripped


class AnalysisSpec(BaseModel):
    discipline: Literal["structural", "topology"]
    analysis_type: Literal["static", "buckling", "modal", "topology_compliance"]
    case_name: str | None = None
    write_solution: bool | None = None
    settings: dict[str, SchemaScalar] = Field(default_factory=dict)
    load_cases: list[LoadCaseSpec] = Field(default_factory=list)
    buckling_setup: dict[str, SchemaScalar] = Field(default_factory=dict)
    modal_setup: dict[str, SchemaScalar] = Field(default_factory=dict)


class ExecutionSpec(BaseModel):
    initial_tasks: list[str] = Field(default_factory=list)
    backend_hints: dict[str, str] = Field(default_factory=dict)
    source: str = "workflow_config_adapter"

    @field_validator("initial_tasks")
    @classmethod
    def _validate_initial_tasks(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for task in value:
            stripped = task.strip()
            if not stripped:
                raise ValueError("Execution tasks must not contain empty names.")
            normalized.append(stripped)
        return normalized


class ProblemSchema(BaseModel):
    problem: ProblemMetadata
    geometry: GeometrySpec | None = None
    meshing: MeshingSpec | None = None
    model: ModelSpec
    materials: list[MaterialSpec] = Field(default_factory=list)
    analysis: AnalysisSpec
    node_sets: list[NodeSetSpec] = Field(default_factory=list)
    boundary_conditions: list[BoundaryConditionSpec] = Field(default_factory=list)
    loads: list[LoadSpec] = Field(default_factory=list)
    design_variables: list[DesignVariableSpec] = Field(default_factory=list)
    objectives: list[ObjectiveSpec] = Field(default_factory=list)
    constraints: list[ConstraintSpec] = Field(default_factory=list)
    optimizer: OptimizerSpec | None = None
    execution: ExecutionSpec = Field(default_factory=ExecutionSpec)

    @model_validator(mode="after")
    def _validate_problem_schema(self) -> "ProblemSchema":
        node_set_names = {node_set.name for node_set in self.node_sets}
        for boundary_condition in self.boundary_conditions:
            if (
                boundary_condition.target.kind == "node_set"
                and boundary_condition.target.name not in node_set_names
            ):
                raise ValueError(
                    f"Boundary condition references unknown node set "
                    f"'{boundary_condition.target.name}'."
                )
        for load in self.loads:
            if load.target.kind == "node_set" and load.target.name not in node_set_names:
                raise ValueError(f"Load references unknown node set '{load.target.name}'.")

        optimization_requested = "optimizer" in self.execution.initial_tasks
        if self.model.type == "topology":
            if self.geometry is None or self.geometry.source_type != "structured_domain":
                raise ValueError("Topology problems require structured-domain geometry.")
            if self.meshing is not None:
                raise ValueError("Topology problems must not define a meshing block.")
            if self.analysis.discipline != "topology" or self.analysis.analysis_type != "topology_compliance":
                raise ValueError("Topology problems require topology_compliance analysis.")
            if not self.objectives:
                raise ValueError("Topology problems require at least one objective.")
            if self.optimizer is None or not self.optimizer.enabled:
                raise ValueError("Topology problems require an enabled optimizer.")
            return self

        if self.analysis.discipline != "structural":
            raise ValueError("Non-topology problems must use structural analysis.")
        if self.meshing is None and self.model.model_input_path is None:
            raise ValueError(
                "Structural shell/solid/plane_stress problems require either meshing settings "
                "or a model_input_path."
            )
        if optimization_requested:
            if self.optimizer is None or not self.optimizer.enabled:
                raise ValueError(
                    "Problems with an optimizer task require an enabled optimizer specification."
                )
            if not self.objectives:
                raise ValueError("Problems with an optimizer task require at least one objective.")
            if not self.constraints:
                raise ValueError("Problems with an optimizer task require at least one constraint.")
        return self
