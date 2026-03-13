from abc import ABC, abstractmethod

from mass_town.config import WorkflowConfig
from mass_town.models.design_state import DesignState
from mass_town.models.result import AgentResult


class BaseAgent(ABC):
    name: str
    task_name: str

    @abstractmethod
    def run(self, state: DesignState, config: WorkflowConfig) -> AgentResult:
        raise NotImplementedError
