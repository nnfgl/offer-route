import time

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.modules.auth.security import password_hasher, token_digest

ORIGIN = {"Origin": "http://localhost:5173"}
ACCOUNT = {
    "email": "teammate@example.com",
    "password": "correct-horse-battery",
    "display_name": "小林",
}


@pytest.fixture
def client(tmp_path):
    settings = Settings(environment="test", database_path=tmp_path / "test.db", auth_rate_limit=100)
    with TestClient(create_app(settings), headers=ORIGIN) as test_client:
        yield test_client


def register(client):
    response = client.post("/api/v1/auth/register", json=ACCOUNT)
    assert response.status_code == 201
    return response


def test_register_restore_logout_and_protected_access(client):
    assert client.get("/api/v1/workspace").status_code == 401
    response = register(client)
    assert response.json()["user"]["display_name"] == "小林"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "password" not in response.text
    assert client.get("/api/v1/auth/me").json() == response.json()
    workspace = client.get("/api/v1/workspace")
    assert len(workspace.json()["modules"]) == 4
    assert workspace.headers["cache-control"] == "no-store"
    result = client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": response.json()["csrf_token"]}
    )
    assert result.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/workspace").status_code == 401


def test_password_is_hashed_and_session_is_not_stored_in_plaintext(client):
    register(client)
    token = client.cookies.get("offer_session")
    with client.app.state.database.connect() as connection:
        user = connection.execute("SELECT * FROM users").fetchone()
        session = connection.execute("SELECT * FROM sessions").fetchone()
    assert user["password_hash"].startswith("$argon2id$")
    assert password_hasher.verify(ACCOUNT["password"], user["password_hash"])
    assert session["token_hash"] == token_digest(token)
    assert token not in str(dict(session))


def test_duplicate_case_insensitive_email(client):
    register(client)
    response = client.post(
        "/api/v1/auth/register", json={**ACCOUNT, "email": "TEAMMATE@example.com"}
    )
    assert response.status_code == 409
    with client.app.state.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


@pytest.mark.parametrize("email", ["teammate@example.com", "unknown@example.com"])
def test_invalid_login_has_generic_error(client, email):
    register(client)
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "not-the-password"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_successful_login_rotates_and_revokes_old_session(client):
    registered = register(client)
    old_token = client.cookies.get("offer_session")
    logged_in = client.post("/api/v1/auth/login", json=ACCOUNT)
    assert logged_in.status_code == 200
    assert client.cookies.get("offer_session") != old_token
    assert logged_in.json()["csrf_token"] != registered.json()["csrf_token"]
    assert (
        client.get("/api/v1/auth/me", headers={"Cookie": f"offer_session={old_token}"}).status_code
        == 401
    )


def test_logout_requires_csrf_and_trusted_origin(client):
    session = register(client).json()
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert (
        client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "https://evil.example", "X-CSRF-Token": session["csrf_token"]},
        ).status_code
        == 403
    )
    assert client.get("/api/v1/auth/me").status_code == 200


@pytest.mark.parametrize("endpoint", ["register", "login"])
def test_cross_site_auth_rejected(client, endpoint):
    response = client.post(
        f"/api/v1/auth/{endpoint}", json=ACCOUNT, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403


def test_missing_origin_rejected(client):
    client.headers.pop("origin")
    assert client.post("/api/v1/auth/register", json=ACCOUNT).status_code == 403


@pytest.mark.parametrize(
    "changes",
    [
        {"password": "short"},
        {"email": "invalid"},
        {"display_name": "   "},
        {"password": "x" * 129},
    ],
)
def test_validation_does_not_echo_password(client, changes):
    response = client.post("/api/v1/auth/register", json={**ACCOUNT, **changes})
    assert response.status_code == 422
    assert ACCOUNT["password"] not in response.text
    assert changes.get("password", "never-present") not in response.text


def test_expired_and_forged_sessions_rejected(client):
    register(client)
    with client.app.state.database.connect() as connection:
        connection.execute("UPDATE sessions SET expires_at = ?", (int(time.time()) - 1,))
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.set("offer_session", "forged-token")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_logout_revokes_session_server_side(client):
    registered = register(client)
    token = client.cookies.get("offer_session")
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": registered.json()["csrf_token"]})
    assert (
        client.get("/api/v1/auth/me", headers={"Cookie": f"offer_session={token}"}).status_code
        == 401
    )


def test_separate_users_have_separate_sessions(client):
    first = register(client).json()["user"]
    with TestClient(client.app, headers=ORIGIN) as another:
        second = another.post(
            "/api/v1/auth/register",
            json={**ACCOUNT, "email": "another@example.com", "display_name": "另一位同学"},
        ).json()["user"]
        assert second["id"] != first["id"]
        assert another.get("/api/v1/auth/me").json()["user"] == second
        assert client.get("/api/v1/auth/me").json()["user"] == first


def test_rate_limit(tmp_path):
    settings = Settings(environment="test", database_path=tmp_path / "rate.db", auth_rate_limit=2)
    with TestClient(create_app(settings), headers=ORIGIN) as client:
        for _ in range(2):
            assert client.post("/api/v1/auth/login", json=ACCOUNT).status_code == 401
        response = client.post("/api/v1/auth/login", json=ACCOUNT)
        assert response.status_code == 429
        assert "retry-after" in response.headers


def test_database_survives_app_restart(tmp_path):
    settings = Settings(environment="test", database_path=tmp_path / "persistent.db")
    with TestClient(create_app(settings), headers=ORIGIN) as first:
        register(first)
    with TestClient(create_app(settings), headers=ORIGIN) as second:
        assert second.post("/api/v1/auth/login", json=ACCOUNT).status_code == 200


def test_production_configuration_requires_https(tmp_path):
    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        Settings(environment="production", database_path=tmp_path / "prod.db")
    with pytest.raises(ValueError, match="HTTPS"):
        Settings(environment="production", cookie_secure=True)
