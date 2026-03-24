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
    - Agent controllers should store memory files to improve their performance over time.
    - Memory files could include actions likely to cause failures, high success-rate corrective actions
