"""能力诊断持久化工作流：简历落库、诊断执行、写入 diagnosis_tasks、中断恢复。

- 所有查询同时约束 id + user_id，避免跨用户读取；
- 诊断结果只写 diagnosis_tasks.result_payload（DiagnosisResult），不新建其它表。
"""

import asyncio
import json
import time
from threading import BoundedSemaphore
from uuid import uuid4

from app.agents.diagnosis.agent import (
    apply_confidence_filter,
    build_summary,
    diagnose_with_model,
    rule_diagnose,
)
from app.agents.diagnosis.prompting import load_template
from app.agents.diagnosis.schemas import DiagnosisResult, DiagnosisTask, Resume
from app.agents.job.schemas import JobTask
from app.core.config import Settings
from app.core.database import Database
from app.core.model_client import DeepSeekClient, ModelFailure


class JobAnalysisNotFound(Exception):
    pass


class JobAnalysisNotReady(Exception):
    def __init__(self, status: str):
        self.status = status
        super().__init__(status)


class ResumeNotFound(Exception):
    pass


class DiagnosisWorkflow:
    def __init__(self, database: Database, settings: Settings, model: DeepSeekClient):
        self.database, self.settings, self.model = database, settings, model
        # 诊断是重模型任务，独立槽位，缓解与岗位分析的并发争抢。
        self.slots = BoundedSemaphore(2)

    def create_resume(self, user_id: str, title: str, source_text: str) -> Resume:
        resume = Resume(
            id=str(uuid4()),
            user_id=user_id,
            title=title,
            source_text=source_text,
            created_at=int(time.time()),
        )
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO resumes (id, user_id, title, source_text, parsed_payload, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    resume.id,
                    resume.user_id,
                    resume.title,
                    resume.source_text,
                    json.dumps(resume.parsed_payload),
                    resume.created_at,
                ),
            )
        return resume

    def get_resume(self, user_id: str, resume_id: str) -> Resume:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM resumes WHERE id = ? AND user_id = ?", (resume_id, user_id)
            ).fetchone()
        if not row:
            raise ResumeNotFound()
        data = dict(row)
        data["parsed_payload"] = json.loads(data["parsed_payload"])
        return Resume.model_validate(data)

    def job_requirements(self, user_id: str, job_analysis_id: str) -> list[dict]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT payload, status FROM job_analysis_tasks WHERE id = ? AND user_id = ?",
                (job_analysis_id, user_id),
            ).fetchone()
        if not row:
            raise JobAnalysisNotFound()
        task = JobTask.model_validate_json(row["payload"])
        if task.status != "completed":
            raise JobAnalysisNotReady(task.status)
        return [
            {
                "id": req.id,
                "text": req.text,
                "priority": req.priority,
                "category": req.category,
                "quote": req.quote,
            }
            for req in task.requirements
        ]

    def _insert(self, task: DiagnosisTask) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO diagnosis_tasks "
                "(id, user_id, job_analysis_id, resume_id, status, result_payload, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task.id,
                    task.user_id,
                    task.job_analysis_id,
                    task.resume_id,
                    task.status,
                    task.result_payload.model_dump_json(),
                    task.created_at,
                    task.updated_at,
                ),
            )

    def save(self, task: DiagnosisTask) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE diagnosis_tasks SET status = ?, result_payload = ?, updated_at = ? "
                "WHERE id = ? AND user_id = ?",
                (
                    task.status,
                    task.result_payload.model_dump_json(),
                    task.updated_at,
                    task.id,
                    task.user_id,
                ),
            )

    def recover_interrupted(self) -> None:
        now = int(time.time())
        payload = DiagnosisResult(summary="服务重启导致诊断中断，请重新提交").model_dump_json()
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, user_id FROM diagnosis_tasks WHERE status = 'running'"
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE diagnosis_tasks SET status = 'failed', result_payload = ?, "
                    "updated_at = ? WHERE id = ? AND user_id = ?",
                    (payload, now, row["id"], row["user_id"]),
                )

    async def run(self, user_id: str, resume_id: str, job_analysis_id: str) -> DiagnosisTask:
        resume = self.get_resume(user_id, resume_id)
        requirements = self.job_requirements(user_id, job_analysis_id)
        task = DiagnosisTask(
            id=str(uuid4()),
            user_id=user_id,
            job_analysis_id=job_analysis_id,
            resume_id=resume_id,
            status="running",
            created_at=int(time.time()),
            updated_at=int(time.time()),
        )
        self._insert(task)
        try:
            if self.settings.diagnosis_provider == "deepseek":
                result, _ = await diagnose_with_model(
                    self.model, load_template(), resume.source_text, requirements
                )
            else:
                result = rule_diagnose(resume.source_text, requirements)
            result = apply_confidence_filter(result)
            result.summary = build_summary(result)
            task.result_payload = result
            task.status = (
                "completed"
                if (result.strengths or result.gaps or result.pending_verification)
                else "needs_input"
            )
        except ModelFailure as exc:
            task.status = "failed"
            task.result_payload = DiagnosisResult(summary=exc.message)
        except asyncio.CancelledError:
            task.status = "failed"
            task.result_payload = DiagnosisResult(summary="诊断被中断，请重新提交")
            self.save(task)
            raise
        except Exception:
            task.status = "failed"
            task.result_payload = DiagnosisResult(summary="诊断未能完成，请稍后重试")
        task.updated_at = int(time.time())
        self.save(task)
        return task