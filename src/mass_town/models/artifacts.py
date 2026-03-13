from pydantic import BaseModel, Field


class ArtifactRecord(BaseModel):
    name: str
    path: str
    kind: str
    metadata: dict[str, str | float | int | bool] = Field(default_factory=dict)
