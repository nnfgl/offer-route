import json
from contextlib import contextmanager

from fastapi import HTTPException

from app.agents.training.schemas import SubmissionOutput, TaskOutput


def missing():
    return HTTPException(404, {"code": "not_found", "message": "记录不存在或不可访问"})


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def task_output(row) -> TaskOutput:
    data = dict(row)
    data.pop("user_id", None)
    data["task_payload"] = json.loads(data["task_payload"])
    return TaskOutput.model_validate(data)


def submission_output(row) -> SubmissionOutput:
    data = dict(row)
    data.pop("user_id", None)
    data["evaluation_payload"] = json.loads(data["evaluation_payload"])
    return SubmissionOutput.model_validate(data)


class TrainingRepository:
    def __init__(self, database):
        self.database = database

    def diagnosis(self, diagnosis_id: str, user_id: str, connection=None):
        if connection is None:
            with self.database.connect() as connection:
                return self.diagnosis(diagnosis_id, user_id, connection)
        row = connection.execute(
            "SELECT * FROM diagnosis_tasks WHERE id=? AND user_id=?", (diagnosis_id, user_id)
        ).fetchone()
        if row is None:
            raise missing()
        return dict(row)

    def verified_gap(self, diagnosis: dict, user_id: str, gap):
        sources = {
            f"job_analysis:{diagnosis['job_analysis_id']}": (
                "job_analysis_tasks",
                diagnosis["job_analysis_id"],
            ),
            f"resume:{diagnosis['resume_id']}": ("resumes", diagnosis["resume_id"]),
        }
        if gap.source not in sources:
            raise HTTPException(
                422,
                {
                    "code": "invalid_evidence_source",
                    "message": "薄弱点依据未关联该诊断的岗位或简历",
                },
            )
        table, record_id = sources[gap.source]
        with self.database.connect() as connection:
            # The table name comes only from the fixed mapping above, never browser input.
            row = connection.execute(
                f"SELECT source_text FROM {table} WHERE id=? AND user_id=?", (record_id, user_id)
            ).fetchone()
        if row is None or gap.excerpt not in row["source_text"]:
            raise HTTPException(
                422,
                {
                    "code": "evidence_not_verbatim",
                    "message": "薄弱点引用无法在原文中逐字定位",
                },
            )
        text = row["source_text"]
        if gap.start is not None or gap.end is not None:
            if gap.start is None or gap.end is None or text[gap.start : gap.end] != gap.excerpt:
                raise HTTPException(
                    422,
                    {
                        "code": "evidence_position_mismatch",
                        "message": "薄弱点引用位置与原文不一致",
                    },
                )
            return gap
        start = text.index(gap.excerpt)
        return gap.model_copy(update={"start": start, "end": start + len(gap.excerpt)})

    def task(self, task_id: str, user_id: str, connection=None, *, lock=False):
        if connection is None:
            with self.database.connect() as connection:
                return self.task(task_id, user_id, connection)
        suffix = " FOR UPDATE" if lock and self.database.dialect == "mysql" else ""
        row = connection.execute(
            "SELECT * FROM training_tasks WHERE id=? AND user_id=?" + suffix, (task_id, user_id)
        ).fetchone()
        if row is None:
            raise missing()
        return task_output(row)

    def insert_task(self, task: TaskOutput, user_id: str):
        with self.database.connect() as connection:
            # Recheck the parent in the write transaction. Composite FK enforces the owner too.
            self.diagnosis(task.diagnosis_id, user_id, connection)
            connection.execute(
                "INSERT INTO training_tasks(id,user_id,diagnosis_id,title,goal,status,"
                "task_payload,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    task.id,
                    user_id,
                    task.diagnosis_id,
                    task.title,
                    task.goal,
                    task.status,
                    encode(task.task_payload.model_dump()),
                    task.created_at,
                    task.updated_at,
                ),
            )

    def tasks(self, user_id: str, limit: int, offset: int):
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM training_tasks WHERE user_id=? "
                "ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset),
            ).fetchall()
            return [task_output(row) for row in rows]

    @contextmanager
    def locked_task(self, task_id: str, user_id: str):
        with self.database.connect() as connection:
            if self.database.dialect == "sqlite":
                connection.execute("BEGIN IMMEDIATE")
            yield connection, self.task(task_id, user_id, connection, lock=True)

    def submissions(self, task_id: str, user_id: str, connection=None):
        if connection is None:
            with self.database.connect() as connection:
                self.task(task_id, user_id, connection)
                return self.submissions(task_id, user_id, connection)
        return [
            submission_output(row)
            for row in connection.execute(
                "SELECT * FROM training_submissions WHERE training_task_id=? AND user_id=? "
                "ORDER BY attempt_no",
                (task_id, user_id),
            ).fetchall()
        ]

    def submission(self, submission_id: str, user_id: str):
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM training_submissions WHERE id=? AND user_id=?",
                (submission_id, user_id),
            ).fetchone()
            if row is None:
                raise missing()
            return submission_output(row)

    def evidence(self, diagnosis_id: str, user_id: str):
        with self.database.connect() as connection:
            self.diagnosis(diagnosis_id, user_id, connection)
            rows = connection.execute(
                "SELECT s.* FROM training_submissions s JOIN training_tasks t "
                "ON s.training_task_id=t.id AND s.user_id=t.user_id "
                "WHERE t.diagnosis_id=? AND t.user_id=? AND s.user_id=? AND s.status='passed' "
                "ORDER BY s.created_at,s.id",
                (diagnosis_id, user_id, user_id),
            ).fetchall()
            return [
                evidence
                for row in rows
                for evidence in submission_output(row).evaluation_payload.evidence
            ]
