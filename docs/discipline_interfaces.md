# Discipline Interfaces

Phase 5.2 standardizes discipline boundaries without changing the public
project inputs. Existing `config.yaml`, `design_state.yaml`, examples, and Pixi
tasks remain valid while internal DTOs prepare the workflow for later MDAO graph
execution.

## Shared Contracts

Shared DTOs live in `mass_town.disciplines.contracts` and cover:

- named regions as canonical cross-discipline identifiers
- material references and shell/solid property assignment hints
- mesh-to-FEA manifests for structured handoff metadata
- timing, diagnostics, artifacts, and optional sensitivity payloads

Named regions are the stable MassTown identity. Export PIDs and BDF `$ REGION`
comments are compatibility details for BDF/TACS paths.

## Discipline Responsibilities

- CAD prepares or validates geometry and may report named regions.
- Meshing consumes geometry and produces mesh artifacts plus region/property
  handoff metadata when available.
- FEA consumes a model or mesh artifact, preferring structured manifests over
  legacy BDF comment parsing when both exist.
- Post-processing owns solver-neutral derived results such as load-case
  normalization, worst-case selection, stress aggregation, feasibility evidence,
  and future reports/plots.
- Optimization consumes design variables and post-processed responses, then
  proposes the next design-variable state.

## Current Handoff

The gmsh BDF export path writes both the structural BDF and a
`*.mesh_to_fea_manifest.json` file. The manifest records named regions, export
PIDs, placeholder property assignments, and mesh metadata. The TACS backend uses
this manifest for region-to-PID lookup when present and falls back to existing
`$ REGION` comments or `pid_N` inference for older BDF inputs.

## Deferred Work

- Move more report and summary generation from `FEAAgent` into post-processing.
- Expand backend consumption of property DTOs beyond the current region/PID
  bridge.
- Connect the additive DTO layer to the Phase 5.3 MDAO/OpenMDAO graph instead
  of changing current project inputs during Phase 5.2.
