-- ================================================================
-- TeamMatch AI — PostgreSQL schema
-- Mirrors the entities the frontend (index.html) already works with.
-- ================================================================

-- Enable UUID generation (Postgres 13+: pgcrypto gives gen_random_uuid()).
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ----------------------------------------------------------------
-- Users: one table, discriminated by `role`.
-- Frontend: authRole "student" | "professor", state.user / state.prof
-- ----------------------------------------------------------------
CREATE TYPE user_role AS ENUM ('student', 'professor');

CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role          user_role   NOT NULL,
    email         TEXT        NOT NULL UNIQUE,
    password_hash TEXT        NOT NULL,
    name          TEXT        NOT NULL,
    -- student-only
    major         TEXT,
    year          SMALLINT,           -- 1..4
    student_id    TEXT,
    bio           TEXT,
    -- professor-only
    dept          TEXT,
    school        TEXT,
    -- soft delete: 탈퇴 시 행은 남기고 비활성화만 한다.
    is_active      BOOLEAN     NOT NULL DEFAULT TRUE,
    deactivated_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT year_range CHECK (year IS NULL OR year BETWEEN 1 AND 6)
);

CREATE INDEX idx_users_role ON users (role);

-- ----------------------------------------------------------------
-- Classes (courses). Frontend: state.prof.classes[]
-- `join_code` is what students type to enroll (frontend: c.join).
-- ----------------------------------------------------------------
CREATE TYPE class_status AS ENUM (
    '설문 진행 중',   -- survey open
    '편성 대기',      -- ready to form teams
    '편성 완료'       -- teams formed
);

CREATE TABLE classes (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    professor_id  UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    code          TEXT NOT NULL,               -- course code e.g. MAT2082
    term          TEXT NOT NULL,               -- "2026학년도 2학기"
    capacity      SMALLINT NOT NULL DEFAULT 40,
    join_code     TEXT NOT NULL UNIQUE,        -- 6-char enrollment code
    survey_deadline TIMESTAMPTZ,
    kind          TEXT,                        -- "개발 프로젝트" etc.
    status        class_status NOT NULL DEFAULT '설문 진행 중',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_classes_professor ON classes (professor_id);

-- ----------------------------------------------------------------
-- Enrollments: student <-> class, plus survey submission status.
-- Frontend: ROSTER rows (state / done / submitted count)
-- ----------------------------------------------------------------
CREATE TABLE enrollments (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    class_id      UUID NOT NULL REFERENCES classes (id) ON DELETE CASCADE,
    student_id    UUID NOT NULL REFERENCES users (id)   ON DELETE CASCADE,
    survey_submitted BOOLEAN NOT NULL DEFAULT FALSE,
    submitted_at  TIMESTAMPTZ,
    reminders     SMALLINT NOT NULL DEFAULT 0,
    enrolled_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (class_id, student_id)
);

CREATE INDEX idx_enrollments_class ON enrollments (class_id);
CREATE INDEX idx_enrollments_student ON enrollments (student_id);

-- ----------------------------------------------------------------
-- Survey responses: one per enrollment. Holds the matching signals.
-- Frontend: state.user.roles, traits, matchReady + the survey the
-- student fills per class.
-- ----------------------------------------------------------------
CREATE TABLE survey_responses (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    enrollment_id UUID NOT NULL UNIQUE REFERENCES enrollments (id) ON DELETE CASCADE,
    roles         TEXT[] NOT NULL DEFAULT '{}',   -- ["프론트엔드","기획"]
    -- traits 1..5 (frontend: state.user.traits)
    trait_pace    SMALLINT,   -- 진행 속도
    trait_prep    SMALLINT,   -- 준비 성향
    trait_lead    SMALLINT,   -- 주도성
    trait_comm    SMALLINT,   -- 소통
    match_ready   BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT trait_pace_rng CHECK (trait_pace IS NULL OR trait_pace BETWEEN 1 AND 5),
    CONSTRAINT trait_prep_rng CHECK (trait_prep IS NULL OR trait_prep BETWEEN 1 AND 5),
    CONSTRAINT trait_lead_rng CHECK (trait_lead IS NULL OR trait_lead BETWEEN 1 AND 5),
    CONSTRAINT trait_comm_rng CHECK (trait_comm IS NULL OR trait_comm BETWEEN 1 AND 5)
);

-- Skills belong to a survey response (frontend: state.user.skills[{n,l}]).
CREATE TABLE survey_skills (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    survey_id     UUID NOT NULL REFERENCES survey_responses (id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    level         SMALLINT NOT NULL DEFAULT 3,   -- 1..5
    CONSTRAINT skill_level_rng CHECK (level BETWEEN 1 AND 5),
    UNIQUE (survey_id, name)
);

CREATE INDEX idx_skills_survey ON survey_skills (survey_id);

-- Weekly availability grid. Frontend: schedule["월-5"] = "y"|"n"|""
-- One row per filled slot; absence of a row means "unknown".
CREATE TYPE avail_state AS ENUM ('y', 'n');  -- available / unavailable

CREATE TABLE survey_availability (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    survey_id     UUID NOT NULL REFERENCES survey_responses (id) ON DELETE CASCADE,
    day           SMALLINT NOT NULL,   -- 0=월 .. 6=일
    block         SMALLINT NOT NULL,   -- index into BLOCKS[]
    state         avail_state NOT NULL,
    CONSTRAINT day_rng CHECK (day BETWEEN 0 AND 6),
    UNIQUE (survey_id, day, block)
);

CREATE INDEX idx_avail_survey ON survey_availability (survey_id);

-- ----------------------------------------------------------------
-- Matching presets. Frontend: state.prof.presets[]
-- `owner_id` NULL = built-in system preset shared by everyone.
-- ----------------------------------------------------------------
CREATE TABLE match_presets (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id      UUID REFERENCES users (id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    description   TEXT,
    team_size     SMALLINT NOT NULL DEFAULT 4,
    -- weights 1..5 (frontend: weights.{major,role,time,trait})
    w_major       SMALLINT NOT NULL DEFAULT 3,
    w_role        SMALLINT NOT NULL DEFAULT 3,
    w_time        SMALLINT NOT NULL DEFAULT 3,
    w_trait       SMALLINT NOT NULL DEFAULT 3,
    -- hard constraints (frontend: hard.{sameMajor,fixPair,splitPair,evenTransfer})
    h_same_major     BOOLEAN NOT NULL DEFAULT FALSE,
    h_fix_pair       BOOLEAN NOT NULL DEFAULT FALSE,
    h_split_pair     BOOLEAN NOT NULL DEFAULT FALSE,
    h_even_transfer  BOOLEAN NOT NULL DEFAULT FALSE,
    is_builtin    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_presets_owner ON match_presets (owner_id);

-- ----------------------------------------------------------------
-- Matching runs + their formed teams.
-- Frontend: state.prof.result and the resulting state.projects[].
-- ----------------------------------------------------------------
CREATE TABLE match_runs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    class_id      UUID NOT NULL REFERENCES classes (id) ON DELETE CASCADE,
    team_size     SMALLINT NOT NULL,
    w_major       SMALLINT NOT NULL,
    w_role        SMALLINT NOT NULL,
    w_time        SMALLINT NOT NULL,
    w_trait       SMALLINT NOT NULL,
    h_same_major     BOOLEAN NOT NULL DEFAULT FALSE,
    h_fix_pair       BOOLEAN NOT NULL DEFAULT FALSE,
    h_split_pair     BOOLEAN NOT NULL DEFAULT FALSE,
    h_even_transfer  BOOLEAN NOT NULL DEFAULT FALSE,
    note          TEXT,                -- free-text professor instruction
    avg_score     NUMERIC(5,2),        -- overall fit across teams
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_runs_class ON match_runs (class_id);

CREATE TABLE teams (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id        UUID NOT NULL REFERENCES match_runs (id) ON DELETE CASCADE,
    class_id      UUID NOT NULL REFERENCES classes (id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    fit_score     NUMERIC(5,2) NOT NULL DEFAULT 0,   -- 0..100
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_teams_run ON teams (run_id);

CREATE TABLE team_members (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id       UUID NOT NULL REFERENCES teams (id) ON DELETE CASCADE,
    student_id    UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    assigned_role TEXT,   -- the role this member covers on the team
    UNIQUE (team_id, student_id)
);

CREATE INDEX idx_team_members_team ON team_members (team_id);

-- ----------------------------------------------------------------
-- Built-in presets seed (frontend ps0..ps4).
-- ----------------------------------------------------------------
INSERT INTO match_presets
    (name, description, team_size, w_major, w_role, w_time, w_trait,
     h_same_major, h_fix_pair, h_split_pair, h_even_transfer, is_builtin)
VALUES
    ('균형 배분', '네 항목을 고르게 반영하는 기본값', 4, 3,3,3,3, TRUE, FALSE, FALSE, FALSE, TRUE),
    ('전공 다양성 우선', '융합 프로젝트처럼 학과가 섞여야 하는 수업', 4, 5,4,2,2, TRUE, FALSE, FALSE, TRUE, TRUE),
    ('역량 균형 우선', '개발·기획 역할이 팀마다 고루 필요한 수업', 4, 3,5,3,2, FALSE, FALSE, FALSE, FALSE, TRUE),
    ('일정 우선', '모일 시간을 맞추기 어려운 야간·대형 수업', 5, 2,3,5,2, FALSE, FALSE, FALSE, FALSE, TRUE),
    ('성향 중심', '한 학기 내내 함께 가는 장기 프로젝트', 4, 2,3,3,5, TRUE, FALSE, TRUE, FALSE, TRUE);
