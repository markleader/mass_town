"""Discipline-level interfaces for MassTown."""

from .cad import CADBackend, CADRequest, CADResult
from .contracts import (
    DisciplineArtifact,
    DisciplineDiagnostic,
    DisciplineTiming,
    MaterialReference,
    MeshToFEAManifest,
    NamedRegion,
    PropertyAssignment,
    SensitivityPayload,
)
from .fea import FEABackend, FEABackendError, FEARequest, FEAResult, resolve_fea_backend
from .meshing import (
    MeshingBackend,
    MeshingBackendError,
    MeshingRequest,
    MeshingResult,
    resolve_meshing_backend,
)
from .optimization import OptimizationBackend, OptimizationRequest, OptimizationResult
from .postprocessing import (
    PostProcessingBackend,
    PostProcessingRequest,
    PostProcessingResult,
    StructuralPostProcessingBackend,
)

__all__ = [
    "CADBackend",
    "CADRequest",
    "CADResult",
    "DisciplineArtifact",
    "DisciplineDiagnostic",
    "DisciplineTiming",
    "FEABackend",
    "FEABackendError",
    "FEARequest",
    "FEAResult",
    "MaterialReference",
    "MeshingBackend",
    "MeshingBackendError",
    "MeshingRequest",
    "MeshingResult",
    "MeshToFEAManifest",
    "NamedRegion",
    "OptimizationBackend",
    "OptimizationRequest",
    "OptimizationResult",
    "PostProcessingBackend",
    "PostProcessingRequest",
    "PostProcessingResult",
    "PropertyAssignment",
    "SensitivityPayload",
    "StructuralPostProcessingBackend",
    "resolve_fea_backend",
    "resolve_meshing_backend",
]
