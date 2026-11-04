"""Opt in to A's shared schema after its migration is provisioned; retain legacy records.

No D-owned DDL or migration numbering here. IDs always include an owner predicate.
The public normalized columns are authoritative; transport state is versioned metadata.
"""

import json
import time
from uuid import uuid4

from fastapi import HTTPException

from app.agents.interview.schemas import InterviewOutput
from app.agents.interview.shared_schemas import ParentContext
from app.agents.interview.voice_schemas import VoiceInterview

MODELS = {"text": InterviewOutput, "voice": VoiceInterview}
LEGACY = {"text": "interviews", "voice": "voice_interviews"}


def has_table(connection, name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        is not None
    )


def ready(connection) -> bool:
    return all(
        has_table(connection, table)
        for table in (
            "job_analysis_tasks",
            "diagnosis_tasks",
            "interview_sessions",
            "interview_turns",
        )
    )


def error(status: int, code: str, message: str):
    raise HTTPException(status, {"code": code, "message": message})


def parent_context(
    connection, user_id: str, job_id: str | None, diagnosis_id: str | None
) -> ParentContext | None:
    if not job_id:
        return None
    if not ready(connection):
        error(503, "shared_schema_pending", "公共面试表尚未就绪，请由 A 合并统一迁移后再关联岗位")
    job = connection.execute(
        "SELECT title, status, payload FROM job_analysis_tasks WHERE id = ? AND user_id = ?",
        (job_id, user_id),
    ).fetchone()
    if not job:
        error(404, "job_not_found", "岗位分析记录不存在")
    if job["status"] != "completed":
        error(409, "job_not_completed", "请选择已完成的岗位分析")
    payload = json.loads(job["payload"])
    diagnosis = None
    if diagnosis_id:
        row = connection.execute(
            "SELECT job_analysis_id, status, result_payload FROM diagnosis_tasks "
            "WHERE id = ? AND user_id = ?",
            (diagnosis_id, user_id),
        ).fetchone()
        if not row:
            error(404, "diagnosis_not_found", "能力诊断记录不存在")
        if row["job_analysis_id"] != job_id:
            error(409, "diagnosis_job_mismatch", "该诊断不属于所选岗位")
        if row["status"] != "completed":
            error(409, "diagnosis_not_completed", "请选择已完成的能力诊断")
        diagnosis = json.loads(row["result_payload"])
    return ParentContext(
        job_title=job["title"], requirements=payload.get("requirements", []), diagnosis=diagnosis
    )


def choices(connection, user_id: str, job_id: str | None = None) -> dict:
    if not ready(connection):
        return {
            "shared_storage_ready": False,
            "requires_job_link": False,
            "jobs": [],
            "diagnoses": [],
        }
    jobs = [
        dict(row)
        for row in connection.execute(
            "SELECT id, title FROM job_analysis_tasks WHERE user_id = ? AND status = 'completed' "
            "ORDER BY created_at DESC LIMIT 50",
            (user_id,),
        )
    ]
    diagnoses = []
    if job_id:
        parent_context(connection, user_id, job_id, None)
        diagnoses = [
            dict(row)
            for row in connection.execute(
                "SELECT id, created_at FROM diagnosis_tasks "
                "WHERE user_id = ? AND job_analysis_id = ? "
                "AND status = 'completed' ORDER BY created_at DESC LIMIT 50",
                (user_id, job_id),
            )
        ]
    return {
        "shared_storage_ready": True,
        "requires_job_link": not all(has_table(connection, table) for table in LEGACY.values()),
        "jobs": jobs,
        "diagnoses": diagnoses,
    }


def _shared_row(connection, mode: str, record_id: str, user_id: str):
    if not has_table(connection, "interview_sessions"):
        return None
    return connection.execute(
        "SELECT * FROM interview_sessions WHERE id = ? AND user_id = ? AND input_mode = ?",
        (record_id, user_id, mode),
    ).fetchone()


def _decode(connection, row, mode: str):
    wrapper = json.loads(row["report_payload"])
    state = wrapper.get("session_state")
    if not isinstance(state, dict) or wrapper.get("schema_version") != 1:
        error(409, "unsupported_interview_schema", "该面试记录格式尚未支持，请先完成协议联调")
    state.update(
        job_analysis_id=row["job_analysis_id"],
        diagnosis_id=row["diagnosis_id"],
        report=wrapper.get("report"),
    )
    turns = connection.execute(
        "SELECT * FROM interview_turns WHERE session_id = ? AND user_id = ? ORDER BY round_no",
        (row["id"], row["user_id"]),
    ).fetchall()
    if mode == "text":
        state["turns"] = [
            {"question": turn["question_text"], "answer": turn["answer_text"]} for turn in turns
        ]
    else:
        state["messages"] = [
            message
            for turn in turns
            for message in json.loads(turn["feedback_payload"]).get("voice_messages", [])
        ]
        state["messages"].sort(key=lambda message: message["sequence"])
    return MODELS[mode].model_validate(state)


def find(connection, mode: str, record_id: str, user_id: str):
    row = _shared_row(connection, mode, record_id, user_id)
    if row:
        return _decode(connection, row, mode)
    if has_table(connection, LEGACY[mode]):
        # Table names are fixed module constants, never request data.
        row = connection.execute(
            f"SELECT payload FROM {LEGACY[mode]} WHERE id = ? AND user_id = ?",
            (record_id, user_id),
        ).fetchone()
        if row:
            return MODELS[mode].model_validate_json(row["payload"])
    error(404, "interview_not_found", "面试记录不存在")


def history(connection, mode: str, user_id: str):
    records = []
    if has_table(connection, "interview_sessions"):
        rows = connection.execute(
            "SELECT * FROM interview_sessions WHERE user_id = ? AND input_mode = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 50",
            (user_id, mode),
        ).fetchall()
        records.extend(_decode(connection, row, mode) for row in rows)
    if has_table(connection, LEGACY[mode]):
        rows = connection.execute(
            f"SELECT payload FROM {LEGACY[mode]} WHERE user_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 50",
            (user_id,),
        ).fetchall()
        records.extend(MODELS[mode].model_validate_json(row["payload"]) for row in rows)
    return sorted(records, key=lambda record: (record.created_at, record.id), reverse=True)[:50]


def _turns(record, mode: str):
    if mode == "text":
        return [
            {"question": turn.question, "answer": turn.answer, "messages": []}
            for turn in record.turns
        ]
    turns, current = [], None
    for message in record.messages:
        # A question plus consecutive answer fragments form one normalized round.
        if current is None or (message.role == "assistant" and current["has_user"]):
            current = {"question": "", "answer": None, "messages": [], "has_user": False}
            turns.append(current)
        current["messages"].append(message.model_dump())
        if message.role == "assistant":
            current["question"] += ("\n" if current["question"] else "") + message.text
        else:
            current["has_user"] = True
            if message.final:
                current["answer"] = (
                    (current["answer"] + "\n") if current["answer"] else ""
                ) + message.text
    for turn in turns:
        if not turn["question"]:
            turn["question"] = "候选人开场陈述（本轮尚无面试官问题）"
    return turns


def save(connection, mode: str, record, user_id: str, *, create: bool = False):
    shared = (
        bool(record.job_analysis_id)
        if create
        else bool(_shared_row(connection, mode, record.id, user_id))
    )
    if not shared:
        if not has_table(connection, LEGACY[mode]):
            error(409, "job_link_required", "统一数据库下请先选择已完成的岗位分析")
        if create:
            connection.execute(
                f"INSERT INTO {LEGACY[mode]}(id, user_id, created_at, payload) VALUES (?, ?, ?, ?)",
                (record.id, user_id, record.created_at, record.model_dump_json()),
            )
        else:
            connection.execute(
                f"UPDATE {LEGACY[mode]} SET payload = ? WHERE id = ? AND user_id = ?",
                (record.model_dump_json(), record.id, user_id),
            )
        return
    if not ready(connection):
        error(503, "shared_schema_pending", "公共面试表尚未就绪")
    normalized = _turns(record, mode)
    max_rounds = 3 if mode == "text" else 20
    if len(normalized) > max_rounds:
        error(409, "interview_round_limit", "已达到本场面试轮数上限，请结束并复盘已保存内容")
    state = record.model_dump(exclude={"turns", "messages", "report"})
    wrapper = json.dumps(
        {
            "schema_version": 1,
            "session_state": state,
            "report": record.report.model_dump() if record.report else None,
        },
        ensure_ascii=False,
    )
    status = (
        {"active": "active", "completed": "completed"}.get(record.status)
        if mode == "text"
        else {
            "created": "created",
            "connecting": "created",
            "live": "active",
            "ended": "completed",
        }[record.status]
    )
    now = max(record.created_at, int(time.time()))
    if create:
        connection.execute(
            "INSERT INTO interview_sessions(id, user_id, job_analysis_id, diagnosis_id, "
            "input_mode, status, max_rounds, report_payload, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                record.id,
                user_id,
                record.job_analysis_id,
                record.diagnosis_id,
                mode,
                status,
                max_rounds,
                wrapper,
                record.created_at,
                now,
            ),
        )
    else:
        connection.execute(
            "UPDATE interview_sessions SET status = ?, report_payload = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (status, wrapper, now, record.id, user_id),
        )
    existing = {
        row["round_no"]: row
        for row in connection.execute(
            "SELECT id, round_no FROM interview_turns WHERE session_id = ? AND user_id = ?",
            (record.id, user_id),
        )
    }
    for number, turn in enumerate(normalized, 1):
        payload = json.dumps(
            {
                "schema_version": 1,
                "voice_messages": turn["messages"],
                "answer_confirmation": "user_submitted" if mode == "text" else "asr_unconfirmed",
            },
            ensure_ascii=False,
        )
        turn_status = (
            "answered"
            if turn["answer"] is not None
            else ("skipped" if record.status in {"completed", "ended"} else "asked")
        )
        if number in existing:
            connection.execute(
                "UPDATE interview_turns SET question_text=?, answer_text=?, status=?, "
                "feedback_payload=?, updated_at=? WHERE id=? AND user_id=?",
                (
                    turn["question"],
                    turn["answer"],
                    turn_status,
                    payload,
                    now,
                    existing[number]["id"],
                    user_id,
                ),
            )
        else:
            connection.execute(
                "INSERT INTO interview_turns(id,user_id,session_id,round_no,"
                "question_text,answer_text,"
                "input_mode,status,audio_duration_ms,feedback_payload,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    user_id,
                    record.id,
                    number,
                    turn["question"],
                    turn["answer"],
                    mode,
                    turn_status,
                    None,
                    payload,
                    record.created_at,
                    now,
                ),
            )
