import asyncio
import json
import time
from threading import BoundedSemaphore
from uuid import uuid4

from app.agents.contracts import AgentRequest
from app.agents.job.agent import (
    SYSTEM_PROMPT,
    agent_result,
    locate,
    rule_extract,
    validate_extraction,
)
from app.agents.job.schemas import JobInput, JobTask, TraceStep
from app.core.config import Settings
from app.core.database import Database
from app.core.model_client import DeepSeekClient, ModelFailure


class JobWorkflow:
    """Persisted first stage. Other agents are integration points, never simulated runs."""

    def __init__(self, database: Database, settings: Settings, model: DeepSeekClient):
        self.database, self.settings, self.model = database, settings, model
        self.slots = BoundedSemaphore(4)

    def save(self, task: JobTask) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE job_analysis_tasks SET status = ?, payload = ? WHERE id = ?",
                (task.status, task.model_dump_json(), task.id),
            )

    def recover_interrupted(self) -> None:
        # The development deployment is single-process; no other worker owns these runs.
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM job_analysis_tasks WHERE status = 'running'"
            ).fetchall()
            for row in rows:
                task = JobTask.model_validate_json(row["payload"])
                task.status = "failed"
                task.error = {
                    "code": "analysis_interrupted",
                    "message": "服务重启导致分析中断，请重新提交",
                }
                task.trace.append(
                    TraceStep(name="恢复任务状态", status="failed", detail=task.error["message"])
                )
                connection.execute(
                    "UPDATE job_analysis_tasks SET status = ?, payload = ? WHERE id = ?",
                    (task.status, task.model_dump_json(), task.id),
                )

    async def run(self, user_id: str, data: JobInput, *, task_id: str | None = None) -> JobTask:
        task = JobTask(
            id=task_id or str(uuid4()),
            title=data.title,
            source_text=data.source_text,
            provider=self.settings.job_provider,
            status="running",
            created_at=int(time.time()),
        )
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO job_analysis_tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task.id,
                    user_id,
                    task.title,
                    task.source_text,
                    task.provider,
                    task.status,
                    task.model_dump_json(),
                    task.created_at,
                ),
            )
        task.trace.append(
            TraceStep(name="接收岗位材料", status="completed", detail="材料已保存到当前账户")
        )
        request = AgentRequest(
            task_id=task.id,
            user_id=user_id,
            goal=data.title,
            context={"source_text": data.source_text},
        )
        try:
            if task.provider == "deepseek":
                extraction, task.usage = await self.model.complete_json(
                    SYSTEM_PROMPT,
                    json.dumps(
                        {"title": data.title, "job_description": data.source_text},
                        ensure_ascii=False,
                    ),
                    lambda payload: validate_extraction(payload, data.source_text),
                )
            else:
                extraction = rule_extract(data.source_text)
            task.trace.append(
                TraceStep(
                    name="提取岗位要求",
                    status="completed",
                    detail="DeepSeek 分析" if task.provider == "deepseek" else "本地规则提取",
                )
            )
            task.requirements = locate(extraction, data.source_text)
            task.trace.append(
                TraceStep(
                    name="核对原文证据",
                    status="completed",
                    detail=f"{len(task.requirements)} 项引用均可在原文定位",
                )
            )
            task.result = agent_result(request, task.requirements)
            task.status = task.result.status
        except ModelFailure as exc:
            task.status, task.usage = "failed", exc.usage
            task.error = {"code": exc.code, "message": exc.message}
            task.trace.append(TraceStep(name="提取岗位要求", status="failed", detail=exc.message))
        except asyncio.CancelledError:
            task.status = "failed"
            task.error = {"code": "analysis_interrupted", "message": "分析被中断，请重新提交"}
            self.save(task)
            raise
        except Exception:
            task.status = "failed"
            task.error = {"code": "analysis_failed", "message": "分析未能完成，请稍后重试"}
            task.trace.append(
                TraceStep(name="提取岗位要求", status="failed", detail=task.error["message"])
            )
        task.trace.append(
            TraceStep(
                name="能力诊断 → 训练 → 面试",
                status="skipped",
                detail="本步骤只分析岗位，后续任务可在求职路线中继续",
            )
        )
        self.save(task)
        return task
