from mass_town.constraints import (
    aggregate_case_stresses,
    evaluate_minimum_buckling_load_factor_constraint,
    evaluate_minimum_natural_frequency_constraint,
)
from mass_town.disciplines.fea.models import FEALoadCaseResult

from .base import PostProcessingBackend
from .models import PostProcessingRequest, PostProcessingResult


class StructuralPostProcessingBackend(PostProcessingBackend):
    name = "local_structural_postprocessing"

    def is_available(self) -> bool:
        return True

    def availability_reason(self) -> str | None:
        return None

    def process(self, request: PostProcessingRequest) -> PostProcessingResult:
        fea_request = request.fea_request
        fea_result = request.fea_result
        normalized_case_results = self._normalized_case_results(fea_result, fea_request)
        ordered_case_names = list(fea_request.load_cases)
        minimum_buckling_load_factor = evaluate_minimum_buckling_load_factor_constraint(
            {
                case_name: tuple(case_result.eigenvalues)
                for case_name, case_result in normalized_case_results.items()
            },
            fea_request.constraints.minimum_buckling_load_factor,
        )
        minimum_natural_frequency = evaluate_minimum_natural_frequency_constraint(
            {
                case_name: tuple(case_result.eigenvalues)
                for case_name, case_result in normalized_case_results.items()
            },
            fea_request.constraints.minimum_natural_frequency_hz,
        )
        worst_case_name = self._select_worst_case_name(
            normalized_case_results,
            ordered_case_names,
            analysis_type=fea_request.analysis_type,
            minimum_buckling_load_factor_case=(
                minimum_buckling_load_factor.controlling_case
                if minimum_buckling_load_factor is not None
                else None
            ),
            minimum_natural_frequency_case=(
                minimum_natural_frequency.controlling_case
                if minimum_natural_frequency is not None
                else None
            ),
        )
        analysis_seconds = fea_result.analysis_seconds
        if analysis_seconds is None:
            case_times = [
                case_result.analysis_seconds
                for case_result in normalized_case_results.values()
                if case_result.analysis_seconds is not None
            ]
            if case_times:
                analysis_seconds = sum(case_times)

        aggregated_stress = aggregate_case_stresses(
            {
                case_name: case_result.max_stress
                for case_name, case_result in normalized_case_results.items()
            },
            fea_request.constraints,
            fea_request.allowable_stress,
            quality_summary_path=request.aggregation_quality_summary_path,
        )

        passed = self._all_cases_passed(normalized_case_results, fea_request.allowable_stress)
        if not normalized_case_results and fea_result.max_stress is not None:
            passed = passed and fea_result.max_stress <= fea_request.allowable_stress
        if aggregated_stress is not None:
            passed = passed and aggregated_stress.passed
        if minimum_buckling_load_factor is not None:
            passed = passed and minimum_buckling_load_factor.passed
        if minimum_natural_frequency is not None:
            passed = passed and minimum_natural_frequency.passed

        return PostProcessingResult(
            backend_name=self.name,
            passed=passed,
            normalized_case_results=normalized_case_results,
            ordered_case_names=ordered_case_names,
            worst_case_name=worst_case_name,
            aggregated_stress=aggregated_stress,
            minimum_buckling_load_factor=minimum_buckling_load_factor,
            minimum_natural_frequency_hz=minimum_natural_frequency,
            analysis_seconds=analysis_seconds,
        )

    def _normalized_case_results(
        self,
        fea_result: object,
        request: object,
    ) -> dict[str, FEALoadCaseResult]:
        if fea_result.load_cases:
            return dict(fea_result.load_cases)
        fallback_case_name = next(iter(request.load_cases), request.case_name)
        return {
            fallback_case_name: FEALoadCaseResult(
                passed=fea_result.passed,
                result_files=list(fea_result.result_files),
                mass=fea_result.mass,
                max_stress=fea_result.max_stress,
                displacement_norm=fea_result.displacement_norm,
                analysis_type=fea_result.analysis_type,
                eigenvalues=list(fea_result.eigenvalues),
                critical_eigenvalue=fea_result.critical_eigenvalue,
                frequencies_hz=list(fea_result.frequencies_hz),
                critical_frequency_hz=fea_result.critical_frequency_hz,
                metadata=dict(fea_result.metadata),
                log_path=fea_result.log_path,
                analysis_seconds=fea_result.analysis_seconds,
            )
        }

    def _select_worst_case_name(
        self,
        case_results: dict[str, FEALoadCaseResult],
        ordered_case_names: list[str],
        *,
        analysis_type: str,
        minimum_buckling_load_factor_case: str | None = None,
        minimum_natural_frequency_case: str | None = None,
    ) -> str | None:
        candidate_names = [name for name in ordered_case_names if name in case_results]
        if not candidate_names:
            candidate_names = list(case_results)
        if not candidate_names:
            return None

        if minimum_buckling_load_factor_case in candidate_names:
            return minimum_buckling_load_factor_case
        if minimum_natural_frequency_case in candidate_names:
            return minimum_natural_frequency_case

        best_name: str | None = None
        if analysis_type in {"buckling", "modal"}:
            best_eigenvalue: float | None = None
            for case_name in candidate_names:
                critical_eigenvalue = case_results[case_name].critical_eigenvalue
                if critical_eigenvalue is None:
                    if best_name is None:
                        best_name = case_name
                    continue
                if best_eigenvalue is None or critical_eigenvalue < best_eigenvalue:
                    best_name = case_name
                    best_eigenvalue = critical_eigenvalue
            return best_name or candidate_names[0]

        best_stress: float | None = None
        for case_name in candidate_names:
            max_stress = case_results[case_name].max_stress
            if max_stress is None:
                if best_name is None:
                    best_name = case_name
                continue
            if best_stress is None or max_stress > best_stress:
                best_name = case_name
                best_stress = max_stress
        return best_name or candidate_names[0]

    def _all_cases_passed(
        self,
        case_results: dict[str, FEALoadCaseResult],
        allowable_stress: float,
    ) -> bool:
        if not case_results:
            return True
        return all(
            self._case_passed(case_result, allowable_stress)
            for case_result in case_results.values()
        )

    def _case_passed(
        self,
        case_result: FEALoadCaseResult,
        allowable_stress: float,
    ) -> bool:
        if not case_result.passed:
            return False
        if case_result.max_stress is not None and case_result.max_stress > allowable_stress:
            return False
        return True
