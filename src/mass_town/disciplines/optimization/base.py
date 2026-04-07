from abc import ABC, abstractmethod

from .models import OptimizationRequest, OptimizationResult


class OptimizationBackend(ABC):
    name: str

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def availability_reason(self) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def optimize(self, request: OptimizationRequest) -> OptimizationResult:
        raise NotImplementedError
