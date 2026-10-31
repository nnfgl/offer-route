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
    CREATE TABLE job_analysis_tasks (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      title TEXT NOT NULL,
      source_text TEXT NOT NULL,
      provider TEXT NOT NULL,
      status TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at INTEGER NOT NULL
    );
    CREATE INDEX job_tasks_owner ON job_analysis_tasks(user_id, created_at DESC);
    """,
    """
    CREATE TABLE resumes (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      title TEXT NOT NULL,
      source_text TEXT NOT NULL CHECK (length(trim(source_text)) > 0),
      parsed_payload TEXT NOT NULL DEFAULT '{}',
      created_at INTEGER NOT NULL CHECK (created_at >= 0),
      UNIQUE(id, user_id)
    );
    CREATE INDEX resumes_owner ON resumes(user_id, created_at DESC);
    CREATE UNIQUE INDEX job_tasks_id_owner ON job_analysis_tasks(id, user_id);
    CREATE TABLE diagnosis_tasks (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      job_analysis_id TEXT NOT NULL,
      resume_id TEXT NOT NULL,
      status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'needs_input', 'failed')),
      result_payload TEXT NOT NULL DEFAULT '{}',
      created_at INTEGER NOT NULL CHECK (created_at >= 0),
      updated_at INTEGER NOT NULL CHECK (updated_at >= created_at),
      UNIQUE(id, user_id),
      FOREIGN KEY(job_analysis_id, user_id)
        REFERENCES job_analysis_tasks(id, user_id) ON DELETE CASCADE,
      FOREIGN KEY(resume_id, user_id)
        REFERENCES resumes(id, user_id) ON DELETE CASCADE
    );
    CREATE INDEX diagnosis_owner ON diagnosis_tasks(user_id, created_at DESC);
    CREATE INDEX diagnosis_job ON diagnosis_tasks(job_analysis_id, user_id);
    CREATE INDEX diagnosis_resume ON diagnosis_tasks(resume_id, user_id);
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
            connection.execute("PRAGMA journal_mode = WAL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            for index in range(version, len(MIGRATIONS)):
                connection.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + MIGRATIONS[index]
                    + f"\nPRAGMA user_version = {index + 1};\nCOMMIT;"
                )
