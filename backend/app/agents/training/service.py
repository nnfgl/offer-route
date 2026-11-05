import hashlib
import json
import time
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.agents.training.exercises import PROMPT, TABLES, TITLE
from app.agents.training.integration import diagnosis_gaps
from app.agents.training.repository import TrainingRepository, encode
from app.agents.training.runner import CheckResult
from app.agents.training.schemas import (
    CreateTask,
    EvaluationPayload,
    EvidenceRecord,
    ProfileOutput,
    SubmissionOutput,
    SubmitAnswer,
    TaskOutput,
    TaskPayload,
)


def conflict(code: str, message: str):
    return HTTPException(409, {"code": code, "message": message})


class TrainingService:
    def __init__(self, database, runner, knowledge):
        self.repository = TrainingRepository(database)
        self.runner = runner
        self.knowledge = knowledge

    def materials(self, query: str):
        try:
            return self.knowledge.search(query)
        except Exception as exc:
            raise HTTPException(
                503,
                {
                    "code": "knowledge_unavailable",
                    "message": "本地训练资料暂不可用",
                },
            ) from exc

    def create(self, data: CreateTask, user_id: str, *, task_id: str | None = None) -> TaskOutput:
        diagnosis = self.repository.diagnosis(str(data.diagnosis_id), user_id)
        if diagnosis["status"] != "completed":
            raise conflict("diagnosis_not_completed", "请先完成能力诊断")
        try:
            gaps = diagnosis_gaps(self.repository.database, diagnosis, user_id)
        except (ValidationError, ValueError) as exc:
            raise HTTPException(
                422,
                {
                    "code": "diagnosis_contract_mismatch",
                    "message": "诊断结果不符合训练输入约定，请按对接文档适配 gaps 结构",
                },
            ) from exc
        gap = next((item for item in gaps if item.requirement_id == data.requirement_id), None)
        if gap is None:
            raise HTTPException(422, {"code": "gap_not_found", "message": "未找到对应待训练项"})
        if gap.skill_id not in {"sql", "sql.join_aggregation"}:
            raise HTTPException(
                422,
                {
                    "code": "unsupported_skill",
                    "message": "首期仅支持 SQL 查询与聚合训练",
                },
            )
        gap = self.repository.verified_gap(diagnosis, user_id, gap)
        try:
            materials = self.knowledge.search("SQL LEFT JOIN GROUP BY COUNT SUM 空值 订单统计")
        except Exception as exc:
            raise HTTPException(
                503,
                {
                    "code": "knowledge_unavailable",
                    "message": "本地训练资料未就绪，请先初始化 Chroma",
                },
            ) from exc
        now = int(time.time())
        task = TaskOutput(
            id=task_id or str(uuid4()),
            diagnosis_id=diagnosis["id"],
            title=TITLE,
            goal=gap.description,
            status="planned",
            created_at=now,
            updated_at=now,
            task_payload=TaskPayload(
                skill_id=gap.skill_id,
                requirement_id=gap.requirement_id,
                prompt=PROMPT,
                tables=TABLES,
                diagnosis_evidence=gap,
                materials=materials,
            ),
        )
        self.repository.insert_task(task, user_id)
        return task

    def submit(self, task_id: str, data: SubmitAnswer, user_id: str) -> SubmissionOutput:
        digest = hashlib.sha256(data.answer_text.encode()).hexdigest()
        request_id = str(data.request_id)
        with self.repository.locked_task(task_id, user_id) as (connection, task):
            submissions = self.repository.submissions(task_id, user_id, connection)
            for previous in submissions:
                if previous.evaluation_payload.request_id == request_id:
                    if previous.evaluation_payload.answer_sha256 != digest:
                        raise conflict("idempotency_conflict", "同一请求编号不能提交不同答案")
                    return previous
            if task.status in {"completed", "archived"}:
                raise conflict("task_closed", "任务已完成或归档，请创建新的训练任务")
            if any(item.status == "pending" for item in submissions):
                raise conflict("submission_in_progress", "本题正在校验，请查询已有提交结果")
            if len(submissions) >= 20:
                raise conflict("attempt_limit", "本任务已达到 20 次提交上限，请重新安排训练")
            now = int(time.time())
            submission = SubmissionOutput(
                id=str(uuid4()),
                training_task_id=task_id,
                attempt_no=len(submissions) + 1,
                answer_text=data.answer_text,
                status="pending",
                created_at=now,
                evaluation_payload=EvaluationPayload(
                    request_id=request_id,
                    answer_sha256=digest,
                    code="pending",
                    feedback="答案已接收，正在进行确定性校验。",
                ),
            )
            connection.execute(
                "INSERT INTO training_submissions(id,user_id,training_task_id,attempt_no,"
                "answer_text,status,evaluation_payload,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    submission.id,
                    user_id,
                    task_id,
                    submission.attempt_no,
                    data.answer_text,
                    "pending",
                    encode(submission.evaluation_payload.model_dump()),
                    now,
                ),
            )
            connection.execute(
                "UPDATE training_tasks SET status='active',updated_at=? WHERE id=? AND user_id=?",
                (max(now, task.created_at), task_id, user_id),
            )
        # The transaction is committed before any expensive/external validation.
        try:
            checked = self.runner.check(data.answer_text)
        except Exception:
            checked = CheckResult("error", "runner_error", "校验服务失败，本次不作能力判断。")
        evaluation = submission.evaluation_payload.model_copy(
            update={
                "code": checked.code,
                "feedback": checked.feedback,
                "checked_cases": checked.checked_cases,
                "passed_cases": checked.passed_cases,
                "duration_ms": checked.duration_ms,
            }
        )
        if checked.status == "passed":
            evaluation.evidence = [
                EvidenceRecord(
                    source=f"training_submission:{submission.id}",
                    excerpt=checked.feedback,
                    training_task_id=task_id,
                    submission_id=submission.id,
                    diagnosis_id=task.diagnosis_id,
                    skill_id=task.task_payload.skill_id,
                    requirement_id=task.task_payload.requirement_id,
                    answer_sha256=digest,
                    created_at=int(time.time()),
                )
            ]
        with self.repository.locked_task(task_id, user_id) as (connection, current):
            connection.execute(
                "UPDATE training_submissions SET status=?,evaluation_payload=? "
                "WHERE id=? AND user_id=? AND status='pending'",
                (checked.status, encode(evaluation.model_dump()), submission.id, user_id),
            )
            connection.execute(
                "UPDATE training_tasks SET status=?,updated_at=? WHERE id=? AND user_id=?",
                (
                    "completed" if checked.status == "passed" else "active",
                    max(int(time.time()), current.updated_at),
                    task_id,
                    user_id,
                ),
            )
        return self.repository.submission(submission.id, user_id)

    def archive(self, task_id: str, user_id: str) -> TaskOutput:
        with self.repository.locked_task(task_id, user_id) as (connection, task):
            if any(
                item.status == "pending"
                for item in self.repository.submissions(task_id, user_id, connection)
            ):
                raise conflict("submission_in_progress", "校验进行中，暂不能归档")
            connection.execute(
                "UPDATE training_tasks SET status='archived',updated_at=? WHERE id=? AND user_id=?",
                (max(int(time.time()), task.updated_at), task_id, user_id),
            )
        return self.repository.task(task_id, user_id)

    def evidence(self, diagnosis_id: str, user_id: str) -> ProfileOutput:
        return ProfileOutput(
            diagnosis_id=diagnosis_id,
            evidence=self.repository.evidence(diagnosis_id, user_id),
        )

    def recover_interrupted(self) -> int:
        """Single-process local entry point only; do not use with multiple API workers."""
        with self.repository.database.connect() as connection:
            rows = connection.execute(
                "SELECT id,user_id,evaluation_payload FROM training_submissions "
                "WHERE status='pending'"
            ).fetchall()
            for row in rows:
                payload = json.loads(row["evaluation_payload"])
                payload.update(
                    code="execution_interrupted", feedback="校验被服务重启中断，请新建提交。"
                )
                connection.execute(
                    "UPDATE training_submissions SET status='error',evaluation_payload=? "
                    "WHERE id=? AND user_id=? AND status='pending'",
                    (encode(payload), row["id"], row["user_id"]),
                )
        return len(rows)
