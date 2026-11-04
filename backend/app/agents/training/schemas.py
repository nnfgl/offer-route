from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

TaskStatus = Literal["planned", "active", "completed", "archived"]
SubmissionStatus = Literal["pending", "passed", "failed", "error"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Gap(ContractModel):
    requirement_id: str = Field(min_length=1, max_length=100)
    skill_id: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2000)
    source: str = Field(min_length=1, max_length=200)
    excerpt: str = Field(min_length=1, max_length=2000)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)


class DiagnosisPayload(ContractModel):
    schema_version: Literal[1] = 1
    gaps: list[Gap] = Field(min_length=1, max_length=100)


class KnowledgeReference(ContractModel):
    source: str
    excerpt: str
    content_sha256: str
    embedding_profile: Literal["local-test-hash-v1"] = "local-test-hash-v1"


class TaskPayload(ContractModel):
    schema_version: Literal[1] = 1
    exercise_id: Literal["backend-sql-orders-v1"] = "backend-sql-orders-v1"
    exercise_version: Literal[1] = 1
    fixture_version: Literal[1] = 1
    rubric_version: Literal[1] = 1
    skill_id: str
    requirement_id: str
    dialect: Literal["sqlite"] = "sqlite"
    prompt: str
    tables: dict[str, list[str]]
    order_matters: bool = False
    diagnosis_evidence: Gap
    materials: list[KnowledgeReference] = Field(default_factory=list)
    generator: Literal["verified-template"] = "verified-template"


class EvidenceRecord(ContractModel):
    source: str
    excerpt: str
    training_task_id: str
    submission_id: str
    diagnosis_id: str
    skill_id: str
    requirement_id: str
    answer_sha256: str
    created_at: int
    verification: Literal["task_verified"] = "task_verified"


class EvaluationPayload(ContractModel):
    schema_version: Literal[1] = 1
    request_id: str
    answer_sha256: str
    exercise_version: Literal[1] = 1
    fixture_version: Literal[1] = 1
    rubric_version: Literal[1] = 1
    runner_version: Literal["restricted-sql-v1"] = "restricted-sql-v1"
    code: str
    feedback: str
    checked_cases: int = 0
    passed_cases: int = 0
    duration_ms: int = 0
    evidence: list[EvidenceRecord] = Field(default_factory=list)


class CreateTask(ContractModel):
    diagnosis_id: UUID
    requirement_id: str = Field(min_length=1, max_length=100)


class SubmitAnswer(ContractModel):
    request_id: UUID
    answer_text: str = Field(min_length=1, max_length=12000)

    @field_validator("answer_text")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Answer must not be blank")
        return value


class TaskOutput(ContractModel):
    id: str
    diagnosis_id: str
    title: str
    goal: str
    status: TaskStatus
    task_payload: TaskPayload
    created_at: int
    updated_at: int


class SubmissionOutput(ContractModel):
    id: str
    training_task_id: str
    attempt_no: int
    answer_text: str
    status: SubmissionStatus
    evaluation_payload: EvaluationPayload
    created_at: int


class ProfileOutput(ContractModel):
    schema_version: Literal[1] = 1
    diagnosis_id: str
    evidence: list[EvidenceRecord]
    note: str = "仅汇总训练证据，不修改诊断结果或推断整体技能等级。"
