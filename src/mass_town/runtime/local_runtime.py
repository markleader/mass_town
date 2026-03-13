from pathlib import Path

from mass_town.config import WorkflowConfig
from mass_town.models.design_state import DesignState
from mass_town.orchestration.workflow_engine import WorkflowEngine
from mass_town.runtime.runtime_interface import RuntimeInterface


class LocalRuntime(RuntimeInterface):
    def __init__(self, config: WorkflowConfig) -> None:
        self.engine = WorkflowEngine(config=config)

    def run(self, state_path: Path, run_root: Path) -> DesignState:
        return self.engine.run(state_path=state_path, run_root=run_root)
