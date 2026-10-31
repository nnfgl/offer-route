import asyncio
import json
import sqlite3
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents.job.agent import locate, rule_extract
from app.agents.job.schemas import JobTask
from app.core.config import Settings
from app.core.database import MIGRATIONS
from app.core.model_client import DeepSeekClient, ModelFailure
from app.main import create_app

ORIGIN = {"Origin": "http://localhost:5173"}
SOURCE = (
    "😀 测试岗位\n任职要求：\n1. 熟悉 Python 和 SQL。\n2. 本科及以上学历。\n"
    "加分项：\n1. 有 Redis 实践经验优先。\n岗位职责：\n熟悉公司流程并负责项目开发。"
)
INPUT = {"title": "Python 后端", "source_text": SOURCE}
ACCOUNT = {
    "email": "jobs@example.com",
    "password": "a-long-unique-password",
    "display_name": "小林",
}


def register(client, email=ACCOUNT["email"]):
    response = client.post("/api/v1/auth/register", json={**ACCOUNT, "email": email})
    assert response.status_code == 201
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        _env_file=None, environment="test", database_path=tmp_path / "jobs.db", job_provider="rules"
    )
    with TestClient(create_app(settings), headers=ORIGIN) as client:
        register(client)
        yield client


def test_rules_keep_evidence_priorities_and_skip_responsibilities():
    extraction = rule_extract(SOURCE)
    assert len(extraction.requirements) == 3
    assert [item.priority for item in extraction.requirements] == [
        "required",
        "required",
        "preferred",
    ]
    for requirement in locate(extraction, SOURCE):
        assert SOURCE[requirement.source_start : requirement.source_end] == requirement.quote
        assert SOURCE[: requirement.source_start].count("\n") + 1 == requirement.source_line


def test_rules_do_not_invent_requirements_or_split_logic():
    source = (
        "任职要求：\n熟悉 Python 或 Java 至少一种，Redis 经验优先。\n学历不限。\n无需项目经验。"
    )
    items = rule_extract(source).requirements
    assert len(items) == 1
    assert "Python 或 Java" in items[0].quote
    assert items[0].priority == "unspecified"


def test_create_history_detail_and_agent_contract(client):
    response = client.post("/api/v1/jobs/analyses", json=INPUT)
    assert response.status_code == 201
    task = response.json()
    assert task["status"] == "completed" and task["provider"] == "rules"
    assert task["result"]["agent"] == "job"
    assert task["result"]["task_id"] == task["id"]
    assert task["trace"][-1]["status"] == "skipped"
    assert len(task["result"]["evidence"]) == len(task["requirements"])
    assert client.get(f"/api/v1/jobs/analyses/{task['id']}").json() == task
    history = client.get("/api/v1/jobs/analyses").json()
    assert history[0]["id"] == task["id"] and "source_text" not in history[0]
    assert task["usage"]["attempts"] == 0


def test_other_users_cannot_read_record(client):
    task_id = client.post("/api/v1/jobs/analyses", json=INPUT).json()["id"]
    register(client, "second@example.com")
    assert client.get(f"/api/v1/jobs/analyses/{task_id}").status_code == 404
    assert client.get("/api/v1/jobs/analyses").json() == []


def test_authentication_csrf_and_forged_owner(client):
    for path in ("/jobs/analyses", "/jobs/analyses/unknown", "/jobs/capabilities"):
        assert client.get("/api/v1" + path, headers={"Cookie": ""}).status_code == 401
    assert (
        client.post(
            "/api/v1/jobs/analyses", json=INPUT, headers={"X-CSRF-Token": "wrong"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/jobs/analyses", json=INPUT, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        client.post("/api/v1/jobs/analyses", json={**INPUT, "user_id": "another"}).status_code
        == 422
    )


@pytest.mark.parametrize("source", [" " * 30, "很短", "x" * 20001])
def test_invalid_input(client, source):
    assert (
        client.post("/api/v1/jobs/analyses", json={**INPUT, "source_text": source}).status_code
        == 422
    )
    assert client.get("/api/v1/jobs/analyses").json() == []


def test_missing_materials_have_needs_input_state(client):
    task = client.post(
        "/api/v1/jobs/analyses",
        json={**INPUT, "source_text": "欢迎加入我们的团队，一起创造美好的未来，携手共进。"},
    ).json()
    assert task["status"] == "needs_input"
    assert task["result"]["status"] == "needs_input"
    assert task["requirements"] == []


def test_concurrency_and_per_user_rate_limit(client):
    flow = client.app.state.job_workflow
    for _ in range(4):
        assert flow.slots.acquire(blocking=False)
    try:
        assert client.post("/api/v1/jobs/analyses", json=INPUT).status_code == 429
    finally:
        for _ in range(4):
            flow.slots.release()
    for _ in range(5):
        assert client.post("/api/v1/jobs/analyses", json=INPUT).status_code == 201
    assert client.post("/api/v1/jobs/analyses", json=INPUT).status_code == 429


def model_response(content, tokens=12):
    return httpx.Response(
        200,
        json={
            "choices": [{"finish_reason": "stop", "message": {"content": content}}],
            "usage": {"prompt_tokens": 25, "completion_tokens": tokens},
        },
    )


GOOD = {
    "requirements": [
        {
            "text": "熟悉 Python 和 SQL",
            "priority": "required",
            "category": "skill",
            "quote": "熟悉 Python 和 SQL",
        }
    ]
}


def test_deepseek_uses_shared_client_and_verifies_evidence(tmp_path):
    requests = []

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            invalid = {"requirements": [{**GOOD["requirements"][0], "quote": "虚构的要求"}]}
            return model_response(json.dumps(invalid))
        return model_response(json.dumps(GOOD))

    settings = Settings(
        _env_file=None,
        environment="test",
        database_path=tmp_path / "model.db",
        job_provider="deepseek",
        DEEPSEEK_API_KEY="a-test-secret",
    )
    app = create_app(settings)
    app.state.job_workflow.model = DeepSeekClient(settings, httpx.MockTransport(respond))
    with TestClient(app, headers=ORIGIN) as client:
        register(client)
        task = client.post("/api/v1/jobs/analyses", json=INPUT).json()
        assert task["status"] == "completed"
        assert task["usage"] == {"attempts": 2, "prompt_tokens": 50, "completion_tokens": 24}
        assert "a-test-secret" not in json.dumps(task)
        assert requests[0].headers["authorization"] == "Bearer a-test-secret"
        sent = json.loads(requests[0].content)
        assert sent["response_format"] == {"type": "json_object"}
        assert "source_text" not in client.get("/api/v1/jobs/analyses").text


@pytest.mark.parametrize(
    "response,expected,attempts",
    [
        (httpx.Response(401, text="private-provider-detail"), "model_access_denied", 1),
        (httpx.Response(429), "model_busy", 2),
        (httpx.Response(500), "model_busy", 2),
        (httpx.Response(400), "model_request_rejected", 1),
        (model_response(" "), "invalid_model_output", 2),
        (httpx.Response(200, json=[]), "invalid_model_output", 2),
    ],
)
def test_model_failures_are_bounded_and_persisted(tmp_path, response, expected, attempts):
    settings = Settings(
        _env_file=None,
        environment="test",
        database_path=tmp_path / "failure.db",
        job_provider="deepseek",
        DEEPSEEK_API_KEY="a-test-secret",
    )
    app = create_app(settings)
    app.state.job_workflow.model = DeepSeekClient(settings, httpx.MockTransport(lambda _: response))
    with TestClient(app, headers=ORIGIN) as client:
        register(client)
        task = client.post("/api/v1/jobs/analyses", json=INPUT).json()
        assert task["status"] == "failed"
        assert task["error"]["code"] == expected and task["usage"]["attempts"] == attempts
        assert "private-provider-detail" not in json.dumps(task)
        assert client.get(f"/api/v1/jobs/analyses/{task['id']}").json()["status"] == "failed"


def test_missing_key_is_explicit_and_no_secret_is_exposed(tmp_path):
    settings = Settings(
        _env_file=None,
        environment="test",
        database_path=tmp_path / "key.db",
        job_provider="deepseek",
        DEEPSEEK_API_KEY="",
    )
    with TestClient(create_app(settings), headers=ORIGIN) as client:
        register(client)
        assert client.get("/api/v1/jobs/capabilities").json()["configured"] is False
        task = client.post("/api/v1/jobs/analyses", json=INPUT).json()
        assert task["error"]["code"] == "model_not_configured"
        assert task["usage"]["attempts"] == 0


def test_budget_blocks_excess_calls():
    calls = []
    settings = Settings(_env_file=None, DEEPSEEK_API_KEY="test", model_output_budget=1800)
    model = DeepSeekClient(
        settings,
        httpx.MockTransport(
            lambda request: calls.append(request) or model_response("invalid json")
        ),
    )
    with pytest.raises(ModelFailure) as exc:
        asyncio.run(model.complete_json("json", "text", lambda payload: payload))
    assert exc.value.code == "model_budget_exceeded" and len(calls) == 1


def test_total_deadline_stops_slow_provider():
    async def slow(request):
        await asyncio.sleep(2)
        return model_response(json.dumps(GOOD))

    settings = Settings(_env_file=None, DEEPSEEK_API_KEY="test", model_timeout_seconds=1)
    model = DeepSeekClient(settings, httpx.MockTransport(slow))
    with pytest.raises(ModelFailure) as exc:
        asyncio.run(model.complete_json("json", "text", lambda payload: payload))
    assert exc.value.code == "model_timeout" and exc.value.usage.attempts == 1


def test_restart_recovers_interrupted_task_without_losing_history(tmp_path):
    settings = Settings(_env_file=None, environment="test", database_path=tmp_path / "restart.db")
    task_id = str(uuid4())
    with TestClient(create_app(settings), headers=ORIGIN) as client:
        register(client)
        user_id = client.get("/api/v1/auth/me").json()["user"]["id"]
        task = JobTask(
            id=task_id,
            title="测试岗位",
            source_text=SOURCE,
            provider="rules",
            status="running",
            created_at=1,
        )
        with client.app.state.database.connect() as connection:
            connection.execute(
                "INSERT INTO job_analysis_tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    user_id,
                    task.title,
                    task.source_text,
                    "rules",
                    "running",
                    task.model_dump_json(),
                    1,
                ),
            )
    with TestClient(create_app(settings), headers=ORIGIN) as client:
        response = client.post("/api/v1/auth/login", json=ACCOUNT)
        assert response.status_code == 200
        task = client.get(f"/api/v1/jobs/analyses/{task_id}").json()
        assert task["status"] == "failed" and task["error"]["code"] == "analysis_interrupted"


def test_migration_from_original_schema_preserves_accounts(tmp_path):
    path = tmp_path / "v1.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(MIGRATIONS[0])
        connection.execute("PRAGMA user_version = 1")
        connection.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
            ("existing", "old@example.com", "旧用户", "hash", 1),
        )
    settings = Settings(_env_file=None, environment="test", database_path=path)
    with TestClient(create_app(settings)) as client:
        with client.app.state.database.connect() as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
            assert connection.execute("SELECT id FROM users").fetchone()[0] == "existing"
            assert connection.execute("SELECT COUNT(*) FROM job_analysis_tasks").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM resumes").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM diagnosis_tasks").fetchone()[0] == 0
