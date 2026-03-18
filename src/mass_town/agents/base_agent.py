from abc import ABC, abstractmethod
from pathlib import Path

from mass_town.config import WorkflowConfig
from mass_town.models.design_state import DesignState
from mass_town.models.result import AgentResult


class BaseAgent(ABC):
    name: str
    task_name: str

    @abstractmethod
    def run(self, state: DesignState, config: WorkflowConfig, run_root: Path) -> AgentResult:
        raise NotImplementedError
