import secrets
import sqlite3
import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.modules.auth.schemas import Credentials, RegisterInput, SessionOutput, UserOutput
from app.modules.auth.security import DUMMY_HASH, password_hasher, token_digest

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE_NAME = "offer_session"


def check_origin(request: Request) -> None:
    if request.headers.get("origin") not in request.app.state.settings.allowed_origins:
        raise HTTPException(403, {"code": "invalid_origin", "message": "请求来源不被允许"})


def rate_limit(request: Request) -> None:
    # Do not trust user-provided forwarding headers.
    request.app.state.rate_limiter.check(request.client.host if request.client else "unknown")


def current_session(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        with request.app.state.database.connect() as connection:
            row = connection.execute(
                "SELECT u.id, u.email, u.display_name, s.csrf_token FROM sessions s "
                "JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?",
                (token_digest(token), int(time.time())),
            ).fetchone()
        if row:
            return dict(row)
    raise HTTPException(401, {"code": "unauthenticated", "message": "请先登录"})


def current_user(session: dict = Depends(current_session)) -> UserOutput:
    return UserOutput.model_validate(session)


def issue_session(request: Request, response: Response, user: UserOutput) -> SessionOutput:
    settings = request.app.state.settings
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = int(time.time())
    old_token = request.cookies.get(COOKIE_NAME)
    with request.app.state.database.connect() as connection:
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        if old_token:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (token_digest(old_token),)
            )
        connection.execute(
            "INSERT INTO sessions(token_hash, user_id, csrf_token, expires_at) VALUES (?, ?, ?, ?)",
            (token_digest(token), user.id, csrf, now + settings.session_ttl_seconds),
        )
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api",
    )
    return SessionOutput(user=user, csrf_token=csrf)


@router.post(
    "/register",
    response_model=SessionOutput,
    status_code=201,
    dependencies=[Depends(check_origin), Depends(rate_limit)],
)
def register(data: RegisterInput, request: Request, response: Response):
    user = UserOutput(id=str(uuid4()), email=str(data.email), display_name=data.display_name)
    encoded = password_hasher.hash(data.password)
    try:
        with request.app.state.database.connect() as connection:
            connection.execute(
                "INSERT INTO users(id, email, display_name, password_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user.id, user.email, user.display_name, encoded, int(time.time())),
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            409, {"code": "email_unavailable", "message": "该邮箱无法注册，请尝试登录"}
        ) from exc
    return issue_session(request, response, user)


@router.post(
    "/login",
    response_model=SessionOutput,
    dependencies=[Depends(check_origin), Depends(rate_limit)],
)
def login(data: Credentials, request: Request, response: Response):
    with request.app.state.database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE email = ?", (str(data.email),)
        ).fetchone()
    valid = password_hasher.verify(data.password, row["password_hash"] if row else DUMMY_HASH)
    if not row or not valid:
        raise HTTPException(401, {"code": "invalid_credentials", "message": "邮箱或密码错误"})
    return issue_session(request, response, UserOutput.model_validate(dict(row)))


@router.get("/me", response_model=SessionOutput)
def me(session: dict = Depends(current_session)):
    return SessionOutput(user=UserOutput.model_validate(session), csrf_token=session["csrf_token"])


def require_csrf(request: Request, session: dict = Depends(current_session)) -> None:
    """Use on every authenticated mutation added by business modules."""
    check_origin(request)
    if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), session["csrf_token"]):
        raise HTTPException(403, {"code": "invalid_csrf", "message": "请求校验失败，请刷新后重试"})


@router.post("/logout", status_code=204, dependencies=[Depends(require_csrf)])
def logout(request: Request, response: Response):
    with request.app.state.database.connect() as connection:
        connection.execute(
            "DELETE FROM sessions WHERE token_hash = ?",
            (token_digest(request.cookies[COOKIE_NAME]),),
        )
    response.delete_cookie(
        COOKIE_NAME,
        path="/api",
        secure=request.app.state.settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
