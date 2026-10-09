import sys
from pathlib import Path

# backend/ 디렉토리를 sys.path에 추가
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import Class, User
from app.security import create_access_token, hash_password

client = TestClient(app)

def setup_test_data():
    db = SessionLocal()
    try:
        # 기존 테스트 데이터 정리 (이메일 중복 방지)
        db.query(User).filter(User.email.in_(["prof1_test@univ.ac.kr", "prof2_test@univ.ac.kr"])).delete(synchronize_session=False)
        db.commit()

        # 1. 교수 계정 2개 생성
        prof1 = User(
            email="prof1_test@univ.ac.kr",
            password_hash=hash_password("password123"),
            name="김교수",
            role="professor"
        )
        prof2 = User(
            email="prof2_test@univ.ac.kr",
            password_hash=hash_password("password123"),
            name="이교수",
            role="professor"
        )
        db.add_all([prof1, prof2])
        db.commit()
        db.refresh(prof1)
        db.refresh(prof2)

        # 2. 수업 2개 생성
        class_active = Class(
            name="테스트 컴퓨터구조",
            code="CS301",
            term="2026-1",
            capacity=30,
            professor_id=prof1.id,
            status="설문 진행 중",
            join_code="TEST01"
        )
        class_completed = Class(
            name="테스트 데이터베이스",
            code="CS302",
            term="2026-1",
            capacity=30,
            professor_id=prof1.id,
            status="편성 완료",
            join_code="TEST02"
        )
        db.add_all([class_active, class_completed])
        db.commit()
        db.refresh(class_active)
        db.refresh(class_completed)

        # 토큰 생성 (sub에 email 대신 user.id의 UUID 문자열 전달)
        token_prof1 = create_access_token(str(prof1.id), role="professor")
        token_prof2 = create_access_token(str(prof2.id), role="professor")

        return {
            "prof1_token": token_prof1,
            "prof2_token": token_prof2,
            "class_active_id": str(class_active.id),
            "class_completed_id": str(class_completed.id),
        }
    finally:
        db.close()


def test_matching_exceptions():
    data = setup_test_data()
    headers_prof1 = {"Authorization": f"Bearer {data['prof1_token']}"}
    headers_prof2 = {"Authorization": f"Bearer {data['prof2_token']}"}

    payload = {
        "team_size": 4,
        "weights": {"major": 3, "role": 3, "time": 3, "trait": 3},
        "hard": {"same_major": False, "fix_pair": False, "split_pair": False, "even_transfer": False}
    }

    # -------------------------------------------------------------
    # 검증 1: 422 - 설문 제출 학생 없음
    # -------------------------------------------------------------
    res1 = client.post(
        f"/api/classes/{data['class_active_id']}/match",
        json=payload,
        headers=headers_prof1
    )
    print(f"[테스트 1] 설문 제출자 없음 -> Status: {res1.status_code}")
    assert res1.status_code == 422, f"기대값 422, 실제값 {res1.status_code}"

    # -------------------------------------------------------------
    # 검증 2: 409 - 이미 편성 완료된 수업 중복 실행
    # -------------------------------------------------------------
    res2 = client.post(
        f"/api/classes/{data['class_completed_id']}/match",
        json=payload,
        headers=headers_prof1
    )
    print(f"[테스트 2] 이미 편성 완료된 수업 -> Status: {res2.status_code}")
    assert res2.status_code == 409, f"기대값 409, 실제값 {res2.status_code}"

    # -------------------------------------------------------------
    # 검증 3: 403 - 타 교수의 수업 접근
    # -------------------------------------------------------------
    res3 = client.post(
        f"/api/classes/{data['class_active_id']}/match",
        json=payload,
        headers=headers_prof2
    )
    print(f"[테스트 3] 타 교수 수업 접근 -> Status: {res3.status_code}")
    assert res3.status_code == 403, f"기대값 403, 실제값 {res3.status_code}"

    print("\n 모든 예외 처리 자동 테스트 통과!")


if __name__ == "__main__":
    test_matching_exceptions()