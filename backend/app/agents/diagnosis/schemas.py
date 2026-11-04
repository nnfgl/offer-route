"""能力诊断的数据模型。

字段命名严格对齐 docs/database-schema.sql：
- resumes        -> Resume
- diagnosis_tasks -> DiagnosisTask（result_payload 承载 DiagnosisResult）

DiagnosisResult / DiagnosisItem 是 result_payload 内的业务 JSON，
按 docs/database.md 用 schema_version 标识版本。
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvidenceType(StrEnum):
    """证据强度分类，必须在提示词中强制 LLM 区分。"""

    SELF_CLAIMED = "self_claimed"  # 用户自述
    PORTFOLIO_SUPPORTED = "portfolio_supported"  # 作品支持
    TASK_VERIFIED = "task_verified"  # 任务验证


class DiagnosisItem(BaseModel):
    """一条诊断判断（优势 / 缺口 / 待验证项共用），每条都必须关联证据。

    evidence_type 对能力缺口（无证据）为 None，其余情况为三类证据之一。
    """

    model_config = ConfigDict(extra="forbid")

    requirement_id: str | None = Field(default=None, max_length=64)
    claim_content: str = Field(min_length=1, max_length=800)
    matched_requirement: str = Field(min_length=1, max_length=800)
    evidence_type: EvidenceType | None = None
    evidence_excerpt: str | None = Field(default=None, max_length=2000)
    confidence_score: float = Field(ge=0.0, le=1.0)

    @field_validator("claim_content", "matched_requirement", mode="before")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip() if isinstance(value, str) else value
        if not value:
            raise ValueError("claim_content / matched_requirement 不能为空")
        return value

    @field_validator("requirement_id", "evidence_excerpt", mode="before")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class DiagnosisResult(BaseModel):
    """诊断结果，持久化到 diagnosis_tasks.result_payload。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    summary: str = Field(default="", max_length=2000)
    strengths: list[DiagnosisItem] = Field(default_factory=list, max_length=50)
    gaps: list[DiagnosisItem] = Field(default_factory=list, max_length=50)
    pending_verification: list[DiagnosisItem] = Field(default_factory=list, max_length=50)

    @field_validator("summary", mode="before")
    @classmethod
    def strip_summary(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class Resume(BaseModel):
    """对齐 resumes 表；parsed_payload 在边界处做 JSON 序列化。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    title: str = Field(min_length=1, max_length=120)
    source_text: str = Field(min_length=1, max_length=20000)
    parsed_payload: dict = Field(default_factory=dict)
    created_at: int = Field(ge=0)

    @field_validator("title", "source_text", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip() if isinstance(value, str) else value
        if not value:
            raise ValueError("title / source_text 不能为空")
        return value


class DiagnosisTask(BaseModel):
    """对齐 diagnosis_tasks 表。result_payload 承载 DiagnosisResult。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    job_analysis_id: str
    resume_id: str
    status: Literal["running", "completed", "needs_input", "failed"]
    result_payload: DiagnosisResult = Field(default_factory=DiagnosisResult)
    created_at: int = Field(ge=0)
    updated_at: int = Field(ge=0)


class DiagnosisInput(BaseModel):
    """创建一次诊断：粘贴简历 + 引用一条已完成的岗位分析。"""

    model_config = ConfigDict(extra="forbid")

    job_analysis_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=2, max_length=120)
    source_text: str = Field(min_length=20, max_length=20000)

    @field_validator("job_analysis_id", "title", "source_text", mode="before")
    @classmethod
    def strip_input(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class DiagnosisSummary(BaseModel):
    """诊断历史摘要；resume_title / job_title 由联表补齐便于展示。"""

    id: str
    resume_id: str
    job_analysis_id: str
    status: Literal["running", "completed", "needs_input", "failed"]
    resume_title: str
    job_title: str
    summary: str
    created_at: int


class DiagnosisDetail(BaseModel):
    """诊断详情；result 为 result_payload 解析出的结构化结果。"""

    id: str
    resume_id: str
    job_analysis_id: str
    status: Literal["running", "completed", "needs_input", "failed"]
    result: DiagnosisResult
    created_at: int
    updated_at: int