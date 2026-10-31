-- LOCAL EXPERIMENT ONLY: a MySQL 8 translation of PR #7, not a team migration.
-- Run only through training.local_tools in the fixed, isolated Task C database.
CREATE TABLE users (
 id VARCHAR(36) PRIMARY KEY, email VARCHAR(320) NOT NULL UNIQUE,
 display_name VARCHAR(40) NOT NULL, password_hash TEXT NOT NULL,
 created_at BIGINT NOT NULL CHECK(created_at >= 0)
) ENGINE=InnoDB;
CREATE TABLE sessions (
 token_hash CHAR(64) PRIMARY KEY, user_id VARCHAR(36) NOT NULL,
 csrf_token VARCHAR(128) NOT NULL, expires_at BIGINT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
 INDEX sessions_expiry(expires_at)
) ENGINE=InnoDB;
CREATE TABLE job_analysis_tasks (
 id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL, title TEXT NOT NULL,
 source_text LONGTEXT NOT NULL, provider VARCHAR(40) NOT NULL, status VARCHAR(20) NOT NULL,
 payload LONGTEXT NOT NULL CHECK(JSON_VALID(payload)), created_at BIGINT NOT NULL,
 UNIQUE(id, user_id), INDEX job_tasks_owner(user_id, created_at DESC),
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
 CHECK(status IN ('running','completed','needs_input','failed'))
) ENGINE=InnoDB;
CREATE TABLE resumes (
 id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL, title TEXT NOT NULL,
 source_text LONGTEXT NOT NULL CHECK(CHAR_LENGTH(TRIM(source_text)) > 0),
 parsed_payload LONGTEXT NOT NULL CHECK(JSON_VALID(parsed_payload)),
 created_at BIGINT NOT NULL CHECK(created_at >= 0), UNIQUE(id,user_id),
 INDEX resumes_owner(user_id,created_at DESC),
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;
CREATE TABLE diagnosis_tasks (
 id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL,
 job_analysis_id VARCHAR(36) NOT NULL, resume_id VARCHAR(36) NOT NULL,
 status VARCHAR(20) NOT NULL CHECK(status IN ('running','completed','needs_input','failed')),
 result_payload LONGTEXT NOT NULL CHECK(JSON_VALID(result_payload)),
 created_at BIGINT NOT NULL CHECK(created_at >= 0),
 updated_at BIGINT NOT NULL, CHECK(updated_at >= created_at), UNIQUE(id,user_id),
 INDEX diagnosis_owner(user_id,created_at DESC),
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(job_analysis_id,user_id) REFERENCES job_analysis_tasks(id,user_id) ON DELETE CASCADE,
 FOREIGN KEY(resume_id,user_id) REFERENCES resumes(id,user_id) ON DELETE CASCADE
) ENGINE=InnoDB;
CREATE TABLE training_tasks (
 id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL, diagnosis_id VARCHAR(36) NOT NULL,
 title TEXT NOT NULL, goal TEXT NOT NULL,
 status VARCHAR(20) NOT NULL CHECK(status IN ('planned','active','completed','archived')),
 task_payload LONGTEXT NOT NULL CHECK(JSON_VALID(task_payload)),
 created_at BIGINT NOT NULL CHECK(created_at >= 0),
 updated_at BIGINT NOT NULL, CHECK(updated_at >= created_at), UNIQUE(id,user_id),
 INDEX training_owner(user_id,created_at DESC),
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(diagnosis_id,user_id) REFERENCES diagnosis_tasks(id,user_id) ON DELETE CASCADE
) ENGINE=InnoDB;
CREATE TABLE training_submissions (
 id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL, training_task_id VARCHAR(36) NOT NULL,
 attempt_no INTEGER NOT NULL CHECK(attempt_no >= 1), answer_text LONGTEXT NOT NULL,
 status VARCHAR(20) NOT NULL CHECK(status IN ('pending','passed','failed','error')),
 evaluation_payload LONGTEXT NOT NULL CHECK(JSON_VALID(evaluation_payload)),
 created_at BIGINT NOT NULL CHECK(created_at >= 0),
 UNIQUE(training_task_id,attempt_no), INDEX submissions_owner(user_id,created_at DESC),
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(training_task_id,user_id) REFERENCES training_tasks(id,user_id) ON DELETE CASCADE
) ENGINE=InnoDB;
CREATE TABLE interview_sessions (
 id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL, job_analysis_id VARCHAR(36) NOT NULL,
 diagnosis_id VARCHAR(36), input_mode VARCHAR(10) NOT NULL DEFAULT 'text',
 status VARCHAR(20) NOT NULL, max_rounds INTEGER NOT NULL DEFAULT 5,
 report_payload LONGTEXT NOT NULL CHECK(JSON_VALID(report_payload)),
 created_at BIGINT NOT NULL CHECK(created_at >= 0),
 updated_at BIGINT NOT NULL, CHECK(updated_at >= created_at), UNIQUE(id,user_id),
 INDEX interviews_owner(user_id,created_at DESC),
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(job_analysis_id,user_id) REFERENCES job_analysis_tasks(id,user_id) ON DELETE CASCADE,
 FOREIGN KEY(diagnosis_id,user_id) REFERENCES diagnosis_tasks(id,user_id) ON DELETE CASCADE,
 CHECK(input_mode IN ('text','voice')),
 CHECK(status IN ('created','active','completed','cancelled','failed')),
 CHECK(max_rounds BETWEEN 1 AND 20)
) ENGINE=InnoDB;
CREATE TABLE interview_turns (
 id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL, session_id VARCHAR(36) NOT NULL,
 round_no INTEGER NOT NULL CHECK(round_no >= 1),
 question_text LONGTEXT NOT NULL CHECK(CHAR_LENGTH(TRIM(question_text)) > 0),
 answer_text LONGTEXT, input_mode VARCHAR(10) NOT NULL DEFAULT 'text', status VARCHAR(20) NOT NULL,
 audio_duration_ms INTEGER CHECK(audio_duration_ms BETWEEN 0 AND 60000),
 feedback_payload LONGTEXT NOT NULL CHECK(JSON_VALID(feedback_payload)),
 created_at BIGINT NOT NULL CHECK(created_at >= 0),
 updated_at BIGINT NOT NULL, CHECK(updated_at >= created_at), UNIQUE(session_id,round_no),
 INDEX turns_owner(user_id,created_at DESC),
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(session_id,user_id) REFERENCES interview_sessions(id,user_id) ON DELETE CASCADE,
 CHECK(input_mode IN ('text','voice')), CHECK(status IN ('asked','answered','skipped'))
) ENGINE=InnoDB;
