from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.agents.orchestration.service import JobWorkflow
from app.core.config import Settings
from app.core.database import Database
from app.core.errors import install_error_handlers
from app.core.model_client import DeepSeekClient
from app.modules.auth.router import current_user, router
from app.modules.auth.schemas import UserOutput
from app.modules.auth.security import RateLimiter
from app.modules.jobs.router import router as jobs_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    database = Database(settings.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.migrate()
        app.state.job_workflow.recover_interrupted()
        yield

    app = FastAPI(title="Offer Route API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database
    app.state.job_workflow = JobWorkflow(database, settings, DeepSeekClient(settings))
    app.state.job_rate_limiter = RateLimiter(6, 60)
    app.state.rate_limiter = RateLimiter(
        settings.auth_rate_limit, settings.auth_rate_window_seconds
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )
    install_error_handlers(app)

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(router, prefix="/api/v1")
    app.include_router(jobs_router, prefix="/api/v1")

    @app.get("/api/v1/health", tags=["system"])
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/v1/workspace", tags=["workspace"])
    def workspace(user: UserOutput = Depends(current_user)):
        return {
            "user": user,
            "modules": [
                {"id": "job", "title": "岗位分析", "status": "available"},
                {"id": "diagnosis", "title": "能力诊断", "status": "planned"},
                {"id": "training", "title": "实战训练", "status": "planned"},
                {"id": "interview", "title": "模拟面试", "status": "planned"},
            ],
        }

    return app


app = create_app()
