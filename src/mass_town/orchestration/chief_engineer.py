from mass_town.models.design_state import DecisionRecord, DesignState
from mass_town.models.result import Diagnostic
from mass_town.orchestration.task_queue import TaskQueue
from mass_town.orchestration.triage_engine import TriageEngine


class ChiefEngineer:
    def __init__(self, triage_engine: TriageEngine) -> None:
        self.triage_engine = triage_engine

    def triage(self, state: DesignState, diagnostic: Diagnostic, queue: TaskQueue) -> str:
        decision = self.triage_engine.classify(diagnostic)
        self._apply_action(state, decision.action)
        queue.replace(decision.requeue)
        state.decision_history.append(
            DecisionRecord(
                iteration=state.iteration,
                action=decision.action,
                reason=decision.reason,
            )
        )
        return decision.action

    def _apply_action(self, state: DesignState, action: str) -> None:
        if action == "repair_geometry":
            state.design_variables["thickness"] = max(
                state.design_variables.get("thickness", 0.1), 0.2
            )
            state.geometry_state.valid = True
            state.geometry_state.notes = "Adjusted thickness to a valid minimum."
        elif action == "refine_mesh":
            state.mesh_state.quality = min(1.0, state.mesh_state.quality + 0.2)
        elif action == "increase_thickness":
            state.design_variables["thickness"] = round(
                state.design_variables.get("thickness", 0.1) + 0.2, 3
            )
