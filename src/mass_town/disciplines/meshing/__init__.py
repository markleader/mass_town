"""Meshing discipline interfaces and backend registry."""

from .base import MeshingBackend
from .models import MeshingRequest, MeshingResult
from .registry import MeshingBackendError, resolve_meshing_backend

__all__ = [
    "MeshingBackend",
    "MeshingBackendError",
    "MeshingRequest",
    "MeshingResult",
    "resolve_meshing_backend",
]

