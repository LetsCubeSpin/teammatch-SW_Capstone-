"""목적함수 J 기반 팀 편성 최적화 엔진.

사진 5~8의 4단계 파이프라인을 그대로 구현한다.

  ① 초기 배정 (greedy seed)
     발표·개발 경험처럼 '귀한 조건' 보유자를 팀마다 먼저 나누고,
     나머지는 점수가 가장 오르는 팀에 넣는다.
  ② 지역 탐색 LS (local search, 2명 교환)
     두 학생을 맞바꿔 '평균 + 최저 팀' 점수가 오를 때만 채택.
     최저 팀(주황 테두리)을 계속 끌어올리는 방향.
  ③ 시뮬레이티드 어닐링 SA
     잠시 점수가 내려가는 교환도 확률적으로 허용해 지역 최적해를
     벗어난 뒤, 마무리는 다시 지역 탐색으로 다듬는다.
  ④ 완료 (best-of-3)
     서로 다른 초기값에서 3회 실행해 그중 J가 가장 높은 결과 채택.

목적함수 J = 평균 조화도 + 최저 팀 점수 − 1000 × 하드 위반  (constraints.objective)
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ..matching import Candidate
from .constraints import HardRules, Objective, SoftWeights, objective, soft_score, team_violations


@dataclass
class Trace:
    """최적화 진행 기록(사진의 '조화도 추이' 그래프용)."""

    stage: list[str] = field(default_factory=list)   # 각 지점의 단계명
    avg: list[float] = field(default_factory=list)   # 평균 조화도 추이
    low: list[float] = field(default_factory=list)   # 최저 팀 점수 추이


@dataclass
class Solution:
    teams: list[list[Candidate]]
    obj: Objective
    swaps: int                 # 채택된 교환 횟수 (사진 '매칭 교환')
    trace: Trace


def _team_count(n: int, team_size: int) -> int:
    return max(1, round(n / team_size)) if n and team_size else 0


# ---- ① 초기 배정 --------------------------------------------------------
def _seed(candidates: list[Candidate], k: int, w: SoftWeights, hard: HardRules,
          rng: random.Random) -> list[list[Candidate]]:
    pool = list(candidates)
    rng.shuffle(pool)

    # 귀한 역할/경험(=role_minimums 태그) 보유자를 먼저 팀마다 분산.
    def rarity(c: Candidate) -> int:
        return sum(1 for tag in hard.role_minimums if tag in c.roles or c.traits.get(tag))

    pool.sort(key=rarity, reverse=True)
    teams: list[list[Candidate]] = [[] for _ in range(k)]

    # 라운드로빈으로 귀한 보유자 우선 분산
    idx = 0
    for c in pool[:k]:
        teams[idx].append(c)
        idx += 1

    # 나머지는 '추가 시 점수가 가장 오르는' 미달 팀에 그리디 배정
    target = _balanced_sizes(len(candidates), k)
    for c in pool[k:]:
        best, best_gain = None, float("-inf")
        for ti, t in enumerate(teams):
            if len(t) >= target[ti]:
                continue
            gain = soft_score(t + [c], w) - soft_score(t, w)
            # 하드 위반을 늘리는 배치는 강하게 회피
            gain -= 1000 * (team_violations(t + [c], hard) - team_violations(t, hard))
            if gain > best_gain:
                best, best_gain = ti, gain
        teams[best if best is not None else _smallest(teams, target)].append(c)
    return teams


def _balanced_sizes(n: int, k: int) -> list[int]:
    base, extra = divmod(n, k)
    return [base + 1 if i < extra else base for i in range(k)]


def _smallest(teams: list[list[Candidate]], target: list[int]) -> int:
    return min(range(len(teams)), key=lambda i: len(teams[i]) - target[i])


def _pair_metric(teams, w, hard) -> tuple[float, Objective]:
    o = objective(teams, w, hard)
    # LS/SA가 끌어올릴 대상: 평균 + 최저 − 하드패널티 (= J와 동일 방향)
    return o.j, o


# ---- ② 지역 탐색 (2명 교환) --------------------------------------------
def _local_search(teams, w, hard, rng, trace, max_pass=40) -> int:
    swaps = 0
    cur, _ = _pair_metric(teams, w, hard)
    improved = True
    passes = 0
    while improved and passes < max_pass:
        improved = False
        passes += 1
        for a in range(len(teams)):
            for b in range(a + 1, len(teams)):
                for i in range(len(teams[a])):
                    for j in range(len(teams[b])):
                        teams[a][i], teams[b][j] = teams[b][j], teams[a][i]
                        cand, o = _pair_metric(teams, w, hard)
                        if cand > cur + 1e-9:
                            cur = cand
                            swaps += 1
                            improved = True
                            trace.stage.append("LS")
                            trace.avg.append(o.avg_fit)
                            trace.low.append(o.min_fit)
                        else:
                            teams[a][i], teams[b][j] = teams[b][j], teams[a][i]  # 되돌림
    return swaps


# ---- ③ 시뮬레이티드 어닐링 ---------------------------------------------
def _anneal(teams, w, hard, rng, trace, iters=9000, t0=8.0, t1=0.05) -> int:
    swaps = 0
    cur, _ = _pair_metric(teams, w, hard)
    for step in range(iters):
        temp = t0 * (t1 / t0) ** (step / max(1, iters - 1))  # 지수 냉각
        a, b = rng.sample(range(len(teams)), 2)
        if not teams[a] or not teams[b]:
            continue
        i = rng.randrange(len(teams[a]))
        j = rng.randrange(len(teams[b]))
        teams[a][i], teams[b][j] = teams[b][j], teams[a][i]
        cand, o = _pair_metric(teams, w, hard)
        delta = cand - cur
        # 개선이면 수락, 악화여도 exp(delta/temp) 확률로 수락
        if delta > 0 or rng.random() < math.exp(delta / max(temp, 1e-6)):
            cur = cand
            swaps += 1
            if step % 300 == 0:
                trace.stage.append("SA")
                trace.avg.append(o.avg_fit)
                trace.low.append(o.min_fit)
        else:
            teams[a][i], teams[b][j] = teams[b][j], teams[a][i]  # 되돌림
    return swaps


# ---- 한 번의 전체 실행 --------------------------------------------------
def _run_once(candidates, team_size, w, hard, rng) -> Solution:
    k = _team_count(len(candidates), team_size)
    trace = Trace()
    teams = _seed(candidates, k, w, hard, rng)

    o0 = objective(teams, w, hard)
    trace.stage.append("seed"); trace.avg.append(o0.avg_fit); trace.low.append(o0.min_fit)

    swaps = _local_search(teams, w, hard, rng, trace)   # ② LS
    swaps += _anneal(teams, w, hard, rng, trace)        # ③ SA
    swaps += _local_search(teams, w, hard, rng, trace)  # 마무리 LS

    return Solution(teams=teams, obj=objective(teams, w, hard), swaps=swaps, trace=trace)


# ---- ④ best-of-3 공개 진입점 -------------------------------------------
def optimize(
    candidates: list[Candidate],
    team_size: int,
    weights: SoftWeights,
    hard: HardRules,
    starts: int = 3,
    seed: int | None = None,
) -> Solution:
    """서로 다른 초기값에서 starts회 실행해 J가 가장 큰 해를 반환."""
    if not candidates:
        return Solution(teams=[], obj=objective([], weights, hard), swaps=0, trace=Trace())

    best: Solution | None = None
    for s in range(starts):
        rng = random.Random((seed if seed is not None else 0) + s)
        sol = _run_once(candidates, team_size, weights, hard, rng)
        if best is None or sol.obj.j > best.obj.j:
            best = sol
    return best
