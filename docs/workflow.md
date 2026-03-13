# Workflow

The prototype implements a deterministic supervision loop:

1. Load persisted design state and workflow configuration.
2. Select the next pending task.
3. Execute the responsible discipline agent.
4. Record artifacts, metrics, and diagnostics.
5. If a task fails, triage the failure and apply a corrective action.
6. Continue until all tasks succeed or the run reaches a safety limit.

This is intentionally a triage loop, not a single linear pipeline.
