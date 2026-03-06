# 변경 이력 (Changelog)

퍼블리싱QA1팀 **Slack 알림 봇 (QA Supporter)** 버전 기록입니다.

> **버전 규칙 (Semantic Versioning)**
> - **Major** `x.0.0` : 기존 버전과 호환되지 않는 파격적 변경 (아키텍처 전면 개편 등)
> - **Minor** `0.x.0` : **새로운 기능 카테고리 추가 시에만** 올림
>   - 현재 기능: ① 슬랙 알리미(스케줄 알림)  ② /wiki 슬래시 커맨드
>   - 세 번째 기능 카테고리 추가 시 → v1.2.0
> - **Patch** `0.0.x` : 기능 추가 없는 버그 수정 / 기존 기능 개선 / 설정 변경
>   - 알리미 기능 개선(미션 리마인더 등), wiki 안정화 등은 모두 Patch
>
> **롤백 방법**: 각 버전은 git tag로 관리됩니다.
> ```powershell
> git checkout v1.1.3      # 특정 버전 코드 확인
> git checkout main        # 최신으로 복귀
> ```

---

## [1.1.5] - 2026-03-06 ← 현재

### 추가
- **알리미: 미션 미정 채널 전용 "선정 독려" 포맷** (`slack_sender.py`)
  - `mission.name == "미정"` 또는 빈 값이면 진행 현황 대신 독려 메시지 자동 전환
  - 진행율 막대 · 서브태스크 · 댓글 요청 블록 없이 심플한 구조
  - 포맷 내용: `⏳ 미션 선정 대기 중` + `💬 빨리 미션을 확정하고 도전을 시작해 봐요 🔥`
  - 미션 확정 시 `config.json`의 `name` 값만 변경하면 즉시 진행 현황 포맷으로 전환
- **`test_mission.py` 멀티 채널 지원**
  - 인수 없이 실행 시 확정 미션 3개 전체 전송
  - 인수 지정 시 특정 채널만 선택 전송 (예: `python test_mission.py mission-roundtable`)

---

## [1.1.4] - 2026-03-06

### 추가
- **WIKI 페이지별 검색 전략 예외처리 시스템** (`wiki_search_rules.json` 신규)
  - 페이지 제목 + 질문 키워드 조합으로 다른 CQL 조회 전략 자동 적용
  - `match_type` 지원: `exact` / `contains` / `startswith` / `regex`
  - 봇 재시작 없이 파일 수정만으로 즉시 반영 (**hot reload**)
- **`get_latest_descendant()` 메서드 추가** (`wiki_client.py`)
  - `ancestor = "페이지" ORDER BY created DESC LIMIT 1` CQL
  - 상위 페이지 전체 본문 로드 대비 토큰 대폭 절약
- **버전 관리 체계 도입** — `CHANGELOG.md` 생성, `git tag` 기반 롤백 지원

### 등록된 예외 규칙
| 규칙 ID | 페이지 | 트리거 | 전략 |
|---------|--------|--------|------|
| `rule-001` | `2026_MGQA` | 최근 / 최신 / 마지막 등 | `get_latest_descendant` |

> 배경: `2026_MGQA` 상위 페이지 본문에는 월별 하위 링크가 1월부터 순서대로 나열됨.
> "가장 최근 업무" 질문 시 1월 데이터를 답변하는 오류를 방지하기 위한 규칙.

---

## [1.1.3] - 2026-03-05

### 추가
- **WIKI: Confluence 브레드크럼 경로(` / ` 구분자) 지원**
  - Confluence UI에서 경로 그대로 복사하여 `/wiki` 커맨드에 붙여넣기 가능
  - `>` (봇 포맷)와 ` / ` (Confluence 포맷) 모두 지원
- **WIKI: 3단계 폴백 전략 완성**
  1. ancestor CQL 포함 검색
  2. CQL 파싱 오류 시 제목만으로 재시도
  3. 결과 없을 시 ancestor 조건 완전 제거 후 재시도
- **WIKI: 구조화된 디버그 로그** (`[wiki][1차]`, `[wiki][2차]`, `[wiki][결과] N건`)
- **WIKI: 실패 시 힌트 메시지** — 단순 제목 검색 / search 커맨드로 유도
- **알리미: Roundtable 채널 추가** (C0AKGRX2BKJ) — 토론 진행 기획
- **알리미: Tech Support 채널 추가** (C0AKGRTU36U) — Testrail TC 업로드 자동화
- **알리미: 스레드 진행율 댓글 요청 메시지** — 미완료 미션에만 표시

### 수정
- WIKI: CQL 특수문자(`[ ] { } ( )`) 포함 ancestor 자동 제외
  - `[Team Weekly Report]` 등 대괄호 포함 경로명으로 인한 CQL 파싱 오류 방지
- 알리미: Roundtable 채널 내용 TBD → 실제 내용으로 업데이트

---

## [1.1.2] - 2026-02-28

### 추가
- **알리미: 미션 진행 현황 리마인더** (신규 스케줄 타입 `mission`)
  - 6개 채널 평일 09:00~09:30 랜덤 지연 자동 발송
  - D-Day 카운터, 진행율 막대(████░░), 서브태스크 목록 포함
  - 전날 스레드 댓글에서 `N%` 패턴 자동 파싱 → 다음 날 진행율 반영
  - `mission_state.json` 채널별 상태 파일 관리
  - APScheduler `jitter=1800` 랜덤 지연

### 등록된 미션 채널 (6개, v1.1.3에서 일부 업데이트)
| 채널 | 미션 |
|------|------|
| AI-Driven QA Efficiency | Slack QA Supporter 활용 가이드 |
| Balance Engineering | (TBD) |
| Data analysis | (TBD) |
| Knowledge Management | (TBD) |
| Roundtable | (TBD → v1.1.3에서 업데이트) |
| Tech Support | (→ v1.1.3에서 추가) |

---

## [1.1.1] - 2026-02-20

### 수정
- **WIKI: SSE 응답 인코딩 버그 수정**
  - `r.text` (ISO-8859-1 자동 디코딩) → `r.content.decode('utf-8')` 명시 처리
  - 한글 페이지 제목/내용 깨짐 문제 해결
- **WIKI: `get_page_by_title` MCP 서버 버그** → `cql_search`로 대체
- **WIKI: 전체 본문 조회** — `cql_search` excerpt 대신 `get_page_by_id + expand: body.view`
- **WIKI: HTML 테이블 구조 보존** — `</td><td>` → ` | `, `<tr>` → `\n` 변환
- **WIKI: MCP 세션 만료 자동 재연결** — `_is_session_error()` + `_retry` 메커니즘
- **WIKI: Claude 답변 연도 범위 혼용 버그 수정** — 프롬프트 지침 추가
- **중복 프로세스 방지** — `_ensure_single_instance()` + PID 파일

---

## [1.1.0] - 2026-02-15

### 추가 (두 번째 기능 카테고리: Wiki 응답)
- **`/wiki` 슬래시 커맨드** (Confluence Wiki MCP 연동)
  - 페이지 제목 직접 검색
  - 계층 경로 지정 검색 (`>` 구분자)
  - Claude AI 기반 질문 답변 (`claude-haiku-4-5-20251001`)
  - 키워드 페이지 목록 검색 (`/wiki search`)
- **`/calendar` 슬래시 커맨드** (Confluence 캘린더 조회/등록)
- `_McpSession` 클래스 — Streamable HTTP 프로토콜 구현
- 페이지 본문 TTL 캐시 (300초)
- MCP 서버 연동: `http://mcp.sginfra.net/confluence-wiki-mcp`

---

## [1.0.0] - 2026-02-01

### 추가 (최초 릴리즈 — 첫 번째 기능 카테고리: 슬랙 알리미)
- **인터랙티브 체크리스트** (Slack Block Kit 기반)
  - 그룹 항목 / 단독 항목 혼용 구조
  - 다중 사용자 동시 체크 — merge 전략 (actions delta 기반)
  - 진행율 막대 실시간 업데이트 (`chat.update`)
  - 전일 누락 섹션 표시
- **등록 스케줄 (7종)**
  - 일일 업무 헤더 (09:00)
  - 일일 QA 체크리스트 (10:00)
  - 주간 QA 보고 (금 10:00)
  - 에픽세븐 업데이트 차수 체크리스트 (3주 간격)
  - 카제나 업데이트 차수 체크리스트 (3주 간격)
  - 월간 QA 체크리스트 (매월 마지막 금요일)
  - 분기 QA 체크리스트 (분기 첫째 주 월요일)
- **스케줄 타입 7종**: `daily` / `weekly` / `monthly` / `monthly_last_weekday` / `biweekly` / `nweekly` / `quarterly_first_monday` / `specific`
- **Railway + 로컬 PC 분리 아키텍처**
  - Railway: `--scheduler-only` (스케줄 발송 전담)
  - 로컬 PC: `--commands-only` (인터랙션 + 슬래시 커맨드)
- **상태 파일 fallback** — 로컬 상태 없을 때 Slack body + config.json으로 재구성
