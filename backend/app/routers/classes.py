"""Classes: professor CRUD + roster, student enrollment via join code."""
from __future__ import annotations

import datetime as dt
import secrets
import string
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Class, Enrollment, User
from ..schemas import (
    CandidatePreview,
    CandidatesSummary,
    ClassCreate,
    ClassOut,
    ClassUpdate,
    JoinRequest,
)
from ..security import get_current_user, require_professor, require_student

router = APIRouter(prefix="/api/classes", tags=["classes"])

_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _generate_join_code(db: Session) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        if not db.scalar(select(Class).where(Class.join_code == code)):
            return code
    raise HTTPException(status_code=500, detail="참여 코드를 생성하지 못했습니다.")


def _to_out(db: Session, c: Class) -> ClassOut:
    enrolled = db.scalar(
        select(func.count()).select_from(Enrollment).where(Enrollment.class_id == c.id)
    ) or 0
    submitted = db.scalar(
        select(func.count())
        .select_from(Enrollment)
        .where(Enrollment.class_id == c.id, Enrollment.survey_submitted.is_(True))
    ) or 0
    out = ClassOut.model_validate(c)
    out.enrolled = enrolled
    out.submitted = submitted
    return out


def _owned_class(db: Session, class_id: uuid.UUID, prof: User) -> Class:
    """교수 본인이 소유한 수업만 돌려준다. 아니면 404."""
    c = db.get(Class, class_id)
    if not c or c.professor_id != prof.id:
        raise HTTPException(status_code=404, detail="수업을 찾을 수 없습니다.")
    return c


@router.post("", response_model=ClassOut, status_code=status.HTTP_201_CREATED)
def create_class(
    body: ClassCreate, prof: User = Depends(require_professor), db: Session = Depends(get_db)
) -> ClassOut:
    c = Class(
        professor_id=prof.id,
        name=body.name,
        code=body.code,
        term=body.term,
        capacity=body.capacity,
        kind=body.kind,
        survey_deadline=body.survey_deadline,
        join_code=_generate_join_code(db),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _to_out(db, c)


@router.get("", response_model=list[ClassOut])
def list_classes(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[ClassOut]:
    if user.role == "professor":
        rows = db.scalars(select(Class).where(Class.professor_id == user.id)).all()
    else:
        rows = db.scalars(
            select(Class)
            .join(Enrollment, Enrollment.class_id == Class.id)
            .where(Enrollment.student_id == user.id)
        ).all()
    return [_to_out(db, c) for c in rows]


@router.get("/{class_id}/roster")
def roster(
    class_id: uuid.UUID, prof: User = Depends(require_professor), db: Session = Depends(get_db)
) -> list[dict]:
    _owned_class(db, class_id, prof)
    rows = db.scalars(
        select(Enrollment).where(Enrollment.class_id == class_id)
    ).all()
    out = []
    for e in rows:
        s = e.student
        out.append(
            {
                "student_id": str(s.id),
                "name": s.name,
                "major": s.major,
                "year": s.year,
                "survey_submitted": e.survey_submitted,
                "reminders": e.reminders,
                "submitted_at": e.submitted_at,
            }
        )
    return out


@router.post("/join", response_model=ClassOut)
def join_class(
    body: JoinRequest, student: User = Depends(require_student), db: Session = Depends(get_db)
) -> ClassOut:
    c = db.scalar(select(Class).where(Class.join_code == body.join_code.upper()))
    if not c:
        raise HTTPException(status_code=404, detail="참여 코드가 올바르지 않습니다.")

    existing = db.scalar(
        select(Enrollment).where(
            Enrollment.class_id == c.id, Enrollment.student_id == student.id
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="이미 참여한 수업입니다.")

    db.add(Enrollment(class_id=c.id, student_id=student.id))
    db.commit()
    return _to_out(db, c)


# ================================================================
# 백엔드1 3번: 과목 수정 / 삭제
# ================================================================
@router.put("/{class_id}", response_model=ClassOut)
def update_class(
    class_id: uuid.UUID,
    body: ClassUpdate,
    prof: User = Depends(require_professor),
    db: Session = Depends(get_db),
) -> ClassOut:
    """과목 수정(부분 수정). 교수 본인 수업만 가능."""
    c = _owned_class(db, class_id, prof)
    for field in ("name", "code", "term", "capacity", "kind", "survey_deadline", "status"):
        value = getattr(body, field)
        if value is not None:
            setattr(c, field, value)
    db.commit()
    db.refresh(c)
    return _to_out(db, c)


@router.delete("/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_class(
    class_id: uuid.UUID,
    prof: User = Depends(require_professor),
    db: Session = Depends(get_db),
) -> None:
    """과목 삭제. 교수 본인 수업만 가능.

    주의: FK가 ON DELETE CASCADE 라서 수강/설문/매칭 결과도 함께 삭제된다.
    (이미 편성이 끝난 수업을 지울 때는 신중해야 함)
    """
    c = _owned_class(db, class_id, prof)
    db.delete(c)
    db.commit()
    return None


# ================================================================
# 백엔드1 4번: 매칭 전 후보/조건 미리 조회
# ================================================================
@router.get("/{class_id}/candidates", response_model=CandidatesSummary)
def list_candidates(
    class_id: uuid.UUID,
    prof: User = Depends(require_professor),
    db: Session = Depends(get_db),
) -> CandidatesSummary:
    """매칭 실행 전에 '누가 대상인지'와 분포를 미리 보여준다.

    match_ready=true 인 제출자만 실제 매칭 대상(ready)이다.
    학과/희망역할 분포도 함께 집계해, 교수가 가중치·하드제약을
    정하기 전에 참고할 수 있게 한다.
    """
    _owned_class(db, class_id, prof)

    rows = db.scalars(select(Enrollment).where(Enrollment.class_id == class_id)).all()

    enrolled = len(rows)
    submitted = 0
    ready = 0
    major_breakdown: dict[str, int] = {}
    role_breakdown: dict[str, int] = {}
    previews: list[CandidatePreview] = []

    for e in rows:
        if e.survey_submitted:
            submitted += 1
        survey = e.survey
        is_ready = bool(survey and survey.match_ready)
        if is_ready:
            ready += 1
            s = e.student
            if s.major:
                major_breakdown[s.major] = major_breakdown.get(s.major, 0) + 1
            for r in (survey.roles or []):
                role_breakdown[r] = role_breakdown.get(r, 0) + 1
            previews.append(
                CandidatePreview(
                    student_id=s.id,
                    name=s.name,
                    major=s.major,
                    year=s.year,
                    roles=list(survey.roles or []),
                    skill_count=len(survey.skills),
                    filled_slots=sum(1 for a in survey.availability if a.state == "y"),
                    match_ready=True,
                )
            )

    return CandidatesSummary(
        class_id=class_id,
        enrolled=enrolled,
        submitted=submitted,
        ready=ready,
        major_breakdown=major_breakdown,
        role_breakdown=role_breakdown,
        candidates=previews,
    )
