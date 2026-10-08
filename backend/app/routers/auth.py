"""Auth: signup, login, current-user."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import SignupRequest, TokenResponse, UserOut, UserUpdate
from ..security import create_access_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, db: Session = Depends(get_db)) -> TokenResponse:
    if db.scalar(select(User).where(User.email == body.email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="이미 가입된 이메일입니다.")

    if body.role == "student" and not body.student_id:
        raise HTTPException(status_code=422, detail="학번을 입력하세요.")

    user = User(
        role=body.role,
        name=body.name,
        email=body.email,
        password_hash=hash_password(body.password),
        major=body.major,
        year=body.year,
        student_id=body.student_id,
        dept=body.dept,
        school=body.school,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token, role=user.role, name=user.name)


@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> TokenResponse:
    # OAuth2 form uses `username`; we treat it as email.
    user = db.scalar(select(User).where(User.email == form.username))
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="탈퇴한 계정입니다. 로그인할 수 없습니다.",
        )
    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token, role=user.role, name=user.name)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.put("/me", response_model=UserOut)
def update_me(
    body: UserUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """본인 프로필 수정(부분 수정). 보낸 필드만 변경한다."""
    # 1) 이메일 변경 — 다른 사람이 이미 쓰는 이메일이면 거부
    if body.email and body.email != user.email:
        taken = db.scalar(select(User).where(User.email == body.email, User.id != user.id))
        if taken:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="이미 사용 중인 이메일입니다.")
        user.email = body.email

    # 2) 비밀번호 변경 — 현재 비밀번호 확인 후에만 허용
    if body.new_password:
        if not body.current_password or not verify_password(body.current_password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="현재 비밀번호가 올바르지 않습니다.")
        user.password_hash = hash_password(body.new_password)

    # 3) 일반 프로필 필드 — 보낸 것만 반영
    for field in ("name", "bio", "major", "year", "dept", "school"):
        value = getattr(body, field)
        if value is not None:
            setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    """회원 탈퇴 (soft delete).

    행을 지우지 않고 is_active=False 로 비활성화만 한다. 덕분에
    교수가 탈퇴해도 그가 만든 수업/매칭 결과가 보존되고, 학생이 탈퇴해도
    과거 수강/설문 기록이 남는다. 비활성 계정은 로그인/인증에서 차단된다.
    """
    if user.is_active:
        user.is_active = False
        user.deactivated_at = dt.datetime.now(dt.timezone.utc)
        db.commit()
    return None
