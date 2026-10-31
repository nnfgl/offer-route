from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.contracts import AgentResult


class InterviewInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    role: str = Field(min_length=1, max_length=100)
    experience: str = Field(min_length=10, max_length=5000)


class AnswerInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    round: int = Field(ge=1, le=3)
    answer: str = Field(min_length=1, max_length=5000)


class Turn(BaseModel):
    question: str
    answer: str | None = None


class InterviewOutput(BaseModel):
    id: str
    role: str
    experience: str
    status: Literal["active", "completed"]
    created_at: int
    turns: list[Turn]
    report: AgentResult | None = None
