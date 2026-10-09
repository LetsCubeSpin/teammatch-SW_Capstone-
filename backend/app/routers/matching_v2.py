"""매칭 엔진 v2 라우터 (TeamFit AI).

엔드포인트
  POST /api/classes/{id}/precheck   : 실행 전 점검 (사진 4)
  POST /api/classes/{id}/match-v2   : J 최적화 실행 + 지표/추이 (사진 5~10)

기존 matching.py 의 _load_candidates 를 재사용해 설문 제출자를 모은 뒤,
engine 패키지(constraints/precheck/optimizer/nl_rules)로 편성한다.
결과는 기존 match_runs/teams/team_members 테이블에 저장한다.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..engine import nl_rules
from ..engine.constraints import HardRules, SoftWeights, objective
from ..engine.optimizer import optimize
from ..engine.precheck import precheck
from ..models import Class, MatchRun, Team, TeamMember, User
from ..matching import assign_roles
from ..schemas import (
    CheckItemOut,
    MatchV2Request,
    MatchV2Result,
    ParsedRuleOut,
    PrecheckOut,
    TraceOut,
    V2MemberOut,
    V2TeamOut,
)
from ..security import require_professor
from .matching import _load_candidates

router = APIRouter(prefix="/api", tags=["matching-v2"])


def _owned_class(db: Session, class_id: uuid.UUID, prof: User) -> Class:
    c = db.get(Class, class_id)
    if not c or c.professor_id != prof.id:
        raise HTTPException(status_code=404, detail="수업을 찾을 수 없습니다.")
    return c


def _build_hard(body: MatchV2Request, note_hard: HardRules | None) -> HardRules:
    """요청의 하드 제약 + 주관식 해석 하드 제약을 병합."""
    hard = HardRules(
        same_major_max=body.hard.same_major_max,
        separate_pairs=[tuple(p) for p in body.hard.separate_pairs],
        fixed_pairs=[tuple(p) for p in body.hard.fixed_pairs],
        spread_tags=list(body.hard.spread_tags),
        role_minimums=dict(body.hard.role_minimums),
    )
    if note_hard:
        for tag, need in note_hard.role_minimums.items():
            hard.role_minimums[tag] = max(hard.role_minimums.get(tag, 0), need)
        for tag in note_hard.spread_tags:
            if tag not in hard.spread_tags:
                hard.spread_tags.append(tag)
    return hard


@router.post("/classes/{class_id}/precheck", response_model=PrecheckOut)
def run_precheck(
    class_id: uuid.UUID,
    body: MatchV2Request,
    prof: User = Depends(require_professor),
    db: Session = Depends(get_db),
) -> PrecheckOut:
    _owned_class(db, class_id, prof)
    candidates, _ = _load_candidates(db, class_id)

    parsed = nl_rules.parse_requirements(body.note or "")
    hard = _build_hard(body, parsed.hard_patch)

    result = precheck(candidates, body.team_size, hard)
    return PrecheckOut(
        feasible=result.feasible,
        team_count=result.team_count,
        composition=result.composition,
        items=[CheckItemOut(name=i.name, ok=i.ok, detail=i.detail, suggestion=i.suggestion)
               for i in result.items],
    )


@router.post("/classes/{class_id}/match-v2", response_model=MatchV2Result)
def run_match_v2(
    class_id: uuid.UUID,
    body: MatchV2Request,
    prof: User = Depends(require_professor),
    db: Session = Depends(get_db),
) -> MatchV2Result:
    c = _owned_class(db, class_id, prof)
    candidates, _ = _load_candidates(db, class_id)
    if len(candidates) < body.team_size:
        raise HTTPException(
            status_code=422, detail=f"편성 가능한 제출자가 부족합니다. (현재 {len(candidates)}명)"
        )

    # 1) 주관식 요구사항 해석 → 하드/소프트 보정
    parsed = nl_rules.parse_requirements(body.note or "")
    base_w = SoftWeights(**body.weights.model_dump())
    weights = nl_rules.apply_weight_patch(base_w, parsed.weight_patch)
    hard = _build_hard(body, parsed.hard_patch)

    # 2) 실행 전 점검 — 불가능하면 완화안과 함께 막는다
    pc = precheck(candidates, body.team_size, hard)
    if not pc.feasible:
        blocked = [i.name for i in pc.items if not i.ok]
        raise HTTPException(
            status_code=422,
            detail=f"현재 조건으로는 편성이 불가능합니다: {', '.join(blocked)}. 조건을 완화하세요.",
        )

    # 3) J 최적화 (초기배정 → LS → SA → best-of-3)
    sol = optimize(candidates, body.team_size, weights, hard, starts=body.starts, seed=body.seed)

    # 4) 결과 저장 (기존 테이블 재사용)
    run = MatchRun(
        class_id=class_id,
        team_size=body.team_size,
        w_major=weights.major, w_role=weights.role, w_time=weights.time, w_trait=weights.trait,
        h_same_major=bool(hard.same_major_max),
        h_fix_pair=bool(hard.fixed_pairs),
        h_split_pair=bool(hard.separate_pairs),
        h_even_transfer=bool(hard.spread_tags),
        note=body.note,
        avg_score=sol.obj.avg_fit,
    )
    db.add(run)
    db.flush()

    # 최저 팀 식별(주황 테두리)
    scores = sol.obj.team_scores
    min_score = min(scores) if scores else 0.0

    teams_out: list[V2TeamOut] = []
    for i, team in enumerate(sol.teams, start=1):
        score = sol.obj.team_scores[i - 1] if i - 1 < len(sol.obj.team_scores) else 0.0
        row = Team(run_id=run.id, class_id=class_id, name=f"{i}팀", fit_score=score)
        db.add(row)
        db.flush()
        roles = assign_roles(team)
        members_out: list[V2MemberOut] = []
        for m in team:
            db.add(TeamMember(team_id=row.id, student_id=uuid.UUID(m.student_id),
                              assigned_role=roles.get(m.student_id)))
            members_out.append(V2MemberOut(
                student_id=uuid.UUID(m.student_id), name=m.name,
                major=m.major, year=m.year, assigned_role=roles.get(m.student_id),
            ))
        teams_out.append(V2TeamOut(
            name=row.name, fit_score=score,
            is_lowest=(abs(score - min_score) < 1e-9), members=members_out,
        ))

    c.status = "편성 완료"
    db.commit()

    return MatchV2Result(
        team_count=len(sol.teams),
        objective_j=sol.obj.j,
        avg_fit=sol.obj.avg_fit,
        min_fit=sol.obj.min_fit,
        hard_violations=sol.obj.violations,
        swaps=sol.swaps,
        teams=teams_out,
        trace=TraceOut(stage=sol.trace.stage, avg=sol.trace.avg, low=sol.trace.low),
        parsed_rules=[ParsedRuleOut(source=r.source, kind=r.kind,
                                    description=r.description, applied=r.applied)
                      for r in parsed.rules],
    )
