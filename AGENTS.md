# Agent Notes

## Pixi environment model

This repository uses three named Pixi environments:

- `default`: lightweight core development and tests
- `mdao`: extends `default` with OpenMDAO-focused dependencies
- `fea`: extends `mdao` with FEA/TACS workflow support

Environments are selected one at a time (`pixi run -e <env> ...` or
`pixi shell -e <env>`). Do not describe them as stacked or mixed in a single
runtime session.

## Dependency placement rules

- Keep `default` minimal and fast to install.
- Put OpenMDAO-like tooling in `mdao`, not `default`.
- Put TACS/FEA-specific tooling in `fea`, not `default`.
- Do not promote heavy optional dependencies into `default`.
- Prefer the lightest environment that can run a new example or task.

## TACS local setup expectations

- TACS is optional and local setup is still required.
- Avoid hard-coding machine-specific absolute paths in `pixi.toml`.
- Use documented local hooks (`../tacs` comment placeholder and
  `install-local-tacs` task with optional `TACS_DIR`) for local development.

## Docs and task consistency

- Keep README/docs Pixi command examples aligned with actual environment names
  and tasks defined in `pixi.toml`.
- When adding or renaming a Pixi task, update all user-facing examples in the
  same change.
