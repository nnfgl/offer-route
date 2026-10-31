import asyncio
import time
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.agents.interview import voice_provider
from app.agents.interview.voice_schemas import (
    VoiceConnectInput,
    VoiceEndInput,
    VoiceInput,
    VoiceInterview,
    VoiceMessagesInput,
)
from app.modules.auth.router import current_user, require_csrf
from app.modules.auth.schemas import UserOutput

router = APIRouter(prefix="/voice-interviews", tags=["voice-interview"])


def fail(status: int, code: str, message: str):
    raise HTTPException(status, {"code": code, "message": message})


def find(connection, interview_id: str, user_id: str) -> VoiceInterview:
    row = connection.execute(
        "SELECT payload FROM voice_interviews WHERE id = ? AND user_id = ?",
        (interview_id, user_id),
    ).fetchone()
    if not row:
        fail(404, "voice_not_found", "语音面试记录不存在")
    return VoiceInterview.model_validate_json(row["payload"])


def save(connection, interview: VoiceInterview, user_id: str):
    connection.execute(
        "UPDATE voice_interviews SET payload = ? WHERE id = ? AND user_id = ?",
        (interview.model_dump_json(), interview.id, user_id),
    )


def require_config(request: Request):
    if not voice_provider.configured(request.app.state.settings):
        fail(503, "voice_not_configured", "语音服务尚未配置，请配置后端语音 API Key 和业务空间地址")


def limit_voice(request: Request, user: UserOutput = Depends(current_user)):
    request.app.state.voice_limiter.check(user.id)


@router.get("/config")
def config(request: Request, user: UserOutput = Depends(current_user)):
    settings = request.app.state.settings
    return {
        "configured": voice_provider.configured(settings),
        "max_minutes": settings.voice_max_minutes,
        "provider": "阿里云百炼",
    }


@router.get("", response_model=list[VoiceInterview])
def list_interviews(request: Request, user: UserOutput = Depends(current_user)):
    with request.app.state.database.connect() as connection:
        rows = connection.execute(
            "SELECT payload FROM voice_interviews WHERE user_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 50",
            (user.id,),
        ).fetchall()
    return [VoiceInterview.model_validate_json(row["payload"]) for row in rows]


@router.get("/{interview_id}", response_model=VoiceInterview)
def get_interview(interview_id: str, request: Request, user: UserOutput = Depends(current_user)):
    with request.app.state.database.connect() as connection:
        return find(connection, interview_id, user.id)


@router.post(
    "",
    status_code=201,
    response_model=VoiceInterview,
    dependencies=[Depends(require_csrf), Depends(limit_voice)],
)
def create_interview(data: VoiceInput, request: Request, user: UserOutput = Depends(current_user)):
    require_config(request)
    interview = VoiceInterview(
        id=str(uuid4()), role=data.role, experience=data.experience, created_at=int(time.time())
    )
    with request.app.state.database.connect() as connection:
        connection.execute(
            "INSERT INTO voice_interviews(id, user_id, created_at, payload) VALUES (?, ?, ?, ?)",
            (interview.id, user.id, interview.created_at, interview.model_dump_json()),
        )
    return interview


@router.post("/{interview_id}/connect", dependencies=[Depends(require_csrf), Depends(limit_voice)])
async def connect(
    interview_id: str,
    data: VoiceConnectInput,
    request: Request,
    user: UserOutput = Depends(current_user),
):
    require_config(request)
    if not data.offer_sdp.startswith("v=0") or "m=audio" not in data.offer_sdp:
        fail(422, "invalid_sdp", "语音连接参数无效")
    database, settings = request.app.state.database, request.app.state.settings
    attempt = str(uuid4())
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        interview = find(connection, interview_id, user.id)
        if interview.status != "created" and not (
            interview.status == "connecting"
            and int(time.time()) - (interview.connected_at or 0) > 30
        ):
            fail(409, "voice_connection_conflict", "该面试已连接或结束，请查看记录或新建一场面试")
        interview.status = "connecting"
        interview.connected_at = int(time.time())
        interview.connection_attempt = attempt
        save(connection, interview, user.id)
    try:
        answer = await voice_provider.exchange_sdp(settings, data.offer_sdp)
    except (Exception, asyncio.CancelledError) as exc:
        with database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            record = find(connection, interview_id, user.id)
            if record.connection_attempt == attempt and record.status == "connecting":
                record.status = "created"
                save(connection, record, user.id)
        if isinstance(exc, asyncio.CancelledError):
            raise
        # Do not return upstream bodies: they can contain credential or billing details.
        fail(
            502, "voice_connection_failed", "语音连接失败，请检查后端服务地址、密钥、模型权限及网络"
        )
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        interview = find(connection, interview_id, user.id)
        if interview.connection_attempt != attempt or interview.status != "connecting":
            fail(409, "voice_connection_conflict", "连接状态已变化，请重新加载记录")
        interview.status = "live"
        save(connection, interview, user.id)
    return {"answer_sdp": answer, "session": voice_provider.session_config(settings, interview)}


@router.post(
    "/{interview_id}/messages", response_model=VoiceInterview, dependencies=[Depends(require_csrf)]
)
def persist_messages(
    interview_id: str,
    data: VoiceMessagesInput,
    request: Request,
    user: UserOutput = Depends(current_user),
):
    with request.app.state.database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        interview = find(connection, interview_id, user.id)
        if interview.status != "live":
            fail(409, "voice_not_live", "当前面试无法继续写入转写")
        messages = {message.id: message for message in interview.messages}
        if len({message.id for message in data.messages}) != len(data.messages):
            fail(422, "duplicate_message", "转写消息 ID 不可重复")
        for message in data.messages:
            previous = messages.get(message.id)
            if previous and (
                previous.role != message.role
                or previous.sequence != message.sequence
                or previous.final
                and (not message.final or previous.text != message.text)
            ):
                fail(409, "transcript_conflict", "已保存的完整转写不能被覆盖")
            messages[message.id] = message
        interview.messages = sorted(messages.values(), key=lambda message: message.sequence)
        if len(messages) > 200 or sum(len(message.text) for message in messages.values()) > 100000:
            fail(422, "transcript_limit", "对话记录已达到本场上限，请结束面试")
        save(connection, interview, user.id)
    return interview


async def review_job(database, settings, interview_id: str, user_id: str, attempt: str):
    with database.connect() as connection:
        interview = find(connection, interview_id, user_id)
    report, error = None, None
    try:
        report = await asyncio.wait_for(voice_provider.generate_review(settings, interview), 70)
    except Exception:
        error = "复盘生成失败，已保存面试转写。请检查模型配置或重试。"
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        interview = find(connection, interview_id, user_id)
        if interview.report_attempt != attempt:
            return
        interview.report = report
        interview.report_error = error
        interview.report_status = "failed" if error else "completed"
        save(connection, interview, user_id)


def enqueue(interview: VoiceInterview, request: Request, user_id: str, tasks: BackgroundTasks):
    interview.report_status = "processing"
    interview.report_error = None
    interview.report_started_at = int(time.time())
    interview.report_attempt = str(uuid4())
    tasks.add_task(
        review_job,
        request.app.state.database,
        request.app.state.settings,
        interview.id,
        user_id,
        interview.report_attempt,
    )


@router.post(
    "/{interview_id}/end", response_model=VoiceInterview, dependencies=[Depends(require_csrf)]
)
def end_interview(
    interview_id: str,
    data: VoiceEndInput,
    request: Request,
    tasks: BackgroundTasks,
    user: UserOutput = Depends(current_user),
):
    with request.app.state.database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        interview = find(connection, interview_id, user.id)
        if data.message_count != len(interview.messages):
            fail(409, "transcript_not_saved", "转写尚未全部保存，请重试结束面试")
        if interview.status == "ended":
            return interview  # Safe retry after losing the HTTP response.
        if (
            interview.status == "connecting"
            and int(time.time()) - (interview.connected_at or 0) < 30
        ):
            fail(409, "voice_connecting", "语音正在连接，请稍后结束")
        if (
            any(message.role == "user" and not message.final for message in interview.messages)
            and not data.accept_incomplete
        ):
            fail(409, "transcript_incomplete", "部分转写尚未完成，请确认使用已保存内容结束")
        interview.status = "ended"
        interview.ended_at = int(time.time())
        interview.incomplete = data.accept_incomplete
        if any(message.role == "user" and message.final for message in interview.messages):
            enqueue(interview, request, user.id, tasks)
        else:
            interview.report_status = "failed"
            interview.report_error = "没有完整的候选人回答，无法生成有依据的复盘。"
        save(connection, interview, user.id)
    return interview


@router.post(
    "/{interview_id}/report",
    status_code=202,
    response_model=VoiceInterview,
    dependencies=[Depends(require_csrf), Depends(limit_voice)],
)
def retry_report(
    interview_id: str,
    request: Request,
    tasks: BackgroundTasks,
    user: UserOutput = Depends(current_user),
):
    require_config(request)
    with request.app.state.database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        interview = find(connection, interview_id, user.id)
        if interview.status != "ended":
            fail(409, "voice_not_ended", "结束面试后才可以生成复盘")
        if not any(message.role == "user" and message.final for message in interview.messages):
            fail(409, "no_complete_answer", "没有完整的候选人回答，无法生成复盘")
        if interview.report_status == "completed" or (
            interview.report_status == "processing"
            and int(time.time()) - (interview.report_started_at or 0) < 90
        ):
            return interview
        enqueue(interview, request, user.id, tasks)
        save(connection, interview, user.id)
    return interview
