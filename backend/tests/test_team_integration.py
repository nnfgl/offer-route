"""Real shared-app flow and regression coverage for cross-branch integration."""

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agents.training.exercises import REFERENCE_SQL
from app.core.config import Settings
from app.core.database import MIGRATIONS, Database
from app.main import create_app

ORIGIN = {"Origin": "http://127.0.0.1:5173"}


def register(client, email="integration@example.com"):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "integration-password-2026",
            "display_name": "联调同学",
        },
    )
    assert response.status_code == 201, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()


def test_shared_app_job_diagnosis_sql_interview_and_restart(tmp_path):
    settings = Settings(
        _env_file=None,
        environment="test",
        database_path=tmp_path / "shared.db",
        auth_rate_limit=100,
    )
    with TestClient(create_app(settings), headers=ORIGIN) as client:
        owner = register(client)
        assert all(
            item["status"] == "available"
            for item in client.get("/api/v1/workspace").json()["modules"]
        )
        response = client.post(
            "/api/v1/jobs/analyses",
            json={
                "title": "Python 后端",
                "source_text": "岗位要求：\n熟悉 Python 开发\n熟悉 SQL 数据库查询与聚合",
            },
        )
        assert response.status_code == 201, response.text
        job = response.json()
        response = client.post(
            "/api/v1/diagnoses",
            json={
                "job_analysis_id": job["id"],
                "title": "模拟简历",
                "source_text": "在校园项目中负责 Python 接口实现，编写单元测试并维护文档。",
            },
        )
        assert response.status_code == 201, response.text
        diagnosis = response.json()
        assert diagnosis["status"] == "completed", diagnosis
        gaps = client.get(f"/api/v1/training/diagnoses/{diagnosis['id']}/gaps").json()["gaps"]
        gap = next(item for item in gaps if item["skill_id"] == "sql.join_aggregation")
        response = client.post(
            "/api/v1/training/tasks",
            json={
                "diagnosis_id": diagnosis["id"],
                "requirement_id": gap["requirement_id"],
            },
        )
        assert response.status_code == 201, response.text
        task = response.json()
        assert task["task_payload"]["diagnosis_evidence"]["excerpt"] in job["source_text"]
        submit_path = f"/api/v1/training/tasks/{task['id']}/submissions"
        assert (
            client.post(
                submit_path, json={"request_id": str(uuid4()), "answer_text": "SELECT 1"}
            ).json()["status"]
            == "failed"
        )
        request_id = str(uuid4())
        response = client.post(
            submit_path, json={"request_id": request_id, "answer_text": REFERENCE_SQL}
        )
        assert response.status_code == 201 and response.json()["status"] == "passed", response.text
        assert (
            client.post(
                submit_path, json={"request_id": request_id, "answer_text": REFERENCE_SQL}
            ).json()["id"]
            == response.json()["id"]
        )
        evidence = client.get(f"/api/v1/training/diagnoses/{diagnosis['id']}/evidence").json()[
            "evidence"
        ]
        assert len(evidence) == 1 and evidence[0]["verification"] == "task_verified"
        response = client.post(
            "/api/v1/interviews",
            json={
                "role": "用户输入岗位",
                "experience": "在校园项目中负责 Python 接口实现，并编写单元测试。",
                "job_analysis_id": job["id"],
                "diagnosis_id": diagnosis["id"],
            },
        )
        assert response.status_code == 201, response.text
        interview = response.json()
        assert interview["parent_context"]["diagnosis"] == diagnosis["result"]
        path = f"/api/v1/interviews/{interview['id']}"
        for round_no in range(1, 4):
            response = client.post(
                path + "/answers",
                json={
                    "round": round_no,
                    "answer": "我实现接口并编写测试，对比方案，记录结果和局限。",
                },
            )
            assert response.status_code == 200, response.text
        assert response.json()["status"] == "completed" and response.json()["report"]["evidence"]
        with client.app.state.database.connect() as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM interview_turns WHERE session_id=?", (interview["id"],)
                ).fetchone()[0]
                == 3
            )
            assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        # A second normal account cannot consume somebody else's B/C/D records.
        register(client, "other@example.com")
        assert client.get(f"/api/v1/training/diagnoses/{diagnosis['id']}/gaps").status_code == 404
        assert client.get(f"/api/v1/training/tasks/{task['id']}").status_code == 404
        assert client.get(path).status_code == 404
    with TestClient(create_app(settings), headers=ORIGIN) as client:
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"email": owner["user"]["email"], "password": "integration-password-2026"},
            ).status_code
            == 200
        )
        assert client.get(path).json()["status"] == "completed"
        assert client.get(f"/api/v1/training/tasks/{task['id']}").json()["status"] == "completed"
        assert len(client.get(submit_path).json()) == 2


@pytest.mark.parametrize(
    "layout", ["auth-v1", "job-v2", "diagnosis-v3", "interview-v2", "voice-v3"]
)
def test_upgrade_known_branch_databases_preserves_records(tmp_path, layout):
    database = Database(tmp_path / "old.db")
    with database.connect() as connection:
        connection.executescript(MIGRATIONS[0])
        connection.execute("INSERT INTO users VALUES ('owner','old@example.com','旧用户','hash',1)")
        connection.commit()
        if layout in {"job-v2", "diagnosis-v3"}:
            connection.executescript(MIGRATIONS[1])
            connection.execute(
                "INSERT INTO job_analysis_tasks VALUES "
                "('job','owner','岗位','原文','rules','completed','{}',1)"
            )
            connection.commit()
        if layout == "diagnosis-v3":
            connection.executescript(MIGRATIONS[2])
            connection.execute("INSERT INTO resumes VALUES ('resume','owner','简历','原文','{}',1)")
            connection.execute(
                "INSERT INTO diagnosis_tasks VALUES "
                "('diag','owner','job','resume','completed','{}',1,1)"
            )
        if layout in {"interview-v2", "voice-v3"}:
            connection.execute(
                "CREATE TABLE interviews(id TEXT PRIMARY KEY,user_id TEXT,"
                "created_at INTEGER,payload TEXT)"
            )
            connection.execute(
                "INSERT INTO interviews VALUES ('interview','owner',1,'{\"keep\":true}')"
            )
        if layout == "voice-v3":
            connection.execute(
                "CREATE TABLE voice_interviews(id TEXT PRIMARY KEY,user_id TEXT,"
                "created_at INTEGER,payload TEXT)"
            )
            connection.execute(
                "INSERT INTO voice_interviews VALUES ('voice','owner',1,'{\"keep\":true}')"
            )
        version = 3 if layout.endswith("v3") else 2 if layout.endswith("v2") else 1
        connection.execute(f"PRAGMA user_version = {version}")
    database.migrate()
    database.migrate()
    with database.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
        assert connection.execute("SELECT id FROM users").fetchone()[0] == "owner"
        if layout in {"job-v2", "diagnosis-v3"}:
            assert connection.execute("SELECT id FROM job_analysis_tasks").fetchone()[0] == "job"
        if layout == "diagnosis-v3":
            assert connection.execute("SELECT id FROM diagnosis_tasks").fetchone()[0] == "diag"
        if layout in {"interview-v2", "voice-v3"}:
            assert json.loads(connection.execute("SELECT payload FROM interviews").fetchone()[0])[
                "keep"
            ]
        if layout == "voice-v3":
            assert json.loads(
                connection.execute("SELECT payload FROM voice_interviews").fetchone()[0]
            )["keep"]
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
