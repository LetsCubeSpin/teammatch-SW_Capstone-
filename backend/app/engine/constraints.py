"""소프트 가중치, 하드 제약, 목적함수 J.

사진 공식 반영
--------------
- 소프트(조화도) 점수:   score = Σ(wₖ · sₖ) / Σ(wₖ) × 100
    · sₖ : 축별 0..1 점수(전공 다양성 / 역할 균형 / 일정 / 성향)
    · wₖ : 교수가 설정한 1..5 가중치
- 목적함수 J:            J = 평균 조화도 + 최저 팀 점수 − 1000 × (하드 위반 수)
    · "평균 + 최저"를 함께 보기 때문에, 전체 평균뿐 아니라
      가장 약한 팀(주황 테두리)까지 끌어올리는 방향으로 최적화됩니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 기존 엔진의 축별 점수 함수와 후보 타입을 재사용한다.
from ..matching import (
    Candidate,
    _major_score,
    _role_score,
    _time_score,
    _trait_score,
)

HARD_PENALTY = 1000.0  # 사진: "위반 시 1,000 패널티 = 사실상 금지"


@dataclass
class SoftWeights:
    """축별 1..5 가중치 (사진 '가중치' 슬라이더)."""

    major: int = 3   # 전공 다양성
    role: int = 3    # 역할 역량 균형
    time: int = 3    # 일정 호환성
    trait: int = 3   # 성향 호환성


@dataclass
class HardRules:
    """하드 제약 (사진 '하드 제약' 체크 + 지정 목록).

    same_major_max : 한 팀 내 같은 학과 허용 인원 상한 (예: 2명 이하)
    separate_pairs : 서로 다른 팀으로 분리해야 하는 학생 쌍들
    fixed_pairs    : 반드시 같은 팀으로 고정할 학생 쌍들
    spread_tags    : 각 팀에 고르게 배치해야 하는 태그(예: 편입생/유학생)
    role_minimums  : 각 팀이 최소 n명 보유해야 하는 역할/경험
                     (예: 발표 경험 1명 이상, 개발 경험 1명 이상)
    """

    same_major_max: int | None = None
    separate_pairs: list[tuple[str, str]] = field(default_factory=list)
    fixed_pairs: list[tuple[str, str]] = field(default_factory=list)
    spread_tags: list[str] = field(default_factory=list)
    role_minimums: dict[str, int] = field(default_factory=dict)


def soft_score(members: list[Candidate], w: SoftWeights) -> float:
    """팀 하나의 소프트 조화도 점수 0..100 (Σwₖsₖ/Σwₖ)."""
    if not members:
        return 0.0
    axes = {
        # 하드로 같은 학과 상한을 다루므로, 소프트 전공축은 '다양성'으로 둔다.
        "major": _major_score(members, same_major=False),
        "role": _role_score(members),
        "time": _time_score(members),
        "trait": _trait_score(members),
    }
    weights = {"major": w.major, "role": w.role, "time": w.time, "trait": w.trait}
    total = sum(weights.values()) or 1
    return round(sum(axes[k] * weights[k] for k in axes) / total, 2)


# ---- 하드 제약 위반 집계 ------------------------------------------------
def _has_tag(c: Candidate, tag: str) -> bool:
    """후보가 특정 태그/경험을 가졌는지. 역할 목록 또는 traits 키로 판단."""
    if tag in c.roles:
        return True
    return bool(c.traits.get(tag))


def team_violations(team: list[Candidate], hard: HardRules) -> int:
    """팀 하나가 어긴 하드 제약 개수."""
    v = 0

    # 1) 같은 학과 상한
    if hard.same_major_max is not None:
        counts: dict[str, int] = {}
        for m in team:
            if m.major:
                counts[m.major] = counts.get(m.major, 0) + 1
        v += sum(1 for n in counts.values() if n > hard.same_major_max)

    ids = {m.student_id for m in team}

    # 2) 분리 쌍: 둘 다 같은 팀에 있으면 위반
    for a, b in hard.separate_pairs:
        if a in ids and b in ids:
            v += 1

    # 3) 고정 쌍: 한 명만 이 팀에 있으면(= 떨어졌으면) 위반 (쌍당 한 번만 세도록 a 기준)
    for a, b in hard.fixed_pairs:
        if (a in ids) ^ (b in ids):
            v += 1

    # 4) 역할/경험 최소 보유 (예: 발표 1명 이상)
    for tag, need in hard.role_minimums.items():
        have = sum(1 for m in team if _has_tag(m, tag))
        if have < need:
            v += 1

    return v


def total_violations(teams: list[list[Candidate]], hard: HardRules) -> int:
    v = sum(team_violations(t, hard) for t in teams)

    # 분산 태그: 특정 팀에만 몰리면 위반 (팀 수 대비 과밀 팀 1개당 1 위반)
    for tag in hard.spread_tags:
        holders = [sum(1 for m in t if _has_tag(m, tag)) for t in teams]
        total_tag = sum(holders)
        if total_tag and teams:
            cap = -(-total_tag // len(teams))  # ceil: 팀당 허용 상한
            v += sum(1 for h in holders if h > cap)
    return v


# ---- 목적함수 J ---------------------------------------------------------
@dataclass
class Objective:
    j: float                 # 목적함수 값
    avg_fit: float           # 평균 조화도
    min_fit: float           # 최저 팀 점수
    violations: int          # 하드 위반 총합
    team_scores: list[float]  # 팀별 조화도


def objective(teams: list[list[Candidate]], w: SoftWeights, hard: HardRules) -> Objective:
    """J = 평균 조화도 + 최저 팀 점수 − 1000 × 하드 위반."""
    scores = [soft_score(t, w) for t in teams if t]
    if not scores:
        return Objective(j=0.0, avg_fit=0.0, min_fit=0.0, violations=0, team_scores=[])
    avg = round(sum(scores) / len(scores), 2)
    low = round(min(scores), 2)
    viol = total_violations(teams, hard)
    j = round(avg + low - HARD_PENALTY * viol, 2)
    return Objective(j=j, avg_fit=avg, min_fit=low, violations=viol, team_scores=scores)
