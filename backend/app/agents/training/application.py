"""Explicit local entry point; the shared main app and migration queue stay intact."""

import sqlite3
from contextlib import asynccontextmanager
from json import JSONDecodeError

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.agents.training.agent import TrainingAgent
from app.agents.training.database import build_database
from app.agents.training.knowledge import TrainingKnowledge
from app.agents.training.router import router
from app.agents.training.runner import SQLRunner
from app.agents.training.service import TrainingService
from app.agents.training.settings import TrainingSettings
from app.core.config import Settings
from app.main import create_app


def create_training_app(
    settings: TrainingSettings | None = None,
    *,
    knowledge=None,
    runner=None,
    initialize_sqlite: bool = False,
):
    training_settings = settings or TrainingSettings()
    database = build_database(training_settings)
    shared = create_app(Settings(database_path=training_settings.sqlite_path))
    shared.state.database = database
    shared.state.training_settings = training_settings

    @asynccontextmanager
    async def lifespan(app):
        if initialize_sqlite:
            if database.dialect != "sqlite":
                raise RuntimeError("MySQL schema creation requires the explicit bootstrap command")
            database.migrate_local()
        database.validate_schema()
        materials = knowledge if knowledge is not None else TrainingKnowledge(training_settings)
        service = TrainingService(database, runner or SQLRunner(training_settings), materials)
        app.state.training = service
        app.state.training_agent = TrainingAgent(service)
        service.recover_interrupted()
        yield

    shared.router.lifespan_context = lifespan
    shared.include_router(router, prefix="/api/v1")

    @shared.exception_handler(ValidationError)
    @shared.exception_handler(JSONDecodeError)
    async def stored_data_error(request: Request, exc: ValidationError):
        return JSONResponse(
            {"error": {"code": "stored_data_invalid", "message": "已保存的数据不符合当前版本约定"}},
            status_code=503,
        )

    @shared.exception_handler(sqlite3.IntegrityError)
    async def constraint_error(request: Request, exc):
        return JSONResponse(
            {"error": {"code": "database_conflict", "message": "数据关联或状态冲突，请重新查询"}},
            status_code=409,
        )

    @shared.exception_handler(sqlite3.DatabaseError)
    async def database_error(request: Request, exc):
        return JSONResponse(
            {"error": {"code": "database_unavailable", "message": "本地数据库暂不可用"}},
            status_code=503,
        )

    if database.dialect == "mysql":
        import pymysql

        shared.add_exception_handler(pymysql.MySQLError, database_error)

    return shared


app = create_training_app()
