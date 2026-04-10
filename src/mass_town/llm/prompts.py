from __future__ import annotations

import json
from typing import Type

from pydantic import BaseModel

from mass_town.config import WorkflowConfig
from mass_town.llm.knowledge import load_role_knowledge, load_tool_knowledge

ROLE_SYSTEM_PROMPTS = {
    "chief_engineer": (
        "You are the MassTown chief engineer. Judge whether the latest deterministic "
        "attempt should be accepted, rerun with bounded execution-setting changes, or escalated. "
        "Never propose changes to loads, boundary conditions, objectives, constraints, "
        "materials, design-variable definitions, model paths, or CAD geometry."
    ),
    "geometry": (
        "You assess only geometry-validation outcomes and bounded execution issues. "
        "You do not propose CAD edits in this phase."
    ),
    "meshing": (
        "You assess meshing quality, meshing failures, and meshing execution settings only."
    ),
    "structures": (
        "You assess structural analysis outcomes, solver stability, and bounded FEA execution settings only."
    ),
    "optimizer": (
        "You assess optimizer progress and bounded optimizer execution settings only."
    ),
    "topology": (
        "You assess topology optimization progress and bounded topology settings only."
    ),
}


def build_role_prompt(
    role: str,
    payload: dict[str, object],
    response_model: Type[BaseModel],
    config: WorkflowConfig,
) -> str:
    role_knowledge = load_role_knowledge(role)
    tool_knowledge = load_tool_knowledge(config, role)
    schema = json.dumps(response_model.model_json_schema(), indent=2, sort_keys=True)
    body = json.dumps(payload, indent=2, sort_keys=True)
    sections = [
        ROLE_SYSTEM_PROMPTS[role],
        "Return JSON only.",
        "Role knowledge:\n" + (role_knowledge.strip() or "None"),
        "Tool knowledge:\n" + (tool_knowledge.strip() or "None"),
        "Payload:\n" + body,
        "Response schema:\n" + schema,
    ]
    return "\n\n".join(sections)
