import importlib
import json
from pathlib import Path
from typing import Any

from mass_town.disciplines.fea import FEABackend, FEARequest, FEAResult
from mass_town.storage.filesystem import ensure_directory


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

        output_directory = ensure_directory(request.output_directory)
        summary_path = output_directory / f"{model_path.stem}.tacs.summary.json"
        log_path = output_directory / f"{model_path.stem}.tacs.log"

        pyTACS, functions = self._load_tacs_modules()

        try:
            assembler = pyTACS(str(model_path), options={"outputDir": str(output_directory)})
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
            max_stress = self._extract_max_stress(function_values)
            displacement_norm = self._extract_displacement_norm(problem)
        except Exception as exc:
            log_path.write_text(f"TACS analysis failed: {exc}\n")
            raise RuntimeError(f"TACS analysis failed. See log: {log_path}") from exc

        summary = {
            "backend": self.name,
            "case_name": selected_name,
            "input_model": str(model_path),
            "load_source": "bdf",
            "loads": request.loads,
            "max_stress": max_stress,
            "displacement_norm": displacement_norm,
            "functions": function_values,
        }
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        log_path.write_text("TACS analysis completed successfully.\n")

        metadata: dict[str, str | float | int | bool] = {
            "input_model": str(model_path),
            "case_name": selected_name,
            "load_source": "bdf",
            "function_names": ",".join(sorted(function_values)),
        }
        backend_version = self._backend_version()
        if backend_version is not None:
            metadata["backend_version"] = backend_version
        if request.mesh_input_path is not None:
            metadata["mesh_input_path"] = str(request.mesh_input_path)

        passed = max_stress is None or max_stress <= request.allowable_stress

        return FEAResult(
            backend_name=self.name,
            passed=passed,
            max_stress=max_stress,
            displacement_norm=displacement_norm,
            result_files=[summary_path],
            metadata=metadata,
            log_path=log_path,
        )

    def _load_tacs_modules(self) -> tuple[Any, Any]:
        pytacs_module = importlib.import_module("tacs.pytacs")
        functions_module = importlib.import_module("tacs.functions")
        return pytacs_module.pyTACS, functions_module

    def _backend_version(self) -> str | None:
        try:
            module = importlib.import_module("tacs")
        except ImportError:
            return None
        return getattr(module, "__version__", None)

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
            problem.addFunction("ks_vmfailure", functions.KSFailure)

    def _extract_max_stress(self, function_values: dict[str, float]) -> float | None:
        for name, value in function_values.items():
            lowered = name.lower()
            if "failure" in lowered or "stress" in lowered:
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
