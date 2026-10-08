-- ================================================================
-- TeamMatch AI — MySQL schema (MySQL 8.0+)
-- MySQL port of schema.sql (PostgreSQL). Differences from Postgres:
--   * UUIDs stored as CHAR(36), defaulted with UUID() (MySQL 8.0+).
--   * ENUMs are inline column-level ENUM(...) (no CREATE TYPE).
--   * `roles` array -> its own survey_roles child table.
--   * TIMESTAMPTZ -> TIMESTAMP (MySQL stores UTC internally).
--   * NUMERIC -> DECIMAL. Engine InnoDB, charset utf8mb4 for Korean text + FKs.
-- ================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------------------------------------------
-- Users: one table, discriminated by `role`.
-- ----------------------------------------------------------------
CREATE TABLE users (
    id            CHAR(36)     NOT NULL DEFAULT (UUID()),
    role          ENUM('student','professor') NOT NULL,
    email         VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name          VARCHAR(255) NOT NULL,
    -- student-only
    major         VARCHAR(255) NULL,
    year          SMALLINT     NULL,
    student_id    VARCHAR(64)  NULL,
    bio           TEXT         NULL,
    -- professor-only
    dept          VARCHAR(255) NULL,
    school        VARCHAR(255) NULL,
    -- soft delete: 탈퇴 시 행은 남기고 비활성화만 한다.
    is_active      TINYINT(1)  NOT NULL DEFAULT 1,
    deactivated_at TIMESTAMP   NULL,
    created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_email (email),
    KEY idx_users_role (role),
    CONSTRAINT year_range CHECK (year IS NULL OR (year BETWEEN 1 AND 6))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------
-- Classes (courses).
-- ----------------------------------------------------------------
CREATE TABLE classes (
    id              CHAR(36)     NOT NULL DEFAULT (UUID()),
    professor_id    CHAR(36)     NOT NULL,
    name            VARCHAR(255) NOT NULL,
    code            VARCHAR(64)  NOT NULL,
    term            VARCHAR(64)  NOT NULL,
    capacity        SMALLINT     NOT NULL DEFAULT 40,
    join_code       VARCHAR(12)  NOT NULL,
    survey_deadline TIMESTAMP    NULL,
    kind            VARCHAR(64)  NULL,
    status          ENUM('설문 진행 중','편성 대기','편성 완료') NOT NULL DEFAULT '설문 진행 중',
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_classes_join_code (join_code),
    KEY idx_classes_professor (professor_id),
    CONSTRAINT fk_classes_professor FOREIGN KEY (professor_id)
        REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------
-- Enrollments: student <-> class + survey submission status.
-- ----------------------------------------------------------------
CREATE TABLE enrollments (
    id               CHAR(36)  NOT NULL DEFAULT (UUID()),
    class_id         CHAR(36)  NOT NULL,
    student_id       CHAR(36)  NOT NULL,
    survey_submitted TINYINT(1) NOT NULL DEFAULT 0,
    submitted_at     TIMESTAMP NULL,
    reminders        SMALLINT  NOT NULL DEFAULT 0,
    enrolled_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_enroll_class_student (class_id, student_id),
    KEY idx_enrollments_class (class_id),
    KEY idx_enrollments_student (student_id),
    CONSTRAINT fk_enroll_class FOREIGN KEY (class_id)
        REFERENCES classes (id) ON DELETE CASCADE,
    CONSTRAINT fk_enroll_student FOREIGN KEY (student_id)
        REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------
-- Survey responses: one per enrollment. Holds the matching signals.
-- ----------------------------------------------------------------
CREATE TABLE survey_responses (
    id            CHAR(36)   NOT NULL DEFAULT (UUID()),
    enrollment_id CHAR(36)   NOT NULL,
    trait_pace    SMALLINT   NULL,
    trait_prep    SMALLINT   NULL,
    trait_lead    SMALLINT   NULL,
    trait_comm    SMALLINT   NULL,
    match_ready   TINYINT(1) NOT NULL DEFAULT 0,
    updated_at    TIMESTAMP  NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_survey_enrollment (enrollment_id),
    CONSTRAINT fk_survey_enrollment FOREIGN KEY (enrollment_id)
        REFERENCES enrollments (id) ON DELETE CASCADE,
    CONSTRAINT trait_pace_rng CHECK (trait_pace IS NULL OR (trait_pace BETWEEN 1 AND 5)),
    CONSTRAINT trait_prep_rng CHECK (trait_prep IS NULL OR (trait_prep BETWEEN 1 AND 5)),
    CONSTRAINT trait_lead_rng CHECK (trait_lead IS NULL OR (trait_lead BETWEEN 1 AND 5)),
    CONSTRAINT trait_comm_rng CHECK (trait_comm IS NULL OR (trait_comm BETWEEN 1 AND 5))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Roles: replaces the Postgres ARRAY column (one row per role).
CREATE TABLE survey_roles (
    id        CHAR(36)     NOT NULL DEFAULT (UUID()),
    survey_id CHAR(36)     NOT NULL,
    role      VARCHAR(64)  NOT NULL,   -- 기획 / 프론트엔드 / 백엔드 / 데이터 / 디자인 / 발표
    PRIMARY KEY (id),
    UNIQUE KEY uq_survey_role (survey_id, role),
    KEY idx_roles_survey (survey_id),
    CONSTRAINT fk_roles_survey FOREIGN KEY (survey_id)
        REFERENCES survey_responses (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Skills belong to a survey response.
CREATE TABLE survey_skills (
    id        CHAR(36)     NOT NULL DEFAULT (UUID()),
    survey_id CHAR(36)     NOT NULL,
    name      VARCHAR(128) NOT NULL,
    level     SMALLINT     NOT NULL DEFAULT 3,
    PRIMARY KEY (id),
    UNIQUE KEY uq_survey_skill (survey_id, name),
    KEY idx_skills_survey (survey_id),
    CONSTRAINT skill_level_rng CHECK (level BETWEEN 1 AND 5),
    CONSTRAINT fk_skills_survey FOREIGN KEY (survey_id)
        REFERENCES survey_responses (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Weekly availability grid: one row per filled slot.
CREATE TABLE survey_availability (
    id        CHAR(36)   NOT NULL DEFAULT (UUID()),
    survey_id CHAR(36)   NOT NULL,
    day       SMALLINT   NOT NULL,   -- 0=월 .. 6=일
    block     SMALLINT   NOT NULL,   -- index into BLOCKS[]
    state     ENUM('y','n') NOT NULL, -- available / unavailable
    PRIMARY KEY (id),
    UNIQUE KEY uq_avail_slot (survey_id, day, block),
    KEY idx_avail_survey (survey_id),
    CONSTRAINT day_rng CHECK (day BETWEEN 0 AND 6),
    CONSTRAINT fk_avail_survey FOREIGN KEY (survey_id)
        REFERENCES survey_responses (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------
-- Matching presets. owner_id NULL = built-in system preset.
-- ----------------------------------------------------------------
CREATE TABLE match_presets (
    id              CHAR(36)     NOT NULL DEFAULT (UUID()),
    owner_id        CHAR(36)     NULL,
    name            VARCHAR(128) NOT NULL,
    description     TEXT         NULL,
    team_size       SMALLINT     NOT NULL DEFAULT 4,
    w_major         SMALLINT     NOT NULL DEFAULT 3,
    w_role          SMALLINT     NOT NULL DEFAULT 3,
    w_time          SMALLINT     NOT NULL DEFAULT 3,
    w_trait         SMALLINT     NOT NULL DEFAULT 3,
    h_same_major    TINYINT(1)   NOT NULL DEFAULT 0,
    h_fix_pair      TINYINT(1)   NOT NULL DEFAULT 0,
    h_split_pair    TINYINT(1)   NOT NULL DEFAULT 0,
    h_even_transfer TINYINT(1)   NOT NULL DEFAULT 0,
    is_builtin      TINYINT(1)   NOT NULL DEFAULT 0,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_presets_owner (owner_id),
    CONSTRAINT fk_presets_owner FOREIGN KEY (owner_id)
        REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------
-- Matching runs + their formed teams.
-- ----------------------------------------------------------------
CREATE TABLE match_runs (
    id              CHAR(36)    NOT NULL DEFAULT (UUID()),
    class_id        CHAR(36)    NOT NULL,
    team_size       SMALLINT    NOT NULL,
    w_major         SMALLINT    NOT NULL,
    w_role          SMALLINT    NOT NULL,
    w_time          SMALLINT    NOT NULL,
    w_trait         SMALLINT    NOT NULL,
    h_same_major    TINYINT(1)  NOT NULL DEFAULT 0,
    h_fix_pair      TINYINT(1)  NOT NULL DEFAULT 0,
    h_split_pair    TINYINT(1)  NOT NULL DEFAULT 0,
    h_even_transfer TINYINT(1)  NOT NULL DEFAULT 0,
    note            TEXT        NULL,
    avg_score       DECIMAL(5,2) NULL,
    created_at      TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_runs_class (class_id),
    CONSTRAINT fk_runs_class FOREIGN KEY (class_id)
        REFERENCES classes (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE teams (
    id         CHAR(36)     NOT NULL DEFAULT (UUID()),
    run_id     CHAR(36)     NOT NULL,
    class_id   CHAR(36)     NOT NULL,
    name       VARCHAR(128) NOT NULL,
    fit_score  DECIMAL(5,2) NOT NULL DEFAULT 0,
    created_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_teams_run (run_id),
    CONSTRAINT fk_teams_run FOREIGN KEY (run_id)
        REFERENCES match_runs (id) ON DELETE CASCADE,
    CONSTRAINT fk_teams_class FOREIGN KEY (class_id)
        REFERENCES classes (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE team_members (
    id            CHAR(36)     NOT NULL DEFAULT (UUID()),
    team_id       CHAR(36)     NOT NULL,
    student_id    CHAR(36)     NOT NULL,
    assigned_role VARCHAR(64)  NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_team_student (team_id, student_id),
    KEY idx_team_members_team (team_id),
    CONSTRAINT fk_tm_team FOREIGN KEY (team_id)
        REFERENCES teams (id) ON DELETE CASCADE,
    CONSTRAINT fk_tm_student FOREIGN KEY (student_id)
        REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------
-- Built-in presets seed (frontend ps0..ps4).
-- ----------------------------------------------------------------
INSERT INTO match_presets
    (name, description, team_size, w_major, w_role, w_time, w_trait,
     h_same_major, h_fix_pair, h_split_pair, h_even_transfer, is_builtin)
VALUES
    ('균형 배분', '네 항목을 고르게 반영하는 기본값', 4, 3,3,3,3, 1, 0, 0, 0, 1),
    ('전공 다양성 우선', '융합 프로젝트처럼 학과가 섞여야 하는 수업', 4, 5,4,2,2, 1, 0, 0, 1, 1),
    ('역량 균형 우선', '개발·기획 역할이 팀마다 고루 필요한 수업', 4, 3,5,3,2, 0, 0, 0, 0, 1),
    ('일정 우선', '모일 시간을 맞추기 어려운 야간·대형 수업', 5, 2,3,5,2, 0, 0, 0, 0, 1),
    ('성향 중심', '한 학기 내내 함께 가는 장기 프로젝트', 4, 2,3,3,5, 1, 0, 1, 0, 1);

SET FOREIGN_KEY_CHECKS = 1;
