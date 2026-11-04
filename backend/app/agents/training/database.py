"""Local adapters; never modify core.MIGRATIONS or claim a team v3 migration."""

import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.agents.training.settings import TrainingSettings
from app.core.database import Database

HERE = Path(__file__).parent
SCHEMA_TAG = "task-c-local-pr7-v1"
JOB_SCHEMA = """
CREATE TABLE job_analysis_tasks (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 title TEXT NOT NULL, source_text TEXT NOT NULL, provider TEXT NOT NULL,
 status TEXT NOT NULL, payload TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE INDEX job_tasks_owner ON job_analysis_tasks(user_id,created_at DESC);
"""


class SQLiteTrainingDatabase(Database):
    dialect = "sqlite"

    def migrate_local(self) -> None:
        # This optional entry point now shares the canonical SQLite migration queue.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if (
                "training_tasks" in tables or "diagnosis_tasks" in tables
            ) and "training_local_schema" not in tables:
                raise RuntimeError("Refusing to adopt unmarked experimental tables")
        super().migrate()
        with self.connect() as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "training_local_schema" in tables:
                self.validate_schema()
                return
            connection.executescript(
                "BEGIN IMMEDIATE;\n"
                + "CREATE TABLE training_local_schema (tag TEXT PRIMARY KEY);\n"
                + f"INSERT INTO training_local_schema VALUES ('{SCHEMA_TAG}');\nCOMMIT;"
            )

    def validate_schema(self) -> None:
        with self.connect() as connection:
            row = connection.execute("SELECT tag FROM training_local_schema").fetchone()
            if row is None or row[0] != SCHEMA_TAG:
                raise RuntimeError("Unexpected local schema; no automatic replacement is allowed")


class MySQLConnection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql: str, params=()):
        import pymysql

        cursor = self.raw.cursor()
        try:
            cursor.execute(sql.replace("?", "%s"), params)
        except pymysql.IntegrityError as exc:
            cursor.close()
            # Reuse the existing auth module's duplicate-account error handling.
            raise sqlite3.IntegrityError("Database constraint rejected the operation") from exc
        return cursor


class MySQLTrainingDatabase:
    dialect = "mysql"

    def __init__(self, settings: TrainingSettings):
        self.settings = settings

    def _open(self, *, select_database: bool = True):
        import pymysql

        if self.settings.mysql_password is None:
            raise RuntimeError(
                "Set the password in .env.training-local; never read Navicat secrets"
            )
        return pymysql.connect(
            host=self.settings.mysql_host,
            port=self.settings.mysql_port,
            user=self.settings.mysql_user,
            password=self.settings.mysql_password.get_secret_value(),
            database=self.settings.mysql_database if select_database else None,
            charset="utf8mb4",
            autocommit=False,
            connect_timeout=5,
            read_timeout=10,
            write_timeout=10,
            cursorclass=pymysql.cursors.DictCursor,
        )

    @contextmanager
    def connect(self):
        raw = self._open()
        try:
            yield MySQLConnection(raw)
            raw.commit()
        except BaseException:
            raw.rollback()
            raise
        finally:
            raw.close()

    def migrate_local(self) -> None:
        """Explicit bootstrap only. MySQL DDL commits implicitly; never drop or replace tables."""
        schema = (HERE / "mysql_schema.sql").read_text(encoding="utf-8")
        digest = hashlib.sha256(schema.encode()).hexdigest()
        raw = self._open(select_database=False)
        name = self.settings.mysql_database  # Strictly allowlisted by TrainingSettings.
        try:
            with raw.cursor() as cursor:
                cursor.execute(
                    "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
                    (name,),
                )
                exists = cursor.fetchone() is not None
                if not exists:
                    cursor.execute(
                        f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    )
                raw.select_db(name)
                cursor.execute("SHOW TABLES")
                tables = {next(iter(row.values())) for row in cursor.fetchall()}
                if tables:
                    if "training_local_schema" not in tables:
                        raise RuntimeError("Existing unmarked database: no tables will be changed")
                    cursor.execute("SELECT tag, checksum FROM training_local_schema")
                    marker = cursor.fetchone()
                    if marker != {"tag": SCHEMA_TAG, "checksum": digest}:
                        raise RuntimeError("Schema checksum differs; manual review is required")
                    return
                for statement in schema.split(";"):
                    if statement.strip():
                        cursor.execute(statement)
                cursor.execute(
                    "CREATE TABLE training_local_schema (tag VARCHAR(64) PRIMARY KEY, "
                    "checksum CHAR(64) NOT NULL) ENGINE=InnoDB"
                )
                cursor.execute(
                    "INSERT INTO training_local_schema(tag,checksum) VALUES (%s,%s)",
                    (SCHEMA_TAG, digest),
                )
                raw.commit()
        finally:
            raw.close()

    def validate_schema(self) -> None:
        schema = (HERE / "mysql_schema.sql").read_text(encoding="utf-8")
        digest = hashlib.sha256(schema.encode()).hexdigest()
        with self.connect() as connection:
            row = connection.execute("SELECT tag, checksum FROM training_local_schema").fetchone()
            if row != {"tag": SCHEMA_TAG, "checksum": digest}:
                raise RuntimeError("Run the explicit local bootstrap or review schema differences")


def build_database(settings: TrainingSettings):
    if settings.database_backend == "mysql":
        return MySQLTrainingDatabase(settings)
    return SQLiteTrainingDatabase(settings.sqlite_path)
