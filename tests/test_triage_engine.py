from mass_town.models.result import Diagnostic
from mass_town.orchestration.triage_engine import TriageEngine


def test_triage_engine_returns_expected_action() -> None:
    diagnostic = Diagnostic(
        code="analysis.stress_exceeded",
        message="stress too high",
        task="fea",
        details={"max_stress": 220.0},
    )

    decision = TriageEngine().classify(diagnostic)

    assert decision.action == "increase_thickness"
    assert "optimizer" in decision.requeue
