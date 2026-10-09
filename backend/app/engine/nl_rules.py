"""주관식 요구사항 → 조건(DSL) 해석기.

사진 1·3 반영: "주관식은 언어모델이 조건 형식(DSL)으로 변환 → 교수 확인 후 반영".
교수가 자연어로 적은 요구사항을 구조화된 하드/소프트 조건으로 바꾼다.

설계
----
- `parse_requirements()` 가 공개 진입점. 기본은 규칙기반(규정 없이도 동작).
- 외부 LLM을 쓰고 싶으면 `llm` 콜백을 주입하면 그 결과를 우선 사용하고,
  규칙기반은 fallback 으로 둔다. (키 없이도 데모가 돌아가도록)
- 결과는 사람이 검토할 수 있도록 '원문 → 해석' 매핑(ParsedRule) 목록으로 돌려준다.
  (사진의 '해석 결과' 체크 UI와 대응)

안전장치
--------
자연어는 모호하므로, 해석된 조건은 바로 적용하지 않고 교수가 승인하는
구조를 가정한다(각 ParsedRule.applied 플래그). 여기서는 파싱까지만 담당.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Literal

from .constraints import HardRules, SoftWeights

RuleKind = Literal["hard", "soft"]


@dataclass
class ParsedRule:
    source: str          # 원문 조각
    kind: RuleKind       # 하드 / 소프트
    description: str     # 사람이 읽을 해석
    # 적용 대상 — 아래 중 해당하는 것만 채워짐
    role_min_tag: str | None = None       # 각 팀 최소 보유 태그(발표/개발)
    role_min_count: int = 1
    spread_tag: str | None = None         # 분산 대상 태그(예: '4학년')
    weight_axis: str | None = None        # 가중치 축 조정
    weight_delta: int = 0
    applied: bool = True                  # 교수 승인 여부(기본 True)


@dataclass
class ParseResult:
    rules: list[ParsedRule] = field(default_factory=list)
    # 아래 두 개는 rules를 집계해 엔진에 바로 넣을 수 있는 형태
    hard_patch: HardRules = field(default_factory=HardRules)
    weight_patch: dict[str, int] = field(default_factory=dict)


# 경험/역할 키워드 → 태그 정규화
_TAG_MAP = {
    "발표": "발표",
    "개발": "개발",
    "기획": "기획",
    "디자인": "디자인",
    "데이터": "데이터",
    "백엔드": "백엔드",
    "프론트": "프론트엔드",
}

_YEAR_RE = re.compile(r"([1-4])\s*학년")


def _rule_based(text: str) -> list[ParsedRule]:
    rules: list[ParsedRule] = []
    # 문장 단위로 쪼갠다(마침표/줄바꿈/쉼표 기준은 느슨하게).
    sentences = re.split(r"[.\n]", text)
    for raw in sentences:
        s = raw.strip()
        if not s:
            continue

        # 1) "각 팀에 최소 N명씩 포함" 류 → 하드(역할 최소 보유)
        if ("최소" in s or "1명" in s or "한 명" in s) and ("포함" in s or "이상" in s):
            count = 1
            m = re.search(r"최소\s*([0-9])", s)
            if m:
                count = int(m.group(1))
            for kw, tag in _TAG_MAP.items():
                if kw in s:
                    rules.append(
                        ParsedRule(
                            source=s,
                            kind="hard",
                            description=f"각 팀에 '{tag}' 경험자 {count}명 이상",
                            role_min_tag=tag,
                            role_min_count=count,
                        )
                    )

        # 2) "~학년은 한 팀에 몰리지 않게" 류 → 하드(분산)
        if ("몰리지" in s or "고르게" in s or "분산" in s):
            ym = _YEAR_RE.search(s)
            tag = f"{ym.group(1)}학년" if ym else None
            if tag:
                rules.append(
                    ParsedRule(
                        source=s,
                        kind="hard",
                        description=f"'{tag}'을(를) 여러 팀에 고르게 분산",
                        spread_tag=tag,
                    )
                )

        # 3) "전공/학과 다양하게/섞어서" 류 → 소프트(전공 가중치 ↑)
        if ("전공" in s or "학과" in s) and ("다양" in s or "섞" in s):
            rules.append(
                ParsedRule(
                    source=s,
                    kind="soft",
                    description="전공 다양성 가중치 강화",
                    weight_axis="major",
                    weight_delta=1,
                )
            )
    return rules


def parse_requirements(
    text: str,
    llm: Callable[[str], list[ParsedRule]] | None = None,
) -> ParseResult:
    """자연어 요구사항을 조건으로 해석.

    llm 콜백이 주어지면 그 결과를 우선 사용하고, 비면 규칙기반으로 보완한다.
    (운영에서 LLM 연동 시: 프롬프트로 DSL(JSON)을 받아 ParsedRule로 변환)
    """
    rules: list[ParsedRule] = []
    if llm is not None:
        try:
            rules = llm(text) or []
        except Exception:
            rules = []  # LLM 실패 시 규칙기반으로 안전하게 폴백
    if not rules:
        rules = _rule_based(text)

    # 승인된 규칙만 집계해 엔진 입력으로 변환
    hard = HardRules()
    weight_patch: dict[str, int] = {}
    for r in rules:
        if not r.applied:
            continue
        if r.kind == "hard":
            if r.role_min_tag:
                prev = hard.role_minimums.get(r.role_min_tag, 0)
                hard.role_minimums[r.role_min_tag] = max(prev, r.role_min_count)
            if r.spread_tag and r.spread_tag not in hard.spread_tags:
                hard.spread_tags.append(r.spread_tag)
        elif r.kind == "soft" and r.weight_axis:
            weight_patch[r.weight_axis] = weight_patch.get(r.weight_axis, 0) + r.weight_delta

    return ParseResult(rules=rules, hard_patch=hard, weight_patch=weight_patch)


def apply_weight_patch(base: SoftWeights, patch: dict[str, int]) -> SoftWeights:
    """소프트 가중치 패치를 1..5 범위로 클램프해 적용."""
    def clamp(v: int) -> int:
        return max(1, min(5, v))

    return SoftWeights(
        major=clamp(base.major + patch.get("major", 0)),
        role=clamp(base.role + patch.get("role", 0)),
        time=clamp(base.time + patch.get("time", 0)),
        trait=clamp(base.trait + patch.get("trait", 0)),
    )
