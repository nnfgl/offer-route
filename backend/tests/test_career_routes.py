from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.agents.job.schemas import Extraction
from app.core.config import Settings
from app.core.model_client import ModelFailure, ModelUsage
from app.main import create_app

BASE = "/api/v1/career-routes"
ORIGIN = {"Origin": "http://127.0.0.1:5173"}
ACCOUNT = {
    "email": "route@example.com",
    "password": "career-route-password",
    "display_name": "路线同学",
}
MATERIALS = {
    "job": {
        "title": "Python 后端",
        "source_text": "必需：熟悉 Python 开发\n必需：熟悉 SQL 数据库查询与聚合",
    },
    "resume_title": "联调简历",
    "resume_text": "在校园项目中负责 Python 接口实现，编写单元测试并维护文档。",
}


def register(client, email=ACCOUNT["email"]):
    response = client.post("/api/v1/auth/register", json={**ACCOUNT, "email": email})
    assert response.status_code == 201, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


def create(client):
    data = {**MATERIALS, "request_id": str(uuid4())}
    response = client.post(BASE, json=data)
    assert response.status_code == 201, response.text
    return data, response.json()


def advance(client, route):
    response = client.post(f"{BASE}/{route['id']}/advance", json={"revision": route["revision"]})
    assert response.status_code == 200, response.text
    return response.json()


def test_route_retry_budget_owner_and_recovery(tmp_path):
    settings = Settings(
        _env_file=None,
        environment="test",
        database_path=tmp_path / "route.db",
        job_provider="deepseek",
    )
    app = create_app(settings)
    model = AsyncMock(
        side_effect=[
            ModelFailure("model_busy", "模型繁忙", ModelUsage(attempts=2, prompt_tokens=100)),
            (
                Extraction(
                    requirements=[
                        {
                            "text": "熟悉 SQL 数据库查询与聚合",
                            "quote": "熟悉 SQL 数据库查询与聚合",
                            "priority": "required",
                            "category": "skill",
                        }
                    ]
                ),
                ModelUsage(attempts=1, prompt_tokens=100, completion_tokens=50),
            ),
        ]
    )
    app.state.job_workflow.model.complete_json = model
    with TestClient(app, headers=ORIGIN) as client:
        register(client)
        data, route = create(client)
        path = f"{BASE}/{route['id']}"
        assert client.post(BASE, json=data).json()["id"] == route["id"]
        assert len(client.get(BASE).json()) == 1
        assert client.post(BASE, json={**data, "resume_title": "改过的标题"}).status_code == 409
        failed = advance(client, route)
        assert failed["attempts"][-1]["status"] == "failed"
        assert failed["profile"]["usage"]["attempts"] == 2
        assert client.post(path + "/advance", json={"revision": 0}).status_code == 409
        ready = advance(client, failed)
        assert ready["next_stage"] == "diagnosis"
        assert ready["profile"]["usage"] == {
            "attempts": 3,
            "prompt_tokens": 200,
            "completion_tokens": 50,
        }
        assert model.await_count == 2
        # Simulate a restart between reserving the diagnosis attempt and calling its agent.
        with app.state.database.connect() as db:
            db.execute(
                "INSERT INTO career_attempts VALUES (?,?,3,'diagnosis','running','')",
                (str(uuid4()), route["id"]),
            )
        assert client.post(path + "/advance", json={"revision": 3}).status_code == 409
        register(client, "other-route@example.com")
        assert client.get(path).status_code == 404
        assert client.post(path + "/advance", json={"revision": 3}).status_code == 404
        assert client.post(BASE, json=data).status_code == 404
    with TestClient(create_app(settings), headers=ORIGIN) as client:
        login = client.post("/api/v1/auth/login", json=ACCOUNT)
        client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        recovered = client.get(path).json()
        assert recovered["job_id"] == ready["job_id"]
        assert recovered["attempts"][-1]["status"] == "failed"
        assert recovered["next_stage"] == "diagnosis"
        prepared = advance(client, advance(client, recovered))
        assert prepared["phase"] == "training" and prepared["training_id"]
        assert len(client.get("/api/v1/training/tasks").json()) == 1


def test_step_stops_after_two_failed_runs(tmp_path):
    settings = Settings(
        _env_file=None,
        environment="test",
        database_path=tmp_path / "limit.db",
        job_provider="deepseek",
    )
    app = create_app(settings)
    app.state.job_workflow.model.complete_json = AsyncMock(
        side_effect=ModelFailure("model_busy", "模型繁忙")
    )
    with TestClient(app, headers=ORIGIN) as client:
        register(client)
        _, route = create(client)
        route = advance(client, advance(client, route))
        assert route["next_stage"] is None
        assert client.post(f"{BASE}/{route['id']}/advance", json={"revision": 2}).status_code == 409
        assert app.state.job_workflow.model.complete_json.await_count == 2
