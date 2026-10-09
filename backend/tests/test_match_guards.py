"""매칭 라우터의 예외처리(안전망) 단위 테스트 — DB 불필요.

라우터 함수 자체는 DB 의존성이 있어 직접 호출하지 않고,
순수 검증 헬퍼(_assert_no_duplicate_assignment)만 떼어 테스트한다.
"""
import pytest
from fastapi import HTTPException

from app import matching as engine
from app.routers.matching import _assert_no_duplicate_assignment


def _cand(i):
    return engine.Candidate(student_id=str(i), name=f"s{i}", major="A", year=2)


def _team(ids):
    return engine.TeamResult(members=[_cand(i) for i in ids], fit_score=50.0)


def test_no_duplicate_passes():
    # 서로 겹치지 않는 두 팀 -> 통과(예외 없음)
    teams = [_team([1, 2, 3]), _team([4, 5, 6])]
    _assert_no_duplicate_assignment(teams)  # 예외가 안 나면 성공


def test_duplicate_assignment_raises():
    # 학생 3이 두 팀에 모두 있음 -> 500
    teams = [_team([1, 2, 3]), _team([3, 4, 5])]
    with pytest.raises(HTTPException) as exc:
        _assert_no_duplicate_assignment(teams)
    assert exc.value.status_code == 500


def test_empty_teams_pass():
    # 빈 입력은 중복이 없으므로 통과 (빈 결과 자체는 라우터의 다른 방어가 처리)
    _assert_no_duplicate_assignment([])
