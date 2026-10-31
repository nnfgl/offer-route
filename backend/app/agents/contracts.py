from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class AgentKind(StrEnum):
    JOB = "job"
    DIAGNOSIS = "diagnosis"
    TRAINING = "training"
    INTERVIEW = "interview"


class Evidence(BaseModel):
    source: str
    excerpt: str


class AgentRequest(BaseModel):
    """user_id must be supplied by the authenticated backend, never trusted from a browser."""

    task_id: str
    user_id: str
    goal: str
    context: dict = Field(default_factory=dict)


class AgentResult(BaseModel):
    task_id: str
    agent: AgentKind
    status: Literal["completed", "needs_input", "failed"]
    summary: str
    evidence: list[Evidence] = Field(default_factory=list)
    data: dict = Field(default_factory=dict)
