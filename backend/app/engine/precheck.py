"""실행 전 점검(feasibility pre-check) + 완화안 제안.

사진 4("실행 전 점검 — 이 조건으로 편성이 가능한가?") 반영.
지역 탐색은 '못 맞춤'과 '불가능'을 구분하지 못하므로, 실행 전에
"조건을 동시에 만족하는 편성이 존재할 수 있는지"를 먼저 확인하고,
불가능하면 완화안을 제안한다.

각 항목은 통과 여부 + 사람이 읽을 설명을 함께 돌려준다.
(예: "최다 '수리데이터사이언스학과' 16명 / 수용 22명")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil

from ..matching import Candidate
from .constraints import HardRules, _has_tag


@dataclass
class CheckItem:
    name: str          # 점검 항목 이름
    ok: bool           # 통과 여부
    detail: str        # 근거 설명
    suggestion: str | None = None  # 불가 시 완화안


@dataclass
class PrecheckResult:
    feasible: bool
    team_count: int
    composition: str              # "5명×1 + 4명×10" 같은 팀 구성 요약
    items: list[CheckItem] = field(default_factory=list)


def _team_plan(n: int, team_size: int) -> tuple[int, str]:
    """n명을 team_size 기준으로 몇 팀으로 나누고, 구성을 문자열로."""
    if team_size <= 0 or n <= 0:
        return 0, "—"
    k = max(1, round(n / team_size))
    base = n // k
    extra = n % k            # extra개 팀은 (base+1)명
    bigs = extra
    smalls = k - extra
    parts = []
    if bigs:
        parts.append(f"{base + 1}명×{bigs}")
    if smalls:
        parts.append(f"{base}명×{smalls}")
    return k, " + ".join(parts)


def precheck(
    candidates: list[Candidate], team_size: int, hard: HardRules
) -> PrecheckResult:
    n = len(candidates)
    k, composition = _team_plan(n, team_size)
    items: list[CheckItem] = []

    # 1) 같은 학과 인원 상한 — 가장 많은 학과가 모든 팀에 상한 이하로 분산 가능한가?
    if hard.same_major_max is not None:
        major_counts: dict[str, int] = {}
        for c in candidates:
            if c.major:
                major_counts[c.major] = major_counts.get(c.major, 0) + 1
        if major_counts:
            top_major, top_n = max(major_counts.items(), key=lambda kv: kv[1])
            capacity = k * hard.same_major_max   # 팀마다 상한만큼 수용 가능
            ok = top_n <= capacity
            items.append(
                CheckItem(
                    name=f"같은 학과 인원 {hard.same_major_max}명 이하",
                    ok=ok,
                    detail=f"최다 '{top_major}' {top_n}명 / 수용 {capacity}명",
                    suggestion=None if ok else "상한을 1명 늘리거나 팀 수를 늘리세요.",
                )
            )

    # 2) 분리 쌍 — 팀이 2개 이상이면 분리는 항상 가능
    for i, (a, b) in enumerate(hard.separate_pairs, start=1):
        ok = k >= 2
        items.append(
            CheckItem(
                name=f"특정 학생 분리 {chr(0x2460 + i - 1)}",  # ①②③…
                ok=ok,
                detail="2명 지정",
                suggestion=None if ok else "팀이 1개뿐이라 분리할 수 없습니다.",
            )
        )

    # 3) 역할/경험 최소 보유 — 보유자 수가 '팀 수 × 최소치' 이상인가?
    for tag, need in hard.role_minimums.items():
        have = sum(1 for c in candidates if _has_tag(c, tag))
        required = k * need
        ok = have >= required
        items.append(
            CheckItem(
                name=f"각 팀 '{tag}' {need}명 이상",
                ok=ok,
                detail=f"보유 {have}명 / 필요 {required}명",
                suggestion=None if ok else f"'{tag}' 보유자가 부족합니다. 조건을 완화하세요.",
            )
        )

    # 4) 고정 쌍 — 같은 팀 정원 안에 들어갈 수 있는가(쌍 크기 <= 팀 크기)?
    for a, b in hard.fixed_pairs:
        ok = team_size >= 2
        items.append(
            CheckItem(
                name="특정 학생 같은 팀 고정",
                ok=ok,
                detail="2명 지정",
                suggestion=None if ok else "팀 인원이 2명 미만이라 고정할 수 없습니다.",
            )
        )

    # 5) 팀 구성 자체가 성립하는지
    items.append(
        CheckItem(
            name="팀 구성",
            ok=k > 0 and n >= team_size,
            detail=composition,
            suggestion=None if (k > 0 and n >= team_size) else "제출 인원이 팀 크기보다 적습니다.",
        )
    )

    feasible = all(it.ok for it in items)
    return PrecheckResult(feasible=feasible, team_count=k, composition=composition, items=items)
