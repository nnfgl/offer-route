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
    """

    CREATE TABLE IF NOT EXISTS interviews (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      created_at INTEGER NOT NULL,
      payload TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS interviews_owner ON interviews(user_id, created_at);
    

    CREATE TABLE IF NOT EXISTS voice_interviews (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      created_at INTEGER NOT NULL,
      payload TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS voice_interviews_owner ON voice_interviews(user_id, created_at);
    
CREATE TABLE IF NOT EXISTS training_tasks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    diagnosis_id TEXT NOT NULL,
    title TEXT NOT NULL,
    goal TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('planned', 'active', 'completed', 'archived')),
    task_payload TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(task_payload)),
    created_at INTEGER NOT NULL CHECK(created_at >= 0),
    updated_at INTEGER NOT NULL CHECK(updated_at >= created_at),
    UNIQUE(id, user_id),
    FOREIGN KEY(diagnosis_id, user_id) REFERENCES diagnosis_tasks(id, user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS training_owner ON training_tasks(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS training_diagnosis ON training_tasks(diagnosis_id, user_id);

CREATE TABLE IF NOT EXISTS training_submissions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    training_task_id TEXT NOT NULL,
    attempt_no INTEGER NOT NULL CHECK(attempt_no >= 1),
    answer_text TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'passed', 'failed', 'error')),
    evaluation_payload TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(evaluation_payload)),
    created_at INTEGER NOT NULL CHECK(created_at >= 0),
    UNIQUE(training_task_id, attempt_no),
    FOREIGN KEY(training_task_id, user_id) REFERENCES training_tasks(id, user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS submissions_owner ON training_submissions(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS interview_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_analysis_id TEXT NOT NULL,
    diagnosis_id TEXT,
    input_mode TEXT NOT NULL DEFAULT 'text' CHECK(input_mode IN ('text', 'voice')),
    status TEXT NOT NULL CHECK(status IN ('created', 'active', 'completed', 'cancelled', 'failed')),
    max_rounds INTEGER NOT NULL DEFAULT 5 CHECK(max_rounds BETWEEN 1 AND 20),
    report_payload TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(report_payload)),
    created_at INTEGER NOT NULL CHECK(created_at >= 0),
    updated_at INTEGER NOT NULL CHECK(updated_at >= created_at),
    UNIQUE(id, user_id),
    FOREIGN KEY(job_analysis_id, user_id)
      REFERENCES job_analysis_tasks(id, user_id) ON DELETE CASCADE,
    FOREIGN KEY(diagnosis_id, user_id) REFERENCES diagnosis_tasks(id, user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS interview_sessions_owner ON interview_sessions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS interviews_job ON interview_sessions(job_analysis_id, user_id);
CREATE INDEX IF NOT EXISTS interviews_diagnosis ON interview_sessions(diagnosis_id, user_id);

CREATE TABLE IF NOT EXISTS interview_turns (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    round_no INTEGER NOT NULL CHECK(round_no >= 1),
    question_text TEXT NOT NULL CHECK(length(trim(question_text)) > 0),
    answer_text TEXT,
    input_mode TEXT NOT NULL DEFAULT 'text' CHECK(input_mode IN ('text', 'voice')),
    status TEXT NOT NULL CHECK(status IN ('asked', 'answered', 'skipped')),
    audio_duration_ms INTEGER CHECK(audio_duration_ms BETWEEN 0 AND 60000),
    feedback_payload TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(feedback_payload)),
    created_at INTEGER NOT NULL CHECK(created_at >= 0),
    updated_at INTEGER NOT NULL CHECK(updated_at >= created_at),
    UNIQUE(session_id, round_no),
    FOREIGN KEY(session_id, user_id) REFERENCES interview_sessions(id, user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS turns_owner ON interview_turns(user_id, created_at DESC);

    """,
]


class Database:
    dialect = "sqlite"

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
        """Upgrade canonical and known D experimental layouts without dropping records."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > len(MIGRATIONS):
                raise RuntimeError("数据库版本高于当前分支，请更新代码")
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            required = {
                "users": {"id", "email", "display_name", "password_hash", "created_at"},
                "sessions": {"token_hash", "user_id", "csrf_token", "expires_at"},
                "job_analysis_tasks": {
                    "id",
                    "user_id",
                    "title",
                    "source_text",
                    "provider",
                    "status",
                    "payload",
                    "created_at",
                },
            }
            for table, columns in required.items():
                if table in tables and not columns <= {
                    row[1] for row in connection.execute(f"PRAGMA table_info({table})")
                }:
                    raise RuntimeError("数据库结构不完整，请保留原库并由 A 协调升级")
            if version and not {"users", "sessions"} <= tables:
                raise RuntimeError("数据库结构不完整，请由 A 协调升级")
            if ("resumes" in tables) != ("diagnosis_tasks" in tables):
                raise RuntimeError("诊断表结构不完整，请由 A 协调升级")
            if version >= 2 and not ({"job_analysis_tasks", "interviews"} & tables):
                raise RuntimeError("无法识别数据库分支布局，请由 A 协调升级")
            if version == len(MIGRATIONS):
                expected = {
                    "users",
                    "sessions",
                    "job_analysis_tasks",
                    "resumes",
                    "diagnosis_tasks",
                    "training_tasks",
                    "training_submissions",
                    "interviews",
                    "voice_interviews",
                    "interview_sessions",
                    "interview_turns",
                }
                if not expected <= tables:
                    raise RuntimeError("数据库迁移版本与表结构不一致，请由 A 协调升级")
                return
            steps = []
            if "users" not in tables:
                steps.append(MIGRATIONS[0])
            if "job_analysis_tasks" not in tables:
                steps.append(MIGRATIONS[1])
            if "diagnosis_tasks" not in tables:
                steps.append(MIGRATIONS[2])
            steps.append(MIGRATIONS[3])
            # sqlite3.executescript commits implicitly. Execute complete SQL statements
            # individually so layout detection and every DDL operation share one lock.
            statement = ""
            for line in "\n".join(steps).splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    connection.execute(statement)
                    statement = ""
            if statement.strip():
                raise RuntimeError("Incomplete migration SQL")
            connection.execute(f"PRAGMA user_version = {len(MIGRATIONS)}")
