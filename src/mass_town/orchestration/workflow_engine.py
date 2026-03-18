import logging
from pathlib import Path

from mass_town.agents.fea_agent import FEAAgent
from mass_town.agents.geometry_agent import GeometryAgent
from mass_town.agents.mesh_agent import MeshAgent
from mass_town.agents.optimizer_agent import OptimizerAgent
from mass_town.config import WorkflowConfig
from mass_town.models.design_state import DesignState, TaskRecord
from mass_town.models.result import AgentResult
from mass_town.orchestration.chief_engineer import ChiefEngineer
from mass_town.orchestration.state_manager import StateManager
from mass_town.orchestration.task_queue import TaskQueue
from mass_town.orchestration.triage_engine import TriageEngine
from mass_town.storage.artifact_store import ArtifactStore
from mass_town.storage.run_registry import RunRegistry

logger = logging.getLogger(__name__)


class WorkflowEngine:
    def __init__(
        self,
        config: WorkflowConfig,
        state_manager: StateManager | None = None,
        artifact_store: ArtifactStore | None = None,
        run_registry: RunRegistry | None = None,
    ) -> None:
        self.config = config
        self.state_manager = state_manager or StateManager()
        self.artifact_store = artifact_store or ArtifactStore()
        self.run_registry = run_registry or RunRegistry()
        self.chief_engineer = ChiefEngineer(TriageEngine())
        self.agents = {
            "geometry": GeometryAgent(),
            "mesh": MeshAgent(),
            "fea": FEAAgent(),
            "optimizer": OptimizerAgent(),
        }

    def run(self, state_path: Path, run_root: Path) -> DesignState:
        state = self.state_manager.load(state_path)
        queue = TaskQueue(self.config.initial_tasks.copy())
        state.status = "running"
        self.run_registry.start_run(state.run_id, run_root)
        while not queue.is_empty():
            if state.iteration >= self.config.max_iterations:
                state.status = "failed"
                break

            task_name = queue.pop_next()
            if task_name is None:
                break
            state.iteration += 1
            logger.info("Running task %s", task_name)
            result = self.agents[task_name].run(state, self.config, run_root)
            self._record_result(state, result)
            self.artifact_store.record(run_root, state, result.artifacts)
            if result.status == "failure" and result.diagnostics:
                self.chief_engineer.triage(state, result.diagnostics[0], queue)

            self.state_manager.save(state, state_path)

        if state.status != "failed":
            state.status = "recovered" if state.analysis_state.passed else "failed"
            self.state_manager.save(state, state_path)
        self.run_registry.finish_run(state.run_id, run_root, state.status)
        return state

    def _record_result(self, state: DesignState, result: AgentResult) -> None:
        if "geometry_state" in result.updates:
            state.geometry_state = state.geometry_state.model_copy(
                update=result.updates["geometry_state"]
            )
        if "mesh_state" in result.updates:
            state.mesh_state = state.mesh_state.model_copy(update=result.updates["mesh_state"])
        if "analysis_state" in result.updates:
            state.analysis_state = state.analysis_state.model_copy(
                update=result.updates["analysis_state"]
            )
        if "design_variables" in result.updates:
            state.design_variables = dict(result.updates["design_variables"])

        state.artifacts.extend(result.artifacts)
        state.diagnostics.extend(result.diagnostics)
        state.task_history.append(
            TaskRecord(
                iteration=state.iteration,
                task=result.task,
                status=result.status,
                message=result.message,
            )
        )
