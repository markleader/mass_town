from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

import openmdao.api as om

from mass_town.config import WorkflowConfig
from mass_town.disciplines import SensitivityPayload
from mass_town.disciplines.fea import FEABackend, FEARequest, FEAResult
from mass_town.disciplines.postprocessing import PostProcessingRequest, StructuralPostProcessingBackend
from mass_town.models.design_state import DesignState
from mass_town.problem_schema import ProblemSchema, ProblemSchemaResolver
from mass_town.storage.filesystem import RunLayout


FallbackReporter = Callable[[str, str, str, list[str]], None]


def sensitivity_map(payloads: list[SensitivityPayload]) -> dict[tuple[str, str], float]:
    mapped: dict[tuple[str, str], float] = {}
    for payload in payloads:
        if len(payload.values) != 1:
            continue
        mapped[(payload.response, payload.with_respect_to)] = float(payload.values[0])
    return mapped


class StructuralAnalysisComp(om.ExplicitComponent):
    def __init__(
        self,
        *,
        config: WorkflowConfig,
        problem: ProblemSchema,
        state: DesignState,
        run_root: Path,
        layout: RunLayout,
        backend: FEABackend,
        schema_resolver: ProblemSchemaResolver,
        fallback_reporter: FallbackReporter | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.problem = problem
        self.state = state
        self.run_root = run_root
        self.layout = layout
        self.backend = backend
        self.schema_resolver = schema_resolver
        self.fallback_reporter = fallback_reporter
        self.active_definitions = [
            definition
            for definition in schema_resolver.design_variable_definitions(problem)
            if definition.active
        ]
        self._latest_result: FEAResult | None = None
        self._latest_input_signature: tuple[tuple[str, float], ...] | None = None
        self._latest_sensitivity_map: dict[tuple[str, str], float] = {}

    def setup(self) -> None:
        for definition in self.active_definitions:
            self.add_input(definition.id, val=float(self.state.design_variables.get(definition.id, definition.initial_value)))
        self.add_output("mass", val=0.0)
        self.add_output("max_stress", val=0.0)
        self.add_output("displacement_norm", val=0.0)

    def setup_partials(self) -> None:
        initial_values = {
            definition.id: float(self.state.design_variables.get(definition.id, definition.initial_value))
            for definition in self.active_definitions
        }
        result = self._run_analysis(initial_values)
        self._declare_partials(result)

    def compute(self, inputs: om.DefaultVector, outputs: om.DefaultVector) -> None:
        design_values = {
            definition.id: float(inputs[definition.id][0])
            for definition in self.active_definitions
        }
        result = self._run_analysis(design_values)
        outputs["mass"] = float(result.mass or 0.0)
        outputs["max_stress"] = float(result.max_stress or 0.0)
        outputs["displacement_norm"] = float(result.displacement_norm or 0.0)

    def compute_partials(
        self,
        inputs: om.DefaultVector,
        partials: om.DefaultVector,
    ) -> None:
        if self._latest_result is None:
            design_values = {
                definition.id: float(inputs[definition.id][0])
                for definition in self.active_definitions
            }
            self._run_analysis(design_values)
        for (response, design_variable), value in self._latest_sensitivity_map.items():
            partials[response, design_variable] = value

    @property
    def latest_result(self) -> FEAResult | None:
        return self._latest_result

    def _run_analysis(self, design_values: Mapping[str, float]) -> FEAResult:
        input_signature = tuple(sorted((name, float(value)) for name, value in design_values.items()))
        if self._latest_result is not None and self._latest_input_signature == input_signature:
            return self._latest_result

        transient_state = self.state.model_copy(deep=True)
        transient_state.design_variables.update({name: float(value) for name, value in design_values.items()})
        request = self.schema_resolver.build_fea_request(
            self.problem,
            transient_state,
            self.run_root,
            report_directory=self.layout.reports_dir,
            log_directory=self.layout.logs_dir,
            solution_directory=self.layout.solver_dir,
            mesh_input_path=None,
        )
        result = self.backend.run_analysis(request)
        self._latest_result = result
        self._latest_input_signature = input_signature
        self._latest_sensitivity_map = sensitivity_map(result.sensitivities)
        return result

    def _declare_partials(self, result: FEAResult) -> None:
        available = sensitivity_map(result.sensitivities)
        missing_pairs: list[str] = []
        for response in ("mass", "max_stress", "displacement_norm"):
            for definition in self.active_definitions:
                key = (response, definition.id)
                if key in available:
                    self.declare_partials(of=response, wrt=definition.id)
                else:
                    self.declare_partials(of=response, wrt=definition.id, method="fd")
                    missing_pairs.append(f"{response}<-{definition.id}")
        if missing_pairs and self.fallback_reporter is not None:
            model_name = self.problem.model.model_input_path or "unknown_model"
            self.fallback_reporter("analysis", self.backend.name, model_name, missing_pairs)


class StructuralPostprocessingComp(om.ExplicitComponent):
    def __init__(
        self,
        *,
        config: WorkflowConfig,
        problem: ProblemSchema,
        state: DesignState,
        run_root: Path,
        layout: RunLayout,
        objective_kind: str,
        include_max_stress_constraint: bool,
    ) -> None:
        super().__init__()
        self.config = config
        self.problem = problem
        self.state = state
        self.run_root = run_root
        self.layout = layout
        self.objective_kind = objective_kind
        self.include_max_stress_constraint = include_max_stress_constraint
        self.postprocessor = StructuralPostProcessingBackend()
        self.schema_resolver = ProblemSchemaResolver()
        self._latest_request: PostProcessingRequest | None = None
        self._latest_passed = False
        self._latest_sensitivities: dict[tuple[str, str], float] = {}

    def setup(self) -> None:
        self.add_input("mass", val=0.0)
        self.add_input("max_stress", val=0.0)
        self.add_input("displacement_norm", val=0.0)
        self.add_output("objective", val=0.0)
        if self.include_max_stress_constraint:
            self.add_output("max_stress_margin", val=0.0)

    def setup_partials(self) -> None:
        self.declare_partials(of="objective", wrt="mass")
        if self.include_max_stress_constraint:
            self.declare_partials(of="max_stress_margin", wrt="max_stress")

    def compute(self, inputs: om.DefaultVector, outputs: om.DefaultVector) -> None:
        request = self._build_request(inputs)
        result = self.postprocessor.process(request)
        self._latest_request = request
        self._latest_passed = result.passed
        self._latest_sensitivities = {
            ("objective", "mass"): 1.0,
            ("max_stress_margin", "max_stress"): 1.0,
        }
        if self.objective_kind == "minimize_mass":
            outputs["objective"] = self._scalar_input(inputs, "mass")
        else:
            outputs["objective"] = 0.0
        if self.include_max_stress_constraint:
            outputs["max_stress_margin"] = (
                self._scalar_input(inputs, "max_stress") - float(self.config.allowable_stress)
            )

    def compute_partials(
        self,
        inputs: om.DefaultVector,
        partials: om.DefaultVector,
    ) -> None:
        del inputs
        partials["objective", "mass"] = self._latest_sensitivities.get(("objective", "mass"), 0.0)
        if self.include_max_stress_constraint:
            partials["max_stress_margin", "max_stress"] = self._latest_sensitivities.get(
                ("max_stress_margin", "max_stress"),
                0.0,
            )

    @property
    def latest_passed(self) -> bool:
        return self._latest_passed

    def _build_request(self, inputs: om.DefaultVector) -> PostProcessingRequest:
        transient_state = self.state.model_copy(deep=True)
        fea_request = FEARequest(
            model_input_path=(
                self.run_root / self.problem.model.model_input_path
                if self.problem.model.model_input_path is not None
                else None
            ),
            report_directory=self.layout.reports_dir,
            log_directory=self.layout.logs_dir,
            solution_directory=self.layout.solver_dir,
            run_id=transient_state.run_id,
            loads=dict(transient_state.loads),
            design_variables=dict(transient_state.design_variables),
            design_variable_assignments=self.schema_resolver.design_variable_assignments(
                self.problem,
                transient_state,
                self.run_root,
                model_input_path=(
                    self.run_root / self.problem.model.model_input_path
                    if self.problem.model.model_input_path is not None
                    else None
                ),
                mesh_input_path=None,
            ),
            constraints=self.schema_resolver.constraint_set(self.problem),
            allowable_stress=self.schema_resolver.allowable_stress(self.problem),
            case_name=self.problem.analysis.case_name or "static",
            analysis_type=self.problem.analysis.analysis_type,
        )
        fea_result = FEAResult(
            backend_name="openmdao_structural_analysis",
            passed=self._scalar_input(inputs, "max_stress") <= self.config.allowable_stress,
            mass=self._scalar_input(inputs, "mass"),
            max_stress=self._scalar_input(inputs, "max_stress"),
            displacement_norm=self._scalar_input(inputs, "displacement_norm"),
        )
        return PostProcessingRequest(
            fea_request=fea_request,
            fea_result=fea_result,
        )

    def _scalar_input(self, inputs: om.DefaultVector, name: str) -> float:
        return float(inputs[name][0])
