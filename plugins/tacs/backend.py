import importlib
import json
from pathlib import Path
from typing import Any

from mass_town.disciplines.fea import FEABackend, FEARequest, FEAResult
from mass_town.storage.filesystem import ensure_directory

from .shell_model import classify_boundary_loops, distribute_force_to_nodes, find_boundary_loops


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
            if self._is_shell_model(bdf_info):
                analysis = self._run_shell_analysis(
                    request=request,
                    bdf_info=bdf_info,
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

        summary = {
            "backend": self.name,
            "case_name": analysis["case_name"],
            "input_model": str(model_path),
            "load_source": analysis["load_source"],
            "loads": request.loads,
            "mass": analysis["mass"],
            "failure_index": analysis["failure_index"],
            "max_stress": analysis["max_stress"],
            "displacement_norm": analysis["displacement_norm"],
            "functions": analysis["function_values"],
            "boundary_conditions": analysis.get("boundary_conditions"),
        }
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        log_path.write_text("TACS analysis completed successfully.\n")

        metadata: dict[str, str | float | int | bool] = {
            "input_model": str(model_path),
            "case_name": analysis["case_name"],
            "load_source": analysis["load_source"],
            "function_names": ",".join(sorted(analysis["function_values"])),
        }
        if analysis["failure_index"] is not None:
            metadata["failure_index"] = round(float(analysis["failure_index"]), 6)
        backend_version = self._backend_version()
        if backend_version is not None:
            metadata["backend_version"] = backend_version
        if request.mesh_input_path is not None:
            metadata["mesh_input_path"] = str(request.mesh_input_path)

        passed = analysis["failure_index"] is None or analysis["failure_index"] <= 1.0

        return FEAResult(
            backend_name=self.name,
            passed=passed,
            mass=analysis["mass"],
            max_stress=analysis["max_stress"],
            displacement_norm=analysis["displacement_norm"],
            result_files=[summary_path],
            metadata=metadata,
            log_path=log_path,
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
        pyTACS: Any,
        functions: Any,
        constitutive: Any,
        elements: Any,
        output_directory: Path,
    ) -> dict[str, Any]:
        node_positions = self._extract_node_positions(bdf_info)
        shell_elements = self._extract_shell_elements(bdf_info)
        boundary_loops = find_boundary_loops(node_positions, shell_elements)
        classified_loops = classify_boundary_loops(node_positions, boundary_loops)

        constrained_nodes = classified_loops["left_bore"]
        loaded_nodes = classified_loops["right_bore"]
        bdf_info.add_spc1(1, "123456", constrained_nodes)

        assembler = pyTACS(bdf_info)
        assembler.initialize(
            self._build_shell_element_callback(
                constitutive=constitutive,
                elements=elements,
                thickness=float(request.design_variables.get("thickness", 1.0)),
                allowable_stress=request.allowable_stress,
            )
        )

        problem = assembler.createStaticProblem(request.case_name)
        self._add_functions(problem, functions)
        load_vectors = distribute_force_to_nodes(
            loaded_nodes,
            float(request.loads.get("force", 0.0)),
        )
        problem.addLoadToNodes(loaded_nodes, load_vectors, nastranOrdering=True)
        problem.solve()

        if request.write_solution and hasattr(problem, "writeSolution"):
            problem.writeSolution(outputDir=str(output_directory))

        function_values: dict[str, float] = {}
        problem.evalFunctions(function_values)
        failure_index = self._extract_failure_index(function_values)
        max_stress = (
            float(failure_index) * request.allowable_stress if failure_index is not None else None
        )

        return {
            "case_name": request.case_name,
            "load_source": "script",
            "function_values": function_values,
            "mass": self._extract_mass(function_values),
            "failure_index": failure_index,
            "max_stress": max_stress,
            "displacement_norm": self._extract_displacement_norm(problem),
            "boundary_conditions": {
                "constrained_node_count": len(constrained_nodes),
                "loaded_node_count": len(loaded_nodes),
            },
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

        selected_name, problem = self._select_problem(problems, request.case_name)
        self._add_functions(problem, functions)
        problem.solve()

        if request.write_solution and hasattr(problem, "writeSolution"):
            problem.writeSolution(outputDir=str(output_directory))

        function_values: dict[str, float] = {}
        problem.evalFunctions(function_values)
        failure_index = self._extract_failure_index(function_values)
        max_stress = (
            float(failure_index) * request.allowable_stress if failure_index is not None else None
        )

        return {
            "case_name": selected_name,
            "load_source": "bdf",
            "function_values": function_values,
            "mass": self._extract_mass(function_values),
            "failure_index": failure_index,
            "max_stress": max_stress,
            "displacement_norm": self._extract_displacement_norm(problem),
        }

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
        thickness: float,
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

    def _select_problem(self, problems: Any, requested_case_name: str) -> tuple[str, Any]:
        if isinstance(problems, dict):
            if requested_case_name in problems:
                return requested_case_name, problems[requested_case_name]
            selected_name = next(iter(problems))
            return str(selected_name), problems[selected_name]
        if isinstance(problems, list) and problems:
            return requested_case_name, problems[0]
        raise RuntimeError("Unsupported TACS problem collection returned from pyTACS.")

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
