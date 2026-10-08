"""Pydantic request/response models."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


# ---- Auth ------------------------------------------------------
class SignupRequest(BaseModel):
    role: Literal["student", "professor"]
    name: str
    email: EmailStr
    password: str = Field(min_length=8)
    # student
    major: str | None = None
    year: int | None = Field(default=None, ge=1, le=6)
    student_id: str | None = None
    # professor
    dept: str | None = None
    school: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    name: str


class UserOut(BaseModel):
    id: uuid.UUID
    role: str
    name: str
    email: EmailStr
    major: str | None = None
    year: int | None = None
    student_id: str | None = None
    bio: str | None = None
    dept: str | None = None
    school: str | None = None

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    """프로필 수정 — 보낸 필드만 바꾸는 부분 수정(partial update).

    이메일/비밀번호는 민감하므로 아래 전용 필드로 분리한다.
    역할(role)·학번(student_id)은 신원 정보라 여기서 바꾸지 않는다.
    """
    name: str | None = None
    bio: str | None = None
    major: str | None = None
    year: int | None = Field(default=None, ge=1, le=6)
    dept: str | None = None
    school: str | None = None
    # 이메일 변경(선택)
    email: EmailStr | None = None
    # 비밀번호 변경(선택): 둘 다 있어야 적용
    current_password: str | None = None
    new_password: str | None = Field(default=None, min_length=8)


# ---- Classes ---------------------------------------------------
class ClassCreate(BaseModel):
    name: str
    code: str
    term: str
    capacity: int = 40
    kind: str | None = None
    survey_deadline: dt.datetime | None = None


class ClassUpdate(BaseModel):
    """과목 수정 — 보낸 필드만 변경하는 부분 수정(partial update).

    join_code 는 학생 참여용 식별자라 임의 변경 대상에서 제외한다.
    status 는 매칭 흐름에서 자동 전환되므로 여기서도 수동 변경을 허용하되
    허용값만 받도록 Literal 로 제한한다.
    """
    name: str | None = None
    code: str | None = None
    term: str | None = None
    capacity: int | None = Field(default=None, ge=1, le=500)
    kind: str | None = None
    survey_deadline: dt.datetime | None = None
    status: Literal["설문 진행 중", "편성 대기", "편성 완료"] | None = None


class ClassOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    term: str
    capacity: int
    join_code: str
    kind: str | None
    status: str
    survey_deadline: dt.datetime | None
    submitted: int = 0
    enrolled: int = 0

    model_config = {"from_attributes": True}


class JoinRequest(BaseModel):
    join_code: str


# ---- 매칭 후보 미리 조회 (백엔드1 4번) ----
class CandidatePreview(BaseModel):
    """매칭 전에 교수가 확인할 제출 학생 요약."""
    student_id: uuid.UUID
    name: str
    major: str | None
    year: int | None
    roles: list[str] = []
    skill_count: int = 0
    filled_slots: int = 0          # 가능 시간('y') 개수
    match_ready: bool = False


class CandidatesSummary(BaseModel):
    """후보 목록 + 매칭 가능 여부 요약."""
    class_id: uuid.UUID
    enrolled: int                  # 수강 인원
    submitted: int                 # 설문 제출(완료) 인원
    ready: int                     # match_ready=true 인원 = 실제 매칭 대상
    major_breakdown: dict[str, int] = {}   # 학과별 인원
    role_breakdown: dict[str, int] = {}    # 희망 역할별 인원
    candidates: list[CandidatePreview] = []


# ---- Survey / profile ------------------------------------------
class SkillIn(BaseModel):
    name: str
    level: int = Field(ge=1, le=5)


class AvailabilitySlot(BaseModel):
    day: int = Field(ge=0, le=6)
    block: int = Field(ge=0)
    state: Literal["y", "n"]


class Traits(BaseModel):
    pace: int | None = Field(default=None, ge=1, le=5)
    prep: int | None = Field(default=None, ge=1, le=5)
    lead: int | None = Field(default=None, ge=1, le=5)
    comm: int | None = Field(default=None, ge=1, le=5)


class SurveySubmit(BaseModel):
    roles: list[str] = []
    skills: list[SkillIn] = []
    traits: Traits = Traits()
    availability: list[AvailabilitySlot] = []
    match_ready: bool = False


class SurveyOut(SurveySubmit):
    enrollment_id: uuid.UUID
    updated_at: dt.datetime | None = None


# ---- Matching --------------------------------------------------
class Weights(BaseModel):
    major: int = Field(ge=1, le=5)
    role: int = Field(ge=1, le=5)
    time: int = Field(ge=1, le=5)
    trait: int = Field(ge=1, le=5)


class HardConstraints(BaseModel):
    same_major: bool = False
    fix_pair: bool = False
    split_pair: bool = False
    even_transfer: bool = False


class MatchRequest(BaseModel):
    team_size: int = Field(ge=2, le=8)
    weights: Weights
    hard: HardConstraints = HardConstraints()
    note: str | None = None


class MemberOut(BaseModel):
    student_id: uuid.UUID
    name: str
    major: str | None
    year: int | None
    assigned_role: str | None


class TeamOut(BaseModel):
    id: uuid.UUID
    name: str
    fit_score: float
    members: list[MemberOut]


class MatchResultOut(BaseModel):
    run_id: uuid.UUID
    class_id: uuid.UUID
    team_size: int
    avg_score: float
    teams: list[TeamOut]


class PresetOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    team_size: int
    weights: Weights
    hard: HardConstraints
    is_builtin: bool

    model_config = {"from_attributes": True}


# ================================================================
# 매칭 엔진 v2 (TeamFit AI) — 사진 시연 반영
# ================================================================
class HardRulesIn(BaseModel):
    """하드 제약 입력 (사진 '하드 제약')."""
    same_major_max: int | None = None
    separate_pairs: list[tuple[str, str]] = []
    fixed_pairs: list[tuple[str, str]] = []
    spread_tags: list[str] = []
    role_minimums: dict[str, int] = {}


class MatchV2Request(BaseModel):
    team_size: int = Field(ge=2, le=8)
    weights: Weights
    hard: HardRulesIn = HardRulesIn()
    note: str | None = None          # 주관식 요구사항 (언어모델이 해석)
    starts: int = Field(default=3, ge=1, le=5)   # best-of-N
    seed: int | None = None


# ---- 실행 전 점검 ----
class CheckItemOut(BaseModel):
    name: str
    ok: bool
    detail: str
    suggestion: str | None = None


class PrecheckOut(BaseModel):
    feasible: bool
    team_count: int
    composition: str
    items: list[CheckItemOut]


# ---- 매칭 결과(v2) ----
class V2MemberOut(BaseModel):
    student_id: uuid.UUID
    name: str
    major: str | None
    year: int | None
    assigned_role: str | None


class V2TeamOut(BaseModel):
    name: str
    fit_score: float
    is_lowest: bool = False          # 사진의 '최저' 팀(주황 테두리)
    members: list[V2MemberOut]


class TraceOut(BaseModel):
    stage: list[str]
    avg: list[float]
    low: list[float]


class ParsedRuleOut(BaseModel):
    source: str
    kind: str
    description: str
    applied: bool


class MatchV2Result(BaseModel):
    team_count: int
    objective_j: float               # 목적함수 J
    avg_fit: float                   # 평균 조화도
    min_fit: float                   # 최저 팀 점수
    hard_violations: int
    swaps: int                       # 매칭 교환 횟수
    teams: list[V2TeamOut]
    trace: TraceOut                  # 조화도 추이(그래프용)
    parsed_rules: list[ParsedRuleOut]  # 주관식 해석 결과
