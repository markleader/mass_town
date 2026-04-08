import json
import logging
from pathlib import Path

from mass_town.agents.fea_agent import FEAAgent
from mass_town.agents.geometry_agent import GeometryAgent
from mass_town.agents.mesh_agent import MeshAgent
from mass_town.agents.optimizer_agent import OptimizerAgent
from mass_town.agents.topology_agent import TopologyAgent
from mass_town.config import WorkflowConfig
from mass_town.models.artifacts import ArtifactRecord
from mass_town.models.design_state import DesignState, TaskRecord
from mass_town.models.result import AgentResult
from mass_town.orchestration.chief_engineer import ChiefEngineer
from mass_town.orchestration.run_reporter import RunReporter
from mass_town.orchestration.state_manager import StateManager
from mass_town.orchestration.task_queue import TaskQueue
from mass_town.orchestration.triage_engine import TriageEngine
from mass_town.problem_schema import ProblemSchema, ProblemSchemaResolver
from mass_town.storage.artifact_store import ArtifactStore
from mass_town.storage.filesystem import ensure_run_layout
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
        self.schema_resolver = ProblemSchemaResolver()
        self.reporter = RunReporter(config=config, schema_resolver=self.schema_resolver)
        self.agents = {
            "geometry": GeometryAgent(),
            "mesh": MeshAgent(),
            "fea": FEAAgent(),
            "optimizer": OptimizerAgent(),
            "topology": TopologyAgent(),
        }

    def run(self, state_path: Path, run_root: Path) -> DesignState:
        state = self.state_manager.load(state_path)
        problem_schema = self.schema_resolver.resolve(self.config, state, run_root)
        layout = ensure_run_layout(run_root, state.run_id)
        queue = TaskQueue(self.config.initial_tasks.copy())
        state.status = "running"
        self.run_registry.start_run(state.run_id, run_root)
        self.reporter.write_problem_schema(problem_schema, run_root, state)
        self.reporter.append_workflow_log(
            layout.root / "logs" / "workflow.log",
            f"run_started run_id={state.run_id}",
        )
        while not queue.is_empty():
            if state.iteration >= self.config.max_iterations:
                state.status = "failed"
                break

            task_name = queue.pop_next()
            if task_name is None:
                break
            state.iteration += 1
            logger.info("Running task %s", task_name)
            self.reporter.append_workflow_log(
                layout.root / "logs" / "workflow.log",
                f"iteration={state.iteration} task={task_name} event=start",
            )
            result = self.agents[task_name].run(state, self.config, run_root)
            self._record_result(state, result)
            self.artifact_store.record(run_root, state, result.artifacts)
            if result.status == "failure" and result.diagnostics:
                self.chief_engineer.triage(state, result.diagnostics[0], queue)
            self.reporter.append_workflow_log(
                layout.root / "logs" / "workflow.log",
                f"iteration={state.iteration} task={task_name} status={result.status}",
            )

            self.state_manager.save(state, state_path)

        if state.status != "failed":
            if self.config.topology is not None:
                state.status = "recovered" if state.topology_state.converged else "failed"
            else:
                state.status = "recovered" if state.analysis_state.passed else "failed"
        summary_path = self.reporter.write_run_summary(state, run_root, problem_schema)
        self.reporter.record_run_summary_artifact(state, summary_path, run_root)
        self.artifact_store.record(run_root, state, [state.artifacts[-1]])
        self.state_manager.save(state, state_path)
        self.reporter.append_workflow_log(
            layout.root / "logs" / "workflow.log",
            f"run_finished status={state.status} iteration_count={state.iteration}",
        )
        self.run_registry.finish_run(
            state.run_id,
            run_root,
            state.status,
            iteration_count=state.iteration,
            summary_path=str(summary_path.relative_to(run_root)),
        )
        return state

    def _record_result(self, state: DesignState, result: AgentResult) -> None:
        if "geometry_state" in result.updates:
            state.geometry_state = state.geometry_state.model_copy(
                update=result.updates["geometry_state"]
            )
        if "mesh_state" in result.updates:
            state.mesh_state = state.mesh_state.model_copy(update=result.updates["mesh_state"])
        if "analysis_state" in result.updates:
            merged_analysis_state = state.analysis_state.model_dump(mode="python")
            merged_analysis_state.update(result.updates["analysis_state"])
            state.analysis_state = state.analysis_state.__class__.model_validate(
                merged_analysis_state
            )
        if "topology_state" in result.updates:
            merged_topology_state = state.topology_state.model_dump(mode="python")
            merged_topology_state.update(result.updates["topology_state"])
            state.topology_state = state.topology_state.__class__.model_validate(
                merged_topology_state
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
