from collections.abc import Callable
from importlib import import_module

from .base import TopologyBackend


class TopologyBackendError(RuntimeError):
    """Raised when no suitable topology backend can be resolved."""


BackendLoader = Callable[..., TopologyBackend]


def _load_structured_plane_stress(*_: object) -> TopologyBackend:
    module = import_module("plugins.topopt.backend")
    return module.StructuredPlaneStressTopologyBackend()


BACKEND_LOADERS: dict[str, BackendLoader] = {
    "structured_plane_stress": _load_structured_plane_stress,
}

AUTO_BACKEND_ORDER = ("structured_plane_stress",)


def resolve_topology_backend(tool_name: str) -> TopologyBackend:
    requested_tool = tool_name.lower()
    if requested_tool == "auto":
        for candidate in AUTO_BACKEND_ORDER:
            backend = BACKEND_LOADERS[candidate]()
            if backend.is_available():
                return backend
        raise TopologyBackendError("No topology backend is available.")

    try:
        backend = BACKEND_LOADERS[requested_tool]()
    except KeyError as exc:
        available = ", ".join(sorted(BACKEND_LOADERS))
        raise TopologyBackendError(
            f"Unknown topology backend '{tool_name}'. Available backends: {available}."
        ) from exc

    if not backend.is_available():
        reason = backend.availability_reason() or "backend is unavailable"
        raise TopologyBackendError(
            f"Topology backend '{requested_tool}' is unavailable: {reason}."
        )
    return backend
