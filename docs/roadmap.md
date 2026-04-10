# Roadmap

Near-term next steps:

1. Replace placeholder adapters with real:
    [x] CAD,
    [x] meshing,
    [ ] and solver integrations.
    [ ] Improve test problems along the way.
2. Add richer artifact indexing for meshes, result fields, and reports.
3. Expand the failure taxonomy with confidence scoring and escalation rules.
4. Introduce run resumption across multiple process invocations.
5. Swap the deterministic triage engine for an LLM-assisted controller.
    - Keep the first LLM phase focused on outer-loop rerun decisions, not solver-loop control.
    - Automatic restarts should be bounded by explicit retry budgets and allowed action classes.
    - CAD or geometry edits stay in future work until repair boundaries are defined.
    - Use curated version-controlled knowledge files for roles and tools.
    - Store run-specific observations as artifacts or history rather than auto-updating permanent memory.
