from abc import ABC, abstractmethod

from .models import PostProcessingRequest, PostProcessingResult


class PostProcessingBackend(ABC):
    name: str

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def availability_reason(self) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def process(self, request: PostProcessingRequest) -> PostProcessingResult:
        raise NotImplementedError
