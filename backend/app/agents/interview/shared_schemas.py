from pydantic import BaseModel, ConfigDict, Field, model_validator


class InterviewLinks(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    job_analysis_id: str | None = Field(default=None, min_length=1, max_length=100)
    diagnosis_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def diagnosis_requires_job(self):
        if self.diagnosis_id and not self.job_analysis_id:
            raise ValueError("diagnosis_id requires job_analysis_id")
        return self


class ParentContext(BaseModel):
    schema_version: int = 1
    job_title: str
    requirements: list[dict] = Field(default_factory=list)
    diagnosis: dict | None = None
