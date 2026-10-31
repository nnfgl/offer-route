import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Numbered migrations make shared schema changes reviewable. Never edit an applied migration.
MIGRATIONS = [
    """
    CREATE TABLE users (
      id TEXT PRIMARY KEY,
      email TEXT NOT NULL UNIQUE,
      display_name TEXT NOT NULL,
      password_hash TEXT NOT NULL,
      created_at INTEGER NOT NULL
    );
    CREATE TABLE sessions (
      token_hash TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      csrf_token TEXT NOT NULL,
      expires_at INTEGER NOT NULL
    );
    CREATE INDEX sessions_expiry ON sessions(expires_at);
    """,
    """
    CREATE TABLE interviews (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      created_at INTEGER NOT NULL,
      payload TEXT NOT NULL
    );
    CREATE INDEX interviews_owner ON interviews(user_id, created_at);
    """,
    """
    CREATE TABLE voice_interviews (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      created_at INTEGER NOT NULL,
      payload TEXT NOT NULL
    );
    CREATE INDEX voice_interviews_owner ON voice_interviews(user_id, created_at);
    """,
]


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            # Feature branches published different v2 migrations. A version number alone
            # cannot identify their schemas; never apply this branch's v3 to a job v2 DB.
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            # A owns the common migration queue. A provisioned shared schema needs
            # none of this branch's legacy DDL, irrespective of the old v2 collision.
            if {
                "users",
                "sessions",
                "job_analysis_tasks",
                "diagnosis_tasks",
                "interview_sessions",
                "interview_turns",
            } <= tables:
                connection.execute("PRAGMA journal_mode = WAL")
                return
            if version > len(MIGRATIONS):
                raise RuntimeError("数据库版本高于当前分支，请更新到团队统一迁移版本")
            required = [(1, "users"), (1, "sessions"), (2, "interviews"), (3, "voice_interviews")]
            if any(version >= applied and table not in tables for applied, table in required):
                raise RuntimeError(
                    "数据库迁移编号与当前分支表结构不一致，请保留原数据库并由 A 协调统一迁移。"
                    "不要修改 user_version 或重新运行建表参考 SQL。"
                )
            connection.execute("PRAGMA journal_mode = WAL")
            for index in range(version, len(MIGRATIONS)):
                connection.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + MIGRATIONS[index]
                    + f"\nPRAGMA user_version = {index + 1};\nCOMMIT;"
                )
