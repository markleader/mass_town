from __future__ import annotations

from pathlib import Path

from mass_town.config import WorkflowConfig
from mass_town.constraints import (
    AggregatedStressConstraint,
    ConstraintSet,
    MinimumEigenvalueConstraint,
)
from mass_town.design_variables import (
    DesignVariableBounds,
    DesignVariableDefinition,
    DesignVariableType,
    resolved_design_variable_definitions,
    resolved_design_variable_values,
)
from mass_town.disciplines.contracts import MeshToFEAManifest
from mass_town.disciplines.fea import FEALoadCase, FEARequest
from mass_town.disciplines.fea.models import FEABucklingSetup, FEAModalSetup
from mass_town.disciplines.fea.setup_common import FEABoundaryCondition, FEALoad
from mass_town.disciplines.fea.shell_setup import FEAShellNodeSet, FEAShellSetup
from mass_town.disciplines.fea.solid_setup import FEASolidNodeSet, FEASolidSetup
from mass_town.disciplines.meshing import MeshingRequest
from mass_town.disciplines.topology import (
    TopologyBoundaryConfig,
    TopologyConfig,
    TopologyDomainConfig,
    TopologyFilterConfig,
    TopologyLoadConfig,
    TopologyMaterialConfig,
    TopologyOptimizerConfig,
    TopologyProjectionConfig,
    TopologyRequest,
)
from mass_town.models.design_state import DesignState
from mass_town.problem_schema.models import (
    AnalysisSpec,
    BoundaryConditionSpec,
    ConstraintSpec,
    DesignVariableSpec,
    ExecutionSpec,
    GeometryDomainSpec,
    GeometrySpec,
    LoadCaseSpec,
    LoadSpec,
    MaterialSpec,
    MeshingSpec,
    ModelSpec,
    NodeSetSpec,
    ObjectiveSpec,
    OptimizerSpec,
    ProblemMetadata,
    ProblemSchema,
    SelectorSpec,
    TargetReference,
)


class ProblemSchemaResolver:
    def resolve(self, config: WorkflowConfig, state: DesignState, run_root: Path) -> ProblemSchema:
        if config.topology is not None:
            return self._resolve_topology_problem(config, state, run_root)
        return self._resolve_structural_problem(config, state, run_root)

    def build_meshing_request(
        self,
        problem: ProblemSchema,
        state: DesignState,
        run_root: Path,
        *,
        mesh_directory: Path,
        log_directory: Path,
    ) -> MeshingRequest:
        if problem.meshing is None:
            raise ValueError("Meshing requests require a problem schema with meshing settings.")
        geometry_input_path = run_root / problem.geometry.path if problem.geometry and problem.geometry.path else None
        return MeshingRequest(
            geometry_input_path=geometry_input_path,
            mesh_directory=mesh_directory,
            log_directory=log_directory,
            run_id=state.run_id,
            mesh_dimension=problem.meshing.mesh_dimension,
            step_face_selector=problem.meshing.step_face_selector,
            volume_element_preference=problem.meshing.volume_element_preference,
            output_format=problem.meshing.output_format,
            target_quality=problem.meshing.target_quality,
        )

    def build_fea_request(
        self,
        problem: ProblemSchema,
        state: DesignState,
        run_root: Path,
        *,
        report_directory: Path,
        log_directory: Path,
        solution_directory: Path,
        mesh_input_path: Path | None,
        mesh_manifest_path: Path | None = None,
        mesh_manifest: MeshToFEAManifest | None = None,
    ) -> FEARequest:
        model_input_path = (
            run_root / problem.model.model_input_path
            if problem.model.model_input_path is not None
            else None
        )
        if model_input_path is None and mesh_input_path is not None and mesh_input_path.suffix.lower() == ".bdf":
            model_input_path = mesh_input_path

        design_variable_definitions = self.design_variable_definitions(problem)
        resolved_values = resolved_design_variable_values(design_variable_definitions, state.design_variables)

        return FEARequest(
            model_input_path=model_input_path,
            mesh_input_path=mesh_input_path,
            mesh_manifest_path=mesh_manifest_path,
            mesh_manifest=mesh_manifest,
            report_directory=report_directory,
            log_directory=log_directory,
            solution_directory=solution_directory,
            run_id=state.run_id,
            loads=dict(state.loads),
            design_variables=resolved_values,
            design_variable_assignments=self.design_variable_assignments(
                problem,
                state,
                run_root,
                model_input_path=model_input_path,
                mesh_input_path=mesh_input_path,
            ),
            constraints=self.constraint_set(problem),
            allowable_stress=self.allowable_stress(problem),
            case_name=problem.analysis.case_name or "static",
            analysis_type=self._structural_analysis_type(problem),
            load_cases={
                load_case.name: FEALoadCase(loads=dict(load_case.loads))
                for load_case in problem.analysis.load_cases
            },
            write_solution=bool(problem.analysis.write_solution),
            buckling_setup=self._buckling_setup(problem),
            modal_setup=self._modal_setup(problem),
            shell_setup=self._shell_setup(problem),
            solid_setup=self._solid_setup(problem),
        )

    def build_topology_request(
        self,
        problem: ProblemSchema,
        state: DesignState,
        *,
        report_directory: Path,
        log_directory: Path,
        mesh_directory: Path,
        solution_directory: Path,
    ) -> TopologyRequest:
        return TopologyRequest(
            report_directory=report_directory,
            log_directory=log_directory,
            mesh_directory=mesh_directory,
            solution_directory=solution_directory,
            run_id=state.run_id,
            config=self.topology_config(problem),
        )

    def design_variable_definitions(self, problem: ProblemSchema) -> list[DesignVariableDefinition]:
        definitions: list[DesignVariableDefinition] = []
        for design_variable in problem.design_variables:
            if design_variable.kind == "density_field":
                continue

            definition_type = DesignVariableType(design_variable.kind)
            definitions.append(
                DesignVariableDefinition(
                    id=design_variable.id,
                    name=design_variable.name,
                    type=definition_type,
                    initial_value=design_variable.initial_value,
                    bounds=DesignVariableBounds(
                        lower=design_variable.bounds_lower,
                        upper=design_variable.bounds_upper,
                    ),
                    units=design_variable.units,
                    active=design_variable.active,
                    region=(
                        design_variable.target.name
                        if design_variable.target is not None and design_variable.target.kind == "named_region"
                        else None
                    ),
                    element_ids=list(design_variable.element_ids),
                )
            )
        return definitions

    def allowable_stress(self, problem: ProblemSchema) -> float:
        for constraint in problem.constraints:
            if constraint.kind == "max_stress" and constraint.limit is not None:
                return float(constraint.limit)
            if (
                constraint.kind == "aggregated_stress"
                and constraint.limit is not None
                and constraint.source == "load_cases"
            ):
                return float(constraint.limit)
        return 180.0

    def constraint_set(self, problem: ProblemSchema) -> ConstraintSet:
        constraints = ConstraintSet()
        for constraint in problem.constraints:
            if constraint.kind == "max_stress":
                constraints.max_stress = float(constraint.limit)
            elif constraint.kind == "aggregated_stress":
                constraints.aggregated_stress = AggregatedStressConstraint(
                    method=str(constraint.method),
                    source=str(constraint.source),
                    allowable=float(constraint.limit),
                    ks_weight=float(constraint.metadata.get("ks_weight", 50.0)),
                    p=float(constraint.metadata.get("p", 8.0)),
                )
            elif constraint.kind == "minimum_buckling_load_factor":
                constraints.minimum_buckling_load_factor = MinimumEigenvalueConstraint(
                    mode=int(constraint.mode),
                    minimum=float(constraint.limit),
                )
            elif constraint.kind == "minimum_natural_frequency_hz":
                constraints.minimum_natural_frequency_hz = MinimumEigenvalueConstraint(
                    mode=int(constraint.mode),
                    minimum=float(constraint.limit),
                )
        return constraints

    def topology_config(self, problem: ProblemSchema) -> TopologyConfig:
        geometry = problem.geometry
        if geometry is None or geometry.domain is None:
            raise ValueError("Topology schema conversion requires structured-domain geometry.")

        material = problem.materials[0]
        boundary = next(
            bc for bc in problem.boundary_conditions if bc.kind == "domain_fixed"
        )
        load = next(load for load in problem.loads if load.kind == "domain_force")
        volume_fraction_constraint = next(
            constraint for constraint in problem.constraints if constraint.kind == "volume_fraction"
        )
        optimizer = problem.optimizer
        if optimizer is None:
            raise ValueError("Topology schema conversion requires an optimizer.")

        projection_settings = {
            key: optimizer.settings[key]
            for key in ("enabled", "beta", "beta_max", "eta", "beta_scale", "update_interval")
            if key in optimizer.settings
        }

        return TopologyConfig(
            tool=problem.execution.backend_hints.get("topology", "auto"),
            volume_fraction=float(volume_fraction_constraint.limit),
            domain=TopologyDomainConfig(
                nelx=geometry.domain.nelx,
                nely=geometry.domain.nely,
                lx=geometry.domain.lx,
                ly=geometry.domain.ly,
            ),
            material=TopologyMaterialConfig(
                youngs_modulus=float(material.youngs_modulus),
                poisson_ratio=float(material.poisson_ratio),
                simp_penalization=float(material.simp_penalization),
                density_min=float(material.density_min),
            ),
            load=TopologyLoadConfig(
                node_selector=str(load.target.name),
                dof=str(load.dof),
                magnitude=float(load.magnitude),
            ),
            boundary=TopologyBoundaryConfig(fixed_boundary=str(boundary.target.name)),
            filter=TopologyFilterConfig(
                radius=float(problem.optimizer.settings.get("filter_radius", 1.5))
                if problem.optimizer is not None
                else 1.5
            ),
            projection=TopologyProjectionConfig.model_validate(projection_settings),
            optimizer=TopologyOptimizerConfig(
                max_iterations=int(optimizer.max_iterations or 1),
                change_tolerance=float(optimizer.settings.get("change_tolerance", 1e-3)),
                move_limit=float(optimizer.settings.get("move_limit", 0.2)),
            ),
            write_density_plot=bool(optimizer.settings.get("write_density_plot", True)),
        )

    def _resolve_structural_problem(
        self,
        config: WorkflowConfig,
        state: DesignState,
        run_root: Path,
    ) -> ProblemSchema:
        geometry = self._structural_geometry(config)
        meshing = self._structural_meshing(config)
        model_type = self._structural_model_type(config)
        design_variable_definitions = resolved_design_variable_definitions(
            config.design_variables,
            state.design_variables,
        )
        load_cases = (
            [LoadCaseSpec(name=name, loads=dict(load_case.loads)) for name, load_case in state.load_cases.items()]
            if state.load_cases
            else [LoadCaseSpec(name=config.fea.case_name, loads=dict(state.loads))]
        )
        node_sets = self._node_sets_from_structural_config(config)
        boundary_conditions = self._boundary_conditions_from_structural_config(config)
        loads = self._loads_from_structural_config(config)

        return ProblemSchema(
            problem=ProblemMetadata(
                id=state.problem_name or run_root.name,
                name=state.problem_name or run_root.name,
            ),
            geometry=geometry,
            meshing=meshing,
            model=ModelSpec(
                type=model_type,
                input_source="model_file" if config.fea.model_input_path else "meshed_geometry",
                model_input_path=config.fea.model_input_path,
                region_reference_mode=(
                    "named_region"
                    if config.fea.model_input_path or (meshing is not None and meshing.output_format == "bdf")
                    else "not_applicable"
                ),
                metadata_hooks=(
                    {"bdf_region_comments": "$ REGION"}
                    if config.fea.model_input_path or (meshing is not None and meshing.output_format == "bdf")
                    else {}
                ),
            ),
            materials=[self._default_structural_material()],
            analysis=AnalysisSpec(
                discipline="structural",
                analysis_type=config.fea.analysis_type,
                case_name=config.fea.case_name,
                write_solution=config.fea.write_solution,
                load_cases=load_cases,
                buckling_setup=(
                    config.fea.buckling_setup.model_dump(mode="json")
                    if config.fea.buckling_setup is not None
                    else {}
                ),
                modal_setup=(
                    config.fea.modal_setup.model_dump(mode="json")
                    if config.fea.modal_setup is not None
                    else {}
                ),
            ),
            node_sets=node_sets,
            boundary_conditions=boundary_conditions,
            loads=loads,
            design_variables=[
                self._design_variable_spec(definition)
                for definition in design_variable_definitions
            ],
            objectives=self._structural_objectives(config),
            constraints=self._structural_constraints(config, state),
            optimizer=self._structural_optimizer(config),
            execution=ExecutionSpec(
                initial_tasks=list(config.initial_tasks),
                backend_hints={
                    "meshing": config.meshing.tool,
                    "fea": config.fea.tool,
                },
                source="workflow_config_adapter",
            ),
        )

    def _resolve_topology_problem(
        self,
        config: WorkflowConfig,
        state: DesignState,
        run_root: Path,
    ) -> ProblemSchema:
        topology = config.topology
        if topology is None:
            raise ValueError("Topology problem resolution requires a topology configuration.")

        geometry = GeometrySpec(
            source_type="structured_domain",
            domain=GeometryDomainSpec(
                nelx=topology.domain.nelx,
                nely=topology.domain.nely,
                lx=topology.domain.lx,
                ly=topology.domain.ly,
            ),
        )

        return ProblemSchema(
            problem=ProblemMetadata(
                id=state.problem_name or run_root.name,
                name=state.problem_name or run_root.name,
            ),
            geometry=geometry,
            model=ModelSpec(
                type="topology",
                input_source="structured_domain",
                region_reference_mode="not_applicable",
            ),
            materials=[
                MaterialSpec(
                    id="topology_material",
                    name="Topology Material",
                    model="simp_isotropic",
                    youngs_modulus=topology.material.youngs_modulus,
                    poisson_ratio=topology.material.poisson_ratio,
                    simp_penalization=topology.material.simp_penalization,
                    density_min=topology.material.density_min,
                )
            ],
            analysis=AnalysisSpec(
                discipline="topology",
                analysis_type="topology_compliance",
                case_name="topology_compliance",
            ),
            boundary_conditions=[
                BoundaryConditionSpec(
                    kind="domain_fixed",
                    target=TargetReference(kind="domain_boundary", name=topology.boundary.fixed_boundary),
                )
            ],
            loads=[
                LoadSpec(
                    kind="domain_force",
                    target=TargetReference(kind="domain_selector", name=topology.load.node_selector),
                    dof=topology.load.dof,
                    magnitude=topology.load.magnitude,
                )
            ],
            design_variables=[
                DesignVariableSpec(
                    id="density_field",
                    name="Density Field",
                    kind="density_field",
                    initial_value=topology.volume_fraction,
                    bounds_lower=topology.material.density_min,
                    bounds_upper=1.0,
                    units="unitless",
                    metadata={
                        "domain_nelx": topology.domain.nelx,
                        "domain_nely": topology.domain.nely,
                    },
                )
            ],
            objectives=[
                ObjectiveSpec(
                    kind="minimize_compliance",
                    response="topology.objective",
                    metadata={"backend_result_key": "objective"},
                )
            ],
            constraints=[
                ConstraintSpec(kind="volume_fraction", limit=topology.volume_fraction)
            ],
            optimizer=OptimizerSpec(
                enabled=True,
                backend="optimality_criteria",
                strategy="oc_density_update",
                max_iterations=topology.optimizer.max_iterations,
                settings={
                    "change_tolerance": topology.optimizer.change_tolerance,
                    "move_limit": topology.optimizer.move_limit,
                    "filter_radius": topology.filter.radius,
                    "enabled": topology.projection.enabled,
                    "beta": topology.projection.beta,
                    "beta_max": topology.projection.beta_max,
                    "eta": topology.projection.eta,
                    "beta_scale": topology.projection.beta_scale,
                    "update_interval": topology.projection.update_interval,
                    "write_density_plot": topology.write_density_plot,
                },
            ),
            execution=ExecutionSpec(
                initial_tasks=list(config.initial_tasks),
                backend_hints={"topology": topology.tool},
                source="workflow_config_adapter",
            ),
        )

    def _structural_geometry(self, config: WorkflowConfig) -> GeometrySpec | None:
        if config.meshing.geometry_input_path:
            suffix = Path(config.meshing.geometry_input_path).suffix.lower()
            file_format = "step" if suffix == ".step" else "stp" if suffix == ".stp" else "bdf"
            return GeometrySpec(
                source_type="file",
                path=config.meshing.geometry_input_path,
                file_format=file_format,
            )
        if config.fea.model_input_path:
            return GeometrySpec(
                source_type="file",
                path=config.fea.model_input_path,
                file_format="bdf",
            )
        return None

    def _structural_meshing(self, config: WorkflowConfig) -> MeshingSpec | None:
        return MeshingSpec(
            tool=config.meshing.tool,
            gmsh_executable=config.meshing.gmsh_executable,
            mesh_dimension=config.meshing.mesh_dimension,
            step_face_selector=config.meshing.step_face_selector,
            volume_element_preference=config.meshing.volume_element_preference,
            output_format=config.meshing.output_format,
            target_quality=config.meshing.target_quality,
        )

    def _structural_model_type(self, config: WorkflowConfig) -> str:
        if config.fea.solid_setup is not None:
            return "solid"
        if config.fea.model_input_path:
            return "shell"
        if config.meshing.mesh_dimension == 3:
            return "solid"
        return "plane_stress"

    def _default_structural_material(self) -> MaterialSpec:
        return MaterialSpec(
            id="default_structural_material",
            name="Default Structural Material",
            model="implicit_solver_default",
            metadata={"source": "solver_backend_default"},
        )

    def _node_sets_from_structural_config(self, config: WorkflowConfig) -> list[NodeSetSpec]:
        node_sets: list[NodeSetSpec] = []
        if config.fea.shell_setup is not None:
            for name, node_set in config.fea.shell_setup.node_sets.items():
                parameters = {
                    key: value
                    for key, value in node_set.model_dump(mode="python").items()
                    if key != "selector" and value is not None
                }
                node_sets.append(
                    NodeSetSpec(
                        name=name,
                        selector=SelectorSpec(kind=node_set.selector, parameters=parameters),
                    )
                )
        if config.fea.solid_setup is not None:
            for name, node_set in config.fea.solid_setup.node_sets.items():
                parameters = {
                    key: value
                    for key, value in node_set.model_dump(mode="python").items()
                    if key != "selector" and value is not None
                }
                node_sets.append(
                    NodeSetSpec(
                        name=name,
                        selector=SelectorSpec(kind=node_set.selector, parameters=parameters),
                    )
                )
        return node_sets

    def _boundary_conditions_from_structural_config(
        self,
        config: WorkflowConfig,
    ) -> list[BoundaryConditionSpec]:
        setup = config.fea.shell_setup or config.fea.solid_setup
        if setup is None:
            return []
        return [
            BoundaryConditionSpec(
                kind="displacement_fixed",
                target=TargetReference(kind="node_set", name=boundary_condition.node_set),
                dof=boundary_condition.dof,
            )
            for boundary_condition in setup.boundary_conditions
        ]

    def _loads_from_structural_config(self, config: WorkflowConfig) -> list[LoadSpec]:
        setup = config.fea.shell_setup or config.fea.solid_setup
        if setup is None:
            return []
        return [
            LoadSpec(
                kind="nodal_force",
                target=TargetReference(kind="node_set", name=load.node_set),
                load_key=load.load_key,
                direction=load.direction,
                distribution=load.distribution,
                metadata=dict(load.metadata),
            )
            for load in setup.loads
        ]

    def _design_variable_spec(self, definition: DesignVariableDefinition) -> DesignVariableSpec:
        target = None
        if definition.region is not None:
            target = TargetReference(kind="named_region", name=definition.region)
        return DesignVariableSpec(
            id=definition.id,
            name=definition.name,
            kind=definition.type.value,
            initial_value=definition.initial_value,
            bounds_lower=definition.bounds.lower,
            bounds_upper=definition.bounds.upper,
            units=definition.units,
            active=definition.active,
            target=target,
            element_ids=list(definition.element_ids),
        )

    def _structural_objectives(self, config: WorkflowConfig) -> list[ObjectiveSpec]:
        if "optimizer" not in config.initial_tasks:
            return []
        return [
            ObjectiveSpec(
                kind="feasibility",
                response="analysis.constraints",
                metadata={
                    "optimizer_backend": "mass_town_heuristic",
                    "note": "Current structural optimizer is a placeholder feasibility recovery loop.",
                },
            )
        ]

    def _structural_constraints(
        self,
        config: WorkflowConfig,
        state: DesignState,
    ) -> list[ConstraintSpec]:
        constraints: list[ConstraintSpec] = []
        if state.constraints.max_stress is not None:
            constraints.append(ConstraintSpec(kind="max_stress", limit=state.constraints.max_stress))
        elif config.allowable_stress is not None:
            constraints.append(ConstraintSpec(kind="max_stress", limit=config.allowable_stress))
        if state.constraints.aggregated_stress is not None:
            constraints.append(
                ConstraintSpec(
                    kind="aggregated_stress",
                    limit=(
                        state.constraints.aggregated_stress.allowable
                        if state.constraints.aggregated_stress.allowable is not None
                        else (state.constraints.max_stress or config.allowable_stress)
                    ),
                    method=state.constraints.aggregated_stress.method,
                    source=state.constraints.aggregated_stress.source,
                    metadata={
                        "ks_weight": state.constraints.aggregated_stress.ks_weight,
                        "p": state.constraints.aggregated_stress.p,
                    },
                )
            )
        if state.constraints.minimum_buckling_load_factor is not None:
            constraints.append(
                ConstraintSpec(
                    kind="minimum_buckling_load_factor",
                    limit=state.constraints.minimum_buckling_load_factor.minimum,
                    mode=state.constraints.minimum_buckling_load_factor.mode,
                )
            )
        if state.constraints.minimum_natural_frequency_hz is not None:
            constraints.append(
                ConstraintSpec(
                    kind="minimum_natural_frequency_hz",
                    limit=state.constraints.minimum_natural_frequency_hz.minimum,
                    mode=state.constraints.minimum_natural_frequency_hz.mode,
                )
            )
        return constraints

    def _structural_optimizer(self, config: WorkflowConfig) -> OptimizerSpec:
        if "optimizer" not in config.initial_tasks:
            return OptimizerSpec(
                enabled=False,
                backend="none",
                strategy="not_requested",
                max_iterations=config.max_iterations,
            )
        return OptimizerSpec(
            enabled=True,
            backend="mass_town_heuristic",
            strategy="stress_recovery_thickness_update",
            max_iterations=config.max_iterations,
            settings={
                "allowable_stress_source": "problem_schema.constraints.max_stress",
                "step_rule": "increase_thickness_when_failed",
            },
        )

    def _structural_analysis_type(self, problem: ProblemSchema) -> str:
        if problem.analysis.analysis_type == "topology_compliance":
            raise ValueError("FEA request conversion does not support topology analysis.")
        return problem.analysis.analysis_type

    def _buckling_setup(self, problem: ProblemSchema) -> FEABucklingSetup | None:
        if problem.analysis.analysis_type != "buckling":
            return None
        if not problem.analysis.buckling_setup:
            return FEABucklingSetup()
        return FEABucklingSetup.model_validate(problem.analysis.buckling_setup)

    def _modal_setup(self, problem: ProblemSchema) -> FEAModalSetup | None:
        if problem.analysis.analysis_type != "modal":
            return None
        if not problem.analysis.modal_setup:
            return FEAModalSetup()
        return FEAModalSetup.model_validate(problem.analysis.modal_setup)

    def _shell_setup(self, problem: ProblemSchema) -> FEAShellSetup | None:
        if problem.model.type not in {"shell", "plane_stress"}:
            return None
        node_sets = {
            node_set.name: FEAShellNodeSet.model_validate(
                {"selector": node_set.selector.kind, **node_set.selector.parameters}
            )
            for node_set in problem.node_sets
        }
        boundary_conditions = [
            FEABoundaryCondition(node_set=bc.target.name, dof=str(bc.dof))
            for bc in problem.boundary_conditions
            if bc.target.kind == "node_set"
        ]
        loads = [
            FEALoad(
                node_set=load.target.name,
                load_key=str(load.load_key),
                direction=tuple(float(component) for component in load.direction or (0.0, 0.0, 0.0)),
                distribution="equal",
                metadata=dict(load.metadata),
            )
            for load in problem.loads
            if load.kind == "nodal_force"
        ]
        return FEAShellSetup(
            node_sets=node_sets,
            boundary_conditions=boundary_conditions,
            loads=loads,
        )

    def _solid_setup(self, problem: ProblemSchema) -> FEASolidSetup | None:
        if problem.model.type != "solid":
            return None
        node_sets = {
            node_set.name: FEASolidNodeSet.model_validate(
                {"selector": node_set.selector.kind, **node_set.selector.parameters}
            )
            for node_set in problem.node_sets
        }
        boundary_conditions = [
            FEABoundaryCondition(node_set=bc.target.name, dof=str(bc.dof))
            for bc in problem.boundary_conditions
            if bc.target.kind == "node_set"
        ]
        loads = [
            FEALoad(
                node_set=load.target.name,
                load_key=str(load.load_key),
                direction=tuple(float(component) for component in load.direction or (0.0, 0.0, 0.0)),
                distribution="equal",
                metadata=dict(load.metadata),
            )
            for load in problem.loads
            if load.kind == "nodal_force"
        ]
        return FEASolidSetup(
            node_sets=node_sets,
            boundary_conditions=boundary_conditions,
            loads=loads,
        )

    def design_variable_assignments(
        self,
        problem: ProblemSchema,
        state: DesignState,
        run_root: Path,
        *,
        model_input_path: Path | None,
        mesh_input_path: Path | None,
    ):
        from mass_town.design_variables import (
            DesignVariableContext,
            bdf_design_variable_context,
            map_design_variables_to_analysis,
        )

        design_variable_definitions = self.design_variable_definitions(problem)
        resolved_values = resolved_design_variable_values(design_variable_definitions, state.design_variables)
        mapping_context = (
            bdf_design_variable_context(model_input_path)
            if model_input_path is not None and model_input_path.suffix.lower() == ".bdf"
            else bdf_design_variable_context(mesh_input_path)
            if mesh_input_path is not None and mesh_input_path.suffix.lower() == ".bdf"
            else DesignVariableContext()
        )
        return map_design_variables_to_analysis(
            design_variable_definitions,
            resolved_values,
            mapping_context,
        )
