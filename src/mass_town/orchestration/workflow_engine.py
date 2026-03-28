import json
import logging
from pathlib import Path

from mass_town.agents.fea_agent import FEAAgent
from mass_town.agents.geometry_agent import GeometryAgent
from mass_town.agents.mesh_agent import MeshAgent
from mass_town.agents.optimizer_agent import OptimizerAgent
from mass_town.config import WorkflowConfig
from mass_town.models.artifacts import ArtifactRecord
from mass_town.models.design_state import DesignState, TaskRecord
from mass_town.models.result import AgentResult
from mass_town.orchestration.chief_engineer import ChiefEngineer
from mass_town.orchestration.state_manager import StateManager
from mass_town.orchestration.task_queue import TaskQueue
from mass_town.orchestration.triage_engine import TriageEngine
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
        self.agents = {
            "geometry": GeometryAgent(),
            "mesh": MeshAgent(),
            "fea": FEAAgent(),
            "optimizer": OptimizerAgent(),
        }

    def run(self, state_path: Path, run_root: Path) -> DesignState:
        state = self.state_manager.load(state_path)
        layout = ensure_run_layout(run_root, state.run_id)
        queue = TaskQueue(self.config.initial_tasks.copy())
        state.status = "running"
        self.run_registry.start_run(state.run_id, run_root)
        self._append_workflow_log(layout.root / "logs" / "workflow.log", f"run_started run_id={state.run_id}")
        while not queue.is_empty():
            if state.iteration >= self.config.max_iterations:
                state.status = "failed"
                break

            task_name = queue.pop_next()
            if task_name is None:
                break
            state.iteration += 1
            logger.info("Running task %s", task_name)
            self._append_workflow_log(
                layout.root / "logs" / "workflow.log",
                f"iteration={state.iteration} task={task_name} event=start",
            )
            result = self.agents[task_name].run(state, self.config, run_root)
            self._record_result(state, result)
            self.artifact_store.record(run_root, state, result.artifacts)
            if result.status == "failure" and result.diagnostics:
                self.chief_engineer.triage(state, result.diagnostics[0], queue)
            self._append_workflow_log(
                layout.root / "logs" / "workflow.log",
                f"iteration={state.iteration} task={task_name} status={result.status}",
            )

            self.state_manager.save(state, state_path)

        if state.status != "failed":
            state.status = "recovered" if state.analysis_state.passed else "failed"
        summary_path = self._write_run_summary(state, run_root)
        self._record_run_summary_artifact(state, summary_path, run_root)
        self.artifact_store.record(run_root, state, [state.artifacts[-1]])
        self.state_manager.save(state, state_path)
        self._append_workflow_log(
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

    def _append_workflow_log(self, path: Path, line: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _write_run_summary(self, state: DesignState, run_root: Path) -> Path:
        layout = ensure_run_layout(run_root, state.run_id)
        summary_path = layout.reports_dir / "run_summary.json"
        latest_mesh_path = state.mesh_state.mesh_path
        analysis_log_path = self._latest_artifact_metadata_value(state, "fea-summary", "log_path")
        mesh_log_path = self._latest_artifact_metadata_value(state, "mesh-output", "log_path")
        summary = {
            "run_id": state.run_id,
            "problem_name": state.problem_name,
            "status": state.status,
            "feasible": state.status == "recovered" and state.analysis_state.passed,
            "iteration_count": state.iteration,
            "final_thickness": state.design_variables.get("thickness"),
            "mass": state.analysis_state.mass,
            "max_stress": state.analysis_state.max_stress,
            "allowable_stress": self.config.allowable_stress,
            "artifact_paths": {
                "workflow_log": str((layout.logs_dir / "workflow.log").relative_to(run_root)),
                "mesh_model": latest_mesh_path,
                "mesh_log": mesh_log_path,
                "analysis_summary": state.analysis_state.result_path,
                "analysis_log": analysis_log_path,
                "solver_directory": str(layout.solver_dir.relative_to(run_root)),
            },
        }
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        return summary_path

    def _record_run_summary_artifact(self, state: DesignState, summary_path: Path, run_root: Path) -> None:
        state.artifacts = [artifact for artifact in state.artifacts if artifact.kind != "run_summary"]
        state.artifacts.append(
            ArtifactRecord(
                name="run-summary",
                path=str(summary_path.relative_to(run_root)),
                kind="run_summary",
                metadata={
                    "status": state.status,
                    "iteration_count": state.iteration,
                    "feasible": state.status == "recovered" and state.analysis_state.passed,
                },
            )
        )

    def _latest_artifact_metadata_value(
        self, state: DesignState, artifact_name: str, key: str
    ) -> str | None:
        for artifact in reversed(state.artifacts):
            if artifact.name == artifact_name:
                value = artifact.metadata.get(key)
                if value is not None:
                    return str(value)
        return None
