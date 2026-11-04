import argparse
import json
import secrets
from uuid import uuid4

from fastapi.testclient import TestClient

from app.agents.training.application import create_training_app
from app.agents.training.database import build_database
from app.agents.training.demo import seed_diagnosis
from app.agents.training.exercises import REFERENCE_SQL
from app.agents.training.knowledge import TrainingKnowledge
from app.agents.training.settings import LOCAL_ROOT, TrainingSettings

ORIGIN = "http://127.0.0.1:5173"


def smoke(settings: TrainingSettings):
    app = create_training_app(settings)
    checks = []
    with TestClient(app, headers={"Origin": ORIGIN}) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": f"training-c-{uuid4().hex}@example.com",
                "password": secrets.token_urlsafe(24),
                "display_name": "C 本地模拟用户",
            },
        )
        assert response.status_code == 201, "Synthetic registration failed"
        session = response.json()
        headers = {"X-CSRF-Token": session["csrf_token"]}
        diagnosis_id = seed_diagnosis(app.state.database, session["user"]["id"])
        response = client.post(
            "/api/v1/training/tasks",
            headers=headers,
            json={
                "diagnosis_id": diagnosis_id,
                "requirement_id": "req-sql-01",
            },
        )
        assert response.status_code == 201, "Task generation failed"
        task_id = response.json()["id"]
        checks.append("task_planned_with_chroma_references")
        wrong = client.post(
            f"/api/v1/training/tasks/{task_id}/submissions",
            headers=headers,
            json={"request_id": str(uuid4()), "answer_text": "SELECT 1"},
        )
        assert wrong.status_code == 201 and wrong.json()["status"] == "failed"
        checks.append("wrong_answer_failed_without_evidence")
        request_id = str(uuid4())
        correct = client.post(
            f"/api/v1/training/tasks/{task_id}/submissions",
            headers=headers,
            json={"request_id": request_id, "answer_text": REFERENCE_SQL},
        )
        assert correct.status_code == 201 and correct.json()["status"] == "passed"
        checks.append("correct_answer_verified")
        repeated = client.post(
            f"/api/v1/training/tasks/{task_id}/submissions",
            headers=headers,
            json={"request_id": request_id, "answer_text": REFERENCE_SQL},
        )
        assert repeated.json()["id"] == correct.json()["id"]
        checks.append("idempotency_same_submission")
        evidence = client.get(f"/api/v1/training/diagnoses/{diagnosis_id}/evidence")
        assert evidence.status_code == 200 and len(evidence.json()["evidence"]) == 1
        checks.append("one_traceable_training_evidence")
        user_id = session["user"]["id"]
    return {
        "database_backend": settings.database_backend,
        "database": settings.mysql_database
        if settings.database_backend == "mysql"
        else str(settings.sqlite_path),
        "synthetic_user_id": user_id,
        "diagnosis_id": diagnosis_id,
        "training_task_id": task_id,
        "checks_passed": checks,
        "real_llm_called": False,
        "knowledge": TrainingKnowledge(settings).status(),
    }


def main():
    parser = argparse.ArgumentParser(description="Explicit Task C local-only tooling")
    parser.add_argument(
        "command", choices=["probe", "bootstrap", "seed-knowledge", "seed-diagnosis", "smoke"]
    )
    parser.add_argument("--backend", choices=["sqlite", "mysql"])
    parser.add_argument("--user-id")
    args = parser.parse_args()
    overrides = {"database_backend": args.backend} if args.backend else {}
    settings = TrainingSettings(**overrides)
    database = build_database(settings)
    if args.command == "probe":
        if database.dialect == "mysql":
            raw = database._open(select_database=False)
            try:
                with raw.cursor() as cursor:
                    cursor.execute("SELECT VERSION() AS version, CURRENT_USER() AS account")
                    print(json.dumps(cursor.fetchone()))
            finally:
                raw.close()
        else:
            print(json.dumps({"backend": "sqlite", "path": str(settings.sqlite_path)}))
    elif args.command == "bootstrap":
        database.migrate_local()
        print(
            json.dumps(
                {
                    "backend": database.dialect,
                    "schema": "task-c-local-pr7-v1",
                    "formal_team_migration": False,
                }
            )
        )
    elif args.command == "seed-knowledge":
        count = TrainingKnowledge(settings).seed()
        print(
            json.dumps(
                {
                    "documents": count,
                    "path": str(settings.chroma_path),
                    "embedding_profile": "local-test-hash-v1",
                }
            )
        )
    elif args.command == "seed-diagnosis":
        if not args.user_id:
            parser.error("--user-id is required; register an account first")
        print(
            json.dumps({"diagnosis_id": seed_diagnosis(database, args.user_id), "synthetic": True})
        )
    else:
        result = smoke(settings)
        LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
        report = LOCAL_ROOT / f"acceptance-{settings.database_backend}-{uuid4().hex[:8]}.json"
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"report": str(report), "checks_passed": result["checks_passed"]}))


if __name__ == "__main__":
    main()
