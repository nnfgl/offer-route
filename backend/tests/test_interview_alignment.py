import asyncio
import json
import sqlite3

import httpx
import pytest

from app.agents.interview.schemas import InterviewOutput
from app.agents.interview.voice_schemas import VoiceInterview
from app.core.config import Settings
from app.core.database import MIGRATIONS, Database
from app.core.model_client import DeepSeekClient, ModelFailure


def test_job_branch_database_is_not_migrated_as_interview_branch(tmp_path):
    database = Database(tmp_path / "job-v2.db")
    with sqlite3.connect(database.path) as connection:
        connection.executescript(MIGRATIONS[0])
        connection.executescript(
            "CREATE TABLE job_analysis_tasks(id TEXT PRIMARY KEY, payload TEXT);"
            "INSERT INTO job_analysis_tasks VALUES ('keep-job', '{}');"
            "PRAGMA user_version = 2;"
        )
        connection.execute(
            "INSERT INTO users VALUES ('keep-user', 'old@example.com', '旧账号', 'hash', 1)"
        )
    with pytest.raises(RuntimeError, match="由 A 协调"):
        database.migrate()
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("SELECT id FROM users").fetchone()[0] == "keep-user"
        assert connection.execute("SELECT id FROM job_analysis_tasks").fetchone()[0] == "keep-job"
        assert not connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'voice_interviews'"
        ).fetchone()


def test_future_schema_is_not_silently_accepted(tmp_path):
    database = Database(tmp_path / "future.db")
    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA user_version = 999")
    with pytest.raises(RuntimeError, match="高于当前分支"):
        database.migrate()


def test_existing_interview_payloads_default_to_schema_version_one():
    old_text = {
        "id": "text",
        "role": "Python",
        "experience": "模拟项目经历",
        "status": "active",
        "created_at": 1,
        "turns": [{"question": "你的个人贡献？"}],
    }
    old_voice = {"id": "voice", "role": "Python", "experience": "模拟项目经历", "created_at": 1}
    assert InterviewOutput.model_validate(old_text).schema_version == 1
    assert VoiceInterview.model_validate(old_voice).schema_version == 1


def test_shared_client_configuration_and_validation_retry():
    calls = []
    settings = Settings(_env_file=None, DEEPSEEK_API_KEY="shared-test-key")

    def respond(request):
        calls.append(request)
        value = {"verified": len(calls) > 1}
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    def validate(payload):
        if not payload["verified"]:
            raise ValueError("Missing valid evidence")
        return payload

    result, usage = asyncio.run(
        DeepSeekClient(settings, httpx.MockTransport(respond)).complete_json(
            "Return verified JSON",
            "模拟面试转写",
            validate,
        )
    )
    assert result == {"verified": True} and usage.attempts == 2
    assert usage.prompt_tokens == 20 and usage.completion_tokens == 10
    assert calls[0].headers["authorization"] == "Bearer shared-test-key"
    assert "shared-test-key" not in json.dumps(usage.model_dump())


def test_shared_client_rejects_invalid_key_without_retry_or_leaking_details():
    calls = []
    settings = Settings(_env_file=None, DEEPSEEK_API_KEY="shared-test-key")
    model = DeepSeekClient(
        settings,
        httpx.MockTransport(
            lambda request: (
                calls.append(request) or httpx.Response(401, text="upstream-private-body")
            )
        ),
    )
    with pytest.raises(ModelFailure) as raised:
        asyncio.run(model.complete_json("JSON", "模拟转写", lambda value: value))
    assert raised.value.code == "model_access_denied" and len(calls) == 1
    assert "upstream-private-body" not in str(raised.value)
