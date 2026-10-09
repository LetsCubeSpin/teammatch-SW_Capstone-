# TeamMatch 백엔드 테스트 가이드

이 문서는 `backend/` 코드를 **처음부터 끝까지(가입 → 수업 → 설문 → 매칭 성공)**
테스트하는 방법을 정리한 것입니다. 팀원이 공유해준 테스트 메모를 바탕으로,
빠진 선행 단계와 "매칭 성공" 시나리오, v2 엔드포인트를 보충했습니다.

> 참고: 팀원 메모는 다른 레포(teammatch-SW_Capstone-) 기준이라 일부 에러
> 메시지/상태코드가 이 코드와 다릅니다. 아래는 이 `backend/` 코드 기준입니다.

---

## 0. 선행 설치 (메모에 빠져 있던 단계)

uvicorn을 바로 실행하면 패키지가 없어서 실패합니다. 먼저 설치하세요.

```powershell
cd <프로젝트 경로>\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # 그리고 DATABASE_URL 등 값 확인/수정
```

`.env`의 `DATABASE_URL`이 실제 PostgreSQL 접속 정보와 맞는지 꼭 확인하세요.
(기본값: `postgresql+psycopg://teammatch:teammatch@localhost:5432/teammatch`)

---

## 1. 데이터베이스 준비

```sql
-- psql에서
CREATE DATABASE teammatch;
\c teammatch
\i 'C:/.../backend/db/schema.sql'
```

### 한글 인코딩 오류가 날 때
`schema.sql`에는 한글(ENUM 값, 프리셋 이름)이 들어 있어 인코딩 문제가 잦습니다.

- 방법 A) psql 세션에서 `\encoding UTF8` 후 다시 `\i` 실행
- 방법 B) `\i` 대신 명령줄에서 직접 로드(더 안정적):
  ```powershell
  psql -U postgres -d teammatch -f "C:/.../backend/db/schema.sql" -v ON_ERROR_STOP=1
  ```
- 그래도 깨지면 DB를 드롭 후 재생성하고 다시 시도:
  ```sql
  \c postgres
  DROP DATABASE teammatch;
  CREATE DATABASE teammatch;
  ```

---

## 2. 서버 실행

```powershell
cd <프로젝트 경로>\backend
uvicorn app.main:app --reload
```

- Swagger UI: http://127.0.0.1:8000/docs
- 헬스체크: http://127.0.0.1:8000/health → `{"status":"ok"}`

---

## 3. 교수 흐름 (수업 만들기)

### 3-1. 교수 가입 — `POST /api/auth/signup`
```json
{
  "role": "professor",
  "name": "Kim",
  "email": "prof@test.com",
  "password": "password123",
  "school": "ERICA",
  "dept": "CS"
}
```

### 3-2. 로그인 — `POST /api/auth/login`
- Swagger 상단 **Authorize** 클릭 → `username`에 이메일, `password` 입력
- (주의) 로그인 폼의 username = **이메일**입니다. 비밀번호 8자 이상.

### 3-3. 수업 생성 — `POST /api/classes`
```json
{ "name": "Algorithm", "code": "CS101", "term": "2026_1", "capacity": 30 }
```
- 응답 201에서 **`id`(class_id)** 와 **`join_code`(참여 코드)** 를 기억해 둡니다.

---

## 4. 학생 흐름 (설문 제출) — 매칭 성공을 위해 꼭 필요

팀원 메모가 "제출 학생 없음"에서 막힌 이유가 여기입니다. 매칭은
**설문을 match_ready=true 로 제출한 학생만** 후보로 삼습니다.
팀을 만들려면 team_size 이상의 학생이 필요합니다(기본 테스트는 4명 이상 권장).

학생마다 아래 3단계를 반복합니다. (학생마다 다른 이메일 사용)

### 4-1. 학생 가입 — `POST /api/auth/signup`
```json
{
  "role": "student",
  "name": "Lee",
  "email": "stu1@test.com",
  "password": "password123",
  "major": "CS",
  "year": 2,
  "student_id": "2024000001"
}
```

### 4-2. 학생으로 로그인 후, 수업 참여 — `POST /api/classes/join`
```json
{ "join_code": "<3-3에서 받은 참여 코드>" }
```

### 4-3. 설문 제출 — `PUT /api/classes/{class_id}/survey`
```json
{
  "roles": ["백엔드", "데이터"],
  "skills": [{ "name": "Python", "level": 4 }],
  "traits": { "pace": 3, "prep": 2, "lead": 4, "comm": 3 },
  "availability": [
    { "day": 0, "block": 5, "state": "y" },
    { "day": 1, "block": 5, "state": "y" }
  ],
  "match_ready": true
}
```

> ★ 함정: `match_ready` 를 `true` 로 보내야 매칭 후보에 포함됩니다.
> `false`(또는 생략)면 설문을 냈어도 `survey_submitted=false` 로 저장되어
> 매칭에서 제외됩니다. (surveys.py: `survey_submitted = body.match_ready`)

---

## 5. 매칭 실행 (성공 케이스) — `POST /api/classes/{class_id}/match`

다시 **교수로 로그인**한 뒤 실행합니다.
```json
{
  "team_size": 4,
  "weights": { "major": 3, "role": 3, "time": 3, "trait": 3 },
  "hard": { "same_major": false, "fix_pair": false, "split_pair": false, "even_transfer": false }
}
```
- 학생이 team_size 이상 제출돼 있으면 200과 함께 팀 목록이 나옵니다.

### 실패/경계 케이스(팀원 메모 재현 — 이 코드 기준 값)
| 입력 | 결과 |
|---|---|
| `team_size: 0` | 422 (스키마 검증: 2~8 범위 밖) |
| 존재하지 않는 class_id | 404 "수업을 찾을 수 없습니다." |
| 제출 학생 < team_size | 422 "편성 가능한 제출자가 부족합니다. (현재 N명)" |

---

## 6. v2 엔진 테스트 (TeamFit) — 팀원 메모에 없던 신규

### 6-1. 실행 전 점검 — `POST /api/classes/{class_id}/precheck`
```json
{
  "team_size": 4,
  "weights": { "major": 4, "role": 5, "time": 3, "trait": 3 },
  "hard": { "same_major_max": 2, "role_minimums": { "발표": 1 } },
  "note": "발표 경험이 있는 학생을 각 팀에 최소 1명씩 포함해 주세요."
}
```
- 조건 충족 가능 여부(feasible)와 항목별 점검 결과를 돌려줍니다.

### 6-2. v2 매칭 실행 — `POST /api/classes/{class_id}/match-v2`
- 같은 body 사용. 응답에 목적함수 J, 평균/최저 조화도, 하드위반 수,
  교환 횟수, 팀별 결과(최저 팀 표시), 조화도 추이, 주관식 해석이 담깁니다.
- 점검이 불가능(feasible=false)하면 422로 막고 완화 안내를 줍니다.

### 6-3. 엔진 단위 테스트 (DB 불필요, 가장 빠른 검증)
```powershell
cd backend
pytest -q
```

---

## 7. soft delete(회원 탈퇴) 확인

1. `DELETE /api/auth/me` 호출 → 204
2. 같은 계정으로 다시 `POST /api/auth/login` → 403 "탈퇴한 계정입니다."
3. 탈퇴 전 토큰으로 `GET /api/auth/me` → 403 (인증 단계에서 차단)
   (DB에서 행은 지워지지 않고 `is_active=false`, `deactivated_at` 기록됨)

---

## 부록 A. 팀원 테스트 메모의 문제점 분석

> 동작 자체는 정상이었고(검증 성공), 아래는 "가이드 문서로서의 공백"입니다.

1. **선행 설치 단계 누락**
   - `pip install -r requirements.txt`, `.env` 생성이 없음.
   - 이 상태면 uvicorn 실행이 실패하는데, 메모만 보면 원인을 알기 어렵습니다.

2. **실패 경로만 검증, 성공 경로 없음**
   - 메모의 매칭 테스트는 전부 404/422/400 같은 "막히는" 경우입니다.
   - 학생 가입→참여→설문 제출이 없어 **팀이 실제로 편성되는 성공 케이스**를
     한 번도 확인하지 못했습니다. (가장 중요한 경로가 비어 있음)

3. **에러 메시지/상태코드가 이 코드와 불일치**
   - 메모: 400 "매칭 참여가 가능한 설문 제출 학생이 없습니다."
   - 이 코드: 422 "편성 가능한 제출자가 부족합니다."
   - → 테스트한 레포가 이 `backend/`와 다른 버전임을 시사. 어떤 코드를
     최종본으로 삼을지 팀 내 합의가 필요합니다.

4. **match_ready 함정 미언급**
   - 설문을 내도 `match_ready=true`가 아니면 매칭에서 빠지는데, 메모에
     이 조건이 없어 "설문 냈는데 왜 매칭 안 되지?"에 빠지기 쉽습니다.

5. **v2 엔드포인트 미포함**
   - `/precheck`, `/match-v2`가 테스트 범위에 전혀 없습니다.

6. **경로가 로컬 절대경로에 고정**
   - `C:/users/administrator/...` 처럼 특정 PC 경로라 다른 팀원이 그대로
     못 씁니다. `<프로젝트 경로>`처럼 치환 표기가 안전합니다.

---

## 부록 B. 이 백엔드 코드/문서의 문제점 분석 (자체 점검)

솔직한 자체 진단입니다. 과제용으로는 괜찮지만, 아래는 알고 있어야 합니다.

1. **ORM 모델이 테이블을 자동 생성하지 않음**
   - `Base.metadata.create_all()` 호출이 없어, 반드시 `schema.sql`을 수동
     로드해야 합니다. 스키마와 모델이 어긋나면 런타임 오류가 납니다.
     (예: 이번에 추가한 `is_active` 컬럼을 기존 DB에 안 넣으면 깨짐)

2. **스키마 변경 시 2곳(+모델) 수동 동기화**
   - `models.py`, `schema.sql`, `schema.mysql.sql`을 사람이 맞춰야 합니다.
   - Alembic 같은 마이그레이션 도구가 없어 실수 가능성이 있습니다.

3. **매칭 결과 조회 API 부재**
   - 매칭 결과를 저장만 하고 다시 조회하는 엔드포인트가 없습니다.
     (TODO: `GET /api/classes/{id}/result`)

4. **하드 제약 세부값이 저장되지 않음**
   - v2의 상한값/지정 쌍 등은 실행에만 쓰이고 DB에는 bool 플래그로만
     남습니다. 결과 재현/감사에 한계가 있습니다.

5. **테스트가 엔진에 치우침**
   - `tests/`는 매칭 엔진 로직만 검증합니다. 라우터(인증/권한/수업 흐름)
     레벨 테스트가 없어, API 리그레션을 못 잡습니다.
   - 게다가 v2 테스트는 아직 `pytest`로 **실행 검증을 하지 않았습니다.**

6. **운영 설정 미비**
   - `.gitignore`, 배포 설정(Docker 등), 운영용 비밀키 관리가 없습니다.
   - `config.py`의 `jwt_secret` 기본값이 placeholder라 운영 전 교체 필수.

7. **CORS 출처가 예시값**
   - `config.py`의 `cors_origins`가 로컬 개발 포트로 고정. 실제 프론트
     주소에 맞춰 조정해야 브라우저에서 호출됩니다.
