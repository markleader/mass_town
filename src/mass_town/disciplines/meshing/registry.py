from collections.abc import Callable
from importlib import import_module

from .base import MeshingBackend


class MeshingBackendError(RuntimeError):
    """Raised when no suitable meshing backend can be resolved."""


BackendLoader = Callable[..., MeshingBackend]


def _load_gmsh(executable: str = "gmsh") -> MeshingBackend:
    module = import_module("plugins.gmsh.backend")
    return module.GmshMeshingBackend(executable=executable)


def _load_mock(*_: object) -> MeshingBackend:
    module = import_module("plugins.mock.backend")
    return module.MockMeshingBackend()


BACKEND_LOADERS: dict[str, BackendLoader] = {
    "gmsh": _load_gmsh,
    "mock": _load_mock,
}

AUTO_BACKEND_ORDER = ("gmsh", "mock")


def resolve_meshing_backend(tool_name: str, gmsh_executable: str = "gmsh") -> MeshingBackend:
    requested_tool = tool_name.lower()
    if requested_tool == "auto":
        for candidate in AUTO_BACKEND_ORDER:
            backend = BACKEND_LOADERS[candidate](gmsh_executable)
            if backend.is_available():
                return backend
        raise MeshingBackendError("No meshing backend is available.")

    try:
        backend = BACKEND_LOADERS[requested_tool](gmsh_executable)
    except KeyError as exc:
        available = ", ".join(sorted(BACKEND_LOADERS))
        raise MeshingBackendError(
            f"Unknown meshing backend '{tool_name}'. Available backends: {available}."
        ) from exc

    if not backend.is_available():
        reason = backend.availability_reason() or "backend is unavailable"
        raise MeshingBackendError(
            f"Meshing backend '{requested_tool}' is unavailable: {reason}."
        )
    return backend
