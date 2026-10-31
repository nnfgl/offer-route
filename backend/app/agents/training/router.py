from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.agents.training.schemas import (
    CreateTask,
    ProfileOutput,
    SubmissionOutput,
    SubmitAnswer,
    TaskOutput,
)
from app.modules.auth.router import current_user, require_csrf
from app.modules.auth.schemas import UserOutput

router = APIRouter(prefix="/training", tags=["training-local"])


@router.post(
    "/tasks", response_model=TaskOutput, status_code=201, dependencies=[Depends(require_csrf)]
)
def create_task(data: CreateTask, request: Request, user: UserOutput = Depends(current_user)):
    return request.app.state.training.create(data, user.id)


@router.get("/tasks", response_model=list[TaskOutput])
def list_tasks(
    request: Request,
    user: UserOutput = Depends(current_user),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return request.app.state.training.repository.tasks(user.id, limit, offset)


@router.get("/tasks/{task_id}", response_model=TaskOutput)
def get_task(task_id: UUID, request: Request, user: UserOutput = Depends(current_user)):
    return request.app.state.training.repository.task(str(task_id), user.id)


@router.post(
    "/tasks/{task_id}/archive", response_model=TaskOutput, dependencies=[Depends(require_csrf)]
)
def archive_task(task_id: UUID, request: Request, user: UserOutput = Depends(current_user)):
    return request.app.state.training.archive(str(task_id), user.id)


@router.post(
    "/tasks/{task_id}/submissions",
    response_model=SubmissionOutput,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
def submit(
    task_id: UUID,
    data: SubmitAnswer,
    request: Request,
    response: Response,
    user: UserOutput = Depends(current_user),
):
    result = request.app.state.training.submit(str(task_id), data, user.id)
    if result.status == "pending":
        response.status_code = 202
    return result


@router.get("/tasks/{task_id}/submissions", response_model=list[SubmissionOutput])
def list_submissions(task_id: UUID, request: Request, user: UserOutput = Depends(current_user)):
    return request.app.state.training.repository.submissions(str(task_id), user.id)


@router.get("/submissions/{submission_id}", response_model=SubmissionOutput)
def get_submission(submission_id: UUID, request: Request, user: UserOutput = Depends(current_user)):
    return request.app.state.training.repository.submission(str(submission_id), user.id)


@router.get("/diagnoses/{diagnosis_id}/evidence", response_model=ProfileOutput)
def get_evidence(diagnosis_id: UUID, request: Request, user: UserOutput = Depends(current_user)):
    return request.app.state.training.evidence(str(diagnosis_id), user.id)


@router.get("/materials")
def materials(
    request: Request,
    query: str = Query(min_length=1, max_length=500),
    user: UserOutput = Depends(current_user),
):
    return {
        "schema_version": 1,
        "synthetic": True,
        "items": request.app.state.training.materials(query),
    }
