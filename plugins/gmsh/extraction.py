from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import re

from .mesh_model import MeshElement, MeshNode, MeshRegion, NormalizedMesh

SUPPORTED_GMSH_TYPES: dict[int, tuple[str, int]] = {
    2: ("triangle", 3),
    3: ("quadrilateral", 4),
    4: ("tetrahedron", 4),
    5: ("hexahedron", 8),
}
IGNORED_GMSH_TYPES = {1, 15}

_SANITIZE_PATTERN = re.compile(r"[^A-Za-z0-9_-]+")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_UNDERSCORE_PATTERN = re.compile(r"_+")


def parse_gmsh_msh2(path: Path) -> NormalizedMesh:
    lines = path.read_text().splitlines()
    sections = _split_sections(lines)

    nodes = _parse_nodes(sections)
    elements, unsupported, ignored = _parse_elements(sections)
    if unsupported:
        details = ", ".join(
            f"type {element_type} ({count} elements)"
            for element_type, count in sorted(unsupported.items())
        )
        raise ValueError(
            "Unsupported gmsh element types for BDF export: "
            f"{details}. Supported types: 2, 3, 4, 5."
        )
    if not nodes:
        raise ValueError("Generated gmsh mesh contains no nodes; cannot export BDF.")
    if not elements:
        raise ValueError("Generated gmsh mesh contains no elements; cannot export BDF.")

    physical_names = _parse_physical_names(sections)
    target_dimension = max(
        _entity_dimension_for_topology(str(element["topology"]))
        for element in elements
    )
    normalized_elements = [
        MeshElement(
            id=element["id"],
            topology=element["topology"],
            node_ids=element["node_ids"],
            physical_group_id=element["physical_group_id"],
            physical_group_name=physical_names.get(element["physical_group_id"]),
            entity_dim=element["entity_dim"],
            entity_tag=element["entity_tag"],
        )
        for element in sorted(elements, key=lambda item: item["id"])
        if int(element["entity_dim"]) == target_dimension
    ]
    regions = _build_regions(normalized_elements)
    return NormalizedMesh(
        nodes=sorted(nodes, key=lambda node: node.id),
        elements=normalized_elements,
        regions=regions,
        metadata={
            "source_format": "msh2",
            "node_count": len(nodes),
            "element_count": len(normalized_elements),
            "region_count": len(regions),
            "shell_element_count": sum(
                1 for element in normalized_elements if element.element_kind == "shell"
            ),
            "solid_element_count": sum(
                1 for element in normalized_elements if element.element_kind == "solid"
            ),
            "target_dimension": target_dimension,
            "ignored_lower_dimensional_element_count": ignored + len(elements) - len(normalized_elements),
        },
    )


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line.startswith("$") or line.startswith("$End"):
            index += 1
            continue
        section_name = line[1:]
        end_marker = f"$End{section_name}"
        start = index + 1
        index = start
        while index < len(lines) and lines[index].strip() != end_marker:
            index += 1
        if index >= len(lines):
            raise ValueError(f"Malformed gmsh mesh: missing {end_marker}.")
        sections[section_name] = lines[start:index]
        index += 1
    return sections


def _parse_nodes(sections: dict[str, list[str]]) -> list[MeshNode]:
    try:
        node_lines = sections["Nodes"]
    except KeyError as exc:
        raise ValueError("Malformed gmsh mesh: missing $Nodes section.") from exc
    if not node_lines:
        raise ValueError("Malformed gmsh mesh: empty $Nodes section.")

    try:
        expected_count = int(node_lines[0].strip())
    except ValueError as exc:
        raise ValueError("Malformed gmsh mesh: invalid node count.") from exc

    nodes: list[MeshNode] = []
    for raw_line in node_lines[1:]:
        parts = raw_line.split()
        if len(parts) != 4:
            raise ValueError(f"Malformed gmsh mesh node entry: {raw_line}")
        node_id = int(parts[0])
        x, y, z = (float(parts[1]), float(parts[2]), float(parts[3]))
        nodes.append(MeshNode(id=node_id, x=x, y=y, z=z))

    if len(nodes) != expected_count:
        raise ValueError(
            "Malformed gmsh mesh: declared node count does not match parsed nodes."
        )
    return nodes


def _parse_elements(
    sections: dict[str, list[str]],
) -> tuple[list[dict[str, object]], Counter[int], int]:
    try:
        element_lines = sections["Elements"]
    except KeyError as exc:
        raise ValueError("Malformed gmsh mesh: missing $Elements section.") from exc
    if not element_lines:
        raise ValueError("Malformed gmsh mesh: empty $Elements section.")

    try:
        expected_count = int(element_lines[0].strip())
    except ValueError as exc:
        raise ValueError("Malformed gmsh mesh: invalid element count.") from exc

    elements: list[dict[str, object]] = []
    unsupported: Counter[int] = Counter()
    ignored = 0
    for raw_line in element_lines[1:]:
        parts = raw_line.split()
        if len(parts) < 4:
            raise ValueError(f"Malformed gmsh mesh element entry: {raw_line}")
        element_id = int(parts[0])
        element_type = int(parts[1])
        tag_count = int(parts[2])
        if len(parts) < 3 + tag_count:
            raise ValueError(f"Malformed gmsh mesh element tags: {raw_line}")
        tags = [int(value) for value in parts[3 : 3 + tag_count]]
        node_tokens = parts[3 + tag_count :]
        if element_type in IGNORED_GMSH_TYPES:
            ignored += 1
            continue
        if element_type not in SUPPORTED_GMSH_TYPES:
            unsupported[element_type] += 1
            continue
        topology, expected_nodes = SUPPORTED_GMSH_TYPES[element_type]
        if len(node_tokens) != expected_nodes:
            raise ValueError(
                f"Malformed gmsh mesh element {element_id}: expected {expected_nodes} nodes "
                f"for type {element_type}, found {len(node_tokens)}."
            )
        physical_group_id = tags[0] if tag_count >= 1 and tags[0] > 0 else None
        entity_tag = tags[1] if tag_count >= 2 else 0
        entity_dim = _entity_dimension_for_topology(topology)
        elements.append(
            {
                "id": element_id,
                "topology": topology,
                "node_ids": tuple(int(token) for token in node_tokens),
                "physical_group_id": physical_group_id,
                "entity_tag": entity_tag,
                "entity_dim": entity_dim,
            }
        )

    if len(elements) + sum(unsupported.values()) != expected_count:
        if len(elements) + sum(unsupported.values()) + ignored != expected_count:
            raise ValueError(
                "Malformed gmsh mesh: declared element count does not match parsed elements."
            )
    return elements, unsupported, ignored


def _parse_physical_names(sections: dict[str, list[str]]) -> dict[int, str]:
    lines = sections.get("PhysicalNames")
    if not lines:
        return {}
    try:
        expected_count = int(lines[0].strip())
    except ValueError as exc:
        raise ValueError("Malformed gmsh mesh: invalid physical name count.") from exc
    names: dict[int, str] = {}
    for raw_line in lines[1:]:
        parts = raw_line.split(maxsplit=2)
        if len(parts) != 3:
            raise ValueError(f"Malformed gmsh physical name entry: {raw_line}")
        _, physical_id_text, name_text = parts
        physical_id = int(physical_id_text)
        name = name_text.strip()
        if len(name) >= 2 and name[0] == '"' and name[-1] == '"':
            name = name[1:-1]
        names[physical_id] = name
    if len(names) != expected_count:
        raise ValueError(
            "Malformed gmsh mesh: declared physical name count does not match parsed names."
        )
    return names


def _build_regions(elements: list[MeshElement]) -> list[MeshRegion]:
    grouped: dict[tuple[int | None, str | None], list[MeshElement]] = defaultdict(list)
    for element in elements:
        grouped[(element.physical_group_id, element.physical_group_name)].append(element)

    used_names: set[str] = set()
    sortable_regions: list[tuple[tuple[str, int, int, int], MeshRegion]] = []
    for key, region_elements in grouped.items():
        first = min(region_elements, key=lambda element: element.id)
        raw_name = first.physical_group_name or (
            f"PHYS_{first.physical_group_id}"
            if first.physical_group_id is not None
            else "UNASSIGNED"
        )
        sanitized_name = _deduplicate_name(_sanitize_name(raw_name), used_names, first, key)
        kinds = {element.element_kind for element in region_elements}
        if len(kinds) > 1:
            kind_names = ", ".join(sorted(kinds))
            raise ValueError(
                f"Physical group '{raw_name}' mixes shell and solid elements; "
                f"BDF export requires one property type per region. Encountered: {kind_names}."
            )
        region = MeshRegion(
            key=key,
            pid=0,
            name=sanitized_name,
            raw_name=raw_name,
            gmsh_physical_id=first.physical_group_id,
            element_kind=first.element_kind,
            entity_dim=first.entity_dim,
        )
        sort_key = (
            sanitized_name,
            first.physical_group_id if first.physical_group_id is not None else -1,
            first.entity_dim,
            first.id,
        )
        sortable_regions.append((sort_key, region))

    regions: list[MeshRegion] = []
    for pid, (_, region) in enumerate(sorted(sortable_regions, key=lambda item: item[0]), start=1):
        regions.append(
            MeshRegion(
                key=region.key,
                pid=pid,
                name=region.name,
                raw_name=region.raw_name,
                gmsh_physical_id=region.gmsh_physical_id,
                element_kind=region.element_kind,
                entity_dim=region.entity_dim,
            )
        )
    return regions


def _sanitize_name(raw_name: str) -> str:
    collapsed_whitespace = _WHITESPACE_PATTERN.sub("_", raw_name.strip())
    replaced = _SANITIZE_PATTERN.sub("_", collapsed_whitespace)
    collapsed = _UNDERSCORE_PATTERN.sub("_", replaced).strip("_")
    return collapsed or "UNASSIGNED"


def _deduplicate_name(
    base_name: str,
    used_names: set[str],
    first_element: MeshElement,
    key: tuple[int | None, str | None],
) -> str:
    candidate = base_name
    if candidate not in used_names:
        used_names.add(candidate)
        return candidate
    if key[0] is not None:
        candidate = f"{base_name}_{key[0]}"
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
    candidate = f"{base_name}_{first_element.id}"
    if candidate not in used_names:
        used_names.add(candidate)
        return candidate

    ordinal = 2
    while True:
        candidate = f"{base_name}_{ordinal}"
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
        ordinal += 1


def _entity_dimension_for_topology(topology: str) -> int:
    if topology in {"triangle", "quadrilateral"}:
        return 2
    return 3
