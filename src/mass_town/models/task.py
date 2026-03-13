from typing import Literal

from pydantic import BaseModel, Field

TaskName = Literal["geometry", "mesh", "fea", "optimizer"]
TaskStatus = Literal["pending", "running", "succeeded", "failed"]


class Task(BaseModel):
    name: TaskName
    status: TaskStatus = "pending"
    attempts: int = 0
    assigned_agent: str | None = None
    metadata: dict[str, str | float | int | bool] = Field(default_factory=dict)
