import asyncio
import json
import time
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents.contracts import AgentKind, AgentResult
from app.agents.interview import voice_provider
from app.agents.interview.voice_schemas import VoiceInterview, VoiceMessage
from app.core.config import Settings
from app.main import create_app

BASE = "/api/v1/voice-interviews"
ORIGIN = {"Origin": "http://localhost:5173"}
INPUT = {"role": "Python 后端工程师", "experience": "开发校园图书借阅系统，负责接口与数据库设计。"}
ACCOUNT = {
    "email": "voice@example.com",
    "password": "correct-horse-battery",
    "display_name": "语音同学",
}
SDP = "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
MESSAGES = [
    {"id": "question-1", "role": "assistant", "text": "介绍你的项目", "final": True},
    {"id": "answer-1", "role": "user", "text": "我负责接口，并编写自动化测试。", "final": True},
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    settings = Settings(
        environment="test",
        database_path=tmp_path / "voice.db",
        auth_rate_limit=100,
        voice_api_key="test-secret-do-not-expose",
        voice_webrtc_url="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/webrtc/realtime",
    )
    monkeypatch.setattr(voice_provider, "exchange_sdp", AsyncMock(return_value=SDP))
    monkeypatch.setattr(
        voice_provider,
        "generate_review",
        AsyncMock(
            return_value=AgentResult(
                task_id="test",
                agent=AgentKind.INTERVIEW,
                status="completed",
                summary="面试后的复盘",
            )
        ),
    )
    with TestClient(create_app(settings), headers=ORIGIN) as client:
        session = client.post("/api/v1/auth/register", json=ACCOUNT).json()
        client.headers["X-CSRF-Token"] = session["csrf_token"]
        yield client


def start(client):
    response = client.post(BASE, json=INPUT)
    assert response.status_code == 201
    return response.json()


def live(client):
    record = start(client)
    response = client.post(f"{BASE}/{record['id']}/connect", json={"offer_sdp": SDP})
    assert response.status_code == 200
    assert "test-secret-do-not-expose" not in response.text
    return f"{BASE}/{record['id']}"


def test_live_does_not_evaluate_and_end_freezes_saved_transcript(client):
    path = live(client)
    assert client.post(path + "/report").status_code == 409
    saved = client.post(path + "/messages", json={"messages": MESSAGES})
    assert saved.status_code == 200
    assert saved.json()["report"] is None
    assert saved.json()["report_status"] == "not_started"
    voice_provider.generate_review.assert_not_awaited()
    assert client.post(path + "/end", json={"message_count": 1}).status_code == 409
    ended = client.post(path + "/end", json={"message_count": 2})
    assert ended.status_code == 200 and ended.json()["status"] == "ended"
    evaluated = voice_provider.generate_review.await_args.args[1]
    assert evaluated.status == "ended"
    assert [message.text for message in evaluated.messages] == [item["text"] for item in MESSAGES]
    assert client.get(path).json()["report_status"] == "completed"
    assert client.post(path + "/messages", json={"messages": MESSAGES}).status_code == 409
    assert client.post(path + "/end", json={"message_count": 2}).status_code == 200
    assert client.post(path + "/report").status_code == 202
    assert voice_provider.generate_review.await_count == 1
    assert client.get(BASE).json()[0]["id"] == evaluated.id


def test_final_snapshot_retries_and_interrupt_flag_do_not_duplicate_or_rewrite_answers(client):
    path = live(client)
    assert client.post(path + "/messages", json={"messages": MESSAGES}).status_code == 200
    repeated = client.post(path + "/messages", json={"messages": MESSAGES})
    assert len(repeated.json()["messages"]) == 2
    interrupted = [{**MESSAGES[0], "interrupted": True}]
    assert client.post(path + "/messages", json={"messages": interrupted}).status_code == 200
    for changes in [{"text": "伪造改写"}, {"role": "assistant"}, {"final": False}]:
        assert (
            client.post(
                path + "/messages", json={"messages": [{**MESSAGES[1], **changes}]}
            ).status_code
            == 409
        )
    assert (
        client.post(path + "/messages", json={"messages": [MESSAGES[0], MESSAGES[0]]}).status_code
        == 422
    )


def test_pending_final_transcript_requires_explicit_acknowledgment(client):
    path = live(client)
    partial = {"id": "answer-2", "role": "user", "text": "最后一句未转写完", "final": False}
    client.post(path + "/messages", json={"messages": [*MESSAGES, partial]})
    assert client.post(path + "/end", json={"message_count": 3}).status_code == 409
    voice_provider.generate_review.assert_not_awaited()
    ended = client.post(path + "/end", json={"message_count": 3, "accept_incomplete": True})
    assert ended.status_code == 200 and ended.json()["incomplete"]


def test_late_asr_completion_preserves_conversation_order(client):
    path = live(client)
    question = {**MESSAGES[0], "sequence": 0}
    answer = {**MESSAGES[1], "sequence": 1}
    followup = {**question, "id": "question-2", "text": "具体如何测试？", "sequence": 2}
    client.post(path + "/messages", json={"messages": [question, followup]})
    saved = client.post(path + "/messages", json={"messages": [answer]}).json()
    assert [message["id"] for message in saved["messages"]] == [
        "question-1",
        "answer-1",
        "question-2",
    ]
    assert (
        client.post(path + "/messages", json={"messages": [{**answer, "sequence": 3}]}).status_code
        == 409
    )


def test_no_answer_does_not_invent_a_report(client):
    path = live(client)
    response = client.post(path + "/end", json={"message_count": 0})
    assert response.status_code == 200
    assert response.json()["report_status"] == "failed"
    assert client.post(path + "/report").status_code == 409
    voice_provider.generate_review.assert_not_awaited()


def test_review_failure_is_retryable_and_transcript_is_kept(client):
    path = live(client)
    client.post(path + "/messages", json={"messages": MESSAGES})
    voice_provider.generate_review.side_effect = RuntimeError("upstream-private-error")
    client.post(path + "/end", json={"message_count": 2})
    failed = client.get(path)
    assert failed.json()["report_status"] == "failed"
    assert "upstream-private-error" not in failed.text
    assert len(failed.json()["messages"]) == 2
    voice_provider.generate_review.side_effect = None
    assert client.post(path + "/report").status_code == 202
    assert client.get(path).json()["report_status"] == "completed"


def test_connection_failure_can_retry_without_leaking_upstream_or_key(client):
    record = start(client)
    path = f"{BASE}/{record['id']}"
    voice_provider.exchange_sdp.side_effect = RuntimeError("test-secret-do-not-expose")
    response = client.post(path + "/connect", json={"offer_sdp": SDP})
    assert response.status_code == 502
    assert "test-secret" not in response.text
    assert client.get(path).json()["status"] == "created"
    voice_provider.exchange_sdp.side_effect = None
    assert client.post(path + "/connect", json={"offer_sdp": SDP}).status_code == 200
    assert client.post(path + "/connect", json={"offer_sdp": SDP}).status_code == 409


def test_all_voice_records_and_mutations_are_isolated_by_user(client):
    path = live(client)
    with TestClient(client.app, headers=ORIGIN) as other:
        session = other.post(
            "/api/v1/auth/register", json={**ACCOUNT, "email": "other@example.com"}
        ).json()
        other.headers["X-CSRF-Token"] = session["csrf_token"]
        assert other.get(BASE).json() == []
        assert other.get(path).status_code == 404
        for endpoint, body in [
            ("/connect", {"offer_sdp": SDP}),
            ("/messages", {"messages": MESSAGES}),
            ("/end", {"message_count": 0}),
            ("/report", None),
        ]:
            assert other.post(path + endpoint, json=body).status_code == 404
    client.cookies.clear()
    assert client.get(BASE + "/config").status_code == 401
    assert client.get(BASE).status_code == 401
    assert client.get(path).status_code == 401
    assert client.post(BASE, json=INPUT).status_code == 401
    assert client.post(path + "/connect", json={"offer_sdp": SDP}).status_code == 401
    assert client.post(path + "/messages", json={"messages": MESSAGES}).status_code == 401
    assert client.post(path + "/end", json={"message_count": 0}).status_code == 401
    assert client.post(path + "/report").status_code == 401


@pytest.mark.parametrize("headers", [{"X-CSRF-Token": "bad"}, {"Origin": "https://evil.example"}])
def test_every_voice_write_requires_csrf_and_origin(client, headers):
    path = live(client)
    for endpoint, body in [
        (BASE, INPUT),
        (path + "/connect", {"offer_sdp": SDP}),
        (path + "/messages", {"messages": MESSAGES}),
        (path + "/end", {"message_count": 0}),
        (path + "/report", None),
    ]:
        assert client.post(endpoint, json=body, headers=headers).status_code == 403


def test_missing_configuration_and_invalid_inputs_are_explicit(client):
    config = client.get(BASE + "/config")
    assert config.json()["configured"]
    assert "test-secret" not in config.text and "workspace" not in config.text
    assert client.post(BASE, json={**INPUT, "user_id": "forged"}).status_code == 422
    record = start(client)
    assert (
        client.post(f"{BASE}/{record['id']}/connect", json={"offer_sdp": "x" * 30}).status_code
        == 422
    )
    client.app.state.settings.voice_webrtc_url = ""
    assert not client.get(BASE + "/config").json()["configured"]
    assert client.post(BASE, json=INPUT).status_code == 503
    assert client.post(f"{BASE}/{record['id']}/connect", json={"offer_sdp": SDP}).status_code == 503


def test_interrupted_report_worker_can_be_retried_after_lease_timeout(client):
    path = live(client)
    client.post(path + "/messages", json={"messages": MESSAGES})
    client.post(path + "/end", json={"message_count": 2})
    record = client.get(path).json()
    record.update(report_status="processing", report_started_at=int(time.time()) - 100, report=None)
    with client.app.state.database.connect() as connection:
        connection.execute(
            "UPDATE voice_interviews SET payload = ? WHERE id = ?",
            (json.dumps(record), record["id"]),
        )
    assert client.post(path + "/report").status_code == 202
    assert client.get(path).json()["report_status"] == "completed"


@pytest.mark.parametrize(
    "invalid",
    [
        "valid",
        "fabricated_quote",
        "assistant_evidence",
        "partial_evidence",
        "duplicate_dimension",
        "score_without_evidence",
    ],
)
def test_model_report_accepts_only_verifiable_evidence(monkeypatch, invalid):
    interview = VoiceInterview(
        id="voice-test",
        role="Python",
        experience=INPUT["experience"],
        created_at=1,
        status="ended",
        messages=[VoiceMessage.model_validate(m) for m in MESSAGES],
    )
    dimensions = [
        {
            "name": name,
            "score": 2,
            "reason": "根据回答分析",
            "suggestion": "补充具体证据",
            "evidence": [{"message_id": "answer-1", "quote": "我负责接口"}],
        }
        for name in ["岗位理解", "技术与经历", "表达结构", "反思改进"]
    ]
    if invalid == "fabricated_quote":
        dimensions[0]["evidence"][0]["quote"] = "从来没说过"
    if invalid == "assistant_evidence":
        dimensions[0]["evidence"][0] = {"message_id": "question-1", "quote": "介绍"}
    if invalid == "partial_evidence":
        interview.messages[1].final = False
    if invalid == "duplicate_dimension":
        dimensions[0]["name"] = "表达结构"
    if invalid == "score_without_evidence":
        dimensions[0]["evidence"] = []
    body = {
        "choices": [
            {"message": {"content": json.dumps({"summary": "复盘", "dimensions": dimensions})}}
        ]
    }
    original = httpx.AsyncClient
    monkeypatch.setattr(
        voice_provider.httpx,
        "AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)), **kwargs
        ),
    )
    if invalid == "valid":
        result = asyncio.run(voice_provider.generate_review(Settings(), interview))
        assert result.task_id == interview.id and result.agent == AgentKind.INTERVIEW
        assert result.data["score"] == 8 and result.data["max_score"] == 20
        assert len(result.evidence) == 4 and len(result.data["training_items"]) == 4
        assert result.evidence[0].source == "voice:voice-test:message:answer-1"
    else:
        with pytest.raises(ValueError):
            asyncio.run(voice_provider.generate_review(Settings(), interview))


def test_voice_transcript_and_report_survive_restart(client):
    path = live(client)
    client.post(path + "/messages", json={"messages": MESSAGES})
    client.post(path + "/end", json={"message_count": 2})
    expected = client.get(path).json()
    with TestClient(create_app(client.app.state.settings), headers=ORIGIN) as restarted:
        assert restarted.post("/api/v1/auth/login", json=ACCOUNT).status_code == 200
        assert restarted.get(path).json() == expected
