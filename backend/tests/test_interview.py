from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import MIGRATIONS, Database
from app.main import create_app
from app.modules.auth.security import password_hasher

ORIGIN = {"Origin": "http://localhost:5173"}
INPUT = {
    "role": "Python 后端工程师",
    "experience": "开发一个校园图书借阅系统，负责后端接口和数据库。",
}
ACCOUNT = {
    "email": "interview@example.com",
    "password": "correct-horse-battery",
    "display_name": "面试同学",
}


@pytest.fixture
def client(tmp_path):
    settings = Settings(environment="test", database_path=tmp_path / "test.db", auth_rate_limit=100)
    with TestClient(create_app(settings), headers=ORIGIN) as client:
        session = client.post("/api/v1/auth/register", json=ACCOUNT).json()
        client.headers["X-CSRF-Token"] = session["csrf_token"]
        yield client


def start(client):
    response = client.post("/api/v1/interviews", json=INPUT)
    assert response.status_code == 201
    return response.json()


def test_three_round_interview_report_and_history(client):
    interview = start(client)
    path = f"/api/v1/interviews/{interview['id']}"
    assert interview["status"] == "active"
    assert INPUT["experience"] in interview["turns"][0]["question"]
    answers = [
        "我实现图书借阅接口，使用 FastAPI 和 SQLite。",
        "我对比过同步和异步方案，先考虑团队经验。",
        "暂时还没有补充内容。",
    ]
    for round_number, answer in enumerate(answers, 1):
        response = client.post(path + "/answers", json={"round": round_number, "answer": answer})
        assert response.status_code == 200
        interview = response.json()
        assert interview["turns"][round_number - 1]["answer"] == answer
        if round_number < 3:
            assert answer in interview["turns"][-1]["question"]
            assert interview["report"] is None
    assert interview["status"] == "completed"
    report = interview["report"]
    assert report["agent"] == "interview" and report["task_id"] == interview["id"]
    assert report["data"]["score"] == 2
    assert report["data"]["max_score"] == 4
    assert {item["skill"] for item in report["data"]["training_items"]} == {"结果验证", "反思改进"}
    for item in report["data"]["training_items"]:
        assert item["source_task_id"] == interview["id"] and item["status"] == "pending"
    for evidence in report["evidence"]:
        index = int(evidence["source"].rsplit(":", 1)[1]) - 1
        assert evidence["excerpt"] in answers[index]
    assert client.get(path).json() == interview
    assert client.get("/api/v1/interviews").json() == [interview]
    assert client.get(path).headers["cache-control"] == "no-store"
    assert client.post(path + "/answers", json={"round": 3, "answer": "重发"}).status_code == 409
    assert client.get(path).json() == interview


def test_unverified_answers_produce_training_items_without_fake_evidence(client):
    interview = start(client)
    path = f"/api/v1/interviews/{interview['id']}/answers"
    for number in range(1, 4):
        response = client.post(path, json={"round": number, "answer": "暂时不清楚"})
    report = response.json()["report"]
    assert report["data"]["score"] == 0
    assert len(report["data"]["training_items"]) == 4
    assert report["evidence"] == []


def test_stale_and_concurrent_answers_cannot_skip_rounds(client):
    interview = start(client)
    path = f"/api/v1/interviews/{interview['id']}"
    assert client.post(path + "/answers", json={"round": 2, "answer": "跳过"}).status_code == 409
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda _: client.post(path + "/answers", json={"round": 1, "answer": "同一轮回答"}),
                range(2),
            )
        )
    assert sorted(response.status_code for response in responses) == [200, 409]
    stored = client.get(path).json()
    assert len(stored["turns"]) == 2
    assert stored["turns"][1]["answer"] is None


def test_user_cannot_read_or_write_another_users_interview(client):
    interview = start(client)
    path = f"/api/v1/interviews/{interview['id']}"
    with TestClient(client.app, headers=ORIGIN) as other:
        session = other.post(
            "/api/v1/auth/register", json={**ACCOUNT, "email": "other@example.com"}
        )
        other.headers["X-CSRF-Token"] = session.json()["csrf_token"]
        assert other.get("/api/v1/interviews").json() == []
        assert other.get(path).status_code == 404
        assert other.post(path + "/answers", json={"round": 1, "answer": "越权"}).status_code == 404
        assert (
            other.post("/api/v1/interviews", json={**INPUT, "user_id": "forged"}).status_code == 422
        )
    assert client.get(path).json() == interview
    assert client.get("/api/v1/interviews/not-found").status_code == 404


def test_all_interview_endpoints_require_login(client):
    interview = start(client)
    client.cookies.clear()
    path = f"/api/v1/interviews/{interview['id']}"
    assert client.get("/api/v1/interviews").status_code == 401
    assert client.get(path).status_code == 401
    assert client.post("/api/v1/interviews", json=INPUT).status_code == 401
    assert client.post(path + "/answers", json={"round": 1, "answer": "未登录"}).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {"X-CSRF-Token": "wrong"},
        {"Origin": "https://evil.example"},
        {"Origin": ""},
        {"X-CSRF-Token": ""},
    ],
)
def test_both_mutations_require_csrf_and_origin(client, headers):
    interview = start(client)
    assert client.post("/api/v1/interviews", json=INPUT, headers=headers).status_code == 403
    assert (
        client.post(
            f"/api/v1/interviews/{interview['id']}/answers",
            json={"round": 1, "answer": "回答"},
            headers=headers,
        ).status_code
        == 403
    )
    assert client.get(f"/api/v1/interviews/{interview['id']}").json() == interview


@pytest.mark.parametrize(
    "changes",
    [
        {"role": "   "},
        {"role": "x" * 101},
        {"experience": "短"},
        {"experience": " " * 10},
        {"experience": "x" * 5001},
        {"user_id": "forged"},
    ],
)
def test_invalid_interview_input(client, changes):
    assert client.post("/api/v1/interviews", json={**INPUT, **changes}).status_code == 422
    assert client.get("/api/v1/interviews").json() == []


@pytest.mark.parametrize(
    "changes",
    [
        {"round": 0},
        {"round": 4},
        {"answer": "   "},
        {"answer": "x" * 5001},
        {"user_id": "forged"},
    ],
)
def test_invalid_answer_does_not_change_progress(client, changes):
    interview = start(client)
    path = f"/api/v1/interviews/{interview['id']}"
    response = client.post(path + "/answers", json={"round": 1, "answer": "回答", **changes})
    assert response.status_code == 422
    assert client.get(path).json() == interview


def test_migration_preserves_accounts_and_restart_restores_interviews(tmp_path):
    settings = Settings(environment="test", database_path=tmp_path / "persistent.db")
    database = Database(settings.database_path)
    with database.connect() as connection:
        connection.executescript(MIGRATIONS[0] + "PRAGMA user_version = 1;")
        connection.execute(
            "INSERT INTO users(id, email, display_name, password_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "existing-user",
                ACCOUNT["email"],
                ACCOUNT["display_name"],
                password_hasher.hash(ACCOUNT["password"]),
                1,
            ),
        )
    with TestClient(create_app(settings), headers=ORIGIN) as first:
        response = first.post("/api/v1/auth/login", json=ACCOUNT)
        assert response.status_code == 200
        session = response.json()
        assert session["user"]["id"] == "existing-user"
        first.headers["X-CSRF-Token"] = session["csrf_token"]
        interview = start(first)
        path = f"/api/v1/interviews/{interview['id']}"
        first.post(path + "/answers", json={"round": 1, "answer": "我负责后端"})
    with TestClient(create_app(settings), headers=ORIGIN) as second:
        assert second.post("/api/v1/auth/login", json=ACCOUNT).status_code == 200
        restored = second.get(path).json()
        assert len(restored["turns"]) == 2
        assert restored["turns"][0]["answer"] == "我负责后端"
