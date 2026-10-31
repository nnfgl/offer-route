-- DESIGN REFERENCE ONLY. Not loaded by the application.
-- Requires the existing v1 (users/sessions) and PR #5 v2 (job_analysis_tasks).
-- A must review and append a numbered migration before team members use these tables.
-- Execute against an isolated database for review, not an existing development database.

PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE UNIQUE INDEX job_tasks_id_owner ON job_analysis_tasks(id, user_id);

CREATE TABLE resumes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    source_text TEXT NOT NULL CHECK(length(trim(source_text)) > 0),
    parsed_payload TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(parsed_payload)),
    created_at INTEGER NOT NULL CHECK(created_at >= 0),
    UNIQUE(id, user_id)
);
CREATE INDEX resumes_owner ON resumes(user_id, created_at DESC);

CREATE TABLE diagnosis_tasks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_analysis_id TEXT NOT NULL,
    resume_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'needs_input', 'failed')),
    result_payload TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(result_payload)),
    created_at INTEGER NOT NULL CHECK(created_at >= 0),
    updated_at INTEGER NOT NULL CHECK(updated_at >= created_at),
    UNIQUE(id, user_id),
    FOREIGN KEY(job_analysis_id, user_id) REFERENCES job_analysis_tasks(id, user_id) ON DELETE CASCADE,
    FOREIGN KEY(resume_id, user_id) REFERENCES resumes(id, user_id) ON DELETE CASCADE
);
CREATE INDEX diagnosis_owner ON diagnosis_tasks(user_id, created_at DESC);
CREATE INDEX diagnosis_job ON diagnosis_tasks(job_analysis_id, user_id);
CREATE INDEX diagnosis_resume ON diagnosis_tasks(resume_id, user_id);

CREATE TABLE training_tasks (
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
CREATE INDEX training_owner ON training_tasks(user_id, created_at DESC);
CREATE INDEX training_diagnosis ON training_tasks(diagnosis_id, user_id);

CREATE TABLE training_submissions (
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
CREATE INDEX submissions_owner ON training_submissions(user_id, created_at DESC);

CREATE TABLE interview_sessions (
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
    FOREIGN KEY(job_analysis_id, user_id) REFERENCES job_analysis_tasks(id, user_id) ON DELETE CASCADE,
    FOREIGN KEY(diagnosis_id, user_id) REFERENCES diagnosis_tasks(id, user_id) ON DELETE CASCADE
);
CREATE INDEX interview_sessions_owner ON interview_sessions(user_id, created_at DESC);
CREATE INDEX interviews_job ON interview_sessions(job_analysis_id, user_id);
CREATE INDEX interviews_diagnosis ON interview_sessions(diagnosis_id, user_id);

CREATE TABLE interview_turns (
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
CREATE INDEX turns_owner ON interview_turns(user_id, created_at DESC);

COMMIT;
