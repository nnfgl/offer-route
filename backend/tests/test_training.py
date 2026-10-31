import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.agents.contracts import AgentRequest
from app.agents.training.application import create_training_app
from app.agents.training.database import SQLiteTrainingDatabase
from app.agents.training.demo import seed_diagnosis
from app.agents.training.exercises import REFERENCE_SQL
from app.agents.training.knowledge import TrainingKnowledge, embed
from app.agents.training.runner import CheckResult, SQLRunner
from app.agents.training.schemas import KnowledgeReference, SubmitAnswer
from app.agents.training.settings import TrainingSettings

ORIGIN = "http://127.0.0.1:5173"


class FixtureKnowledge:
    def search(self, query):
        return [
            KnowledgeReference(
                source="synthetic:unit-test",
                excerpt="LEFT JOIN 保留没有订单的客户。",
                content_sha256=hashlib.sha256("test".encode()).hexdigest(),
            )
        ]


@pytest.fixture
def training(tmp_path):
    settings = TrainingSettings(database_backend="sqlite", sqlite_path=tmp_path / "local.sqlite3")
    app = create_training_app(settings, knowledge=FixtureKnowledge(), initialize_sqlite=True)
    with TestClient(app, headers={"Origin": ORIGIN}) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "training@example.com",
                "password": "local-test-only-password",
                "display_name": "模拟训练用户",
            },
        )
        assert response.status_code == 201
        session = response.json()
        diagnosis_id = seed_diagnosis(app.state.database, session["user"]["id"])
        yield client, app, session, diagnosis_id


def create(training):
    client, _, session, diagnosis_id = training
    response = client.post(
        "/api/v1/training/tasks",
        json={
            "diagnosis_id": diagnosis_id,
            "requirement_id": "req-sql-01",
        },
        headers={"X-CSRF-Token": session["csrf_token"]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def submit(training, task_id, sql, request_id=None):
    client, _, session, _ = training
    return client.post(
        f"/api/v1/training/tasks/{task_id}/submissions",
        json={
            "request_id": request_id or str(uuid4()),
            "answer_text": sql,
        },
        headers={"X-CSRF-Token": session["csrf_token"]},
    )


def test_generation_is_not_user_completion(training):
    task = create(training)
    assert task["status"] == "planned"
    assert task["task_payload"]["schema_version"] == 1
    assert task["task_payload"]["materials"][0]["embedding_profile"] == "local-test-hash-v1"
    assert "REFERENCE_SQL" not in json.dumps(task)
    assert "expected" not in json.dumps(task)
    client, _, _, diagnosis_id = training
    assert (
        client.get(f"/api/v1/training/diagnoses/{diagnosis_id}/evidence").json()["evidence"] == []
    )


def test_wrong_then_correct_preserves_attempts_and_evidence(training):
    task = create(training)
    wrong = submit(training, task["id"], "SELECT 1")
    assert wrong.status_code == 201 and wrong.json()["status"] == "failed"
    assert wrong.json()["evaluation_payload"]["evidence"] == []
    correct = submit(training, task["id"], REFERENCE_SQL)
    assert correct.status_code == 201 and correct.json()["status"] == "passed"
    assert correct.json()["attempt_no"] == 2
    client, app, session, diagnosis_id = training
    assert client.get(f"/api/v1/training/tasks/{task['id']}").json()["status"] == "completed"
    evidence = client.get(f"/api/v1/training/diagnoses/{diagnosis_id}/evidence").json()["evidence"]
    assert len(evidence) == 1 and evidence[0]["submission_id"] == correct.json()["id"]
    assert evidence[0]["verification"] == "task_verified"
    assert len(client.get(f"/api/v1/training/tasks/{task['id']}/submissions").json()) == 2
    original = app.state.training.repository.diagnosis(diagnosis_id, session["user"]["id"])
    assert json.loads(original["result_payload"])["gaps"]  # B's diagnosis was not overwritten.


def test_idempotent_retry_and_request_reuse_conflict(training):
    task = create(training)
    request_id = str(uuid4())
    first = submit(training, task["id"], "SELECT 1", request_id).json()
    repeated = submit(training, task["id"], "SELECT 1", request_id).json()
    assert first == repeated
    changed = submit(training, task["id"], "SELECT 2", request_id)
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "idempotency_conflict"


def test_passed_retry_does_not_duplicate_evidence(training):
    task = create(training)
    request_id = str(uuid4())
    first = submit(training, task["id"], REFERENCE_SQL, request_id)
    repeated = submit(training, task["id"], REFERENCE_SQL, request_id)
    assert first.json()["id"] == repeated.json()["id"]
    assert submit(training, task["id"], REFERENCE_SQL).status_code == 409


def test_all_writes_require_csrf_and_origin(training):
    client, _, session, diagnosis_id = training
    payload = {"diagnosis_id": diagnosis_id, "requirement_id": "req-sql-01"}
    assert client.post("/api/v1/training/tasks", json=payload).status_code == 403
    assert (
        client.post(
            "/api/v1/training/tasks",
            json=payload,
            headers={"X-CSRF-Token": session["csrf_token"], "Origin": "https://untrusted.example"},
        ).status_code
        == 403
    )
    task = create(training)
    assert client.post(f"/api/v1/training/tasks/{task['id']}/archive").status_code == 403
    assert (
        client.post(
            f"/api/v1/training/tasks/{task['id']}/submissions",
            json={"request_id": str(uuid4()), "answer_text": "SELECT 1"},
        ).status_code
        == 403
    )


def test_unauthenticated_reads_are_rejected(training):
    client, _, _, diagnosis_id = training
    task = create(training)
    client.cookies.clear()
    for path in [
        "tasks",
        f"tasks/{task['id']}",
        f"diagnoses/{diagnosis_id}/evidence",
        f"submissions/{uuid4()}",
        "materials?query=SQL",
    ]:
        assert client.get("/api/v1/training/" + path).status_code == 401


def test_cannot_read_or_mutate_another_users_records(training):
    task = create(training)
    submission = submit(training, task["id"], "SELECT 1").json()
    client, _, _, diagnosis_id = training
    client.cookies.clear()
    other = client.post(
        "/api/v1/auth/register",
        json={
            "email": "other@example.com",
            "password": "another-local-password",
            "display_name": "另一模拟用户",
        },
    ).json()
    headers = {"X-CSRF-Token": other["csrf_token"]}
    for path in [
        f"tasks/{task['id']}",
        f"tasks/{task['id']}/submissions",
        f"submissions/{submission['id']}",
        f"diagnoses/{diagnosis_id}/evidence",
    ]:
        assert client.get("/api/v1/training/" + path).status_code == 404
    assert client.get("/api/v1/training/tasks").json() == []
    assert (
        client.post(
            "/api/v1/training/tasks",
            headers=headers,
            json={"diagnosis_id": diagnosis_id, "requirement_id": "req-sql-01"},
        ).status_code
        == 404
    )
    assert (
        client.post(f"/api/v1/training/tasks/{task['id']}/archive", headers=headers).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/training/tasks/{task['id']}/submissions",
            headers=headers,
            json={"request_id": str(uuid4()), "answer_text": "SELECT 1"},
        ).status_code
        == 404
    )


def test_browser_cannot_supply_user_id(training):
    client, _, session, diagnosis_id = training
    response = client.post(
        "/api/v1/training/tasks",
        json={
            "diagnosis_id": diagnosis_id,
            "requirement_id": "req-sql-01",
            "user_id": str(uuid4()),
        },
        headers={"X-CSRF-Token": session["csrf_token"]},
    )
    assert response.status_code == 422
    assert "user_id" in response.json()["error"]["fields"]


def test_incomplete_or_incompatible_diagnosis_rejected(training):
    client, app, session, diagnosis_id = training
    with app.state.database.connect() as connection:
        connection.execute(
            "UPDATE diagnosis_tasks SET status='running' WHERE id=?", (diagnosis_id,)
        )
    response = client.post(
        "/api/v1/training/tasks",
        json={"diagnosis_id": diagnosis_id, "requirement_id": "req-sql-01"},
        headers={"X-CSRF-Token": session["csrf_token"]},
    )
    assert response.status_code == 409
    with app.state.database.connect() as connection:
        connection.execute(
            "UPDATE diagnosis_tasks SET status='completed',result_payload='{}' WHERE id=?",
            (diagnosis_id,),
        )
    response = client.post(
        "/api/v1/training/tasks",
        json={"diagnosis_id": diagnosis_id, "requirement_id": "req-sql-01"},
        headers={"X-CSRF-Token": session["csrf_token"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "diagnosis_contract_mismatch"


def test_archive_is_not_delete(training):
    task = create(training)
    first = submit(training, task["id"], "SELECT 1").json()
    client, _, session, _ = training
    response = client.post(
        f"/api/v1/training/tasks/{task['id']}/archive",
        headers={"X-CSRF-Token": session["csrf_token"]},
    )
    assert response.json()["status"] == "archived"
    assert client.get(f"/api/v1/training/submissions/{first['id']}").status_code == 200
    assert submit(training, task["id"], "SELECT 1").status_code == 409


def test_runner_failure_is_error_not_wrong_answer(training):
    task = create(training)
    client, app, _, diagnosis_id = training

    class BrokenRunner:
        def check(self, sql):
            raise RuntimeError("internal details should not be returned")

    app.state.training.runner = BrokenRunner()
    response = submit(training, task["id"], REFERENCE_SQL)
    assert response.json()["status"] == "error"
    assert "internal details" not in response.text
    assert (
        client.get(f"/api/v1/training/diagnoses/{diagnosis_id}/evidence").json()["evidence"] == []
    )


def test_concurrent_same_request_creates_one_submission(training):
    task = create(training)
    _, app, session, _ = training
    entered, release = threading.Event(), threading.Event()

    class WaitingRunner:
        def check(self, sql):
            entered.set()
            assert release.wait(timeout=5)
            return CheckResult("failed", "answer_mismatch", "测试未通过")

    service = app.state.training
    service.runner = WaitingRunner()
    data = SubmitAnswer(request_id=uuid4(), answer_text="SELECT 1")
    user_id = session["user"]["id"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.submit, task["id"], data, user_id)
        try:
            assert entered.wait(timeout=5)
            pending = service.submit(task["id"], data, user_id)
            assert pending.status == "pending"
            with pytest.raises(HTTPException) as error:
                service.submit(
                    task["id"], SubmitAnswer(request_id=uuid4(), answer_text="SELECT 2"), user_id
                )
            assert error.value.status_code == 409
        finally:
            release.set()
        result = future.result(timeout=5)
    assert result.id == pending.id
    assert len(service.repository.submissions(task["id"], user_id)) == 1


def test_interrupted_pending_is_recovered_without_reexecution(training):
    task = create(training)
    record = submit(training, task["id"], "SELECT 1").json()
    _, app, session, _ = training
    with app.state.database.connect() as connection:
        connection.execute(
            "UPDATE training_submissions SET status='pending' WHERE id=?", (record["id"],)
        )
    assert app.state.training.recover_interrupted() == 1
    result = app.state.training.repository.submission(record["id"], session["user"]["id"])
    assert result.status == "error"
    assert result.evaluation_payload.code == "execution_interrupted"


def test_agent_contract_keeps_agent_execution_distinct_from_training_progress(training):
    _, app, session, diagnosis_id = training
    result = app.state.training_agent.run(
        AgentRequest(
            task_id="orchestrator-call-1",
            user_id=session["user"]["id"],
            goal="SQL 训练",
            context={"diagnosis_id": diagnosis_id, "requirement_id": "req-sql-01"},
        )
    )
    assert result.status == "completed"
    assert result.data["training_task"]["status"] == "planned"


def test_local_migration_is_repeatable_and_preserves_accounts(training):
    _, app, session, _ = training
    app.state.database.migrate_local()
    with app.state.database.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute(
            "SELECT id FROM users WHERE id=?", (session["user"]["id"],)
        ).fetchone()


def test_composite_fk_rejects_cross_owner_even_when_api_is_bypassed(training):
    task = create(training)
    _, app, _, _ = training
    with pytest.raises(sqlite3.IntegrityError), app.state.database.connect() as connection:
        connection.execute(
            "INSERT INTO training_submissions(id,user_id,training_task_id,attempt_no,answer_text,"
            "status,evaluation_payload,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (str(uuid4()), str(uuid4()), task["id"], 1, "SELECT 1", "pending", "{}", 0),
        )


def test_failed_local_schema_does_not_claim_migration_success(tmp_path, monkeypatch):
    import app.agents.training.database as module

    database = SQLiteTrainingDatabase(tmp_path / "failed.sqlite3")
    monkeypatch.setattr(module, "JOB_SCHEMA", "INVALID SQL;")
    with pytest.raises(sqlite3.Error):
        database.migrate_local()
    with database.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert not connection.execute(
            "SELECT name FROM sqlite_master WHERE name='training_local_schema'"
        ).fetchone()


def test_real_runner_accepts_reference_answer():
    result = SQLRunner(TrainingSettings()).check(REFERENCE_SQL)
    assert result.status == "passed", result
    assert result.passed_cases == 3


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM customers",
        "DROP TABLE orders",
        "ATTACH DATABASE '/tmp/x' AS x",
        "PRAGMA database_list",
        "SELECT * FROM sqlite_master",
        "SELECT load_extension('anything')",
        "SELECT readfile('anything')",
        "SELECT 1; SELECT 2",
        "SELECT * FROM missing_table",
        "SELECT randomblob(100000000)",
        "SELECT c.id, COUNT(*), SUM(o.amount_cents) FROM customers c "
        "JOIN orders o ON c.id=o.customer_id GROUP BY c.id",
    ],
)
def test_real_runner_rejects_forbidden_or_wrong_sql(sql):
    result = SQLRunner(TrainingSettings()).check(sql)
    assert result.status == "failed", result


def test_real_runner_limits_recursive_query():
    result = SQLRunner(TrainingSettings(sql_max_steps=1000)).check(
        "WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x) SELECT SUM(n) FROM x"
    )
    assert result.status == "error" and result.code == "execution_timeout", result


def test_real_chroma_persists_synthetic_documents_and_exact_citations(tmp_path):
    settings = TrainingSettings(chroma_path=tmp_path / "chroma")
    knowledge = TrainingKnowledge(settings)
    assert knowledge.seed() == 6
    assert knowledge.seed() == 6
    references = TrainingKnowledge(settings).search("SQL LEFT JOIN COUNT SUM 订单统计", limit=2)
    assert len(references) == 2
    assert "SQL 多表查询" in references[0].excerpt
    assert all(
        hashlib.sha256(item.excerpt.encode()).hexdigest() == item.content_sha256
        for item in references
    )
    assert embed("SQL") == embed("SQL")


def test_settings_refuse_other_databases_or_remote_servers():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TrainingSettings(mysql_database="existing_business_database")
    with pytest.raises(ValidationError):
        TrainingSettings(mysql_host="192.168.1.10")


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("excerpt", "原文从未出现的内容", "evidence_not_verbatim"),
        ("source", "resume:unrelated-id", "invalid_evidence_source"),
        ("start", 0, "evidence_position_mismatch"),
    ],
)
def test_fabricated_or_mislocated_diagnosis_evidence_is_rejected(training, field, value, code):
    client, app, session, diagnosis_id = training
    with app.state.database.connect() as connection:
        row = connection.execute(
            "SELECT result_payload FROM diagnosis_tasks WHERE id=?", (diagnosis_id,)
        ).fetchone()
        payload = json.loads(row["result_payload"])
        payload["gaps"][0][field] = value
        connection.execute(
            "UPDATE diagnosis_tasks SET result_payload=? WHERE id=?",
            (json.dumps(payload, ensure_ascii=False), diagnosis_id),
        )
    response = client.post(
        "/api/v1/training/tasks",
        json={
            "diagnosis_id": diagnosis_id,
            "requirement_id": "req-sql-01",
        },
        headers={"X-CSRF-Token": session["csrf_token"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_knowledge_outage_is_structured_and_creates_no_task(training):
    client, app, session, diagnosis_id = training

    class UnavailableKnowledge:
        def search(self, query):
            raise RuntimeError("internal connection settings must not be disclosed")

    app.state.training.knowledge = UnavailableKnowledge()
    response = client.get("/api/v1/training/materials?query=SQL")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "knowledge_unavailable"
    assert "internal connection" not in response.text
    response = client.post(
        "/api/v1/training/tasks",
        json={
            "diagnosis_id": diagnosis_id,
            "requirement_id": "req-sql-01",
        },
        headers={"X-CSRF-Token": session["csrf_token"]},
    )
    assert response.status_code == 503
    assert client.get("/api/v1/training/tasks").json() == []
