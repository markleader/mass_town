from __future__ import annotations

from collections import Counter, defaultdict, deque


ShellElement = tuple[str, tuple[int, ...]]


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


def classify_boundary_loops(
    node_positions: dict[int, tuple[float, float, float]],
    loops: list[list[int]],
) -> dict[str, list[int]]:
    if len(loops) < 3:
        raise ValueError(
            "Expected at least three boundary loops (outer boundary plus two bores)."
        )

    ranked = [
        {
            "nodes": loop,
            "area": abs(_loop_area_xy(node_positions, loop)),
            "centroid_x": sum(node_positions[node_id][0] for node_id in loop) / len(loop),
        }
        for loop in loops
    ]
    ranked.sort(key=lambda item: item["area"], reverse=True)
    outer = ranked[0]["nodes"]
    bores = ranked[1:3]
    bores.sort(key=lambda item: item["centroid_x"])

    return {
        "outer": list(outer),
        "left_bore": list(bores[0]["nodes"]),
        "right_bore": list(bores[1]["nodes"]),
    }


def distribute_force_to_nodes(
    node_ids: list[int],
    total_force: float,
    direction: tuple[float, float, float] = (0.0, -1.0, 0.0),
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
