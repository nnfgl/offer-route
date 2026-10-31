import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.agents.contracts import AgentKind, AgentResult
from app.agents.interview import voice_provider
from app.core.config import Settings
from app.core.database import MIGRATIONS, Database
from app.main import create_app

ORIGIN = {"Origin": "http://localhost:5173"}
ACCOUNT = {
    "email": "shared@example.com",
    "password": "a-long-unique-password",
    "display_name": "联调同学",
}
JOBS_DDL = """
CREATE TABLE job_analysis_tasks (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 title TEXT NOT NULL, source_text TEXT NOT NULL, provider TEXT NOT NULL,
 status TEXT NOT NULL, payload TEXT NOT NULL, created_at INTEGER NOT NULL
);
"""
SHARED_SQL = (Path(__file__).resolve().parents[2] / "docs/database-schema.sql").read_text(
    encoding="utf-8"
)
INPUT = {
    "role": "浏览器提供的标题",
    "experience": "在校园图书借阅系统中负责后端接口与数据库设计。",
    "job_analysis_id": "job-one",
    "diagnosis_id": "diagnosis-one",
}
SDP = "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"


def register(client, email=ACCOUNT["email"]):
    response = client.post("/api/v1/auth/register", json={**ACCOUNT, "email": email})
    assert response.status_code == 201
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()["user"]["id"]


def seed_parents(database, user_id):
    with database.connect() as connection:
        for job_id, title, status in [
            ("job-one", "Python 后端工程师", "completed"),
            ("job-two", "前端工程师", "completed"),
            ("job-failed", "失败任务", "failed"),
        ]:
            payload = json.dumps(
                {"requirements": [{"id": "req-1", "text": "熟悉 Python", "quote": "熟悉 Python"}]}
            )
            connection.execute(
                "INSERT INTO job_analysis_tasks VALUES (?,?,?,?,?,?,?,?)",
                (job_id, user_id, title, "要求：熟悉 Python", "rules", status, payload, 1),
            )
        connection.execute(
            "INSERT INTO resumes VALUES (?,?,?,?,?,?)",
            ("resume-one", user_id, "模拟简历", "模拟项目经历", "{}", 1),
        )
        for diagnosis_id, job_id, status in [
            ("diagnosis-one", "job-one", "completed"),
            ("diagnosis-other-job", "job-two", "completed"),
            ("diagnosis-running", "job-one", "running"),
        ]:
            connection.execute(
                "INSERT INTO diagnosis_tasks VALUES (?,?,?,?,?,?,?,?)",
                (
                    diagnosis_id,
                    user_id,
                    job_id,
                    "resume-one",
                    status,
                    '{"schema_version":1,"weaknesses":["测试证据"]}',
                    1,
                    1,
                ),
            )


@pytest.fixture
def client(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        environment="test",
        database_path=tmp_path / "shared.db",
        auth_rate_limit=100,
        voice_api_key="voice-test",
        DEEPSEEK_API_KEY="deepseek-test",
        voice_webrtc_url="https://example.com/realtime",
    )
    # Simulate A's future migration on top of A's v2, not D's old numbered list.
    with sqlite3.connect(settings.database_path) as connection:
        connection.executescript(MIGRATIONS[0] + JOBS_DDL + "PRAGMA user_version=2;")
        connection.executescript(SHARED_SQL)
        connection.execute("PRAGMA user_version=3")
    monkeypatch.setattr(voice_provider, "exchange_sdp", AsyncMock(return_value=SDP))
    monkeypatch.setattr(
        voice_provider,
        "generate_review",
        AsyncMock(
            return_value=AgentResult(
                task_id="shared-test", agent=AgentKind.INTERVIEW, status="completed", summary="复盘"
            )
        ),
    )
    with TestClient(create_app(settings), headers=ORIGIN) as client:
        owner = register(client)
        seed_parents(client.app.state.database, owner)
        yield client


def test_canonical_schema_does_not_create_legacy_tables(client):
    with client.app.state.database.connect() as connection:
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "interviews" not in names and "voice_interviews" not in names
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
    assert (
        client.post(
            "/api/v1/interviews", json={"role": "Python", "experience": INPUT["experience"]}
        ).status_code
        == 409
    )


def test_context_choices_and_valid_parent_snapshots(client):
    choices = client.get("/api/v1/interviews/contexts?job_analysis_id=job-one").json()
    assert choices["shared_storage_ready"] and choices["requires_job_link"]
    assert {job["id"] for job in choices["jobs"]} == {"job-one", "job-two"}
    assert [diagnosis["id"] for diagnosis in choices["diagnoses"]] == ["diagnosis-one"]
    response = client.post("/api/v1/interviews", json=INPUT)
    assert response.status_code == 201
    record = response.json()
    assert record["role"] == "Python 后端工程师"
    assert record["parent_context"]["requirements"][0]["id"] == "req-1"
    assert record["parent_context"]["diagnosis"]["weaknesses"] == ["测试证据"]
    assert record["schema_version"] == 1


@pytest.mark.parametrize(
    "changes,status",
    [
        ({"job_analysis_id": "missing"}, 404),
        ({"job_analysis_id": "job-failed"}, 409),
        ({"diagnosis_id": "missing"}, 404),
        ({"diagnosis_id": "diagnosis-other-job"}, 409),
        ({"diagnosis_id": "diagnosis-running"}, 409),
        ({"job_analysis_id": None}, 422),
    ],
)
def test_parent_relations_are_checked_for_both_interview_modes(client, changes, status):
    for path in ("/api/v1/interviews", "/api/v1/voice-interviews"):
        assert client.post(path, json={**INPUT, **changes}).status_code == status


def test_linked_text_turns_follow_shared_lifecycle_and_preserve_round_ids(client):
    record = client.post("/api/v1/interviews", json=INPUT).json()
    path = f"/api/v1/interviews/{record['id']}"
    with client.app.state.database.connect() as connection:
        first_id = connection.execute(
            "SELECT id FROM interview_turns WHERE session_id=?", (record["id"],)
        ).fetchone()[0]
    for number in range(1, 4):
        response = client.post(
            path + "/answers", json={"round": number, "answer": "我负责接口并编写测试，随后改进。"}
        )
        assert response.status_code == 200
    assert client.get(path).json()["status"] == "completed"
    assert len(client.get("/api/v1/interviews").json()) == 1
    with client.app.state.database.connect() as connection:
        session = connection.execute(
            "SELECT * FROM interview_sessions WHERE id=?", (record["id"],)
        ).fetchone()
        turns = connection.execute(
            "SELECT * FROM interview_turns WHERE session_id=? ORDER BY round_no", (record["id"],)
        ).fetchall()
        assert session["status"] == "completed" and session["input_mode"] == "text"
        assert (
            session["job_analysis_id"] == "job-one" and session["diagnosis_id"] == "diagnosis-one"
        )
        assert turns[0]["id"] == first_id
        assert [turn["status"] for turn in turns] == ["answered"] * 3
        assert all(turn["updated_at"] >= turn["created_at"] for turn in turns)
        assert json.loads(session["report_payload"])["schema_version"] == 1


def test_linked_voice_keeps_realtime_messages_and_reviews_only_after_end(client):
    record = client.post("/api/v1/voice-interviews", json=INPUT).json()
    path = f"/api/v1/voice-interviews/{record['id']}"
    connected = client.post(path + "/connect", json={"offer_sdp": SDP})
    assert connected.status_code == 200
    assert "req-1" in connected.json()["session"]["instructions"]
    messages = [
        {
            "id": "q1",
            "role": "assistant",
            "text": "你的项目贡献？",
            "sequence": 0,
            "interrupted": True,
        },
        {"id": "u1", "role": "user", "text": "我负责接口和自动化测试。", "sequence": 1},
        {"id": "q2", "role": "assistant", "text": "如何验证结果？", "sequence": 2},
    ]
    assert client.post(path + "/messages", json={"messages": messages}).status_code == 200
    assert client.post(path + "/report").status_code == 409
    voice_provider.generate_review.assert_not_awaited()
    assert client.post(path + "/end", json={"message_count": 3}).status_code == 200
    restored = client.get(path).json()
    assert restored["report_status"] == "completed" and restored["messages"][0]["interrupted"]
    with client.app.state.database.connect() as connection:
        session = connection.execute(
            "SELECT * FROM interview_sessions WHERE id=?", (record["id"],)
        ).fetchone()
        turns = connection.execute(
            "SELECT * FROM interview_turns WHERE session_id=? ORDER BY round_no", (record["id"],)
        ).fetchall()
        assert session["status"] == "completed" and session["input_mode"] == "voice"
        assert [turn["status"] for turn in turns] == ["answered", "skipped"]
        assert turns[0]["answer_text"] == "我负责接口和自动化测试。"
        assert all(turn["audio_duration_ms"] is None for turn in turns)
    voice_provider.generate_review.assert_awaited_once()


def test_shared_parents_and_children_cannot_cross_users(client):
    record = client.post("/api/v1/interviews", json=INPUT).json()
    with TestClient(client.app, headers=ORIGIN) as other:
        register(other, "other-shared@example.com")
        assert other.post("/api/v1/interviews", json=INPUT).status_code == 404
        assert other.post("/api/v1/voice-interviews", json=INPUT).status_code == 404
        assert other.get(f"/api/v1/interviews/{record['id']}").status_code == 404
        assert other.get("/api/v1/interviews").json() == []
        assert other.get("/api/v1/interviews/contexts").json()["jobs"] == []


def test_existing_legacy_records_remain_readable_after_shared_tables_are_provisioned(tmp_path):
    settings = Settings(_env_file=None, environment="test", database_path=tmp_path / "mixed.db")
    with TestClient(create_app(settings), headers=ORIGIN) as client:
        owner = register(client)
        old = client.post(
            "/api/v1/interviews", json={"role": "旧练习", "experience": INPUT["experience"]}
        ).json()
        with client.app.state.database.connect() as connection:
            connection.executescript(JOBS_DDL)
            connection.executescript(SHARED_SQL)
        seed_parents(client.app.state.database, owner)
        new = client.post("/api/v1/interviews", json=INPUT)
        assert new.status_code == 201
        assert client.get(f"/api/v1/interviews/{old['id']}").json()["role"] == "旧练习"
        assert len(client.get("/api/v1/interviews").json()) == 2
    Database(settings.database_path).migrate()
