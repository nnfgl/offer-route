"""Resume one persisted career route through the existing agent workflows."""

import json
import logging
import time
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.agents.job.schemas import JobInput
from app.agents.training.integration import diagnosis_gaps
from app.agents.training.schemas import CreateTask
from app.core.model_client import ModelUsage
from app.modules.auth.router import current_user, require_csrf
from app.modules.auth.schemas import UserOutput

router = APIRouter(prefix="/career-routes", tags=["career routes"])
STAGES = ("job", "diagnosis", "training")
MAX_RUNS = 2
logger = logging.getLogger(__name__)


class RouteInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    job: JobInput
    resume_title: str = Field(min_length=2, max_length=120)
    resume_text: str = Field(min_length=20, max_length=20000)


class AdvanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)


class PracticeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    skill: str = Field(min_length=1, max_length=100)
    answer: str = Field(min_length=10, max_length=5000)


def missing():
    return HTTPException(404, {"code": "not_found", "message": "记录不存在或不可访问"})


def conflict(code: str, message: str):
    return HTTPException(409, {"code": code, "message": message})


class CareerWorkflow:
    def __init__(self, database, job, diagnosis, training):
        self.database = database
        self.job = job
        self.diagnosis = diagnosis
        self.training = training

    @staticmethod
    def _route(db, route_id, user_id):
        row = db.execute(
            "SELECT * FROM career_routes WHERE id=? AND user_id=?", (route_id, user_id)
        ).fetchone()
        if row is None:
            raise missing()
        return row

    def create(self, user_id: str, data: RouteInput):
        route_id = str(data.request_id)
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM career_routes WHERE id=?", (route_id,)).fetchone()
            if existing:
                if existing["user_id"] != user_id:
                    raise missing()
                resume = db.execute(
                    "SELECT title, source_text FROM resumes WHERE id=? AND user_id=?",
                    (existing["resume_id"], user_id),
                ).fetchone()
                if (existing["title"], existing["job_source"], *resume) != (
                    data.job.title,
                    data.job.source_text,
                    data.resume_title,
                    data.resume_text,
                ):
                    raise conflict("route_request_conflict", "同一请求编号已用于另一份材料")
            else:
                resume = self.diagnosis.create_resume(
                    user_id, data.resume_title, data.resume_text, connection=db
                )
                db.execute(
                    "INSERT INTO career_routes VALUES (?,?,?,?,?,?)",
                    (
                        route_id,
                        user_id,
                        data.job.title,
                        data.job.source_text,
                        resume.id,
                        int(time.time()),
                    ),
                )
        return self.detail(route_id, user_id)

    def history(self, user_id: str):
        with self.database.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id,title,created_at FROM career_routes WHERE user_id=? "
                    "ORDER BY created_at DESC,rowid DESC LIMIT 50",
                    (user_id,),
                )
            ]

    @staticmethod
    def _artifacts(db, attempt, user_id):
        if attempt["stage"] == "job":
            row = db.execute(
                "SELECT status,payload FROM job_analysis_tasks WHERE id=? AND user_id=?",
                (attempt["id"], user_id),
            ).fetchone()
        elif attempt["stage"] == "diagnosis":
            row = db.execute(
                "SELECT status,result_payload AS payload FROM diagnosis_tasks "
                "WHERE id=? AND user_id=?",
                (attempt["id"], user_id),
            ).fetchone()
        else:
            row = db.execute(
                "SELECT status,task_payload AS payload FROM training_tasks "
                "WHERE id=? AND user_id=?",
                (attempt["id"], user_id),
            ).fetchone()
        return (row["status"], json.loads(row["payload"])) if row else (None, {})

    def _progress(self, db, route):
        attempts = [
            dict(row)
            for row in db.execute(
                "SELECT id,revision,stage,status,message FROM career_attempts WHERE route_id=? "
                "ORDER BY revision",
                (route["id"],),
            )
        ]
        latest = {attempt["stage"]: attempt for attempt in attempts}
        for stage in STAGES:
            attempt = latest.get(stage)
            if attempt and attempt["status"] in {"completed", "skipped"}:
                if stage != "training" or attempt["status"] == "skipped":
                    continue
                status, _ = self._artifacts(db, attempt, route["user_id"])
                if (
                    status != "archived"
                    or db.execute(
                        "SELECT 1 FROM training_submissions WHERE training_task_id=? AND user_id=? "
                        "AND status='passed'",
                        (attempt["id"], route["user_id"]),
                    ).fetchone()
                ):
                    continue
            can_run = (attempt is None or attempt["status"] in {"failed", "completed"}) and (
                sum(item["stage"] == stage for item in attempts) < MAX_RUNS
            )
            return attempts, latest, stage, can_run
        return attempts, latest, None, False

    def detail(self, route_id: str, user_id: str):
        with self.database.connect() as db:
            db.execute("BEGIN")
            route = self._route(db, route_id, user_id)
            attempts, latest, stage, can_run = self._progress(db, route)
            ids = {key: item["id"] for key, item in latest.items() if item["status"] == "completed"}
            payloads = {}
            usage = ModelUsage()
            for item in attempts:
                _, payload = self._artifacts(db, item, user_id)
                item["usage"] = ModelUsage.model_validate(payload.get("usage", {}))
                for key in ModelUsage.model_fields:
                    setattr(usage, key, getattr(usage, key) + getattr(item["usage"], key))
                if item["id"] == ids.get(item["stage"]):
                    payloads[item["stage"]] = payload
            training_status = None
            if "training" in ids:
                training_status, _ = self._artifacts(db, latest["training"], user_id)
            profile = self._profile(db, user_id, ids, payloads, usage)
            phase = stage or "interview"
            if stage is None and training_status in {"planned", "active"}:
                phase = "training"
            elif stage is None and profile["interview"]:
                phase = "completed"
            return {
                "id": route_id,
                "title": route["title"],
                "created_at": route["created_at"],
                "revision": len(attempts),
                "phase": phase,
                "next_stage": stage if can_run else None,
                "attempts": attempts,
                "job_id": ids.get("job"),
                "diagnosis_id": ids.get("diagnosis"),
                "training_id": ids.get("training"),
                "profile": profile,
            }

    def _profile(self, db, user_id, ids, payloads, usage):
        requirements = payloads.get("job", {}).get("requirements", [])
        diagnosis = payloads.get("diagnosis", {})
        verified = (
            self.training.repository.evidence(ids["diagnosis"], user_id, db)
            if "diagnosis" in ids
            else []
        )
        required = {item["id"] for item in requirements if item["priority"] == "required"}
        covered = required.intersection(item.requirement_id for item in verified)
        sessions = db.execute(
            "SELECT id,input_mode,report_payload FROM interview_sessions WHERE user_id=? "
            "AND job_analysis_id=? AND diagnosis_id=? ORDER BY updated_at DESC,rowid DESC",
            (user_id, ids.get("job"), ids.get("diagnosis")),
        )
        interview = None
        for row in sessions:
            payload = json.loads(row["report_payload"])
            voice_usage = payload.get("session_state", {}).get("report_usage", {})
            for key in ModelUsage.model_fields:
                setattr(usage, key, getattr(usage, key) + voice_usage.get(key, 0))
            if interview is None and payload.get("report"):
                interview = {"id": row["id"], "mode": row["input_mode"], **payload["report"]}
        practices = [
            dict(row)
            for row in db.execute(
                "SELECT p.session_id,p.skill,p.prompt,p.answer FROM interview_practice p "
                "JOIN interview_sessions s ON s.id=p.session_id AND s.user_id=p.user_id "
                "WHERE p.user_id=? AND s.job_analysis_id=? AND s.diagnosis_id=? "
                "ORDER BY s.created_at DESC,p.skill",
                (user_id, ids.get("job"), ids.get("diagnosis")),
            )
        ]
        return {
            "requirements": requirements,
            "diagnosis": diagnosis or None,
            "verified": verified,
            "required_count": len(required),
            "verified_required_count": len(covered),
            "interview": interview,
            "practices": practices,
            "usage": usage,
        }

    def _finish(self, db, attempt, user_id, *, skip=False, error=""):
        status, payload = self._artifacts(db, attempt, user_id)
        if skip:
            status, message = "skipped", "未发现当前题库支持的 SQL 缺口，可以继续面试。"
        elif (
            status == "completed"
            or attempt["stage"] == "training"
            and status in {"planned", "active", "archived"}
        ):
            status, message = (
                "completed",
                "已生成 SQL 练习" if attempt["stage"] == "training" else "已完成",
            )
        elif status == "needs_input":
            message = "材料不足以完成分析，请补充后新建路线。"
        else:
            status = "failed"
            message = (payload.get("error") or {}).get("message") or payload.get("summary")
            message = message or error or "步骤中断，请重试当前步骤。"
        db.execute(
            "UPDATE career_attempts SET status=?,message=? WHERE id=? AND status='running'",
            (status, message, attempt["id"]),
        )

    def recover_interrupted(self):
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT a.*,r.user_id FROM career_attempts a "
                "JOIN career_routes r ON r.id=a.route_id "
                "WHERE a.status='running'"
            ).fetchall()
            for attempt in rows:
                self._finish(db, attempt, attempt["user_id"])

    async def advance(self, route_id, user_id, revision):
        slot = None
        try:
            with self.database.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                route = self._route(db, route_id, user_id)
                attempts, latest, stage, can_run = self._progress(db, route)
                if revision != len(attempts) or not can_run:
                    raise conflict("route_changed", "路线已更新，请刷新进度后继续")
                semaphore = {"job": self.job.slots, "diagnosis": self.diagnosis.slots}.get(stage)
                if semaphore is not None:
                    if not semaphore.acquire(blocking=False):
                        raise HTTPException(
                            429, {"code": "agent_busy", "message": "分析服务繁忙，请稍后再试"}
                        )
                    slot = semaphore
                attempt = {"id": str(uuid4()), "stage": stage}
                db.execute(
                    "INSERT INTO career_attempts(id,route_id,revision,stage,status) "
                    "VALUES (?,?,?,?,'running')",
                    (attempt["id"], route_id, revision + 1, stage),
                )
            skip, error = False, ""
            try:
                if stage == "job":
                    await self.job.run(
                        user_id,
                        JobInput(title=route["title"], source_text=route["job_source"]),
                        task_id=attempt["id"],
                    )
                elif stage == "diagnosis":
                    await self.diagnosis.run(
                        user_id, route["resume_id"], latest["job"]["id"], task_id=attempt["id"]
                    )
                else:
                    diagnosis_id = latest["diagnosis"]["id"]
                    diagnosis = self.training.repository.diagnosis(diagnosis_id, user_id)
                    gaps = diagnosis_gaps(self.database, diagnosis, user_id)
                    gap = next(
                        (item for item in gaps if item.skill_id in {"sql", "sql.join_aggregation"}),
                        None,
                    )
                    skip = gap is None
                    if gap:
                        self.training.create(
                            CreateTask(
                                diagnosis_id=UUID(diagnosis_id), requirement_id=gap.requirement_id
                            ),
                            user_id,
                            task_id=attempt["id"],
                        )
            except HTTPException as exc:
                error = (
                    exc.detail.get("message", "步骤失败，请重试。")
                    if isinstance(exc.detail, dict)
                    else "步骤失败，请重试。"
                )
            except Exception as exc:
                logger.error(
                    "Career stage %s failed for attempt %s (%s)",
                    stage,
                    attempt["id"],
                    type(exc).__name__,
                )
            finally:
                with self.database.connect() as db:
                    self._finish(db, attempt, user_id, skip=skip, error=error)
        finally:
            if slot is not None:
                slot.release()
        return self.detail(route_id, user_id)

    def save_practice(self, route_id, session_id, user_id, data):
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            route = self._route(db, route_id, user_id)
            _, latest, _, _ = self._progress(db, route)
            job, diagnosis = latest.get("job"), latest.get("diagnosis")
            if (
                not job
                or not diagnosis
                or job["status"] != "completed"
                or diagnosis["status"] != "completed"
            ):
                raise missing()
            cursor = db.execute(
                "UPDATE interview_practice SET answer=? "
                "WHERE session_id=? AND user_id=? AND skill=? "
                "AND EXISTS (SELECT 1 FROM interview_sessions WHERE id=? AND user_id=? "
                "AND job_analysis_id=? AND diagnosis_id=?)",
                (
                    data.answer,
                    session_id,
                    user_id,
                    data.skill,
                    session_id,
                    user_id,
                    job["id"],
                    diagnosis["id"],
                ),
            )
            if not cursor.rowcount:
                raise missing()
        return self.detail(route_id, user_id)


@router.get("")
def history(request: Request, user: UserOutput = Depends(current_user)):
    return request.app.state.career.history(user.id)


@router.post("", status_code=201, dependencies=[Depends(require_csrf)])
def create(data: RouteInput, request: Request, user: UserOutput = Depends(current_user)):
    request.app.state.career_limiter.check(user.id)
    return request.app.state.career.create(user.id, data)


@router.get("/{route_id}")
def detail(route_id: UUID, request: Request, user: UserOutput = Depends(current_user)):
    return request.app.state.career.detail(str(route_id), user.id)


@router.post("/{route_id}/advance", dependencies=[Depends(require_csrf)])
async def advance(
    route_id: UUID, data: AdvanceInput, request: Request, user: UserOutput = Depends(current_user)
):
    request.app.state.career_limiter.check(user.id)
    return await request.app.state.career.advance(str(route_id), user.id, data.revision)


@router.post("/{route_id}/practices/{session_id}", dependencies=[Depends(require_csrf)])
def save_practice(
    route_id: UUID,
    session_id: UUID,
    data: PracticeInput,
    request: Request,
    user: UserOutput = Depends(current_user),
):
    return request.app.state.career.save_practice(str(route_id), str(session_id), user.id, data)
