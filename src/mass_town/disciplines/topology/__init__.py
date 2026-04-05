"""Topology discipline interfaces and backend registry."""

from .base import TopologyBackend
from .models import (
    TopologyBoundaryConfig,
    TopologyConfig,
    TopologyDomainConfig,
    TopologyFilterConfig,
    TopologyLoadConfig,
    TopologyMaterialConfig,
    TopologyOptimizerConfig,
    TopologyProjectionConfig,
    TopologyRequest,
    TopologyResult,
    TopologyTimingResult,
)
from .registry import TopologyBackendError, resolve_topology_backend

__all__ = [
    "TopologyBackend",
    "TopologyBackendError",
    "TopologyBoundaryConfig",
    "TopologyConfig",
    "TopologyDomainConfig",
    "TopologyFilterConfig",
    "TopologyLoadConfig",
    "TopologyMaterialConfig",
    "TopologyOptimizerConfig",
    "TopologyProjectionConfig",
    "TopologyRequest",
    "TopologyResult",
    "TopologyTimingResult",
    "resolve_topology_backend",
]
