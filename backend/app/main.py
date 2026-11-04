from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.agents.diagnosis.service import DiagnosisWorkflow
from app.agents.interview.router import router as interview_router
from app.agents.interview.voice_router import router as voice_router
from app.agents.orchestration.service import JobWorkflow
from app.agents.training.agent import TrainingAgent
from app.agents.training.knowledge import BundledTrainingKnowledge
from app.agents.training.router import router as training_router
from app.agents.training.runner import SQLRunner
from app.agents.training.service import TrainingService
from app.agents.training.settings import TrainingSettings
from app.core.config import Settings
from app.core.database import Database
from app.core.errors import install_error_handlers
from app.core.model_client import DeepSeekClient
from app.modules.auth.router import current_user, router
from app.modules.auth.schemas import UserOutput
from app.modules.auth.security import RateLimiter
from app.modules.diagnosis.router import router as diagnosis_router
from app.modules.jobs.router import router as jobs_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    database = Database(settings.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.migrate()
        app.state.job_workflow.recover_interrupted()
        app.state.diagnosis_workflow.recover_interrupted()
        app.state.training.recover_interrupted()
        yield

    app = FastAPI(title="Offer Route API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database
    app.state.job_workflow = JobWorkflow(database, settings, DeepSeekClient(settings))
    app.state.job_rate_limiter = RateLimiter(6, 60)
    app.state.diagnosis_workflow = DiagnosisWorkflow(database, settings, DeepSeekClient(settings))
    app.state.diagnosis_rate_limiter = RateLimiter(6, 60)
    app.state.rate_limiter = RateLimiter(
        settings.auth_rate_limit, settings.auth_rate_window_seconds
    )
    app.state.voice_limiter = RateLimiter(10, 60)
    app.state.training = TrainingService(
        database,
        SQLRunner(TrainingSettings(_env_file=None, database_backend="sqlite")),
        BundledTrainingKnowledge(),
    )
    app.state.training_agent = TrainingAgent(app.state.training)
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
    app.include_router(diagnosis_router, prefix="/api/v1")
    app.include_router(interview_router, prefix="/api/v1")
    app.include_router(voice_router, prefix="/api/v1")
    app.include_router(training_router, prefix="/api/v1")

    @app.get("/api/v1/health", tags=["system"])
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/v1/workspace", tags=["workspace"])
    def workspace(user: UserOutput = Depends(current_user)):
        return {
            "user": user,
            "modules": [
                {"id": "job", "title": "岗位分析", "status": "available"},
                {"id": "diagnosis", "title": "能力诊断", "status": "available"},
                {"id": "training", "title": "实战训练", "status": "available"},
                {"id": "interview", "title": "模拟面试", "status": "available"},
            ],
        }

    return app


app = create_app()
