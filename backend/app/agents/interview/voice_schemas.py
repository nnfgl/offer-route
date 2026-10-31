from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.contracts import AgentResult
from app.agents.interview.shared_schemas import InterviewLinks, ParentContext
from app.core.model_client import ModelUsage


class VoiceInput(InterviewLinks):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    role: str = Field(min_length=1, max_length=100)
    experience: str = Field(min_length=10, max_length=5000)


class VoiceConnectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offer_sdp: str = Field(min_length=20, max_length=100000)


class VoiceMessage(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    id: str = Field(min_length=1, max_length=200)
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=10000)
    final: bool = True
    interrupted: bool = False
    sequence: int = Field(default=0, ge=0, le=200)


class VoiceMessagesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[VoiceMessage] = Field(min_length=1, max_length=200)


class VoiceEndInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_count: int = Field(ge=0, le=200)
    accept_incomplete: bool = False


class VoiceInterview(BaseModel):
    schema_version: Literal[1] = 1
    job_analysis_id: str | None = None
    diagnosis_id: str | None = None
    parent_context: ParentContext | None = None
    id: str
    role: str
    experience: str
    created_at: int
    ended_at: int | None = None
    connected_at: int | None = None
    status: Literal["created", "connecting", "live", "ended"] = "created"
    connection_attempt: str | None = None
    messages: list[VoiceMessage] = Field(default_factory=list)
    incomplete: bool = False
    report_status: Literal["not_started", "processing", "completed", "failed"] = "not_started"
    report_started_at: int | None = None
    report_attempt: str | None = None
    report_error: str | None = None
    report: AgentResult | None = None
    report_usage: ModelUsage = Field(default_factory=ModelUsage)


class VoiceEvidence(BaseModel):
    message_id: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=500)


class VoiceDimension(BaseModel):
    name: Literal["岗位理解", "技术与经历", "表达结构", "反思改进"]
    score: int = Field(ge=0, le=5)
    reason: str = Field(min_length=1, max_length=1000)
    evidence: list[VoiceEvidence] = Field(default_factory=list, max_length=4)
    suggestion: str = Field(min_length=1, max_length=1000)


class VoiceReview(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    dimensions: list[VoiceDimension] = Field(min_length=4, max_length=4)
