from abc import ABC, abstractmethod

from .models import FEARequest, FEAResult


class FEABackend(ABC):
    name: str

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def availability_reason(self) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def run_analysis(self, request: FEARequest) -> FEAResult:
        raise NotImplementedError
