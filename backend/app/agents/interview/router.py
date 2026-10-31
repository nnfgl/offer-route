import json
import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from app.agents.contracts import AgentRequest
from app.agents.interview.schemas import AnswerInput, InterviewInput, InterviewOutput
from app.agents.interview.service import first_question, follow_up, review
from app.modules.auth.router import current_user, require_csrf
from app.modules.auth.schemas import UserOutput

router = APIRouter(prefix="/interviews", tags=["interview"])


def find(connection, interview_id: str, user_id: str) -> dict:
    row = connection.execute(
        "SELECT payload FROM interviews WHERE id = ? AND user_id = ?",
        (interview_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, {"code": "interview_not_found", "message": "面试记录不存在"})
    return json.loads(row["payload"])


@router.get("", response_model=list[InterviewOutput])
def list_interviews(request: Request, user: UserOutput = Depends(current_user)):
    with request.app.state.database.connect() as connection:
        rows = connection.execute(
            "SELECT payload FROM interviews WHERE user_id = ? ORDER BY created_at DESC, id DESC "
            "LIMIT 50",
            (user.id,),
        ).fetchall()
    return [json.loads(row["payload"]) for row in rows]


@router.post(
    "", response_model=InterviewOutput, status_code=201, dependencies=[Depends(require_csrf)]
)
def create_interview(
    data: InterviewInput, request: Request, user: UserOutput = Depends(current_user)
):
    interview = InterviewOutput(
        id=str(uuid4()),
        role=data.role,
        experience=data.experience,
        status="active",
        created_at=int(time.time()),
        turns=[{"question": first_question(data.role, data.experience)}],
    )
    with request.app.state.database.connect() as connection:
        connection.execute(
            "INSERT INTO interviews(id, user_id, created_at, payload) VALUES (?, ?, ?, ?)",
            (interview.id, user.id, interview.created_at, interview.model_dump_json()),
        )
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
        connection.execute(
            "UPDATE interviews SET payload = ? WHERE id = ? AND user_id = ?",
            (json.dumps(interview, ensure_ascii=False), interview_id, user.id),
        )
    return interview
