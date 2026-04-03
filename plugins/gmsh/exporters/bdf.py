from __future__ import annotations

from pathlib import Path

from ..mesh_model import NormalizedMesh


def write_bdf(mesh: NormalizedMesh, output_path: Path) -> Path:
    if not mesh.nodes:
        raise ValueError("Generated gmsh mesh contains no nodes; cannot export BDF.")
    if not mesh.elements:
        raise ValueError("Generated gmsh mesh contains no elements; cannot export BDF.")

    region_by_key = {region.key: region for region in mesh.regions}
    lines = [
        "$ MassTown gmsh BDF export",
        "$ Placeholder PSHELL/PSOLID cards are intended for downstream override.",
        "CEND",
        "BEGIN BULK",
    ]
    for region in mesh.regions:
        gmsh_id = str(region.gmsh_physical_id) if region.gmsh_physical_id is not None else "none"
        lines.append(
            f"$ REGION pid={region.pid} gmsh_id={gmsh_id} "
            f"kind={region.element_kind} name={region.name}"
        )
        if region.raw_name is not None and region.raw_name != region.name:
            lines.append(f"$ REGION_RAW pid={region.pid} raw_name={region.raw_name}")

    lines.append("MAT1,1,70000.0,,0.3,1.0")
    for region in mesh.regions:
        if region.element_kind == "shell":
            lines.append(f"PSHELL,{region.pid},1,1.0")
        else:
            lines.append(f"PSOLID,{region.pid},1")

    for node in mesh.nodes:
        lines.append(
            f"GRID,{node.id},,{_format_float(node.x)},{_format_float(node.y)},{_format_float(node.z)}"
        )

    for element in mesh.elements:
        region = region_by_key[(element.physical_group_id, element.physical_group_name)]
        card_name = _card_name(element.topology)
        lines.extend(_element_card_lines(card_name, element.id, region.pid, element.node_ids))

    lines.append("ENDDATA")
    output_path.write_text("\n".join(lines) + "\n")
    return output_path


def _card_name(topology: str) -> str:
    return {
        "triangle": "CTRIA3",
        "quadrilateral": "CQUAD4",
        "tetrahedron": "CTETRA",
        "hexahedron": "CHEXA",
    }[topology]


def _format_float(value: float) -> str:
    text = f"{value:.16g}"
    if "e" in text.lower() or "." in text:
        return text
    return f"{text}.0"


def _element_card_lines(
    card_name: str,
    element_id: int,
    pid: int,
    node_ids: tuple[int, ...],
) -> list[str]:
    if card_name != "CHEXA":
        node_list = ",".join(str(node_id) for node_id in node_ids)
        return [f"{card_name},{element_id},{pid},{node_list}"]

    first_line = ",".join(
        [
            card_name,
            str(element_id),
            str(pid),
            *(str(node_id) for node_id in node_ids[:6]),
        ]
    )
    second_line = ",".join(
        [
            "+",
            *(str(node_id) for node_id in node_ids[6:]),
        ]
    )
    return [first_line, second_line]
