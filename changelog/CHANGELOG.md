# 변경 이력 (Changelog)

퍼블리싱QA1팀 **Slack 알림 봇 (QA Supporter)** 버전 기록입니다.

> **버전 규칙 (Semantic Versioning)**
> - **Major** `x.0.0` : 기존 버전과 호환되지 않는 파격적 변경 (아키텍처 전면 개편 등)
> - **Minor** `0.x.0` : **새로운 기능 카테고리 추가 시에만** 올림
>   - 현재 기능: ① 슬랙 알리미(스케줄 알림)  ② /wiki 슬래시 커맨드  ③ /gdi 슬래시 커맨드  ④ /jira 슬래시 커맨드
>   - 다섯 번째 기능 카테고리 추가 시 → v1.5.0
> - **Patch** `0.0.x` : 기능 추가 없는 버그 수정 / 기존 기능 개선 / 설정 변경
>   - 알리미 기능 개선(미션 리마인더 등), wiki 안정화 등은 모두 Patch
>
> **롤백 방법**: 각 버전은 git tag로 관리됩니다.
> ```powershell
> git checkout v1.1.3      # 특정 버전 코드 확인
> git checkout main        # 최신으로 복귀
> ```

---

## [1.4.1] - 2026-03-10 <- 현재

### 개선
- **Wiki 질문 맥락 인식 검색 (`search_with_context`)**: 질문에서 연도·키워드를 추출하여 맥락에 맞는 페이지 우선 검색
  - 예: `/wiki HotFix 내역 \ 2026년 핫픽스 알려줘` → 인덱스 페이지 대신 `2026_Hot Fix` 페이지 발견
  - CamelCase 분리 ("HotFix" → "Hot"+"Fix") + 연도 CQL 조합으로 정확도 향상
  - `_wiki_fetch_page()`에 `question` 파라미터 추가, 파이프 핸들러 연동
- **Jira 검색 점진적 확장 (broadening fallback)**: 0건 결과 시 키워드를 줄여가며 자동 재시도
  - `question_to_jql_variants()`: 전체 키워드 → 앞 2개 → 첫 키워드만 (점진적 확장)
  - `_extract_keywords()`: 한국어 불용어 제거 후 핵심 키워드 추출
  - 프로젝트 파이프 핸들러에서 JQL variants 순회 로직 적용
- **Jira 자연어→JQL 변환 개선**: `summary ~` → `text ~`로 변경 (summary+description+comments 전체 검색)
  - 한국어 불용어(알려줘, 보여줘, 관련 등) 제거 로직 추가
- **GDI 게임명 접두사 자동 보정**: 폴더 미발견 시 Chaoszero/Epicseven 접두사 자동 시도
- **Wiki MAX_PAGE_CHARS 확장**: 20,000 → 40,000자 (긴 페이지 본문 절단 방지)

### 추가
- **`auto_sync.py` (mcp-cache-layer)**: 2시간 주기 캐시 동기화 스크립트
  - Wiki Full Ingest: 전체 페이지 스캔 + 캐시 갱신 (2000페이지 ~16분)
  - Jira Delta Sync: 프로젝트별 최근 이슈 동기화
  - 경로: `D:\Vibe Dev\QA Ops\mcp-cache-layer\scripts\auto_sync.py`

---

## [1.4.0] - 2026-03-10

### 추가
- **`/jira` 슬래시 커맨드**: Jira MCP 연동 + 3계층 캐시 통합 (Phase 3)
  - `jira_client.py` 신규 생성 — JiraClient 클래스 + Slack 포맷 헬퍼
  - 서브커맨드: `search`, `issue`, `project`, `projects`, `help`
  - `\` 구분자로 AI 질문 지원: `/jira QASGP-123 \ 이 이슈 요약해줘`
  - 자동 JQL 변환: 단순 텍스트 → `summary ~ "..." ORDER BY updated DESC`
  - JQL 직접 입력도 지원 (키워드 자동 감지)
  - 캐시 정책: 이슈 10분, 프로젝트 1시간, 프로젝트목록 24시간, JQL검색 미캐시
  - L1 인메모리 (5분) → L2 SQLite → L3 MCP HTTP
  - `logs/jira_query.log`에 조회 내역 기록
- **MCP 캐시 Jira TTL 설정**: `config.py`에 `JIRA_ISSUE_TTL_HOURS=0.17`, `JIRA_PROJECT_TTL_HOURS=1`, `JIRA_PROJECTS_TTL_HOURS=24`

---

## [1.3.5] - 2026-03-10

### 추가
- **GDI MCP 캐시 통합 (Phase 2)**: `/gdi` 커맨드에 3계층 캐시 적용
  - L1 인메모리 (5분 TTL) → L2 SQLite (폴더 6시간, 파일 24시간) → L3 MCP HTTP
  - 캐시 대상: `list_files_in_folder` (폴더 목록), `search_by_filename` (파일 내용)
  - 반복 조회 시 응답시간 5-14초 → <100ms로 단축
  - `gdi_query.log`에 `cache=` 필드 추가 (HIT_MEM, HIT_DB, MISS, STORE 등)
- **MCP 캐시 GDI TTL 설정**: `config.py`에 `GDI_FOLDER_TTL_HOURS=6`, `GDI_FILE_TTL_HOURS=24`

---

## [1.3.4] - 2026-03-10

### 추가
- **Wiki 캐시 통합 (Phase 1)**: `/wiki` 커맨드에 3계층 캐시 적용
  - L1 인메모리 (5분 TTL) → L2 SQLite (24시간) → L3 MCP HTTP
  - `wiki_query.log`에 `cache=` 필드 추가
- **`/wiki-sync` 커맨드**: 캐시 동기화 관리 (status/full/delta)

### 변경
- `/wiki`, `/gdi` 커맨드 구분자: `|` → `\` (Jira 필터 충돌 방지)

---

## [1.3.3] - 2026-03-10

### 수정
- **daily/weekly 중복 발송 버그 수정**: `misfire_grace_time` 3600 → 60초
  - v1.3.1에서 daily/weekly 잡에 1시간 grace 적용 → Railway 재시작 3회(10:00~10:05) 시 각각 발동 → 체크리스트 3번 중복 발송
  - 60초로 축소: Railway 재시작(수초~수십초) 1회는 허용, 연속 재시작 시 중복 방지
- **전일 누락 항목 업무명 누락 수정** (`missed_tracker.py`)
  - `extract_flat_items()`: group 타입 항목에서 `group_name` 접두사(`[각 프로젝트]` 등)를 제거하고 sub_item text와 결합
  - 예: `group_name="[각 프로젝트] 서비스 장애"`, sub text=`"[에픽세븐]"` → `"[에픽세븐] 서비스 장애"`
  - 기존: `"[에픽세븐]"` 만 표시 (group_name 유실)
- **전일 누락 항목 체크박스 제거** (`slack_sender.py`)
  - `_build_missed_section_blocks()`: `action/checkboxes` 블록 → `section/mrkdwn` 텍스트 리스트
  - 형식: `• *업무명*  담당: 이름` (체크박스 없이 누락 현황만 표시)

---

## [1.3.2] - 2026-03-10

### 수정
- **Railway 재시작 즉시 Slack 알림**: 스케줄러 시작 시 `monitor_alert_channel`에 재시작 시각 알림 발송
  - 기존에는 18:00 모니터링 체크 전까지 재시작 여부를 알 수 없었음
  - 이제 재시작 즉시 알림 → 조기 감지 + 수동 대응 가능
- **`schedule-monitor` 잡 misfire 보호**: `misfire_grace_time=3600` 추가
  - 18:00 모니터링 잡 자체도 Railway 재시작 시 누락되는 케이스 방지

---

## [1.3.1] - 2026-03-10

### 수정
- **Railway 스케줄 누락 방지**: `daily`/`weekly` 스케줄에 `misfire_grace_time=3600` 추가
  - Railway 재시작 후 1시간 이내면 즉시 발송 (기존: 기본값 1초 → 재시작 시 누락)
  - 미션 리마인더는 이미 7200초 설정되어 있었음
- **`/gdi` AI 답변 품질 개선** (질문 의도 감지)
  - "종류/목록" 질문 → 파일 목록+경로 중심 답변 (`_gdi_ask_claude_list`)
  - "요약/내용/분석" 질문 → 가장 관련도 높은 파일 1개 내용 가져와서 답변 (`_gdi_ask_claude_content`)
  - 불필요한 검색 통계/메타데이터 제거, 질문에 집중하는 전용 프롬프트 적용
- **`_fetch_file_content` 헬퍼 분리**: 4단계 폴백 파일 내용 조회 (exact→text→#제거→unified)

---

## [1.3.0] - 2026-03-09

### 추가
- **`/gdi` 슬래시 커맨드** — GDI(Game Doc Insight) MCP 연동 (세 번째 기능 카테고리)
  - `/gdi search [검색어]` — 크로스 컬렉션 통합 검색
  - `/gdi file [파일명]` — 파일명 기반 검색 (청크 내용 포함)
  - `/gdi folder [경로]` — 폴더 내 파일 목록 조회
  - `/gdi [검색어] | [질문]` — 검색 결과 기반 Claude AI 답변
  - `/gdi [폴더명] | [파일명] | [질문]` — 폴더+파일 지정 후 Claude AI 답변
  - GDI MCP 서버: `http://mcp-dev.sginfra.net/game-doc-insight-mcp` (인증 불필요)
- **`mcp_session.py` 신규** — MCP Streamable HTTP 세션 공용 모듈
  - `wiki_client.py`의 `_McpSession` 클래스를 `McpSession`으로 추출
  - wiki, gdi 등 여러 MCP 클라이언트에서 공유
- **`gdi_client.py` 신규** — GDI MCP 클라이언트 + Slack 포맷 헬퍼 + 조회 로거
  - `logs/gdi_query.log`에 조회 내역 기록

### 수정
- **`wiki_client.py` 리팩토링** — `_McpSession` → `mcp_session.McpSession` 사용으로 변경

### 제거
- **`/calendar` 슬래시 커맨드** 제거 — 사용하지 않음 (MCP 서버 미지원)

---

## [1.2.0] - 2026-03-09

### 추가
- **미션 넘버링 시스템** (`config.json`, `slack_sender.py`)
  - 6개 미션에 M-01 ~ M-06 번호 부여 (`mission_number` 필드)
  - 일일 미션 리마인더 메시지에 `[M-XX]` 접두사 표시
  - `mission_state.json` 상태 저장에 mission_number 포함
  - 로그 메시지에 미션 번호 포함
  - 향후 수동 진행율 업데이트 및 웹 관리 페이지의 기반
- **스케줄 모니터링** (`schedule_monitor.py` 신규)
  - APScheduler 등록 스케줄 목록, 다음 실행 시각 조회 기능
- **레포지토리 구조 정리** — 봇 소스 파일을 `Slack Bot/` 서브 폴더로 이동
  - 프로젝트 루트 정리, 소스와 설정/문서 분리
- **개발 관리 시스템 도입** (`.claude/`, `logs/`, `changelog/` 폴더)
  - `.claude/DEV_RULES.md` — 개발 규칙 문서
  - `.claude/WORK_LOG.md` — 일일 작업 히스토리
  - `changelog/CHANGELOG.md` — 이 파일 (루트에서 이동)
  - `logs/wiki_query.log` — /wiki 조회 로그
- **wiki 조회 전용 로그** (`wiki_client.py`)
  - 사용자, 검색어, 결과, 에러 내역을 `logs/wiki_query.log`에 별도 기록
- **체크리스트 복구 스크립트** (`repair_checklist.py` 신규)
  - `groups:history` 없이 로그 파일에서 체크 상태 파싱 → `chat.update` 직접 호출
- **레거시 파일 정리 프로세스** (`.claude/DEV_RULES.md` §7)
  - `_legacy/` 폴더로 이동 → 2주 유예 → 삭제/복원 절차 공식화
  - 분류 기준 테이블, 주의사항 포함

### 수정
- **미션 진행율 0% 버그** — 채널 히스토리 폴백 추가 (`missed_tracker.py`)
- **미션 스케줄러 misfire_grace_time** 2시간 설정 (jitter 구간 중 재시작 대응)
- **`missed_tracker.py` Railway 재시작 대응** — 채널 히스토리 폴백 로직 추가
- **구 봇 프로세스 경로 불일치** — 레포 구조 정리 후 구 프로세스 종료 + 신 경로 재시작

### 삭제
- **Market Rank 폴더 제거** — `D:\Vibe Dev\Maker Store Rank\`에서 별도 관리 중이라 Slack Bot 내 복사본 불필요 (`git rm -r`)
- **레거시 파일 33개** → `_legacy/` 이동 (로그 20, 테스트 7, 텍스트/데이터 5, CHANGELOG 1)

### 등록된 미션 넘버링
| 번호 | 미션 ID | 미션명 |
|------|---------|--------|
| M-01 | mission-ai-driven-qa | Slack QA - Supporter 활용 가이드 |
| M-02 | mission-tech-support | Testrail TC 업로드 자동화 |
| M-03 | mission-roundtable | 토론 진행 기획 |
| M-04 | mission-balance-engineering | (미정) |
| M-05 | mission-data-analysis | (미정) |
| M-06 | mission-knowledge-management | (미정) |

### 교훈
- 파일 이동(refactor) 후 반드시 실행 중인 프로세스를 재시작해야 함
- `groups:history` 미부여 시 `conversations.history` 사용 불가 → 로그 기반 상태 복구로 우회

---

## [1.1.5] - 2026-03-06

### 추가
- **알리미: 미션 미정 채널 전용 "선정 독려" 포맷** (`slack_sender.py`)
  - `mission.name == "미정"` 또는 빈 값이면 진행 현황 대신 독려 메시지 자동 전환
  - 진행율 막대 · 서브태스크 · 댓글 요청 블록 없이 심플한 구조
  - 포맷 내용: `(hourglass) 미션 선정 대기 중` + `(speech_balloon) 빨리 미션을 확정하고 도전을 시작해 봐요 (fire)`
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
- 알리미: Roundtable 채널 내용 TBD -> 실제 내용으로 업데이트

---

## [1.1.2] - 2026-02-28

### 추가
- **알리미: 미션 진행 현황 리마인더** (신규 스케줄 타입 `mission`)
  - 6개 채널 평일 09:00~09:30 랜덤 지연 자동 발송
  - D-Day 카운터, 진행율 막대, 서브태스크 목록 포함
  - 전날 스레드 댓글에서 `N%` 패턴 자동 파싱 -> 다음 날 진행율 반영
  - `mission_state.json` 채널별 상태 파일 관리
  - APScheduler `jitter=1800` 랜덤 지연

### 등록된 미션 채널 (6개, v1.1.3에서 일부 업데이트)
| 채널 | 미션 |
|------|------|
| AI-Driven QA Efficiency | Slack QA Supporter 활용 가이드 |
| Balance Engineering | (TBD) |
| Data analysis | (TBD) |
| Knowledge Management | (TBD) |
| Roundtable | (TBD -> v1.1.3에서 업데이트) |
| Tech Support | (-> v1.1.3에서 추가) |

---

## [1.1.1] - 2026-02-20

### 수정
- **WIKI: SSE 응답 인코딩 버그 수정**
  - `r.text` (ISO-8859-1 자동 디코딩) -> `r.content.decode('utf-8')` 명시 처리
  - 한글 페이지 제목/내용 깨짐 문제 해결
- **WIKI: `get_page_by_title` MCP 서버 버그** -> `cql_search`로 대체
- **WIKI: 전체 본문 조회** — `cql_search` excerpt 대신 `get_page_by_id + expand: body.view`
- **WIKI: HTML 테이블 구조 보존** — `</td><td>` -> ` | `, `<tr>` -> `\n` 변환
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

---

*각 버전 항목은 변경 작업 시 Claude가 업데이트합니다.*
