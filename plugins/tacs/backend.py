import importlib
import json
from pathlib import Path
import re
import time
from typing import Any

from mass_town.constraints import aggregate_case_stresses
from mass_town.disciplines.fea import FEABackend, FEALoadCaseResult, FEARequest, FEAResult
from mass_town.storage.filesystem import ensure_directory

from .shell_model import (
    describe_boundary_loops,
    distribute_force_to_nodes,
    find_boundary_loops,
    select_boundary_loop,
)


class TacsFEABackend(FEABackend):
    name = "tacs"

    def is_available(self) -> bool:
        try:
            self._load_tacs_modules()
        except ImportError:
            return False
        return True

    def availability_reason(self) -> str | None:
        try:
            self._load_tacs_modules()
        except ImportError as exc:
            return f"TACS Python package is not installed or failed to import: {exc}"
        return None

    def run_analysis(self, request: FEARequest) -> FEAResult:
        if request.model_input_path is None:
            raise ValueError("The tacs backend requires a BDF model input path.")

        model_path = request.model_input_path
        if model_path.suffix.lower() != ".bdf":
            raise ValueError("The tacs backend only supports .bdf model input files.")
        if not model_path.exists():
            raise FileNotFoundError(f"FEA model input does not exist: {model_path}")

        report_directory = ensure_directory(request.report_directory)
        log_directory = ensure_directory(request.log_directory)
        solution_directory = ensure_directory(request.solution_directory)
        summary_path = report_directory / f"{model_path.stem}.tacs.summary.json"
        log_path = log_directory / f"{model_path.stem}.tacs.log"

        pyTACS, functions, constitutive, elements, bdf_class = self._load_tacs_modules()

        try:
            bdf_info = self._load_bdf(model_path, bdf_class)
            if request.analysis_type == "buckling":
                if self._is_shell_model(bdf_info):
                    analysis = self._run_shell_buckling_analysis(
                        request=request,
                        bdf_info=bdf_info,
                        bdf_class=bdf_class,
                        pyTACS=pyTACS,
                        functions=functions,
                        constitutive=constitutive,
                        elements=elements,
                        output_directory=solution_directory,
                    )
                else:
                    raise ValueError(
                        "The tacs buckling path currently supports shell BDF models with "
                        "explicit shell load configuration."
                    )
            elif self._is_shell_model(bdf_info):
                analysis = self._run_shell_analysis(
                    request=request,
                    bdf_info=bdf_info,
                    bdf_class=bdf_class,
                    pyTACS=pyTACS,
                    functions=functions,
                    constitutive=constitutive,
                    elements=elements,
                    output_directory=solution_directory,
                )
            elif request.solid_setup is not None:
                analysis = self._run_solid_analysis(
                    request=request,
                    bdf_info=bdf_info,
                    bdf_class=bdf_class,
                    pyTACS=pyTACS,
                    functions=functions,
                    constitutive=constitutive,
                    elements=elements,
                    output_directory=solution_directory,
                )
            else:
                analysis = self._run_bdf_analysis(
                    request=request,
                    model_path=model_path,
                    pyTACS=pyTACS,
                    functions=functions,
                    output_directory=solution_directory,
                )
        except Exception as exc:
            log_path.write_text(f"TACS analysis failed: {exc}\n")
            raise RuntimeError(f"TACS analysis failed. See log: {log_path}") from exc

        requested_case_loads = self._requested_case_loads(request)
        backend_version = self._backend_version()
        case_results: dict[str, FEALoadCaseResult] = {}
        case_result_files: list[Path] = []
        summary_case_data: dict[str, dict[str, Any]] = {}
        for case_name, case_analysis in analysis["load_cases"].items():
            case_summary_path = report_directory / f"{model_path.stem}.{case_name}.tacs.summary.json"
            case_summary = {
                "backend": self.name,
                "case_name": case_name,
                "analysis_type": request.analysis_type,
                "input_model": str(model_path),
                "load_source": case_analysis["load_source"],
                "loads": requested_case_loads.get(case_name, {}),
                "mass": case_analysis["mass"],
                "failure_index": case_analysis["failure_index"],
                "max_stress": case_analysis["max_stress"],
                "raw_max_stress": case_analysis.get("raw_max_stress"),
                "raw_max_stress_source": case_analysis.get("raw_max_stress_source"),
                "displacement_norm": case_analysis["displacement_norm"],
                "functions": case_analysis.get("function_values", {}),
                "static_functions": case_analysis.get("static_function_values"),
                "buckling_functions": case_analysis.get("buckling_function_values"),
                "eigenvalues": case_analysis.get("eigenvalues", []),
                "critical_eigenvalue": case_analysis.get("critical_eigenvalue"),
                "boundary_conditions": case_analysis.get("boundary_conditions"),
                "analysis_seconds": case_analysis["analysis_seconds"],
            }
            if request.analysis_type == "buckling":
                case_summary["buckling_load_factors"] = case_analysis.get("eigenvalues", [])
                case_summary["critical_buckling_load_factor"] = case_analysis.get(
                    "critical_eigenvalue"
                )
            if "selected_case_name" in case_analysis:
                case_summary["selected_case_name"] = case_analysis["selected_case_name"]
            case_summary_path.write_text(json.dumps(case_summary, indent=2, sort_keys=True) + "\n")

            case_metadata: dict[str, str | float | int | bool] = {
                "input_model": str(model_path),
                "case_name": case_name,
                "analysis_type": request.analysis_type,
                "load_source": case_analysis["load_source"],
                "function_names": ",".join(sorted(case_analysis.get("function_values", {}))),
            }
            if "selected_case_name" in case_analysis:
                case_metadata["selected_case_name"] = case_analysis["selected_case_name"]
            if case_analysis["failure_index"] is not None:
                case_metadata["failure_index"] = round(float(case_analysis["failure_index"]), 6)
            if case_analysis.get("raw_max_stress") is not None:
                case_metadata["raw_max_stress"] = round(
                    float(case_analysis["raw_max_stress"]),
                    6,
                )
            if case_analysis.get("raw_max_stress_source") is not None:
                case_metadata["raw_max_stress_source"] = str(
                    case_analysis["raw_max_stress_source"]
                )
            if case_analysis.get("critical_eigenvalue") is not None:
                case_metadata["critical_eigenvalue"] = round(
                    float(case_analysis["critical_eigenvalue"]),
                    6,
                )
            if backend_version is not None:
                case_metadata["backend_version"] = backend_version
            if request.mesh_input_path is not None:
                case_metadata["mesh_input_path"] = str(request.mesh_input_path)

            case_results[case_name] = FEALoadCaseResult(
                passed=(
                    case_analysis["failure_index"] is None
                    or case_analysis["failure_index"] <= 1.0
                ),
                result_files=[case_summary_path],
                mass=case_analysis["mass"],
                max_stress=case_analysis["max_stress"],
                displacement_norm=case_analysis["displacement_norm"],
                analysis_type=request.analysis_type,
                eigenvalues=list(case_analysis.get("eigenvalues", [])),
                critical_eigenvalue=case_analysis.get("critical_eigenvalue"),
                metadata=case_metadata,
                analysis_seconds=case_analysis["analysis_seconds"],
            )
            case_result_files.append(case_summary_path)
            summary_case_data[case_name] = {
                "analysis_type": request.analysis_type,
                "mass": case_analysis["mass"],
                "failure_index": case_analysis["failure_index"],
                "max_stress": case_analysis["max_stress"],
                "raw_max_stress": case_analysis.get("raw_max_stress"),
                "raw_max_stress_source": case_analysis.get("raw_max_stress_source"),
                "displacement_norm": case_analysis["displacement_norm"],
                "eigenvalues": case_analysis.get("eigenvalues", []),
                "critical_eigenvalue": case_analysis.get("critical_eigenvalue"),
                "analysis_seconds": case_analysis["analysis_seconds"],
                "summary_path": str(case_summary_path),
            }
            if request.analysis_type == "buckling":
                summary_case_data[case_name]["buckling_load_factors"] = case_analysis.get(
                    "eigenvalues",
                    [],
                )
                summary_case_data[case_name]["critical_buckling_load_factor"] = case_analysis.get(
                    "critical_eigenvalue"
                )
            if "selected_case_name" in case_analysis:
                summary_case_data[case_name]["selected_case_name"] = case_analysis["selected_case_name"]

        aggregation_quality_summary_path = self._write_aggregation_quality_summary(
            request=request,
            report_directory=report_directory,
            case_analyses=analysis["load_cases"],
        )
        result_files = [summary_path, *case_result_files]
        if aggregation_quality_summary_path is not None:
            result_files.append(aggregation_quality_summary_path)

        summary = {
            "backend": self.name,
            "case_name": analysis["case_name"],
            "analysis_type": request.analysis_type,
            "input_model": str(model_path),
            "load_source": analysis["load_source"],
            "loads": requested_case_loads.get(analysis["case_name"], {}),
            "load_cases": summary_case_data,
            "mass": analysis["mass"],
            "failure_index": analysis["failure_index"],
            "max_stress": analysis["max_stress"],
            "displacement_norm": analysis["displacement_norm"],
            "functions": analysis.get("function_values", {}),
            "static_functions": analysis.get("static_function_values"),
            "buckling_functions": analysis.get("buckling_function_values"),
            "eigenvalues": analysis.get("eigenvalues", []),
            "critical_eigenvalue": analysis.get("critical_eigenvalue"),
            "boundary_conditions": analysis.get("boundary_conditions"),
            "worst_case_name": analysis["case_name"],
            "aggregation_quality_summary_path": (
                str(aggregation_quality_summary_path)
                if aggregation_quality_summary_path is not None
                else None
            ),
            "analysis_seconds": analysis["analysis_seconds"],
        }
        if request.analysis_type == "buckling":
            summary["buckling_load_factors"] = analysis.get("eigenvalues", [])
            summary["critical_buckling_load_factor"] = analysis.get("critical_eigenvalue")
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        log_path.write_text(
            "TACS analysis completed successfully.\n"
            f"case_count={len(case_results)}\n"
            f"worst_case_name={analysis['case_name']}\n"
        )

        metadata: dict[str, str | float | int | bool] = {
            "input_model": str(model_path),
            "case_name": analysis["case_name"],
            "analysis_type": request.analysis_type,
            "load_source": analysis["load_source"],
            "function_names": ",".join(sorted(analysis.get("function_values", {}))),
            "load_case_count": len(case_results),
            "worst_case_name": analysis["case_name"],
        }
        if analysis["failure_index"] is not None:
            metadata["failure_index"] = round(float(analysis["failure_index"]), 6)
        if analysis.get("critical_eigenvalue") is not None:
            metadata["critical_eigenvalue"] = round(float(analysis["critical_eigenvalue"]), 6)
        if backend_version is not None:
            metadata["backend_version"] = backend_version
        if request.mesh_input_path is not None:
            metadata["mesh_input_path"] = str(request.mesh_input_path)
        if analysis["analysis_seconds"] is not None:
            metadata["analysis_seconds"] = round(float(analysis["analysis_seconds"]), 6)
        if aggregation_quality_summary_path is not None:
            metadata["aggregation_quality_summary_path"] = str(
                aggregation_quality_summary_path
            )

        passed = analysis["failure_index"] is None or analysis["failure_index"] <= 1.0

        return FEAResult(
            backend_name=self.name,
            passed=passed,
            mass=analysis["mass"],
            max_stress=analysis["max_stress"],
            displacement_norm=analysis["displacement_norm"],
            analysis_type=request.analysis_type,
            eigenvalues=list(analysis.get("eigenvalues", [])),
            critical_eigenvalue=analysis.get("critical_eigenvalue"),
            result_files=result_files,
            metadata=metadata,
            log_path=log_path,
            load_cases=case_results,
            worst_case_name=analysis["case_name"],
            aggregation_quality_summary_path=aggregation_quality_summary_path,
            analysis_seconds=analysis["analysis_seconds"],
        )

    def _load_tacs_modules(self) -> tuple[Any, Any, Any, Any, Any]:
        pytacs_module = importlib.import_module("tacs.pytacs")
        functions_module = importlib.import_module("tacs.functions")
        constitutive_module = importlib.import_module("tacs.constitutive")
        elements_module = importlib.import_module("tacs.elements")
        bdf_module = importlib.import_module("pyNastran.bdf.bdf")
        return (
            pytacs_module.pyTACS,
            functions_module,
            constitutive_module,
            elements_module,
            bdf_module.BDF,
        )

    def _backend_version(self) -> str | None:
        try:
            module = importlib.import_module("tacs")
        except ImportError:
            return None
        return getattr(module, "__version__", None)

    def _run_shell_analysis(
        self,
        *,
        request: FEARequest,
        bdf_info: Any,
        bdf_class: Any | None = None,
        pyTACS: Any,
        functions: Any,
        constitutive: Any,
        elements: Any,
        output_directory: Path,
    ) -> dict[str, Any]:
        node_positions = self._extract_node_positions(bdf_info)
        shell_elements = self._extract_shell_elements(bdf_info)
        resolved_node_sets = self._resolve_shell_node_sets(
            request=request,
            node_positions=node_positions,
            shell_elements=shell_elements,
        )

        shell_thickness = self._resolve_shell_thickness_assignments(
            request,
            request.model_input_path,
            bdf_info,
        )

        case_analyses: dict[str, dict[str, Any]] = {}
        requested_case_loads = self._requested_case_loads(request)
        for case_name, case_loads in requested_case_loads.items():
            started_at = time.perf_counter()
            case_bdf_info = (
                self._load_bdf(request.model_input_path, bdf_class)
                if bdf_class is not None and request.model_input_path is not None
                else bdf_info
            )
            constrained_nodes, bc_mode = self._apply_shell_boundary_conditions(
                request=request,
                bdf_info=case_bdf_info,
                resolved_node_sets=resolved_node_sets,
            )
            assembler = pyTACS(case_bdf_info)
            assembler.initialize(
                self._build_shell_element_callback(
                    constitutive=constitutive,
                    elements=elements,
                    default_thickness=shell_thickness["default_thickness"],
                    component_thickness=shell_thickness["component_thickness"],
                    allowable_stress=request.allowable_stress,
                )
            )
            problem = assembler.createStaticProblem(case_name)
            self._add_functions(problem, functions)
            loaded_nodes, load_mode = self._apply_shell_loads(
                request=request,
                requested_loads=case_loads,
                problem=problem,
                resolved_node_sets=resolved_node_sets,
            )
            problem.solve()

            if request.write_solution and hasattr(problem, "writeSolution"):
                case_output_directory = ensure_directory(output_directory / case_name)
                problem.writeSolution(outputDir=str(case_output_directory))

            function_values: dict[str, float] = {}
            problem.evalFunctions(function_values)
            failure_index = self._extract_failure_index(function_values)
            max_stress = (
                float(failure_index) * request.allowable_stress if failure_index is not None else None
            )
            raw_max_stress, raw_max_stress_source = self._extract_raw_max_stress(
                problem,
                fallback_stress=max_stress,
            )
            case_analyses[case_name] = {
                "case_name": case_name,
                "load_source": "script",
                "function_values": function_values,
                "mass": self._extract_mass(function_values),
                "failure_index": failure_index,
                "max_stress": max_stress,
                "raw_max_stress": raw_max_stress,
                "raw_max_stress_source": raw_max_stress_source,
                "displacement_norm": self._extract_displacement_norm(problem),
                "boundary_conditions": {
                    "constrained_node_count": len(constrained_nodes),
                    "loaded_node_count": len(loaded_nodes),
                    "bc_mode": bc_mode,
                    "load_mode": load_mode,
                },
                "analysis_seconds": time.perf_counter() - started_at,
            }

        worst_case_name = self._select_worst_case_name(
            case_analyses,
            list(requested_case_loads),
        )
        worst_case = case_analyses[worst_case_name]

        return {
            "case_name": worst_case_name,
            "load_source": "script",
            "function_values": worst_case["function_values"],
            "mass": worst_case["mass"],
            "failure_index": worst_case["failure_index"],
            "max_stress": worst_case["max_stress"],
            "displacement_norm": worst_case["displacement_norm"],
            "boundary_conditions": worst_case["boundary_conditions"],
            "load_cases": case_analyses,
            "analysis_seconds": sum(
                case_analysis["analysis_seconds"] for case_analysis in case_analyses.values()
            ),
        }

    def _run_solid_analysis(
        self,
        *,
        request: FEARequest,
        bdf_info: Any,
        bdf_class: Any | None = None,
        pyTACS: Any,
        functions: Any,
        constitutive: Any,
        elements: Any,
        output_directory: Path,
    ) -> dict[str, Any]:
        node_positions = self._extract_node_positions(bdf_info)
        resolved_node_sets = self._resolve_solid_node_sets(
            request=request,
            node_positions=node_positions,
        )
        case_analyses: dict[str, dict[str, Any]] = {}
        requested_case_loads = self._requested_case_loads(request)
        for case_name, case_loads in requested_case_loads.items():
            started_at = time.perf_counter()
            case_bdf_info = (
                self._load_bdf(request.model_input_path, bdf_class)
                if bdf_class is not None and request.model_input_path is not None
                else bdf_info
            )
            case_node_positions = self._extract_node_positions(case_bdf_info)
            case_resolved_node_sets = (
                self._resolve_solid_node_sets(
                    request=request,
                    node_positions=case_node_positions,
                )
                if case_bdf_info is not bdf_info
                else resolved_node_sets
            )
            constrained_nodes, bc_mode = self._apply_solid_boundary_conditions(
                request=request,
                bdf_info=case_bdf_info,
                resolved_node_sets=case_resolved_node_sets,
            )
            assembler = pyTACS(case_bdf_info)
            assembler.initialize(
                self._build_solid_element_callback(
                    constitutive=constitutive,
                    elements=elements,
                    allowable_stress=request.allowable_stress,
                )
            )
            problem = assembler.createStaticProblem(case_name)
            self._add_functions(problem, functions)
            loaded_nodes, load_mode = self._apply_solid_loads(
                request=request,
                requested_loads=case_loads,
                problem=problem,
                resolved_node_sets=case_resolved_node_sets,
            )
            problem.solve()

            if request.write_solution and hasattr(problem, "writeSolution"):
                case_output_directory = ensure_directory(output_directory / case_name)
                problem.writeSolution(outputDir=str(case_output_directory))

            function_values: dict[str, float] = {}
            problem.evalFunctions(function_values)
            failure_index = self._extract_failure_index(function_values)
            max_stress = (
                float(failure_index) * request.allowable_stress if failure_index is not None else None
            )
            raw_max_stress, raw_max_stress_source = self._extract_raw_max_stress(
                problem,
                fallback_stress=max_stress,
            )
            case_analyses[case_name] = {
                "case_name": case_name,
                "load_source": "script",
                "function_values": function_values,
                "mass": self._extract_mass(function_values),
                "failure_index": failure_index,
                "max_stress": max_stress,
                "raw_max_stress": raw_max_stress,
                "raw_max_stress_source": raw_max_stress_source,
                "displacement_norm": self._extract_displacement_norm(problem),
                "boundary_conditions": {
                    "constrained_node_count": len(constrained_nodes),
                    "loaded_node_count": len(loaded_nodes),
                    "bc_mode": bc_mode,
                    "load_mode": load_mode,
                },
                "analysis_seconds": time.perf_counter() - started_at,
            }

        worst_case_name = self._select_worst_case_name(
            case_analyses,
            list(requested_case_loads),
        )
        worst_case = case_analyses[worst_case_name]
        return {
            "case_name": worst_case_name,
            "load_source": "script",
            "function_values": worst_case["function_values"],
            "mass": worst_case["mass"],
            "failure_index": worst_case["failure_index"],
            "max_stress": worst_case["max_stress"],
            "displacement_norm": worst_case["displacement_norm"],
            "boundary_conditions": worst_case["boundary_conditions"],
            "load_cases": case_analyses,
            "analysis_seconds": sum(
                case_analysis["analysis_seconds"] for case_analysis in case_analyses.values()
            ),
        }

    def _run_shell_buckling_analysis(
        self,
        *,
        request: FEARequest,
        bdf_info: Any,
        bdf_class: Any | None = None,
        pyTACS: Any,
        functions: Any,
        constitutive: Any,
        elements: Any,
        output_directory: Path,
    ) -> dict[str, Any]:
        node_positions = self._extract_node_positions(bdf_info)
        shell_elements = self._extract_shell_elements(bdf_info)
        resolved_node_sets = self._resolve_shell_node_sets(
            request=request,
            node_positions=node_positions,
            shell_elements=shell_elements,
        )
        shell_thickness = self._resolve_shell_thickness_assignments(
            request,
            request.model_input_path,
            bdf_info,
        )

        case_analyses: dict[str, dict[str, Any]] = {}
        requested_case_loads = self._requested_case_loads(request)
        for case_name, case_loads in requested_case_loads.items():
            started_at = time.perf_counter()
            case_bdf_info = (
                self._load_bdf(request.model_input_path, bdf_class)
                if bdf_class is not None and request.model_input_path is not None
                else bdf_info
            )
            constrained_nodes, bc_mode = self._apply_shell_boundary_conditions(
                request=request,
                bdf_info=case_bdf_info,
                resolved_node_sets=resolved_node_sets,
            )
            assembler = pyTACS(case_bdf_info)
            assembler.initialize(
                self._build_shell_element_callback(
                    constitutive=constitutive,
                    elements=elements,
                    default_thickness=shell_thickness["default_thickness"],
                    component_thickness=shell_thickness["component_thickness"],
                    allowable_stress=request.allowable_stress,
                )
            )

            static_problem = assembler.createStaticProblem(case_name)
            self._add_functions(static_problem, functions)
            loaded_nodes, load_mode = self._apply_shell_loads(
                request=request,
                requested_loads=case_loads,
                problem=static_problem,
                resolved_node_sets=resolved_node_sets,
            )
            static_problem.solve()
            if request.write_solution and hasattr(static_problem, "writeSolution"):
                static_output_directory = ensure_directory(output_directory / case_name / "static")
                static_problem.writeSolution(outputDir=str(static_output_directory))

            static_function_values: dict[str, float] = {}
            static_problem.evalFunctions(static_function_values)
            failure_index = self._extract_failure_index(static_function_values)
            max_stress = (
                float(failure_index) * request.allowable_stress if failure_index is not None else None
            )
            raw_max_stress, raw_max_stress_source = self._extract_raw_max_stress(
                static_problem,
                fallback_stress=max_stress,
            )
            displacement_norm = self._extract_displacement_norm(static_problem)
            mass = self._extract_mass(static_function_values)

            buckling_problem = self._create_buckling_problem(assembler, request, case_name)
            self._apply_shell_loads(
                request=request,
                requested_loads=case_loads,
                problem=buckling_problem,
                resolved_node_sets=resolved_node_sets,
            )
            buckling_problem.solve()
            if request.write_solution and hasattr(buckling_problem, "writeSolution"):
                buckling_output_directory = ensure_directory(output_directory / case_name / "buckling")
                buckling_problem.writeSolution(outputDir=str(buckling_output_directory))

            buckling_function_values: dict[str, float] = {}
            buckling_problem.evalFunctions(buckling_function_values)
            eigenvalues = self._extract_eigenvalues(buckling_function_values)
            critical_eigenvalue = self._extract_critical_eigenvalue(eigenvalues)

            case_analyses[case_name] = {
                "case_name": case_name,
                "load_source": "script",
                "function_values": static_function_values,
                "static_function_values": static_function_values,
                "buckling_function_values": buckling_function_values,
                "mass": mass,
                "failure_index": failure_index,
                "max_stress": max_stress,
                "raw_max_stress": raw_max_stress,
                "raw_max_stress_source": raw_max_stress_source,
                "displacement_norm": displacement_norm,
                "eigenvalues": eigenvalues,
                "critical_eigenvalue": critical_eigenvalue,
                "boundary_conditions": {
                    "constrained_node_count": len(constrained_nodes),
                    "loaded_node_count": len(loaded_nodes),
                    "bc_mode": bc_mode,
                    "load_mode": load_mode,
                },
                "analysis_seconds": time.perf_counter() - started_at,
            }

        worst_case_name = self._select_case_name_by_metric(
            case_analyses,
            list(requested_case_loads),
            metric="critical_eigenvalue",
            reverse=False,
        )
        worst_case = case_analyses[worst_case_name]
        return {
            "case_name": worst_case_name,
            "load_source": "script",
            "function_values": worst_case["function_values"],
            "static_function_values": worst_case["static_function_values"],
            "buckling_function_values": worst_case["buckling_function_values"],
            "mass": worst_case["mass"],
            "failure_index": worst_case["failure_index"],
            "max_stress": worst_case["max_stress"],
            "displacement_norm": worst_case["displacement_norm"],
            "eigenvalues": worst_case["eigenvalues"],
            "critical_eigenvalue": worst_case["critical_eigenvalue"],
            "boundary_conditions": worst_case["boundary_conditions"],
            "load_cases": case_analyses,
            "analysis_seconds": sum(
                case_analysis["analysis_seconds"] for case_analysis in case_analyses.values()
            ),
        }

    def _run_bdf_analysis(
        self,
        *,
        request: FEARequest,
        model_path: Path,
        pyTACS: Any,
        functions: Any,
        output_directory: Path,
    ) -> dict[str, Any]:
        assembler = pyTACS(str(model_path))
        assembler.initialize()
        problems = assembler.createTACSProbsFromBDF()
        if not problems:
            raise RuntimeError("TACS did not create any analysis cases from the BDF input.")

        requested_case_loads = self._requested_case_loads(request)
        strict_case_selection = self._requires_strict_case_selection(request)
        case_analyses: dict[str, dict[str, Any]] = {}
        for case_name in requested_case_loads:
            started_at = time.perf_counter()
            selected_name, problem = self._select_problem(
                problems,
                case_name,
                strict=strict_case_selection,
            )
            self._add_functions(problem, functions)
            problem.solve()

            if request.write_solution and hasattr(problem, "writeSolution"):
                case_output_directory = ensure_directory(output_directory / case_name)
                problem.writeSolution(outputDir=str(case_output_directory))

            function_values: dict[str, float] = {}
            problem.evalFunctions(function_values)
            failure_index = self._extract_failure_index(function_values)
            max_stress = (
                float(failure_index) * request.allowable_stress if failure_index is not None else None
            )
            raw_max_stress, raw_max_stress_source = self._extract_raw_max_stress(
                problem,
                fallback_stress=max_stress,
            )
            case_analyses[case_name] = {
                "case_name": case_name,
                "selected_case_name": selected_name,
                "load_source": "bdf",
                "function_values": function_values,
                "mass": self._extract_mass(function_values),
                "failure_index": failure_index,
                "max_stress": max_stress,
                "raw_max_stress": raw_max_stress,
                "raw_max_stress_source": raw_max_stress_source,
                "displacement_norm": self._extract_displacement_norm(problem),
                "analysis_seconds": time.perf_counter() - started_at,
            }

        worst_case_name = self._select_worst_case_name(
            case_analyses,
            list(requested_case_loads),
        )
        worst_case = case_analyses[worst_case_name]

        return {
            "case_name": worst_case_name,
            "load_source": "bdf",
            "function_values": worst_case["function_values"],
            "mass": worst_case["mass"],
            "failure_index": worst_case["failure_index"],
            "max_stress": worst_case["max_stress"],
            "displacement_norm": worst_case["displacement_norm"],
            "load_cases": case_analyses,
            "analysis_seconds": sum(
                case_analysis["analysis_seconds"] for case_analysis in case_analyses.values()
            ),
        }

    def _create_buckling_problem(self, assembler: Any, request: FEARequest, case_name: str) -> Any:
        buckling_setup = request.buckling_setup
        sigma = buckling_setup.sigma if buckling_setup is not None else 10.0
        num_eigenvalues = (
            buckling_setup.num_eigenvalues if buckling_setup is not None else 5
        )
        return assembler.createBucklingProblem(
            f"{case_name}_buckling",
            sigma=sigma,
            numEigs=num_eigenvalues,
        )

    def _load_bdf(self, model_path: Path, bdf_class: Any) -> Any:
        bdf_info = bdf_class(debug=False, log=None)
        bdf_info.read_bdf(str(model_path), xref=False)
        return bdf_info

    def _is_shell_model(self, bdf_info: Any) -> bool:
        shell_types = {"CTRIA3", "CTRIAR", "CQUAD4", "CQUADR"}
        if not bdf_info.elements:
            return False
        return all(getattr(element, "type", "").upper() in shell_types for element in bdf_info.elements.values())

    def _build_shell_element_callback(
        self,
        *,
        constitutive: Any,
        elements: Any,
        default_thickness: float,
        component_thickness: dict[int, float],
        allowable_stress: float,
    ) -> Any:
        def elem_callback(
            dv_num: int,
            comp_id: int,
            comp_descript: str,
            elem_descripts: list[str],
            global_dvs: dict[str, Any],
            **kwargs: Any,
        ) -> tuple[list[Any], list[float]]:
            del comp_descript, global_dvs, kwargs
            thickness = component_thickness.get(int(comp_id), default_thickness)
            material = constitutive.MaterialProperties(
                rho=1.0,
                E=70_000.0,
                nu=0.3,
                ys=allowable_stress,
            )
            shell = constitutive.IsoShellConstitutive(
                material,
                t=thickness,
                tNum=dv_num,
                tlb=max(1e-6, thickness * 0.01),
                tub=max(1.0, thickness * 100.0),
            )

            element_objects: list[Any] = []
            for descript in elem_descripts:
                normalized = descript.upper()
                if normalized in {"CQUAD4", "CQUADR"}:
                    element_objects.append(elements.Quad4Shell(None, shell))
                elif normalized in {"CTRIA3", "CTRIAR"}:
                    element_objects.append(elements.Tri3Shell(None, shell))
                else:
                    raise RuntimeError(f"Unsupported shell element type for TACS setup: {descript}")
            return element_objects, [1.0]

        return elem_callback

    def _build_solid_element_callback(
        self,
        *,
        constitutive: Any,
        elements: Any,
        allowable_stress: float,
    ) -> Any:
        def elem_callback(
            dv_num: int,
            comp_id: int,
            comp_descript: str,
            elem_descripts: list[str],
            global_dvs: dict[str, Any],
            **kwargs: Any,
        ) -> tuple[list[Any], list[float]]:
            del comp_id, comp_descript, global_dvs, kwargs
            material = constitutive.MaterialProperties(
                rho=1.0,
                E=70_000.0,
                nu=0.3,
                ys=allowable_stress,
            )
            solid = constitutive.SolidConstitutive(
                material,
                t=1.0,
                tNum=dv_num,
                tlb=1.0,
                tub=1.0,
            )
            model = elements.LinearElasticity3D(solid)

            element_objects: list[Any] = []
            for descript in elem_descripts:
                normalized = descript.upper()
                if normalized == "CHEXA":
                    basis = elements.LinearHexaBasis()
                elif normalized == "CTETRA":
                    basis = elements.LinearTetrahedralBasis()
                else:
                    raise RuntimeError(f"Unsupported solid element type for TACS setup: {descript}")
                element_objects.append(elements.Element3D(model, basis))

            return element_objects, [100.0]

        return elem_callback

    def _resolve_shell_thickness_assignments(
        self,
        request: FEARequest,
        model_input_path: Path | None,
        bdf_info: Any | None = None,
    ) -> dict[str, Any]:
        assignments = request.design_variable_assignments

        default_thickness = float(
            assignments.global_values.get("thickness", request.design_variables.get("thickness", 1.0))
        )
        region_pid_map = (
            self._parse_region_pid_map(model_input_path, bdf_info)
            if model_input_path is not None and model_input_path.exists()
            else {}
        )
        element_pid_map = self._element_pid_map(bdf_info)
        component_thickness: dict[int, float] = {}
        for region_name, value in assignments.region_values.items():
            pid = region_pid_map.get(region_name)
            if pid is None:
                available = ", ".join(sorted(region_pid_map)) or "none"
                raise RuntimeError(
                    f"Region-thickness assignment requested unknown BDF region '{region_name}'. "
                    f"Available regions: {available}."
                )
            component_thickness[int(pid)] = float(value)

        for element_id, value in assignments.element_values.items():
            pid = element_pid_map.get(int(element_id))
            if pid is None:
                raise RuntimeError(
                    f"Element-thickness assignment requested unknown element id '{element_id}'."
                )
            current = component_thickness.get(pid)
            requested = float(value)
            if current is not None and abs(current - requested) > 1e-12:
                raise RuntimeError(
                    f"Element-thickness assignments for PID {pid} are inconsistent. "
                    "This BDF is component-grouped; use consistent element values per PID "
                    "or prefer region/PID thickness design variables."
                )
            component_thickness[pid] = requested

        return {
            "default_thickness": default_thickness,
            "component_thickness": component_thickness,
        }

    def _parse_region_pid_map(self, path: Path, bdf_info: Any | None = None) -> dict[str, int]:
        pattern = re.compile(r"^\$\s+REGION\s+pid=(?P<pid>\d+).*\sname=(?P<name>\S+)\s*$")
        mapping: dict[str, int] = {}
        for line in path.read_text().splitlines():
            match = pattern.match(line.strip())
            if match is None:
                continue
            mapping[match.group("name")] = int(match.group("pid"))
        if mapping:
            return mapping
        if bdf_info is None:
            return mapping
        for element in bdf_info.elements.values():
            pid = getattr(element, "pid", None)
            if pid is None:
                continue
            mapping[f"pid_{int(pid)}"] = int(pid)
        return mapping

    def _element_pid_map(self, bdf_info: Any | None) -> dict[int, int]:
        if bdf_info is None:
            return {}
        mapping: dict[int, int] = {}
        for element_id, element in bdf_info.elements.items():
            pid = getattr(element, "pid", None)
            if pid is None:
                continue
            mapping[int(element_id)] = int(pid)
        return mapping

    def _has_explicit_spcs(self, bdf_info: Any) -> bool:
        spcs = getattr(bdf_info, "spcs", {})
        spcadds = getattr(bdf_info, "spcadds", {})
        return bool(spcs) or bool(spcadds)

    def _resolve_shell_node_sets(
        self,
        *,
        request: FEARequest,
        node_positions: dict[int, tuple[float, float, float]],
        shell_elements: list[tuple[str, tuple[int, ...]]],
    ) -> dict[str, list[int]]:
        shell_setup = request.shell_setup
        if shell_setup is None or not shell_setup.node_sets:
            return {}

        described_loops = None
        resolved: dict[str, list[int]] = {}
        for name, selector in shell_setup.node_sets.items():
            if selector.selector == "boundary_loop":
                if described_loops is None:
                    boundary_loops = find_boundary_loops(node_positions, shell_elements)
                    described_loops = describe_boundary_loops(node_positions, boundary_loops)
                resolved[name] = select_boundary_loop(
                    described_loops,
                    family=selector.family or "",
                    order_by=selector.order_by or "",
                    index=selector.index or 0,
                )
                continue

            if selector.selector == "closest_node_to_centroid":
                resolved[name] = [self._closest_node_to_centroid(node_positions)]
                continue

            if selector.selector == "bounding_box_extreme":
                resolved[name] = self._resolve_bounding_box_extreme_nodes(
                    node_positions=node_positions,
                    axis=selector.axis or "x",
                    extreme=selector.extreme or "min",
                    tolerance=selector.tolerance,
                )
                continue

            raise RuntimeError(f"Unsupported shell node-set selector '{selector.selector}'.")

        return resolved

    def _resolve_solid_node_sets(
        self,
        *,
        request: FEARequest,
        node_positions: dict[int, tuple[float, float, float]],
    ) -> dict[str, list[int]]:
        solid_setup = request.solid_setup
        if solid_setup is None or not solid_setup.node_sets:
            return {}

        resolved: dict[str, list[int]] = {}
        for name, selector in solid_setup.node_sets.items():
            resolved[name] = self._resolve_bounding_box_extreme_nodes(
                node_positions=node_positions,
                axis=selector.axis,
                extreme=selector.extreme,
                tolerance=selector.tolerance,
            )
        return resolved

    def _resolve_bounding_box_extreme_nodes(
        self,
        *,
        node_positions: dict[int, tuple[float, float, float]],
        axis: str,
        extreme: str,
        tolerance: float,
    ) -> list[int]:
        if not node_positions:
            raise RuntimeError("No nodes are available for bounding-box selector resolution.")
        axis_index = {"x": 0, "y": 1, "z": 2}[axis]
        coordinate_values = [position[axis_index] for position in node_positions.values()]
        target_value = min(coordinate_values) if extreme == "min" else max(coordinate_values)
        resolved = [
            node_id
            for node_id, position in sorted(node_positions.items())
            if abs(position[axis_index] - target_value) <= tolerance
        ]
        if not resolved:
            raise RuntimeError(
                f"No nodes matched the bounding-box selector axis={axis} extreme={extreme}."
            )
        return resolved

    def _apply_shell_boundary_conditions(
        self,
        *,
        request: FEARequest,
        bdf_info: Any,
        resolved_node_sets: dict[str, list[int]],
    ) -> tuple[list[int], str]:
        shell_setup = request.shell_setup
        if shell_setup is not None and shell_setup.boundary_conditions:
            constrained: set[int] = set()
            for boundary_condition in shell_setup.boundary_conditions:
                node_ids = resolved_node_sets[boundary_condition.node_set]
                bdf_info.add_spc1(1, boundary_condition.dof, node_ids)
                constrained.update(node_ids)
            return sorted(constrained), "configured_shell_setup"

        if self._has_explicit_spcs(bdf_info):
            return [], "existing_spc"

        raise RuntimeError(
            "Shell models require boundary conditions from "
            "fea.shell_setup.boundary_conditions or SPC cards in the BDF."
        )

    def _apply_shell_loads(
        self,
        *,
        request: FEARequest,
        requested_loads: dict[str, float],
        problem: Any,
        resolved_node_sets: dict[str, list[int]],
    ) -> tuple[list[int], str]:
        requested_loads = {
            name: float(value) for name, value in requested_loads.items() if abs(float(value)) > 1e-12
        }
        if not requested_loads:
            return [], "none"

        shell_setup = request.shell_setup
        configured_loads = shell_setup.loads if shell_setup is not None else []
        if not configured_loads:
            requested_keys = ", ".join(sorted(requested_loads))
            raise RuntimeError(
                "Shell scripted loads were requested but fea.shell_setup.loads is not configured. "
                f"Requested load keys: {requested_keys}."
            )

        configured_keys = {load.load_key for load in configured_loads}
        missing_keys = sorted(set(requested_loads) - configured_keys)
        if missing_keys:
            missing = ", ".join(missing_keys)
            raise RuntimeError(
                "Shell scripted loads are missing explicit node-set configuration for: "
                f"{missing}."
            )

        loaded_nodes: set[int] = set()
        for load in configured_loads:
            magnitude = requested_loads.get(load.load_key)
            if magnitude is None:
                continue
            node_ids = resolved_node_sets[load.node_set]
            if load.distribution != "equal":
                raise RuntimeError(
                    f"Unsupported shell load distribution '{load.distribution}'."
                )
            load_vectors = distribute_force_to_nodes(node_ids, magnitude, tuple(load.direction))
            problem.addLoadToNodes(node_ids, load_vectors, nastranOrdering=True)
            loaded_nodes.update(node_ids)

        return sorted(loaded_nodes), "configured_shell_setup"

    def _apply_solid_boundary_conditions(
        self,
        *,
        request: FEARequest,
        bdf_info: Any,
        resolved_node_sets: dict[str, list[int]],
    ) -> tuple[list[int], str]:
        solid_setup = request.solid_setup
        if solid_setup is not None and solid_setup.boundary_conditions:
            constrained: set[int] = set()
            for boundary_condition in solid_setup.boundary_conditions:
                node_ids = resolved_node_sets[boundary_condition.node_set]
                bdf_info.add_spc1(1, boundary_condition.dof, node_ids)
                constrained.update(node_ids)
            return sorted(constrained), "configured_solid_setup"

        if self._has_explicit_spcs(bdf_info):
            return [], "existing_spc"

        raise RuntimeError(
            "Solid models require boundary conditions from "
            "fea.solid_setup.boundary_conditions or SPC cards in the BDF."
        )

    def _apply_solid_loads(
        self,
        *,
        request: FEARequest,
        requested_loads: dict[str, float],
        problem: Any,
        resolved_node_sets: dict[str, list[int]],
    ) -> tuple[list[int], str]:
        requested_loads = {
            name: float(value) for name, value in requested_loads.items() if abs(float(value)) > 1e-12
        }
        if not requested_loads:
            return [], "none"

        solid_setup = request.solid_setup
        configured_loads = solid_setup.loads if solid_setup is not None else []
        if not configured_loads:
            requested_keys = ", ".join(sorted(requested_loads))
            raise RuntimeError(
                "Solid scripted loads were requested but fea.solid_setup.loads is not configured. "
                f"Requested load keys: {requested_keys}."
            )

        configured_keys = {load.load_key for load in configured_loads}
        missing_keys = sorted(set(requested_loads) - configured_keys)
        if missing_keys:
            missing = ", ".join(missing_keys)
            raise RuntimeError(
                "Solid scripted loads are missing explicit node-set configuration for: "
                f"{missing}."
            )

        loaded_nodes: set[int] = set()
        for load in configured_loads:
            magnitude = requested_loads.get(load.load_key)
            if magnitude is None:
                continue
            node_ids = resolved_node_sets[load.node_set]
            if load.distribution != "equal":
                raise RuntimeError(
                    f"Unsupported solid load distribution '{load.distribution}'."
                )
            load_vectors = self._distribute_solid_force_to_nodes(
                node_ids,
                magnitude,
                tuple(load.direction),
            )
            problem.addLoadToNodes(node_ids, load_vectors, nastranOrdering=True)
            loaded_nodes.update(node_ids)

        return sorted(loaded_nodes), "configured_solid_setup"

    def _distribute_solid_force_to_nodes(
        self,
        node_ids: list[int],
        magnitude: float,
        direction: tuple[float, float, float],
    ) -> list[list[float]]:
        if not node_ids:
            raise RuntimeError("No solid nodes were selected for load application.")
        component_scale = float(magnitude) / float(len(node_ids))
        return [
            [
                component_scale * float(direction[0]),
                component_scale * float(direction[1]),
                component_scale * float(direction[2]),
            ]
            for _ in node_ids
        ]

    def _closest_node_to_centroid(self, node_positions: dict[int, tuple[float, float, float]]) -> int:
        if not node_positions:
            raise RuntimeError("No shell nodes available for load application.")
        cx = sum(position[0] for position in node_positions.values()) / len(node_positions)
        cy = sum(position[1] for position in node_positions.values()) / len(node_positions)
        cz = sum(position[2] for position in node_positions.values()) / len(node_positions)
        return min(
            node_positions,
            key=lambda node_id: (
                (node_positions[node_id][0] - cx) ** 2
                + (node_positions[node_id][1] - cy) ** 2
                + (node_positions[node_id][2] - cz) ** 2
            ),
        )

    def _extract_node_positions(self, bdf_info: Any) -> dict[int, tuple[float, float, float]]:
        positions: dict[int, tuple[float, float, float]] = {}
        for node_id, node in bdf_info.nodes.items():
            xyz = getattr(node, "xyz", None)
            if xyz is None:
                xyz = node.get_position()
            positions[int(node_id)] = (float(xyz[0]), float(xyz[1]), float(xyz[2]))
        return positions

    def _extract_shell_elements(self, bdf_info: Any) -> list[tuple[str, tuple[int, ...]]]:
        elements: list[tuple[str, tuple[int, ...]]] = []
        for element in bdf_info.elements.values():
            node_ids = tuple(int(node_id) for node_id in element.nodes if node_id is not None)
            elements.append((str(element.type).upper(), node_ids))
        return elements

    def _select_problem(
        self,
        problems: Any,
        requested_case_name: str,
        *,
        strict: bool = False,
    ) -> tuple[str, Any]:
        if isinstance(problems, dict):
            if requested_case_name in problems:
                return requested_case_name, problems[requested_case_name]
            if strict:
                available = ", ".join(str(name) for name in problems)
                raise RuntimeError(
                    f"Requested BDF load case '{requested_case_name}' was not found. "
                    f"Available cases: {available}."
                )
            selected_name = next(iter(problems))
            return str(selected_name), problems[selected_name]
        if isinstance(problems, list) and problems:
            if strict:
                raise RuntimeError(
                    "Requested named BDF load cases, but pyTACS returned an unnamed problem list."
                )
            return requested_case_name, problems[0]
        raise RuntimeError("Unsupported TACS problem collection returned from pyTACS.")

    def _requested_case_loads(self, request: FEARequest) -> dict[str, dict[str, float]]:
        if request.load_cases:
            return {
                case_name: dict(case.loads)
                for case_name, case in request.load_cases.items()
            }
        return {
            request.case_name: dict(request.loads),
        }

    def _requires_strict_case_selection(self, request: FEARequest) -> bool:
        if len(request.load_cases) != 1:
            return bool(request.load_cases)
        if not request.load_cases:
            return False
        only_case_name = next(iter(request.load_cases))
        only_case_loads = request.load_cases[only_case_name].loads
        return not (only_case_name == request.case_name and dict(only_case_loads) == dict(request.loads))

    def _write_aggregation_quality_summary(
        self,
        *,
        request: FEARequest,
        report_directory: Path,
        case_analyses: dict[str, dict[str, Any]],
    ) -> Path | None:
        if request.constraints.aggregated_stress is None:
            return None

        surrogate_result = aggregate_case_stresses(
            {
                case_name: case_analysis.get("max_stress")
                for case_name, case_analysis in case_analyses.items()
            },
            request.constraints,
            request.allowable_stress,
        )
        raw_case_stresses = {
            case_name: case_analysis.get("raw_max_stress")
            for case_name, case_analysis in case_analyses.items()
        }
        raw_global_max_stress = self._max_defined_value(raw_case_stresses)
        surrogate_controlling_case = (
            surrogate_result.controlling_case if surrogate_result is not None else None
        )
        raw_controlling_case = (
            max(
                (
                    case_name
                    for case_name, raw_max_stress in raw_case_stresses.items()
                    if raw_max_stress is not None
                ),
                key=lambda case_name: float(raw_case_stresses[case_name]),
            )
            if raw_global_max_stress is not None
            else None
        )
        absolute_gap = (
            abs(float(surrogate_result.value) - raw_global_max_stress)
            if surrogate_result is not None
            and surrogate_result.value is not None
            and raw_global_max_stress is not None
            else None
        )
        relative_gap = (
            absolute_gap / raw_global_max_stress
            if absolute_gap is not None and raw_global_max_stress not in (None, 0.0)
            else None
        )

        summary_path = report_directory / "stress_aggregation_summary.json"
        summary = {
            "method": (
                surrogate_result.method if surrogate_result is not None else None
            ),
            "source": (
                surrogate_result.source if surrogate_result is not None else None
            ),
            "allowable": (
                surrogate_result.allowable if surrogate_result is not None else None
            ),
            "aggregated_stress_value": (
                surrogate_result.value if surrogate_result is not None else None
            ),
            "raw_global_max_stress": raw_global_max_stress,
            "absolute_gap_to_raw_max": absolute_gap,
            "relative_gap_to_raw_max": relative_gap,
            "controlling_case_by_surrogate": surrogate_controlling_case,
            "controlling_case_by_raw_max": raw_controlling_case,
            "load_cases": {
                case_name: {
                    "aggregated_input_stress": case_analysis.get("max_stress"),
                    "raw_max_stress": case_analysis.get("raw_max_stress"),
                    "raw_max_stress_source": case_analysis.get("raw_max_stress_source"),
                }
                for case_name, case_analysis in case_analyses.items()
            },
        }
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        return summary_path

    def _extract_raw_max_stress(
        self,
        problem: Any,
        *,
        fallback_stress: float | None = None,
    ) -> tuple[float | None, str | None]:
        candidate_targets = (
            ("problem", problem),
            ("assembler", getattr(problem, "assembler", None)),
        )
        scalar_methods = (
            "getRawMaxStress",
            "getMaximumVonMisesStress",
            "getMaxVonMisesStress",
            "getMaxStress",
        )
        array_methods = (
            "getElementVonMisesStresses",
            "getElementStresses",
        )
        array_attributes = (
            "element_stresses",
            "von_mises_stresses",
            "raw_element_stresses",
        )

        for owner, target in candidate_targets:
            if target is None:
                continue
            for method_name in scalar_methods:
                method = getattr(target, method_name, None)
                if callable(method):
                    max_stress = self._coerce_max_stress_value(method())
                    if max_stress is not None:
                        return max_stress, f"{owner}.{method_name}"
            for method_name in array_methods:
                method = getattr(target, method_name, None)
                if callable(method):
                    max_stress = self._coerce_max_stress_value(method())
                    if max_stress is not None:
                        return max_stress, f"{owner}.{method_name}"
            for attribute_name in array_attributes:
                if hasattr(target, attribute_name):
                    max_stress = self._coerce_max_stress_value(getattr(target, attribute_name))
                    if max_stress is not None:
                        return max_stress, f"{owner}.{attribute_name}"

        if fallback_stress is None:
            return None, None
        return float(fallback_stress), "ks_failure_surrogate"

    def _coerce_max_stress_value(self, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, dict):
            coerced = [
                self._coerce_max_stress_value(item)
                for item in value.values()
            ]
        elif hasattr(value, "tolist"):
            return self._coerce_max_stress_value(value.tolist())
        elif isinstance(value, (list, tuple, set)):
            coerced = [self._coerce_max_stress_value(item) for item in value]
        else:
            return None

        defined = [item for item in coerced if item is not None]
        if not defined:
            return None
        return max(defined)

    def _max_defined_value(self, values: dict[str, float | None]) -> float | None:
        defined = [float(value) for value in values.values() if value is not None]
        if not defined:
            return None
        return max(defined)

    def _extract_eigenvalues(self, function_values: dict[str, float]) -> list[float]:
        eigenpairs: list[tuple[int, float]] = []
        pattern = re.compile(r"eigs[bm]\.(\d+)$")
        for name, value in function_values.items():
            match = pattern.search(name.lower())
            if match is None:
                continue
            eigenpairs.append((int(match.group(1)), float(value)))
        return [value for _, value in sorted(eigenpairs, key=lambda item: item[0])]

    def _extract_critical_eigenvalue(self, eigenvalues: list[float]) -> float | None:
        for value in eigenvalues:
            return float(value)
        return None

    def _select_case_name_by_metric(
        self,
        case_analyses: dict[str, dict[str, Any]],
        ordered_case_names: list[str],
        *,
        metric: str,
        reverse: bool,
    ) -> str:
        candidate_names = ordered_case_names or list(case_analyses)
        best_name = candidate_names[0]
        best_value = case_analyses[best_name].get(metric)
        for case_name in candidate_names:
            metric_value = case_analyses[case_name].get(metric)
            if metric_value is None:
                continue
            if best_value is None:
                best_name = case_name
                best_value = metric_value
                continue
            if reverse and metric_value > best_value:
                best_name = case_name
                best_value = metric_value
            if not reverse and metric_value < best_value:
                best_name = case_name
                best_value = metric_value
        return best_name

    def _select_worst_case_name(
        self,
        case_analyses: dict[str, dict[str, Any]],
        ordered_case_names: list[str],
    ) -> str:
        return self._select_case_name_by_metric(
            case_analyses,
            ordered_case_names,
            metric="max_stress",
            reverse=True,
        )

    def _add_functions(self, problem: Any, functions: Any) -> None:
        if hasattr(problem, "addFunction"):
            problem.addFunction("mass", functions.StructuralMass)
            problem.addFunction("ks_vmfailure", functions.KSFailure, ksWeight=100.0)

    def _extract_failure_index(self, function_values: dict[str, float]) -> float | None:
        for name, value in function_values.items():
            lowered = name.lower()
            if "failure" in lowered:
                return float(value)
        return None

    def _extract_mass(self, function_values: dict[str, float]) -> float | None:
        for name, value in function_values.items():
            if "mass" in name.lower():
                return float(value)
        return None

    def _extract_displacement_norm(self, problem: Any) -> float | None:
        if not hasattr(problem, "getVariables"):
            return None

        variables = problem.getVariables()
        if hasattr(variables, "getArray"):
            data = variables.getArray()
            total = 0.0
            for value in data:
                total += float(value) ** 2
            return total ** 0.5
        return None
