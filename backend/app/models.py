"""SQLAlchemy ORM models — 1:1 with backend/db/schema.sql."""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    role: Mapped[str] = mapped_column(String, nullable=False)  # 'student' | 'professor'
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # student
    major: Mapped[str | None] = mapped_column(String)
    year: Mapped[int | None] = mapped_column(SmallInteger)
    student_id: Mapped[str | None] = mapped_column(String)
    bio: Mapped[str | None] = mapped_column(Text)
    # professor
    dept: Mapped[str | None] = mapped_column(String)
    school: Mapped[str | None] = mapped_column(String)
    # soft delete: 탈퇴해도 행은 남기고 비활성화만 한다.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    deactivated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Class(Base):
    __tablename__ = "classes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    professor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String, nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    term: Mapped[str] = mapped_column(String, nullable=False)
    capacity: Mapped[int] = mapped_column(SmallInteger, default=40)
    join_code: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    survey_deadline: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="설문 진행 중")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    enrollments: Mapped[list[Enrollment]] = relationship(back_populates="klass", cascade="all, delete-orphan")


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("class_id", "student_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"))
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    survey_submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    reminders: Mapped[int] = mapped_column(SmallInteger, default=0)
    enrolled_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    klass: Mapped[Class] = relationship(back_populates="enrollments")
    student: Mapped[User] = relationship()
    survey: Mapped[SurveyResponse | None] = relationship(
        back_populates="enrollment", cascade="all, delete-orphan", uselist=False
    )


class SurveyResponse(Base):
    __tablename__ = "survey_responses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("enrollments.id", ondelete="CASCADE"), unique=True
    )
    roles: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    trait_pace: Mapped[int | None] = mapped_column(SmallInteger)
    trait_prep: Mapped[int | None] = mapped_column(SmallInteger)
    trait_lead: Mapped[int | None] = mapped_column(SmallInteger)
    trait_comm: Mapped[int | None] = mapped_column(SmallInteger)
    match_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    enrollment: Mapped[Enrollment] = relationship(back_populates="survey")
    skills: Mapped[list[SurveySkill]] = relationship(cascade="all, delete-orphan")
    availability: Mapped[list[SurveyAvailability]] = relationship(cascade="all, delete-orphan")


class SurveySkill(Base):
    __tablename__ = "survey_skills"
    __table_args__ = (
        UniqueConstraint("survey_id", "name"),
        CheckConstraint("level BETWEEN 1 AND 5", name="skill_level_rng"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    survey_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("survey_responses.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String, nullable=False)
    level: Mapped[int] = mapped_column(SmallInteger, default=3)


class SurveyAvailability(Base):
    __tablename__ = "survey_availability"
    __table_args__ = (UniqueConstraint("survey_id", "day", "block"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    survey_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("survey_responses.id", ondelete="CASCADE"))
    day: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0=월..6=일
    block: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)  # 'y' | 'n'


class MatchPreset(Base):
    __tablename__ = "match_presets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    team_size: Mapped[int] = mapped_column(SmallInteger, default=4)
    w_major: Mapped[int] = mapped_column(SmallInteger, default=3)
    w_role: Mapped[int] = mapped_column(SmallInteger, default=3)
    w_time: Mapped[int] = mapped_column(SmallInteger, default=3)
    w_trait: Mapped[int] = mapped_column(SmallInteger, default=3)
    h_same_major: Mapped[bool] = mapped_column(Boolean, default=False)
    h_fix_pair: Mapped[bool] = mapped_column(Boolean, default=False)
    h_split_pair: Mapped[bool] = mapped_column(Boolean, default=False)
    h_even_transfer: Mapped[bool] = mapped_column(Boolean, default=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MatchRun(Base):
    __tablename__ = "match_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"))
    team_size: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    w_major: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    w_role: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    w_time: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    w_trait: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    h_same_major: Mapped[bool] = mapped_column(Boolean, default=False)
    h_fix_pair: Mapped[bool] = mapped_column(Boolean, default=False)
    h_split_pair: Mapped[bool] = mapped_column(Boolean, default=False)
    h_even_transfer: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)
    avg_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    teams: Mapped[list[Team]] = relationship(cascade="all, delete-orphan")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("match_runs.id", ondelete="CASCADE"))
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String, nullable=False)
    fit_score: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    members: Mapped[list[TeamMember]] = relationship(cascade="all, delete-orphan")


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "student_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    assigned_role: Mapped[str | None] = mapped_column(String)
