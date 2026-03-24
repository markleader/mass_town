from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ElementKind = Literal["shell", "solid"]
Topology = Literal["triangle", "quadrilateral", "tetrahedron", "hexahedron"]


@dataclass(frozen=True, slots=True)
class MeshNode:
    id: int
    x: float
    y: float
    z: float


@dataclass(frozen=True, slots=True)
class MeshElement:
    id: int
    topology: Topology
    node_ids: tuple[int, ...]
    physical_group_id: int | None
    physical_group_name: str | None
    entity_dim: int
    entity_tag: int

    @property
    def element_kind(self) -> ElementKind:
        if self.topology in {"triangle", "quadrilateral"}:
            return "shell"
        return "solid"


@dataclass(frozen=True, slots=True)
class MeshRegion:
    key: tuple[int | None, str | None]
    pid: int
    name: str
    raw_name: str | None
    gmsh_physical_id: int | None
    element_kind: ElementKind
    entity_dim: int


@dataclass(slots=True)
class NormalizedMesh:
    nodes: list[MeshNode]
    elements: list[MeshElement]
    regions: list[MeshRegion]
    metadata: dict[str, str | float | int | bool] = field(default_factory=dict)
