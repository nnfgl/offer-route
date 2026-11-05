import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from app.agents.contracts import AgentRequest
from app.agents.interview import shared_store
from app.agents.interview.schemas import AnswerInput, InterviewInput, InterviewOutput
from app.agents.interview.service import first_question, follow_up, review
from app.modules.auth.router import current_user, require_csrf
from app.modules.auth.schemas import UserOutput

router = APIRouter(prefix="/interviews", tags=["interview"])


def find(connection, interview_id: str, user_id: str) -> dict:
    return shared_store.find(connection, "text", interview_id, user_id).model_dump()


@router.get("", response_model=list[InterviewOutput])
def list_interviews(
    request: Request, diagnosis_id: str | None = None, user: UserOutput = Depends(current_user)
):
    with request.app.state.database.connect() as connection:
        return shared_store.history(connection, "text", user.id, diagnosis_id)


@router.get("/contexts")
def contexts(
    request: Request, job_analysis_id: str | None = None, user: UserOutput = Depends(current_user)
):
    with request.app.state.database.connect() as connection:
        return shared_store.choices(connection, user.id, job_analysis_id)


@router.post(
    "", response_model=InterviewOutput, status_code=201, dependencies=[Depends(require_csrf)]
)
def create_interview(
    data: InterviewInput, request: Request, user: UserOutput = Depends(current_user)
):
    with request.app.state.database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        context = shared_store.parent_context(
            connection, user.id, data.job_analysis_id, data.diagnosis_id
        )
        role = context.job_title if context else data.role
        interview = InterviewOutput(
            id=str(uuid4()),
            role=role,
            experience=data.experience,
            status="active",
            created_at=int(time.time()),
            job_analysis_id=data.job_analysis_id,
            diagnosis_id=data.diagnosis_id,
            parent_context=context,
            turns=[{"question": first_question(role, data.experience)}],
        )
        shared_store.save(connection, "text", interview, user.id, create=True)
    return interview


@router.get("/{interview_id}", response_model=InterviewOutput)
def get_interview(interview_id: str, request: Request, user: UserOutput = Depends(current_user)):
    with request.app.state.database.connect() as connection:
        return find(connection, interview_id, user.id)


@router.post(
    "/{interview_id}/answers", response_model=InterviewOutput, dependencies=[Depends(require_csrf)]
)
def answer_interview(
    interview_id: str, data: AnswerInput, request: Request, user: UserOutput = Depends(current_user)
):
    with request.app.state.database.connect() as connection:
        # Serialize read/modify/write so retries and concurrent submissions cannot skip turns.
        connection.execute("BEGIN IMMEDIATE")
        interview = find(connection, interview_id, user.id)
        if interview["status"] != "active" or data.round != len(interview["turns"]):
            raise HTTPException(
                409,
                {"code": "interview_conflict", "message": "面试进度已变化，请重新打开记录后继续"},
            )
        interview["turns"][-1]["answer"] = data.answer
        if data.round < 3:
            interview["turns"].append(
                {"question": follow_up(data.answer, data.round + 1), "answer": None}
            )
        else:
            interview["status"] = "completed"
            interview["report"] = review(
                AgentRequest(
                    task_id=interview_id,
                    user_id=user.id,
                    goal=interview["role"],
                    context={"turns": interview["turns"]},
                )
            ).model_dump()
        shared_store.save(connection, "text", InterviewOutput.model_validate(interview), user.id)
    return interview
