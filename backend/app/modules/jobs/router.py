from fastapi import APIRouter, Depends, HTTPException, Request

from app.agents.job.schemas import JobInput, JobTask, TaskSummary
from app.modules.auth.router import current_user, require_csrf
from app.modules.auth.schemas import UserOutput

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/capabilities")
def capabilities(request: Request, user: UserOutput = Depends(current_user)):
    settings = request.app.state.settings
    return {
        "provider": settings.job_provider,
        "configured": settings.job_provider == "rules"
        or bool(settings.deepseek_api_key.get_secret_value()),
        "max_source_length": 20000,
    }


@router.post(
    "/analyses", response_model=JobTask, status_code=201, dependencies=[Depends(require_csrf)]
)
async def analyze(data: JobInput, request: Request, user: UserOutput = Depends(current_user)):
    request.app.state.job_rate_limiter.check(user.id)
    flow = request.app.state.job_workflow
    if not flow.slots.acquire(blocking=False):
        raise HTTPException(429, {"code": "analysis_busy", "message": "分析任务较多，请稍后再试"})
    try:
        return await flow.run(user.id, data)
    finally:
        flow.slots.release()


@router.get("/analyses", response_model=list[TaskSummary])
def history(request: Request, user: UserOutput = Depends(current_user)):
    with request.app.state.database.connect() as connection:
        rows = connection.execute(
            "SELECT id, title, provider, status, created_at FROM job_analysis_tasks "
            "WHERE user_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 20",
            (user.id,),
        ).fetchall()
    return [dict(row) for row in rows]


@router.get("/analyses/{task_id}", response_model=JobTask)
def detail(task_id: str, request: Request, user: UserOutput = Depends(current_user)):
    with request.app.state.database.connect() as connection:
        row = connection.execute(
            "SELECT payload FROM job_analysis_tasks WHERE id = ? AND user_id = ?",
            (task_id, user.id),
        ).fetchone()
    if not row:
        raise HTTPException(404, {"code": "analysis_not_found", "message": "未找到该分析记录"})
    return JobTask.model_validate_json(row["payload"])
