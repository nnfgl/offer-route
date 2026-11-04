from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agents.contracts import AgentResult
from app.core.model_client import ModelUsage


class JobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=2, max_length=120)
    source_text: str = Field(min_length=20, max_length=20000)

    @field_validator("title", "source_text", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class Requirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=2, max_length=200)
    priority: Literal["required", "preferred", "unspecified"]
    category: Literal["skill", "experience", "education", "other"]
    quote: str = Field(min_length=2, max_length=2000)


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirements: list[Requirement] = Field(max_length=50)


class LocatedRequirement(Requirement):
    id: str
    source_start: int
    source_end: int
    source_line: int


class TraceStep(BaseModel):
    name: str
    status: Literal["completed", "failed", "skipped"]
    detail: str


class JobTask(BaseModel):
    id: str
    title: str
    source_text: str
    provider: Literal["rules", "deepseek"]
    status: Literal["running", "completed", "needs_input", "failed"]
    created_at: int
    requirements: list[LocatedRequirement] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
    result: AgentResult | None = None
    usage: ModelUsage = Field(default_factory=ModelUsage)
    error: dict[str, str] | None = None


class TaskSummary(BaseModel):
    id: str
    title: str
    provider: str
    status: str
    created_at: int
