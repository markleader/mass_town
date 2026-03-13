from pydantic import BaseModel

from mass_town.models.result import Diagnostic


class TriageDecision(BaseModel):
    action: str
    reason: str
    requeue: list[str]


class TriageEngine:
    def classify(self, diagnostic: Diagnostic) -> TriageDecision:
        if diagnostic.code == "geometry.invalid":
            return TriageDecision(
                action="repair_geometry",
                reason="Geometry dimensions are non-physical.",
                requeue=["geometry", "mesh", "fea", "optimizer"],
            )
        if diagnostic.code == "mesh.poor_quality":
            return TriageDecision(
                action="refine_mesh",
                reason="Mesh quality is too low for reliable analysis.",
                requeue=["mesh", "fea", "optimizer"],
            )
        if diagnostic.code == "analysis.stress_exceeded":
            return TriageDecision(
                action="increase_thickness",
                reason="The current design exceeds the allowable stress limit.",
                requeue=["optimizer", "geometry", "mesh", "fea"],
            )
        return TriageDecision(
            action="escalate",
            reason="Unhandled failure type.",
            requeue=[],
        )
