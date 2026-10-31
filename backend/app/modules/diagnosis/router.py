"""能力诊断 API：写操作复用 require_csrf，身份只来自登录会话，记录按 user_id 隔离。"""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.agents.diagnosis.schemas import (
    DiagnosisDetail,
    DiagnosisInput,
    DiagnosisResult,
    DiagnosisSummary,
)
from app.agents.diagnosis.service import (
    JobAnalysisNotFound,
    JobAnalysisNotReady,
)
from app.modules.auth.router import current_user, require_csrf
from app.modules.auth.schemas import UserOutput

router = APIRouter(prefix="/diagnoses", tags=["diagnosis"])


@router.get("/capabilities")
def capabilities(request: Request, user: UserOutput = Depends(current_user)):
    settings = request.app.state.settings
    return {
        "provider": settings.diagnosis_provider,
        "configured": settings.diagnosis_provider == "rules"
        or bool(settings.deepseek_api_key.get_secret_value()),
        "max_source_length": 20000,
    }


@router.post(
    "", response_model=DiagnosisDetail, status_code=201, dependencies=[Depends(require_csrf)]
)
async def create(
    data: DiagnosisInput, request: Request, user: UserOutput = Depends(current_user)
):
    request.app.state.diagnosis_rate_limiter.check(user.id)
    flow = request.app.state.diagnosis_workflow
    if not flow.slots.acquire(blocking=False):
        raise HTTPException(429, {"code": "diagnosis_busy", "message": "诊断任务较多，请稍后再试"})
    try:
        try:
            flow.job_requirements(user.id, data.job_analysis_id)
        except JobAnalysisNotFound as exc:
            raise HTTPException(
                404, {"code": "job_analysis_not_found", "message": "未找到该岗位分析记录"}
            ) from exc
        except JobAnalysisNotReady as exc:
            raise HTTPException(
                409,
                {"code": "job_analysis_not_ready", "message": "岗位分析尚未完成，请先完成岗位分析"},
            ) from exc
        resume = flow.create_resume(user.id, data.title, data.source_text)
        task = await flow.run(user.id, resume.id, data.job_analysis_id)
    finally:
        flow.slots.release()
    return DiagnosisDetail(
        id=task.id,
        resume_id=task.resume_id,
        job_analysis_id=task.job_analysis_id,
        status=task.status,
        result=task.result_payload,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.get("", response_model=list[DiagnosisSummary])
def history(request: Request, user: UserOutput = Depends(current_user)):
    with request.app.state.database.connect() as connection:
        rows = connection.execute(
            "SELECT d.id, d.resume_id, d.job_analysis_id, d.status, d.result_payload, "
            "d.created_at, r.title AS resume_title, j.title AS job_title "
            "FROM diagnosis_tasks d "
            "JOIN resumes r ON r.id = d.resume_id AND r.user_id = d.user_id "
            "JOIN job_analysis_tasks j ON j.id = d.job_analysis_id AND j.user_id = d.user_id "
            "WHERE d.user_id = ? ORDER BY d.created_at DESC, d.rowid DESC LIMIT 20",
            (user.id,),
        ).fetchall()
    summaries = []
    for row in rows:
        result = DiagnosisResult.model_validate_json(row["result_payload"])
        summaries.append(
            DiagnosisSummary(
                id=row["id"],
                resume_id=row["resume_id"],
                job_analysis_id=row["job_analysis_id"],
                status=row["status"],
                resume_title=row["resume_title"],
                job_title=row["job_title"],
                summary=result.summary,
                created_at=row["created_at"],
            )
        )
    return summaries


@router.get("/{diagnosis_id}", response_model=DiagnosisDetail)
def detail(diagnosis_id: str, request: Request, user: UserOutput = Depends(current_user)):
    with request.app.state.database.connect() as connection:
        row = connection.execute(
            "SELECT id, resume_id, job_analysis_id, status, result_payload, created_at, updated_at "
            "FROM diagnosis_tasks WHERE id = ? AND user_id = ?",
            (diagnosis_id, user.id),
        ).fetchone()
    if not row:
        raise HTTPException(404, {"code": "diagnosis_not_found", "message": "未找到该诊断记录"})
    return DiagnosisDetail(
        id=row["id"],
        resume_id=row["resume_id"],
        job_analysis_id=row["job_analysis_id"],
        status=row["status"],
        result=DiagnosisResult.model_validate_json(row["result_payload"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )