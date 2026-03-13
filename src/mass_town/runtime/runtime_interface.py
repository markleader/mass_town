from abc import ABC, abstractmethod
from pathlib import Path

from mass_town.models.design_state import DesignState


class RuntimeInterface(ABC):
    @abstractmethod
    def run(self, state_path: Path, run_root: Path) -> DesignState:
        raise NotImplementedError
