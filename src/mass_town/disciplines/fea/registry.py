from collections.abc import Callable
from importlib import import_module

from .base import FEABackend


class FEABackendError(RuntimeError):
    """Raised when no suitable FEA backend can be resolved."""


BackendLoader = Callable[..., FEABackend]


def _load_tacs(*_: object) -> FEABackend:
    module = import_module("plugins.tacs.backend")
    return module.TacsFEABackend()


def _load_mock(*_: object) -> FEABackend:
    module = import_module("plugins.mock.backend")
    return module.MockFEABackend()


BACKEND_LOADERS: dict[str, BackendLoader] = {
    "mock": _load_mock,
    "tacs": _load_tacs,
}

AUTO_BACKEND_ORDER = ("tacs",)


def resolve_fea_backend(tool_name: str) -> FEABackend:
    requested_tool = tool_name.lower()
    if requested_tool == "auto":
        for candidate in AUTO_BACKEND_ORDER:
            backend = BACKEND_LOADERS[candidate]()
            if backend.is_available():
                return backend
        raise FEABackendError("No FEA backend is available.")

    try:
        backend = BACKEND_LOADERS[requested_tool]()
    except KeyError as exc:
        available = ", ".join(sorted(BACKEND_LOADERS))
        raise FEABackendError(
            f"Unknown FEA backend '{tool_name}'. Available backends: {available}."
        ) from exc

    if not backend.is_available():
        reason = backend.availability_reason() or "backend is unavailable"
        raise FEABackendError(f"FEA backend '{requested_tool}' is unavailable: {reason}.")
    return backend
