"""TeamFit AI 매칭 엔진 (v2).

사진 시연("TeamFit AI 매칭 엔진")의 설계를 코드로 옮긴 패키지입니다.
구성:
  - constraints.py : 소프트 가중치 / 하드 제약 / 목적함수 J
  - precheck.py    : 실행 전 점검(편성 가능 여부) + 완화안 제안
  - optimizer.py   : 초기배정 → 지역탐색(LS) → 시뮬레이티드 어닐링(SA) → best-of-3
  - nl_rules.py    : 주관식 요구사항 → 조건(DSL) 해석기

기존 app/matching.py 의 축별 점수 함수(_major_score 등)와 Candidate 를
재사용합니다. 이 패키지는 DB에 의존하지 않는 순수 파이썬입니다.
"""
