from __future__ import annotations

from dataclasses import dataclass
from collections import Counter, defaultdict, deque


ShellElement = tuple[str, tuple[int, ...]]


@dataclass(frozen=True)
class BoundaryLoop:
    nodes: list[int]
    area: float
    abs_area: float
    centroid_x: float
    centroid_y: float


def find_boundary_loops(
    node_positions: dict[int, tuple[float, float, float]],
    elements: list[ShellElement],
) -> list[list[int]]:
    edge_counts: Counter[tuple[int, int]] = Counter()
    adjacency: dict[int, set[int]] = defaultdict(set)

    for _, node_ids in elements:
        for edge in _element_edges(node_ids):
            normalized = tuple(sorted(edge))
            edge_counts[normalized] += 1

    boundary_edges = [edge for edge, count in edge_counts.items() if count == 1]
    if not boundary_edges:
        raise ValueError("Shell mesh has no free-edge boundary loops.")

    for node_a, node_b in boundary_edges:
        adjacency[node_a].add(node_b)
        adjacency[node_b].add(node_a)

    loops: list[list[int]] = []
    visited_nodes: set[int] = set()
    for start_node in sorted(adjacency):
        if start_node in visited_nodes:
            continue

        component_nodes = _component_nodes(start_node, adjacency)
        loop = _trace_loop(min(component_nodes), adjacency)
        if any(node_id not in node_positions for node_id in loop):
            raise ValueError("Boundary loop references nodes missing from the shell mesh.")

        loops.append(loop)
        visited_nodes.update(component_nodes)

    return loops


def describe_boundary_loops(
    node_positions: dict[int, tuple[float, float, float]],
    loops: list[list[int]],
) -> list[BoundaryLoop]:
    described: list[BoundaryLoop] = []
    for loop in loops:
        signed_area = _loop_area_xy(node_positions, loop)
        described.append(
            BoundaryLoop(
                nodes=list(loop),
                area=signed_area,
                abs_area=abs(signed_area),
                centroid_x=sum(node_positions[node_id][0] for node_id in loop) / len(loop),
                centroid_y=sum(node_positions[node_id][1] for node_id in loop) / len(loop),
            )
        )
    return described


def select_boundary_loop(
    loop_data: list[BoundaryLoop],
    *,
    family: str,
    order_by: str,
    index: int,
) -> list[int]:
    if index < 0:
        raise ValueError("Boundary-loop selector index must be non-negative.")
    if not loop_data:
        raise ValueError("Shell mesh has no free-edge boundary loops.")

    by_area = sorted(loop_data, key=lambda item: item.abs_area, reverse=True)
    if family == "outer":
        candidates = by_area[:1]
    elif family == "inner":
        candidates = by_area[1:]
    else:
        raise ValueError(f"Unsupported boundary-loop family '{family}'.")

    if not candidates:
        raise ValueError(f"Shell mesh has no boundary loops in family '{family}'.")

    if order_by == "area":
        ranked = sorted(candidates, key=lambda item: item.abs_area, reverse=True)
    elif order_by == "centroid_x":
        ranked = sorted(candidates, key=lambda item: item.centroid_x)
    elif order_by == "centroid_y":
        ranked = sorted(candidates, key=lambda item: item.centroid_y)
    else:
        raise ValueError(f"Unsupported boundary-loop ordering '{order_by}'.")

    try:
        return list(ranked[index].nodes)
    except IndexError as exc:
        raise ValueError(
            f"Boundary-loop selector index {index} is out of range for family '{family}'."
        ) from exc


def distribute_force_to_nodes(
    node_ids: list[int],
    total_force: float,
    direction: tuple[float, float, float],
) -> list[list[float]]:
    if not node_ids:
        raise ValueError("Cannot distribute a load across zero nodes.")

    scale = total_force / len(node_ids)
    fx, fy, fz = direction
    return [[scale * fx, scale * fy, scale * fz, 0.0, 0.0, 0.0] for _ in node_ids]


def _component_nodes(start_node: int, adjacency: dict[int, set[int]]) -> set[int]:
    queue: deque[int] = deque([start_node])
    nodes: set[int] = set()
    while queue:
        node_id = queue.popleft()
        if node_id in nodes:
            continue
        nodes.add(node_id)
        queue.extend(sorted(adjacency[node_id]))
    return nodes


def _trace_loop(start_node: int, adjacency: dict[int, set[int]]) -> list[int]:
    loop = [start_node]
    previous = None
    current = start_node

    while True:
        neighbors = sorted(adjacency[current])
        if len(neighbors) != 2:
            raise ValueError("Shell boundary graph is not a set of simple closed loops.")

        candidates = [neighbor for neighbor in neighbors if neighbor != previous]
        if not candidates:
            raise ValueError("Failed to trace shell boundary loop.")

        next_node = candidates[0]
        if next_node == start_node:
            return loop

        loop.append(next_node)
        previous, current = current, next_node


def _element_edges(node_ids: tuple[int, ...]) -> list[tuple[int, int]]:
    edge_pairs = list(zip(node_ids, node_ids[1:] + node_ids[:1], strict=False))
    return [(int(node_a), int(node_b)) for node_a, node_b in edge_pairs]


def _loop_area_xy(
    node_positions: dict[int, tuple[float, float, float]],
    loop: list[int],
) -> float:
    area = 0.0
    for node_id, next_node_id in zip(loop, loop[1:] + loop[:1], strict=False):
        x1, y1, _ = node_positions[node_id]
        x2, y2, _ = node_positions[next_node_id]
        area += x1 * y2 - x2 * y1
    return 0.5 * area
