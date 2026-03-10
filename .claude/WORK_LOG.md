# Slack Bot 작업 히스토리

> 최신 항목이 위에 위치합니다.
> 각 세션 종료 시 Claude가 자동 업데이트합니다.

---

## 2026-03-10 (화) — 세션 12

### 완료
- **v1.4.1: 검색 정확도 전면 개선 (Wiki + Jira + GDI)**
  - `wiki_client.py`: `search_with_context()` 메서드 추가
    - 질문에서 연도(20XX) 추출 → 제목 키워드와 조합하여 CQL 검색
    - CamelCase 분리: "HotFix" → ["Hot", "Fix"] (Confluence 토크나이저 대응)
    - 예: "2026년 핫픽스 알려줘" + 제목 "HotFix 내역" → CQL `title ~ "2026" AND title ~ "Hot"` → "2026_Hot Fix" 페이지 발견
    - 실패 시 `get_page_by_title()` 폴백
  - `slack_bot.py`: `_wiki_fetch_page()`에 `question` 파라미터 추가
    - 파이프(`\`) 핸들러에서 질문 맥락을 검색에 전달
  - `jira_client.py`: `_extract_keywords()`, `question_to_jql_variants()` 추가
    - 점진적 확장: 전체 키워드 → 앞 2개 → 첫 키워드만
    - `question_to_jql()`: `summary ~` → `text ~` (전체 필드 검색)
    - 한국어 불용어 제거 (알려줘, 보여줘, 관련, 최근 등)
  - `slack_bot.py`: Jira 프로젝트 파이프 핸들러에 broadening 패턴 적용
    - `jql_variants` 순회하며 첫 결과 발견 시 break
- **MCP 캐시 auto_sync 완료 확인**
  - Wiki Full Ingest: 2000페이지 스캔, 1462 추가, 538 갱신, 0 에러 (978.95초)
  - Jira Delta Sync: 6 프로젝트 (EP7, GCZ, LDN, LNA, PRH, SMQA), 0건 신규
- **봇 재시작**: PID 43524 → PID 41436 (전체 변경사항 적용)
- **3개 파일 문법 검증 통과** (`py_compile`)

### 보류
- **자기 학습 검색 시스템**: 사용자 제안 3가지 방향 중 선택 대기
  1. 질의 패턴 학습 (로그 기반 매핑 테이블)
  2. AI 질의 재구성 (Haiku로 검색어 전처리)
  3. 벡터/시맨틱 검색 (임베딩 기반)
- **auto_sync Windows 작업 스케줄러 등록** (2시간 주기 자동 실행)

### 버전
- v1.4.0 → **v1.4.1**

### 수정 파일
- `Slack Bot/wiki_client.py` (수정 — search_with_context 추가)
- `Slack Bot/jira_client.py` (수정 — _extract_keywords, question_to_jql_variants 추가)
- `Slack Bot/slack_bot.py` (수정 — _wiki_fetch_page question 파라미터, jira broadening)
- `changelog/CHANGELOG.md` (수정 — v1.4.1 기록)

---

## 2026-03-10 (화) — 세션 11

### 완료
- **v1.4.0: `/jira` 슬래시 커맨드 + Jira MCP 캐시 통합 (Phase 3)**
  - `jira_client.py` 신규 생성 (480줄)
    - JiraClient 클래스: search_issues, get_issue, get_all_projects, get_project
    - 3계층 캐시: L1 인메모리 5분 → L2 SQLite (이슈 10분, 프로젝트 1시간, 목록 24시간) → L3 MCP
    - 자동 JQL 변환: 텍스트 → `summary ~ "..." ORDER BY updated DESC`
    - 이슈 키 감지: `^[A-Z][A-Z0-9]+-\d+$` 패턴
    - Slack 포맷 헬퍼: format_search_results, format_issue, format_project, format_projects_list
    - Claude AI 컨텍스트 추출: get_issue_context_text, get_search_context_text
    - 조회 로거: logs/jira_query.log
  - `slack_bot.py` 수정
    - /jira 핸들러: search, issue, project, projects, help, 파이프 AI 질문
    - _jira_* 헬퍼 10개 추가
  - `.env`에 JIRA_MCP_URL, JIRA_USERNAME, JIRA_TOKEN, JIRA_BASE_URL 추가
  - `mcp-cache-layer/src/config.py`에 Jira TTL 상수 추가
  - `IMPLEMENTATION_PLAN.md` Phase 3 완료 표시 + 산출물 기록

### 버전
- v1.3.5 → **v1.4.0**

### 수정 파일
- `Slack Bot/jira_client.py` (신규)
- `Slack Bot/slack_bot.py` (수정 — import + 헬퍼 + 핸들러)
- `.env` (수정 — Jira 환경변수)
- `changelog/CHANGELOG.md` (수정 — v1.4.0 기록)
- `.claude/DEV_RULES.md` (수정 — 구조 + 버전)
- `mcp-cache-layer/src/config.py` (수정 — Jira TTL)
- `mcp-cache-layer/docs/IMPLEMENTATION_PLAN.md` (수정 — Phase 3 완료)

---

## 2026-03-10 (화) — 세션 10

### 완료
- **Wiki 캐시 통합 커밋 + Railway 재배포 (v1.3.4)**
  - wiki_client.py 3계층 캐시 + /wiki-sync 커맨드 + 구분자 변경
  - `git push origin main` → Railway 자동 배포
- **MCP Cache Phase 2: GDI MCP 캐시 통합 (v1.3.5)**
  - 설계 문서: `mcp-cache-layer/docs/PHASE2_GDI_DESIGN.md`
  - `gdi_client.py`: 3계층 캐시 통합 (L1 메모리 → L2 SQLite → L3 MCP)
    - `list_files_in_folder`: page=1 캐시 (폴더 TTL 6시간)
    - `search_by_filename`: page=1 + page_size≤20 캐시 (파일 TTL 24시간)
    - `unified_search`: 캐시 미적용 (검색 결과 매번 다름)
  - `config.py`: GDI 전용 TTL 상수 추가
  - `log_gdi_query()`: `cache_status` 필드 추가
  - 봇 재시작 완료 (PID 30760), DB init 2회 확인 (wiki + gdi)

### 보류
- Railway 재배포 (v1.3.5): `/gdi` 캐시는 로컬만 사용 가능, Railway는 다음 커밋+push 시 배포

---

## 2026-03-10 (화) — 세션 9

### 완료
- **daily/weekly 중복 발송 버그 수정 (v1.3.3)**
  - 원인: v1.3.1에서 daily/weekly `misfire_grace_time=3600` 추가 → Railway 10:00~10:05 사이 3번 재시작 → 각각 1시간 이내 판단으로 3번 발동 → 체크리스트 3개 중복 발송
  - 수정: `scheduler.py` `_add_daily()` / `_add_weekly()` `misfire_grace_time`: 3600 → **60**
  - 중복 메시지 2개(ts=1773104401.221139, 1773104687.395599) 삭제는 사용자가 직접 처리
  - 남길 메시지: ts=1773104704.056779 (checklist_state.json에 등록된 최신 메시지)
- **03/10 체크리스트 전일 누락 섹션 재수정**
  - `fix_missed_0310.py` 실행 → ts=1773104704.056779 메시지 `chat.update`
  - 올바른 전일 날짜: `"[일일] 03/09(월)"` (이전 스크립트: `"03/06(금)"` 오류)
  - 올바른 누락 4개: `[에픽세븐] Next Checklist`, `[에픽세븐] 커뮤니티 이슈`, `[에픽세븐] GDI 데이터 파일 업로드`, `[카제나] GDI 데이터 파일 업로드`
  - 체크 상태 6개 유지 (g0_cazena, g1_cazena, g4_cazena, g5_cazena, g3_cazena, g6_cazena)
- **`extract_flat_items()` group_name 결합 수정** (`missed_tracker.py`)
  - group 항목 sub_item에 group_name 접두사 제거 후 결합 (`"[에픽세븐] 서비스 장애"`)
- **`_build_missed_section_blocks()` 체크박스 제거** (`slack_sender.py`)
  - action/checkboxes → section/mrkdwn 텍스트 리스트 (`• *업무명*  담당: 이름`)

### Railway 재배포 필요
- `scheduler.py` 변경(misfire_grace_time 60초) → Railway 재배포해야 적용됨

---

## 2026-03-10 (월) — 세션 8

### 완료
- **03.10 체크리스트 메시지에 전일(03.06 금) 누락 항목 추가**
  - 재발송 없이 `chat.update`로 기존 메시지(ts=1773104704.056779) 수정
  - `groups:history` 없으므로 전일 체크 상태 불가 → 로그(slack_bot.log)에서 오늘 체크된 6개 항목 파악 후 나머지 9개를 "[일일] 03/06(금)" 누락으로 표시
  - `add_missed_0310.py` 1회성 스크립트 실행 후 `_legacy/`로 이동
- **재발 방지 대책 구현 (v1.3.2)**
  - `_notify_startup()`: Railway 재시작 시 즉시 `monitor_alert_channel`에 알림 발송
    → 기존에는 18:00 모니터링 전까지 재시작 여부 인지 불가 → 이제 즉시 감지
  - `schedule-monitor` 잡 `misfire_grace_time=3600` 추가
    → 18:00 모니터링 잡 자체도 Railway 재시작 시 누락 방지
  - v1.3.2 커밋/Push → Railway 자동 재배포

### 재발 방지 구조 요약

| 레이어 | 조치 | 커버 케이스 |
|--------|------|-------------|
| v1.3.1 | daily/weekly misfire_grace_time=3600 | 재시작 후 1시간 이내 스케줄 자동 발송 |
| v1.3.2 | Railway 재시작 즉시 Slack 알림 | 재시작 즉시 인지 → 수동 대응 |
| v1.3.2 | monitor 잡 misfire_grace_time=3600 | 18:00 모니터링 잡 자체 누락 방지 |
| 기존 | 18:00 schedule_monitor check_and_alert | 당일 미발송 잡 18:00에 알림 |

### 미해결 케이스 (수동 대응 필요)
- Railway가 10:00~11:00 사이가 아닌 더 늦게 재시작되는 경우 (예: 12:00 재시작)
  → misfire_grace_time=3600 초과 → 스케줄 누락
  → **_notify_startup 알림으로 즉시 인지 → 수동 발송으로 대응**
  → 18:00 모니터링도 재확인

---

## 2026-03-10 (월) — 세션 7

### 완료
- **03.10 일일 QA 체크리스트 누락 수동 발송**
  - Railway 재시작으로 인해 10:00 스케줄 미실행 → 로컬에서 수동 발송 스크립트 실행
  - `ts=1773104704.056779` — 발송 성공, 상태 등록 + missed_tracker 로그 기록 완료
- **Railway misfire_grace_time 누락 버그 수정 (v1.3.1)**
  - `scheduler.py` `_add_daily` / `_add_weekly` 에 `misfire_grace_time=3600` 추가
  - Railway 재시작 후 1시간 이내 → 즉시 발송 보장 (미션은 이미 7200초 적용 중)
- **/gdi AI 답변 품질 개선** (v1.3.1)
  - 질문 의도 감지: 목록 질문 vs 내용 질문 분기
  - 목록 질문(종류/뭐가 있는지) → 파일 리스트+경로 중심 답변
  - 내용 질문(요약/분석) → 최관련 파일 1개 내용 가져와서 요약
  - 전용 Claude 프롬프트 3종 분리: `_gdi_ask_claude_content`, `_gdi_ask_claude_list`, `_gdi_ask_claude`
  - `_fetch_file_content` 헬퍼 생성 (4단계 폴백 파일 내용 조회)
- **v1.3.1 커밋/Push → Railway 자동 재배포**

### 원인/교훈
- Railway 재시작 원인 불명 (크래시 또는 롤링 재시작 추정)
- **교훈**: APScheduler `misfire_grace_time` 미설정 시 Railway 재시작 타이밍에 따라 스케줄 누락 발생
  - mission은 jitter 때문에 7200초 설정했는데, daily/weekly는 누락되어 있었음

### 핵심 변경 파일
| 파일 | 유형 | 설명 |
|------|------|------|
| `scheduler.py` | 수정 | daily/weekly misfire_grace_time=3600 추가 |
| `slack_bot.py` | 수정 | 질문 의도 감지 + 전용 Claude 프롬프트 분리, _fetch_file_content 헬퍼 |
| `changelog/CHANGELOG.md` | 수정 | v1.3.1 기록 |

---

## 2026-03-09 (일) — 세션 6

### 완료
- **v1.3.0 /gdi 슬래시 커맨드 구현** (GDI MCP 연동)
  - `mcp_session.py` 신규: `_McpSession`을 공용 `McpSession` 클래스로 추출
  - `wiki_client.py` 리팩토링: `_McpSession` 삭제 → `McpSession` import
  - `gdi_client.py` 신규: GdiClient (unified_search, search_by_filename, list_files_in_folder)
  - `slack_bot.py`: `/gdi` 핸들러 + 헬퍼 함수 추가 (search/file/folder/AI 답변)
  - `logs/gdi_query.log` 조회 로거 추가
- **`/calendar` 슬래시 커맨드 제거** — MCP 서버 미지원으로 사용 안 함

### 핵심 변경 파일
| 파일 | 유형 | 설명 |
|------|------|------|
| `mcp_session.py` | 신규 | MCP 세션 공용 모듈 |
| `gdi_client.py` | 신규 | GDI MCP 클라이언트 |
| `wiki_client.py` | 수정 | McpSession import로 리팩토링 |
| `slack_bot.py` | 수정 | /gdi 핸들러, /calendar 제거 |

---

## 2026-03-09 (일) — 세션 5

### 완료
- **미션 넘버링 시스템 구축** (M-01 ~ M-06)
  - `config.json`: 6개 미션에 `mission_number` 필드 추가
  - `slack_sender.py`: `_build_mission_blocks` + `send_mission_reminder`에 `[M-XX]` 접두사 반영
  - 미선정 미션: `⏳ [M-04] 미션 선정 대기 중`, 확정 미션: `🎯 [M-01] Slack QA - Supporter 활용 가이드`
  - 로그/fallback 텍스트/상태 저장에 mission_number 포함
- **mission_state.json 초기화**: 6개 미션 progress: 0으로 생성
- **CHANGELOG.md 업데이트**: v1.2.0에 미션 넘버링 시스템, 레거시 정리, Market Rank 제거 기록

### 수동 진행율 업데이트 흐름 (임시 방편)
1. 사용자가 Claude에게 "M-01 진행율 80%" 전달
2. Claude가 `mission_state.json`의 해당 미션 `progress` 값 직접 수정
3. 다음 스케줄러 실행 시 progress 로드 → 메시지에 반영

### 미션 넘버링 매핑
| 번호 | 미션 ID | 상태 |
|------|---------|------|
| M-01 | mission-ai-driven-qa | 확정 |
| M-02 | mission-tech-support | 확정 |
| M-03 | mission-roundtable | 확정 |
| M-04 | mission-balance-engineering | 미정 |
| M-05 | mission-data-analysis | 미정 |
| M-06 | mission-knowledge-management | 미정 |

### 보류
- HTML 미션 관리 웹페이지 제작 (사용자 향후 계획)

---

## 2026-03-09 (일) — 세션 4

### 완료
- **Market Rank 폴더 통합**: `D:\Vibe Dev\Slack Bot\Market Rank\`와 `D:\Vibe Dev\Maker Store Rank\` 비교
  - 비교 결과: 소스 파일 9개 동일, README.md는 줄끝 문자 차이만 (내용 동일)
  - Maker Store Rank이 상위 집합 (.env, .gitignore, .github, data/ 보유)
  - Slack Bot에서 Market Rank 폴더 `git rm -r` 제거
- **레거시 파일 정리**: 루트 잔여물 33개를 `_legacy/` 폴더로 이동
  - 로그 20개, 테스트 스크립트 7개, 텍스트/데이터 5개, 루트 CHANGELOG.md
  - `_legacy/EXPIRY.md` 생성 (이동일: 3/9, 삭제 예정일: 3/23)
- **DEV_RULES.md v1.1.0**: 레거시 정리 프로세스 섹션 추가 (§7)
  - 파악 → 이동 → 메타 기록 → 2주 유예 → 삭제/복원 절차
  - 레거시 분류 기준 테이블, 주의사항 포함
- **.gitignore 업데이트**: `_legacy/` 추가

### 배경
- Slack Bot 레포가 원래 Market Rank 프로젝트로 시작 → 이후 Slack Bot이 주 프로젝트로 전환
- Market Rank는 `D:\Vibe Dev\Maker Store Rank\`에서 별도 관리 중이라 Slack Bot 내 복사본 불필요

---

## 2026-03-09 (일) — 세션 3

### 완료
- **CHANGELOG.md 초기화**: 기존 루트 CHANGELOG.md를 `changelog/` 폴더로 이동, v1.2.0 섹션 추가
- **wiki 조회 전용 로거 구현**: `wiki_client.py`에 `log_wiki_query()` 함수 + `logs/wiki_query.log` 파일 핸들러 추가
  - 기록 내용: 사용자(ID+이름), 동작(search/get_page/ask_claude), 검색어, 결과, 에러, 소요시간
  - `slack_bot.py`의 `/wiki` 핸들러 3개 분기(search, ask_claude, get_page)에 로깅 호출 추가
- **MEMORY.md 업데이트**: 프로젝트 구조 트리, 봇 경로(`Slack Bot/`), 새 폴더 구조, 제약사항 테이블 반영

---

## 2026-03-09 (일) — 세션 2

### 완료
- **체크리스트 그룹 헤더 소실 복구**: 구 봇 프로세스(PID 9408, 30480)가 이전 경로에서 실행 중이라 config.json을 찾지 못해 그룹 헤더 소실. 구 프로세스 종료 후 신 경로에서 봇 재시작. `repair_checklist.py` 스크립트로 Slack 메시지 직접 복구.
- **전체 메시지 검수**: 로그 분석 결과 손상된 메시지는 3/9 일일 QA 체크리스트 1건만 확인. 다른 메시지(주간 QA 보고, 3/6 일일, 3/8 일일)는 모두 정상.
- **메모리/로그/버전 시스템 구축**: `.claude/`, `logs/`, `changelog/` 폴더 구조 생성, DEV_RULES.md + WORK_LOG.md 초기화
- **wiki 조회 로깅 설계**: wiki_client.py에 별도 로그 파일 기록 기능 설계

### 원인/교훈
- `refactor: 레포 구조 정리` 후 구 봇 프로세스를 재시작하지 않아 경로 불일치 발생
- **교훈**: 파일 이동 후 반드시 실행 중인 프로세스 재시작 확인 필요
- `groups:history` 없이는 `conversations.history` 사용 불가 → 로그 기반 상태 복구 방식 사용

### 보류
- `groups:history` 대안 구현 (슬래시 커맨드 기반 진행율 입력 — B안 권장)
- config.json 핫 리로드 (팀 규모상 긴급하지 않음)

---

## 2026-03-09 (일) — 세션 1

### 완료
- **Anthropic API Key 교체**: 구 키 만료 → 신규 "Slack Bot" 키로 교체
- **Railway 환경변수 업데이트**: 신규 API Key 반영
- **코드 무결성 검증**: slack_bot.py, wiki_client.py 등 주요 파일 정상 확인
- **Windows 작업 스케줄러 재등록**: `SlackQABot` 태스크 경로를 `Slack Bot/Slack Bot/`으로 수정
- **groups:history 필요 이유 분석**: 4곳에서 사용 중 (미션 진행율, 누락 추적 등). 비공개 채널이라 필수.

### 원인/교훈
- API Key 갑작스런 무효화 원인 불명 — 크레딧 부족은 아니었음
- **교훈**: API 호출 에러 로그를 별도 파일에 기록해야 디버깅 가능

### 보류
- 구 API Key Anthropic Console에서 삭제 (사용자 직접 처리)

---

## 2026-03-06 (목)

### 완료
- **미션 진행 현황 리마인더** 기능 구현 (v1.1.0~v1.1.5)
  - 6개 채널 미션 등록 (AI-Driven QA, Balance Engineering, Data Analysis, Knowledge Management, Roundtable, Tech Support)
  - 미정 채널 선정 독려 포맷 분기 추가
  - 스레드 기반 진행율 추적
- **Wiki 검색 개선**: breadcrumb 경로 지원, CQL-unsafe 문자 필터링
- **검색 전략 예외처리 시스템** 추가 (wiki_search_rules.json)
- **CHANGELOG.md 도입** 및 버전 관리 체계 수립 (v1.1.4)
- **스케줄 충돌 수정**: 동시 발송 시 jitter 적용

---

## 2026-03-05 (수)

### 완료
- **인터랙티브 체크리스트 아키텍처 전면 개편**
  - 그룹 체크리스트 구조 도입 (group_name + sub_items)
  - 분기별 QA 체크리스트 추가
  - 주간 QA 보고 스케줄 추가
- **실시간 체크박스 동기화** 구현
  - 동적 action_id로 Slack 클라이언트 강제 재렌더링
  - body[actions] delta 기반 merge 전략
- **GDI 데이터 파일 업로드 항목** 추가
- **전일 누락 항목 표시** 기능 구현

---

## 2026-03-04 (화)

### 완료
- **프로젝트 초기 설정**
  - Slack Bot 기본 구조 생성 (slack_bot.py, slack_sender.py, scheduler.py)
  - 환경변수 설정 (.env)
  - Windows 자동 시작 설정 (autostart_setup.bat)
  - Railway 클라우드 배포 설정 (Procfile, runtime.txt)
- **일일 QA 체크리스트** 기본 구현
- **/wiki 검색 명령어** 구현 (Confluence MCP 연동)

---

*각 항목은 세션 종료 시 Claude가 작성합니다.*
*'슬랙 봇 개발 규칙과 히스토리 불러와' 명령으로 이 파일을 로드합니다.*
