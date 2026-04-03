from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from .setup_common import FEABoundaryCondition, FEABoundingBoxNodeSelector, FEALoad


class FEASolidNodeSet(FEABoundingBoxNodeSelector):
    selector: str = "bounding_box_extreme"


class FEASolidSetup(BaseModel):
    node_sets: dict[str, FEASolidNodeSet] = Field(default_factory=dict)
    boundary_conditions: list[FEABoundaryCondition] = Field(default_factory=list)
    loads: list[FEALoad] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_references(self) -> "FEASolidSetup":
        available_node_sets = set(self.node_sets)
        referenced_node_sets = {
            item.node_set for item in [*self.boundary_conditions, *self.loads]
        }
        missing = sorted(referenced_node_sets - available_node_sets)
        if missing:
            missing_names = ", ".join(missing)
            raise ValueError(
                "Solid setup references unknown node sets: "
                f"{missing_names}."
            )
        return self
