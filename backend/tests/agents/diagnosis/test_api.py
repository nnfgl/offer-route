import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

ORIGIN = {"Origin": "http://localhost:5173"}
ACCOUNT = {"email": "diag@example.com", "password": "a-long-password", "display_name": "诊断"}
JOB_SOURCE = (
    "任职要求：\n1. 熟悉 Python，掌握 FastAPI。\n2. 掌握 SQL，具备数据库设计经验。\n"
    "加分项：\n1. 有 Redis 缓存实践经验优先。"
)
RESUME = (
    "张三：熟悉 Python 与 FastAPI，参与开源项目 offer-route（github.com/offer-route），"
    "优化 QPS 提升 30%。"
)
DIAG = {"title": "张三简历", "source_text": RESUME}


def register(client, email=ACCOUNT["email"]):
    response = client.post("/api/v1/auth/register", json={**ACCOUNT, "email": email})
    assert response.status_code == 201
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        _env_file=None,
        environment="test",
        database_path=tmp_path / "diag.db",
        job_provider="rules",
        diagnosis_provider="rules",
    )
    with TestClient(create_app(settings), headers=ORIGIN) as test_client:
        register(test_client)
        yield test_client


def make_analysis(client):
    response = client.post(
        "/api/v1/jobs/analyses", json={"title": "后端", "source_text": JOB_SOURCE}
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_diagnosis_flow_and_agent_contract(client):
    job_id = make_analysis(client)
    response = client.post("/api/v1/diagnoses", json={**DIAG, "job_analysis_id": job_id})
    assert response.status_code == 201
    task = response.json()
    assert task["status"] == "completed"
    assert task["result"]["schema_version"] == 1
    assert task["result"]["strengths"] and task["result"]["gaps"]
    assert client.get(f"/api/v1/diagnoses/{task['id']}").json() == task
    history = client.get("/api/v1/diagnoses").json()
    assert history[0]["id"] == task["id"]
    assert history[0]["resume_title"] == "张三简历" and history[0]["job_title"] == "后端"
    assert "password" not in json.dumps(task)


def test_authentication_csrf_and_forged_owner(client):
    for path in ("/diagnoses", "/diagnoses/unknown", "/diagnoses/capabilities"):
        assert client.get("/api/v1" + path, headers={"Cookie": ""}).status_code == 401
    job_id = make_analysis(client)
    body = {**DIAG, "job_analysis_id": job_id}
    assert (
        client.post("/api/v1/diagnoses", json=body, headers={"X-CSRF-Token": "wrong"}).status_code
        == 403
    )
    assert (
        client.post("/api/v1/diagnoses", json=body, headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert client.post("/api/v1/diagnoses", json={**body, "user_id": "other"}).status_code == 422
    assert client.post("/api/v1/diagnoses", json={**body, "source_text": "太短"}).status_code == 422
    assert client.post("/api/v1/diagnoses", json={**body, "title": "x"}).status_code == 422
    assert client.get("/api/v1/diagnoses").json() == []


def test_other_users_cannot_read_diagnosis(client):
    job_id = make_analysis(client)
    task_id = client.post(
        "/api/v1/diagnoses", json={**DIAG, "job_analysis_id": job_id}
    ).json()["id"]
    register(client, "second@example.com")
    assert client.get(f"/api/v1/diagnoses/{task_id}").status_code == 404
    assert client.get("/api/v1/diagnoses").json() == []


def test_cross_user_job_reference_is_rejected(client):
    job_id = make_analysis(client)
    register(client, "second@example.com")
    response = client.post("/api/v1/diagnoses", json={**DIAG, "job_analysis_id": job_id})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_analysis_not_found"


def test_diagnosis_busy_when_slots_exhausted(client):
    job_id = make_analysis(client)
    flow = client.app.state.diagnosis_workflow
    for _ in range(2):
        assert flow.slots.acquire(blocking=False)
    try:
        response = client.post("/api/v1/diagnoses", json={**DIAG, "job_analysis_id": job_id})
        assert response.status_code == 429
    finally:
        for _ in range(2):
            flow.slots.release()


def test_deepseek_missing_key_marks_failed(tmp_path):
    settings = Settings(
        _env_file=None,
        environment="test",
        database_path=tmp_path / "key.db",
        job_provider="rules",
        diagnosis_provider="deepseek",
        DEEPSEEK_API_KEY="",
    )
    with TestClient(create_app(settings), headers=ORIGIN) as client:
        register(client)
        assert client.get("/api/v1/diagnoses/capabilities").json()["configured"] is False
        job_id = make_analysis(client)
        task = client.post("/api/v1/diagnoses", json={**DIAG, "job_analysis_id": job_id}).json()
        assert task["status"] == "failed"
        assert "密钥" in task["result"]["summary"]


def test_restart_recovers_interrupted_diagnosis(tmp_path):
    settings = Settings(
        _env_file=None,
        environment="test",
        database_path=tmp_path / "restart.db",
        job_provider="rules",
        diagnosis_provider="rules",
    )
    with TestClient(create_app(settings), headers=ORIGIN) as client:
        register(client)
        user_id = client.get("/api/v1/auth/me").json()["user"]["id"]
        job_id = make_analysis(client)
        with client.app.state.database.connect() as connection:
            connection.execute(
                "INSERT INTO resumes (id, user_id, title, source_text, parsed_payload, created_at) "
                "VALUES ('r0', ?, '简历', ?, '{}', 1)",
                (user_id, RESUME),
            )
            connection.execute(
                "INSERT INTO diagnosis_tasks "
                "(id, user_id, job_analysis_id, resume_id, status, result_payload, created_at, "
                "updated_at) VALUES ('drun', ?, ?, 'r0', 'running', '{}', 1, 1)",
                (user_id, job_id),
            )
    with TestClient(create_app(settings), headers=ORIGIN) as client:
        assert client.post("/api/v1/auth/login", json=ACCOUNT).status_code == 200
        task = client.get("/api/v1/diagnoses/drun").json()
        assert task["status"] == "failed"
        assert task["result"]["summary"] == "服务重启导致诊断中断，请重新提交"