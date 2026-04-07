from pydantic import BaseModel, Field

from mass_town.constraints import AggregatedStressResult, EigenvalueConstraintResult
from mass_town.disciplines.contracts import (
    DisciplineDiagnostic,
    DisciplineTiming,
    MetadataValue,
    SensitivityPayload,
)
from mass_town.disciplines.fea.models import FEALoadCaseResult, FEARequest, FEAResult


class PostProcessingRequest(BaseModel):
    fea_request: FEARequest
    fea_result: FEAResult
    aggregation_quality_summary_path: str | None = None
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class PostProcessingResult(BaseModel):
    backend_name: str
    passed: bool
    normalized_case_results: dict[str, FEALoadCaseResult] = Field(default_factory=dict)
    ordered_case_names: list[str] = Field(default_factory=list)
    worst_case_name: str | None = None
    aggregated_stress: AggregatedStressResult | None = None
    minimum_buckling_load_factor: EigenvalueConstraintResult | None = None
    minimum_natural_frequency_hz: EigenvalueConstraintResult | None = None
    analysis_seconds: float | None = None
    timing: DisciplineTiming = Field(default_factory=DisciplineTiming)
    diagnostics: list[DisciplineDiagnostic] = Field(default_factory=list)
    sensitivities: list[SensitivityPayload] = Field(default_factory=list)
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
