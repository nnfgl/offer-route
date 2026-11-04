"""Synthetic parents for C-only tests, never an implementation of A or B."""

import time
from uuid import uuid4

from app.agents.training.repository import encode
from app.agents.training.schemas import DiagnosisPayload, Gap


def seed_diagnosis(database, user_id: str) -> str:
    job_id, resume_id, diagnosis_id = (str(uuid4()) for _ in range(3))
    now = int(time.time())
    source = "模拟 Python 后端岗位要求：使用 SQL 多表查询、聚合及空值处理构建订单统计接口。"
    excerpt = "SQL 多表查询、聚合及空值处理"
    start = source.index(excerpt)
    payload = DiagnosisPayload(
        gaps=[
            Gap(
                requirement_id="req-sql-01",
                skill_id="sql.join_aggregation",
                description="验证 SQL 多表查询、聚合、订单状态筛选与空值处理能力。",
                source=f"job_analysis:{job_id}",
                excerpt=excerpt,
                start=start,
                end=start + len(excerpt),
            )
        ]
    )
    with database.connect() as connection:
        if connection.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone() is None:
            raise ValueError("The user must register first")
        connection.execute(
            "INSERT INTO job_analysis_tasks(id,user_id,title,source_text,provider,status,payload,"
            "created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                job_id,
                user_id,
                "模拟 Python 后端岗位",
                source,
                "synthetic-fixture",
                "completed",
                encode(
                    {
                        "schema_version": 1,
                        "synthetic": True,
                        "requirements": [
                            {
                                "id": "req-sql-01",
                                "source": source,
                                "excerpt": excerpt,
                                "start": start,
                                "end": start + len(excerpt),
                            }
                        ],
                    }
                ),
                now,
            ),
        )
        connection.execute(
            "INSERT INTO resumes(id,user_id,title,source_text,parsed_payload,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                resume_id,
                user_id,
                "模拟简历",
                "模拟候选人自述：做过 Python API，SQL 能力待验证。",
                encode({"schema_version": 1, "synthetic": True}),
                now,
            ),
        )
        connection.execute(
            "INSERT INTO diagnosis_tasks(id,user_id,job_analysis_id,resume_id,status,"
            "result_payload,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                diagnosis_id,
                user_id,
                job_id,
                resume_id,
                "completed",
                payload.model_dump_json(),
                now,
                now,
            ),
        )
    return diagnosis_id
