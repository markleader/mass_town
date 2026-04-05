from abc import ABC, abstractmethod

from .models import TopologyRequest, TopologyResult


class TopologyBackend(ABC):
    name: str

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def availability_reason(self) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def run_optimization(self, request: TopologyRequest) -> TopologyResult:
        raise NotImplementedError
