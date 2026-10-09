"""TeamFit AI 엔진(v2) 단위 테스트 — DB 불필요."""
from app.matching import Candidate
from app.engine.constraints import HardRules, SoftWeights, objective, soft_score
from app.engine.optimizer import optimize
from app.engine.precheck import precheck
from app.engine import nl_rules


def _mk(i, major, roles, slots=("0-0", "0-1", "0-2"), traits=None, year=2):
    return Candidate(
        student_id=str(i), name=f"s{i}", major=major, year=year,
        roles=list(roles), free_slots=set(slots),
        traits=traits or {"pace": 3, "prep": 3, "lead": 3, "comm": 3},
    )


def _pool(n=12):
    majors = ["데이터사이언스", "경영학", "컴퓨터공학", "시각디자인"]
    roles = ["기획", "프론트엔드", "백엔드", "데이터", "디자인", "발표"]
    return [_mk(i, majors[i % 4], [roles[i % 6]]) for i in range(n)]


# ---- 소프트 점수 / 목적함수 J ----
def test_soft_score_bounded():
    s = soft_score(_pool(4), SoftWeights())
    assert 0 <= s <= 100


def test_objective_penalizes_violation():
    # 같은 학과만 모아 상한 위반을 유도
    same = [_mk(i, "컴퓨터공학", ["기획"]) for i in range(4)]
    hard = HardRules(same_major_max=2)
    o = objective([same], SoftWeights(), hard)
    assert o.violations >= 1
    # J = 평균 + 최저 − 1000*위반 이므로 음수로 크게 떨어진다
    assert o.j < 0


# ---- 최적화 ----
def test_optimize_assigns_everyone_once():
    pool = _pool(12)
    sol = optimize(pool, team_size=4, weights=SoftWeights(), hard=HardRules(), starts=2, seed=1)
    # Solution.teams 는 list[list[Candidate]] 구조다.
    placed = [m.student_id for team in sol.teams for m in team]
    assert sorted(placed) == sorted(c.student_id for c in pool)
    assert len(sol.teams) == 3


def test_optimize_is_deterministic_with_seed():
    pool = _pool(12)
    a = optimize(pool, 4, SoftWeights(), HardRules(), starts=2, seed=42)
    b = optimize(pool, 4, SoftWeights(), HardRules(), starts=2, seed=42)
    assert a.obj.j == b.obj.j


def test_optimize_respects_role_minimum_when_feasible():
    # 12명 중 발표 태그 보유자를 충분히 둬서 각 팀 1명 이상 가능하게
    pool = []
    for i in range(12):
        roles = ["발표"] if i % 2 == 0 else ["백엔드"]
        pool.append(_mk(i, ["A", "B", "C"][i % 3], roles))
    hard = HardRules(role_minimums={"발표": 1})
    sol = optimize(pool, 4, SoftWeights(role=5), hard, starts=3, seed=7)
    # 위반 0이 이상적(가능한 구성이므로); 최소한 패널티로 J가 음수폭주하진 않아야
    assert sol.obj.violations == 0


# ---- 사전 점검 ----
def test_precheck_detects_infeasible_role_min():
    # 발표 보유자 1명뿐인데 3팀 각 1명 요구 → 불가능
    pool = [_mk(i, "A", ["발표"] if i == 0 else ["백엔드"]) for i in range(12)]
    hard = HardRules(role_minimums={"발표": 1})
    pc = precheck(pool, 4, hard)
    assert pc.feasible is False
    assert any(not it.ok for it in pc.items)


def test_precheck_feasible_simple():
    pc = precheck(_pool(12), 4, HardRules())
    assert pc.team_count == 3
    assert pc.feasible is True


# ---- 주관식 해석 ----
def test_parse_role_minimum_and_spread():
    text = "발표 경험이 있는 학생과 개발 경험이 있는 학생을 각 팀에 최소 1명씩 포함해 주세요. 4학년은 한 팀에 몰리지 않게 해주세요."
    res = nl_rules.parse_requirements(text)
    assert res.hard_patch.role_minimums.get("발표") == 1
    assert res.hard_patch.role_minimums.get("개발") == 1
    assert "4학년" in res.hard_patch.spread_tags


def test_parse_major_diversity_to_weight():
    res = nl_rules.parse_requirements("전공이 다양하게 섞이도록 해주세요.")
    assert res.weight_patch.get("major", 0) >= 1
