# LLM Outer-Loop Mock Problem

This Phase 7A example demonstrates the local-first outer-loop controller in the
`default` environment using deterministic mock engineering backends and the
checked-in mock LLM backend.

- Inputs live directly in the example directory:
  - [`config.yaml`](/Users/markleader/git/mass_town/examples/llm_outer_loop_mock_problem/config.yaml)
  - [`design_state.yaml`](/Users/markleader/git/mass_town/examples/llm_outer_loop_mock_problem/design_state.yaml)
  - [`inputs/model/mock_panel.bdf`](/Users/markleader/git/mass_town/examples/llm_outer_loop_mock_problem/inputs/model/mock_panel.bdf)

- The first attempt is intentionally capped with `max_iterations: 3`, so the
  deterministic run stops before the workflow completes.
- The outer-loop controller reads the structured attempt summary, proposes a
  bounded `max_iterations` override, and launches a second deterministic attempt.

Outputs are written under `results/llm-outer-loop/`:

- `outer_loop/attempts/attempt-###/`: attempt-specific state copies and decision artifacts
- `outer_loop/outer_loop_summary.json`: session-level summary
- `outer_loop/outer_loop.log`: outer-loop event log
- `results/llm-outer-loop-attempt-##/`: inner deterministic run artifacts for each attempt

Run it with:

```bash
pixi run -e default run-llm-outer-loop-example
```

The checked-in example uses `llm.backend: mock` so it stays deterministic and
does not require Ollama. Real local-model usage should switch the backend to
`ollama`.
