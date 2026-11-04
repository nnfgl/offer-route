"""Opt-in tests against the isolated local MySQL schema and real Chroma store."""

import os
import secrets
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.agents.training.application import create_training_app
from app.agents.training.demo import seed_diagnosis
from app.agents.training.exercises import REFERENCE_SQL
from app.agents.training.runner import CheckResult
from app.agents.training.schemas import SubmitAnswer
from app.agents.training.settings import TrainingSettings

pytestmark = pytest.mark.skipif(
    os.environ.get("OFFER_RUN_MYSQL_TESTS") != "1", reason="Explicit local MySQL opt-in required"
)
ORIGIN = "http://127.0.0.1:5173"


def register(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"mysql-c-{uuid4().hex}@example.com",
            "password": secrets.token_urlsafe(24),
            "display_name": "MySQL 模拟测试",
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def live():
    app = create_training_app(TrainingSettings(database_backend="mysql"))
    with TestClient(app, headers={"Origin": ORIGIN}) as client:
        session = register(client)
        diagnosis_id = seed_diagnosis(app.state.database, session["user"]["id"])
        response = client.post(
            "/api/v1/training/tasks",
            json={
                "diagnosis_id": diagnosis_id,
                "requirement_id": "req-sql-01",
            },
            headers={"X-CSRF-Token": session["csrf_token"]},
        )
        assert response.status_code == 201
        yield client, app, session, diagnosis_id, response.json()


def test_mysql_chroma_correct_wrong_and_evidence(live):
    client, app, session, diagnosis_id, task = live
    headers = {"X-CSRF-Token": session["csrf_token"]}
    endpoint = f"/api/v1/training/tasks/{task['id']}/submissions"
    materials = task["task_payload"]["materials"]
    assert materials and all(item["source"].startswith("synthetic:") for item in materials)
    assert "SQL 多表查询" in materials[0]["excerpt"]
    wrong = client.post(
        endpoint,
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "answer_text": "SELECT 1",
        },
    )
    assert wrong.status_code == 201 and wrong.json()["status"] == "failed"
    request_id = str(uuid4())
    answer = {"request_id": request_id, "answer_text": REFERENCE_SQL}
    correct = client.post(endpoint, headers=headers, json=answer)
    assert correct.status_code == 201 and correct.json()["status"] == "passed"
    repeated = client.post(endpoint, headers=headers, json=answer)
    assert repeated.json()["id"] == correct.json()["id"]
    evidence = client.get(f"/api/v1/training/diagnoses/{diagnosis_id}/evidence").json()["evidence"]
    assert len(evidence) == 1 and evidence[0]["submission_id"] == correct.json()["id"]
    assert client.get(f"/api/v1/training/tasks/{task['id']}").json()["status"] == "completed"
    assert app.state.training.knowledge.status()["documents"] == 6


def test_mysql_cross_user_and_csrf(live):
    client, _, session, diagnosis_id, task = live
    endpoint = f"/api/v1/training/tasks/{task['id']}/submissions"
    assert (
        client.post(
            endpoint, json={"request_id": str(uuid4()), "answer_text": "SELECT 1"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            endpoint,
            json={"request_id": str(uuid4()), "answer_text": "SELECT 1"},
            headers={"X-CSRF-Token": session["csrf_token"], "Origin": "https://untrusted.example"},
        ).status_code
        == 403
    )
    client.cookies.clear()
    other = register(client)
    headers = {"X-CSRF-Token": other["csrf_token"]}
    assert client.get(f"/api/v1/training/tasks/{task['id']}").status_code == 404
    assert client.get(f"/api/v1/training/diagnoses/{diagnosis_id}/evidence").status_code == 404
    assert (
        client.post(
            endpoint,
            headers=headers,
            json={"request_id": str(uuid4()), "answer_text": REFERENCE_SQL},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/training/tasks",
            headers=headers,
            json={"diagnosis_id": diagnosis_id, "requirement_id": "req-sql-01"},
        ).status_code
        == 404
    )


def test_mysql_schema_constraints_and_migration_preserve_records(live):
    client, app, session, _, task = live
    database = app.state.database
    with database.connect() as connection:
        before = connection.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    database.migrate_local()
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == before
        row = connection.execute(
            "SELECT id FROM users WHERE id=?", (session["user"]["id"],)
        ).fetchone()
        assert row["id"] == session["user"]["id"]
    client.cookies.clear()
    other = register(client)
    # Both users exist: only the composite task/owner FK can reject this link.
    with pytest.raises(sqlite3.IntegrityError), database.connect() as connection:
        connection.execute(
            "INSERT INTO training_submissions(id,user_id,training_task_id,attempt_no,answer_text,"
            "status,evaluation_payload,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (str(uuid4()), other["user"]["id"], task["id"], 1, "SELECT 1", "pending", "{}", 0),
        )
    import pymysql

    with pytest.raises(pymysql.err.OperationalError), database.connect() as connection:
        connection.execute(
            "INSERT INTO resumes(id,user_id,title,source_text,parsed_payload,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (str(uuid4()), other["user"]["id"], "invalid-json-test", "synthetic", "bad json", 0),
        )


def test_mysql_concurrent_retries_and_attempt_numbers(live):
    _, app, session, _, task = live
    service = app.state.training
    entered, release = threading.Event(), threading.Event()

    class WaitingRunner:
        def check(self, sql):
            entered.set()
            assert release.wait(timeout=8)
            return CheckResult("failed", "answer_mismatch", "模拟并发校验未通过")

    service.runner = WaitingRunner()
    user_id = session["user"]["id"]
    data = SubmitAnswer(request_id=uuid4(), answer_text="SELECT 1")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.submit, task["id"], data, user_id)
        try:
            assert entered.wait(timeout=8)
            pending = service.submit(task["id"], data, user_id)
            assert pending.status == "pending"
            with pytest.raises(HTTPException) as error:
                service.submit(
                    task["id"], SubmitAnswer(request_id=uuid4(), answer_text="SELECT 2"), user_id
                )
            assert error.value.status_code == 409
        finally:
            release.set()
        assert future.result(timeout=8).id == pending.id
    second = service.submit(
        task["id"], SubmitAnswer(request_id=uuid4(), answer_text="SELECT 2"), user_id
    )
    assert second.attempt_no == 2
    assert len(service.repository.submissions(task["id"], user_id)) == 2


def test_mysql_runner_error_creates_no_evidence(live):
    client, app, session, diagnosis_id, task = live

    class TimeoutRunner:
        def check(self, sql):
            return CheckResult("error", "execution_timeout", "本次校验超时，不作能力判断。")

    app.state.training.runner = TimeoutRunner()
    response = client.post(
        f"/api/v1/training/tasks/{task['id']}/submissions",
        json={
            "request_id": str(uuid4()),
            "answer_text": REFERENCE_SQL,
        },
        headers={"X-CSRF-Token": session["csrf_token"]},
    )
    assert response.status_code == 201 and response.json()["status"] == "error"
    assert (
        client.get(f"/api/v1/training/diagnoses/{diagnosis_id}/evidence").json()["evidence"] == []
    )
