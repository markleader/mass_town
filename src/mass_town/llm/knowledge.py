from pathlib import Path

from mass_town.config import WorkflowConfig

REPO_ROOT = Path(__file__).resolve().parents[3]
ROLE_KNOWLEDGE_DIR = REPO_ROOT / "docs" / "llm" / "roles"
TOOL_KNOWLEDGE_PATHS = {
    "gmsh": REPO_ROOT / "plugins" / "gmsh" / "KNOWLEDGE.md",
    "tacs": REPO_ROOT / "plugins" / "tacs" / "KNOWLEDGE.md",
    "mock": REPO_ROOT / "plugins" / "mock" / "KNOWLEDGE.md",
    "topopt": REPO_ROOT / "plugins" / "topopt" / "KNOWLEDGE.md",
}


def load_role_knowledge(role: str) -> str:
    path = ROLE_KNOWLEDGE_DIR / f"{role}.md"
    if not path.exists():
        return ""
    return path.read_text()


def load_tool_knowledge(config: WorkflowConfig, role: str) -> str:
    tool_names: list[str] = []
    if role == "meshing":
        tool_names.append(config.meshing.tool)
    elif role == "structures":
        tool_names.append(config.fea.tool)
    elif role == "topology" and config.topology is not None:
        tool_names.append(config.topology.tool)
    elif role == "chief_engineer":
        tool_names.extend(
            filter(
                None,
                [
                    config.meshing.tool,
                    config.fea.tool,
                    config.topology.tool if config.topology is not None else None,
                ],
            )
        )

    chunks: list[str] = []
    for tool_name in dict.fromkeys(tool_names):
        if not tool_name or tool_name == "auto":
            continue
        path = TOOL_KNOWLEDGE_PATHS.get(tool_name)
        if path is None or not path.exists():
            continue
        chunks.append(f"# Tool knowledge: {tool_name}\n\n{path.read_text().strip()}\n")
    return "\n".join(chunks).strip()
