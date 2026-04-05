"""FEA discipline interfaces and backend registry."""

from .base import FEABackend
from .models import (
    FEABucklingSetup,
    FEALoadCase,
    FEALoadCaseResult,
    FEAModalSetup,
    FEARequest,
    FEAResult,
)
from .registry import FEABackendError, resolve_fea_backend

__all__ = [
    "FEABackend",
    "FEABackendError",
    "FEABucklingSetup",
    "FEALoadCase",
    "FEALoadCaseResult",
    "FEAModalSetup",
    "FEARequest",
    "FEAResult",
    "resolve_fea_backend",
]
