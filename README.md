# 🤖 퍼블리싱QA1팀 Slack 알림 봇 (QA Supporter)

**현재 버전: `v1.5.6`** | [변경 이력 →](./changelog/CHANGELOG.md)

> **SGP 퍼블리싱QA1팀** 전용 Slack 자동화 봇
> 일일 업무 헤더, QA 체크리스트, 주간 보고, 업데이트 차수 점검, 월간·분기 체크리스트를 자동 발송하고 담당자가 직접 체크할 수 있는 인터랙티브 메시지를 제공합니다.

---

## 📐 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│  로컬 PC (D:\Vibe Dev\Slack Bot\)                           │
│  ▶ 실행 모드: --commands-only                               │
│  ▶ 역할: 슬래시 커맨드(/wiki,/gdi,/jira) + 인터랙션 처리    │
│  ▶ 봇 시작: start_bot.bat (WMI 백그라운드 실행)             │
└────────────────┬────────────────────────────────────────────┘
                 │ git push (Slack Bot/ 서브폴더)
                 ▼
┌─────────────────────────────────────────────────────────────┐
│  GitHub (SpaceWJK/smith-proxy)                              │
│  └─ Slack Bot/   ← 소스 코드 관리                          │
└────────────────┬────────────────────────────────────────────┘
                 │ 자동 배포 (push 감지, ~1~3분)
                 ▼
┌─────────────────────────────────────────────────────────────┐
│  Railway (exquisite-smile / production)                     │
│  ▶ 실행 모드: --scheduler-only                              │
│  ▶ 역할: 모든 스케줄 메시지 자동 발송                       │
│  ▶ 상태 저장: data/checklist_state.json                     │
└─────────────────────────────────────────────────────────────┘
                 │
                 ▼ Slack Web API / Socket Mode
┌─────────────────────────────────────────────────────────────┐
│  Slack (C07PHCE4RCM — 퍼블리싱QA1팀 채널)                  │
└─────────────────────────────────────────────────────────────┘
```

### 로컬 vs Railway 역할 분리

| 항목 | 로컬 PC | Railway |
|------|---------|---------|
| 실행 모드 | `--commands-only` | `--scheduler-only` |
| 주요 역할 | 체크박스 클릭 처리, `/wiki` `/gdi` `/jira` 커맨드 | 스케줄 메시지 발송 |
| 상태 파일 | 없음 (fallback 재구성) | `data/checklist_state.json` |
| 봇 재시작 | 수동 (`start_bot.bat`) | push 시 자동 재배포 |

---

## 📁 파일 구조

```
D:\Vibe Dev\Slack Bot\              ← 프로젝트 루트
├── .claude/                        ← Claude 메모리 (개발 규칙, 작업 히스토리)
├── logs/                           ← 조회 로그
│   ├── wiki_query.log             ← /wiki 조회 내역
│   ├── gdi_query.log              ← /gdi 조회 내역
│   └── jira_query.log             ← /jira 조회 내역
├── changelog/
│   └── CHANGELOG.md               ← 버전 히스토리
├── scripts/                        ← 유틸리티 스크립트
├── Slack Bot/                      ← 소스 코드 디렉토리
│   ├── slack_bot.py               ← 메인 진입점 (~1700줄)
│   ├── scheduler.py               ← APScheduler 스케줄 관리
│   ├── slack_sender.py            ← Slack Web API 래퍼 + Block Kit 빌더
│   ├── interaction_handler.py     ← 인터랙티브 체크리스트 상태 관리
│   ├── mcp_session.py             ← MCP Streamable HTTP 세션 공용 모듈
│   ├── wiki_client.py             ← Confluence Wiki MCP 클라이언트
│   ├── gdi_client.py              ← GDI(Game Doc Insight) MCP 클라이언트
│   ├── jira_client.py             ← Jira MCP 클라이언트
│   ├── missed_tracker.py          ← 전일 미체크 항목 추적
│   ├── schedule_monitor.py        ← 스케줄 모니터링
│   ├── config.json                ← ★ 스케줄 설정 파일
│   └── wiki_search_rules.json     ← ★ wiki 검색 전략 예외 (hot reload)
├── .env                            ← 환경변수 (비공개)
├── requirements.txt                ← 의존 패키지
├── Procfile                        ← Railway 실행 명령
└── start_bot.bat                   ← 로컬 봇 시작 스크립트
```

---

## 👥 팀원 정보 (user_map)

| 이름 | Slack UID | 비고 |
|------|-----------|------|
| 이동현 | `U07H17HB4MD` | |
| 류석호 | `U07HFLMSYKV` | |
| 정예찬 | `U07H18AD1L7` | |
| 박준선D | `U07HJ9JD31A` | |

> 새 팀원 추가 시 `config.json` → `user_map` 에 `"UID": "이름"` 형식으로 추가

---

## 📅 등록된 스케줄 현황

### ✅ 활성 스케줄 (enabled: true)

#### 1. 일일 업무 헤더
| 항목 | 내용 |
|------|------|
| ID | `daily-work-header` |
| 주기 | 매일 |
| 발송 시각 | 오전 09:00 |
| 메시지 타입 | 텍스트 |
| 채널 | 퍼블리싱QA1팀 |

**발송 형태:**
```
# Game Service 1 - 업무
- Date: 03.06(금)   ← 발송일 날짜 자동 치환
```
팀원들이 해당 메시지에 스레드를 달아 일일 업무 진행 상황을 공유합니다.

---

#### 2. 일일 QA 체크리스트
| 항목 | 내용 |
|------|------|
| ID | `daily-qa-checklist` |
| 주기 | 매일 |
| 발송 시각 | 오전 10:00 |
| 메시지 타입 | 인터랙티브 체크리스트 |
| 채널 | 퍼블리싱QA1팀 |

**업무 목록 (9개 항목 / 8그룹 + 1단독):**

| # | 항목 | 담당 |
|---|------|------|
| 1 | **[각 프로젝트] 서비스 장애** — [에픽세븐] / [카제나] | 이동현 / 류석호 |
| 2 | **[각 프로젝트] 핫픽스 내역** — [에픽세븐] / [카제나] | 이동현 / 류석호 |
| 3 | 마켓 검수 내역 *(단독)* | 이동현 |
| 4 | **[각 프로젝트] Next Checklist** — [에픽세븐] / [카제나] | 이동현 / 류석호 |
| 5 | **[각 프로젝트] 커뮤니티 이슈** — [에픽세븐] / [카제나] | 이동현 / 류석호 |
| 6 | **[각 프로젝트] TEST INFO** — [에픽세븐] / [카제나] | 이동현 / 류석호 |
| 7 | **[각 프로젝트] Release INFO** — [에픽세븐] / [카제나] | 이동현 / 류석호 |
| 8 | **[각 프로젝트] GDI 데이터 파일 업로드** — [에픽세븐] / [카제나] | 이동현 / 류석호 |
| 9 | **[각 프로젝트] QA Task Management** — [에픽세븐] / [카제나] | 이동현 / 류석호 |

> **그룹 완료 조건:** 그룹 내 모든 서브 항목([에픽세븐] + [카제나]) 체크 시 해당 그룹 완료

---

#### 3. 주간 QA 보고
| 항목 | 내용 |
|------|------|
| ID | `weekly-qa-report` |
| 주기 | 매주 |
| 발송 요일 | 금요일 |
| 발송 시각 | 오전 09:50 |
| 메시지 타입 | 인터랙티브 체크리스트 |
| 채널 | 퍼블리싱QA1팀 |

**업무 목록 (1그룹):**

| # | 항목 | 담당 |
|---|------|------|
| 1 | **주간 보고 작성** — 류석호 / 이동현 / 정예찬 | 류석호, 이동현, 정예찬 |

> **완료 조건:** 3명 모두 각자 체크 완료 시 그룹 완료

---

#### 4. 에픽세븐 업데이트 차수 체크리스트
| 항목 | 내용 |
|------|------|
| ID | `epic7-update-checklist` |
| 주기 | 3주마다 |
| 발송 요일 | 목요일 |
| 발송 시각 | 오전 09:55 |
| 시작일 | 2026-03-12 |
| 메시지 타입 | 인터랙티브 체크리스트 |

**업무 목록 (4개):**

| # | 항목 | 담당 |
|---|------|------|
| 1 | [에픽세븐] WiKi Game Service 1 | 이동현 |
| 2 | [에픽세븐] Service QA Report 최신화 | 이동현 |
| 3 | [에픽세븐] Dashboard DB 차수간 최신화 | 이동현 |
| 4 | [에픽세븐] Status Board | 이동현 |

---

#### 5. 카제나 업데이트 차수 체크리스트
| 항목 | 내용 |
|------|------|
| ID | `cazena-update-checklist` |
| 주기 | 3주마다 |
| 발송 요일 | 수요일 |
| 발송 시각 | 오전 09:55 |
| 시작일 | 2026-03-18 |
| 메시지 타입 | 인터랙티브 체크리스트 |

**업무 목록 (4개):**

| # | 항목 | 담당 |
|---|------|------|
| 1 | [카제나] WiKi Game Service 1 | 류석호 |
| 2 | [카제나] Service QA Report 최신화 | 류석호 |
| 3 | [카제나] Dashboard DB 차수간 최신화 | 류석호 |
| 4 | [카제나] Status Board | 류석호 |

---

#### 6. 월간 QA 체크리스트
| 항목 | 내용 |
|------|------|
| ID | `monthly-qa-checklist` |
| 주기 | 매월 마지막 금요일 |
| 발송 시각 | 오전 09:45 |
| 메시지 타입 | 인터랙티브 체크리스트 |

**업무 목록 (5개 항목 / 3그룹 + 2단독):**

| # | 항목 | 담당 |
|---|------|------|
| 1 | **[각 프로젝트] 프로젝트 월간 캘린더 최신화** — [에픽세븐] / [카제나] | 이동현 / 류석호 |
| 2 | 휴가 계획 조사 *(단독)* | 류석호 |
| 3 | 업무 고도화 미팅 *(단독)* | 이동현, 류석호, 정예찬, 박준선D |
| 4 | **[각 프로젝트] Monthly QA Report 최신화** — [에픽세븐] / [카제나] | 이동현 / 류석호 |
| 5 | **[각 프로젝트] Dashboard DB 월간 최신화** — [에픽세븐] / [카제나] | 이동현 / 류석호 |

---

#### 7. 분기 QA 체크리스트
| 항목 | 내용 |
|------|------|
| ID | `quarterly-qa-checklist` |
| 주기 | 분기 첫째 주 월요일 (1/4/7/10월) |
| 발송 시각 | 오전 09:40 |
| 메시지 타입 | 인터랙티브 체크리스트 |

**업무 목록 (1개):**

| # | 항목 | 담당 |
|---|------|------|
| 1 | [호환성] 글로벌 호환성 트렌드 리포트 | 정예찬 |

---

#### 8. 미션 진행 현황 리마인더 (6개 채널)
| 항목 | 내용 |
|------|------|
| 타입 | `mission` |
| 주기 | 평일 매일 |
| 발송 시각 | 09:00~09:30 (채널별 랜덤) |
| 메시지 타입 | Block Kit (진행 막대 + 서브태스크) |

---

### ⏸ 비활성 스케줄 (enabled: false) — 템플릿용

| ID | 이름 | 주기 |
|----|------|------|
| `daily-morning-checklist` | 일일 아침 체크리스트 | 매일 09:00 |
| `weekly-monday-meeting` | 주간 월요일 회의 알림 | 매주 월요일 09:00 |
| `monthly-report-first` | 월간 보고 체크리스트 | 매월 1일 09:00 |
| `biweekly-thursday-review` | 격주 목요일 스토어 랭킹 리뷰 | 격주 목요일 10:00 |
| `specific-event-example` | 특정 이벤트 알림 예시 | 특정 날짜 1회 |

> `"enabled": true` 로 변경하면 즉시 활성화됩니다.

---

## 🔧 기능 상세

### 1. 인터랙티브 체크리스트

담당자가 Slack 메시지에서 직접 체크하면 진행률이 실시간 업데이트됩니다.

```
📋 일일 QA 체크리스트
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2026년 3월  ▓▓▓▓░░░░░░  4/7 완료
📌 담당자  @이동현  @류석호  @정예찬
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[각 프로젝트] 서비스 장애
  ☑ [에픽세븐]  담당: 이동현
  ☑ [카제나]    담당: 류석호

[각 프로젝트] 핫픽스 내역
  ☑ [에픽세븐]  담당: 이동현
  ☐ [카제나]    담당: 류석호
...
```

#### 그룹 항목 완료 조건
- **그룹 항목:** 모든 서브 항목이 체크되어야 해당 그룹 1개 완료로 카운트
- **단독 항목:** 해당 항목 체크 시 즉시 완료

#### 상태 복구 (Fallback)
Railway(스케줄러)와 로컬 PC(인터랙션 처리)가 분리된 환경에서:
- 로컬에 상태 파일 없음 → `config.json` 타이틀 매칭으로 자동 재구성
- 자동 재구성 실패 시 → Slack 메시지 블록에서 직접 파싱

---

### 2. 그룹 체크리스트 구조 (config.json)

```json
{
  "items": [
    {
      "type": "group",
      "group_name": "[각 프로젝트] 서비스 장애",
      "sub_items": [
        {"value": "g0_epic7",  "text": "[에픽세븐]", "mentions": ["U07H17HB4MD"]},
        {"value": "g0_cazena", "text": "[카제나]",   "mentions": ["U07HFLMSYKV"]}
      ]
    },
    {
      "value": "solo_market",
      "text": "마켓 검수 내역",
      "mentions": ["U07H17HB4MD"]
    }
  ]
}
```

- `type: "group"` → 그룹 헤더 + 서브 체크박스 목록으로 렌더링
- 그룹 없이 단독 `value/text/mentions` → 단독 체크박스로 렌더링

---

### 3. 텍스트 메시지 템플릿 변수

`message_type: "text"` 사용 시 아래 변수를 자동 치환합니다.

| 변수 | 치환 값 | 예시 |
|------|---------|------|
| `{date}` | 발송 당일 `MM.DD(요일)` | `03.06(금)` |

**사용 예:**
```json
{
  "message_type": "text",
  "message": "# Game Service 1 - 업무\n- Date: {date}"
}
```

---

### 4. `/wiki` 슬래시 커맨드

Confluence Wiki 페이지를 Slack에서 직접 조회합니다.

| 커맨드 | 설명 |
|--------|------|
| `/wiki [페이지 제목]` | 해당 제목의 Wiki 페이지 내용 조회 |
| `/wiki [상위] > [하위] > [페이지]` | `>` 구분자로 계층 경로 지정 조회 |
| `/wiki [상위] / [하위] / [페이지]` | Confluence 브레드크럼 경로 그대로 붙여넣기 가능 |
| `/wiki [페이지] \ [질문]` | 페이지 내용 기반 Claude AI 답변 |
| `/wiki search [검색어]` | 키워드로 페이지 목록 검색 |
| `/wiki help` | 도움말 출력 |

**경로 검색 폴백 전략 (3단계):**
1. **1차** — `title ~ "페이지명" AND ancestor = "상위경로"` (전체 경로 CQL)
2. **2차** — CQL 파싱 오류 시 제목만으로 재시도
3. **3차** — 결과 없을 시 ancestor 조건 제거 후 제목만으로 재시도 (Confluence 경로명 불일치 대응)

- MCP 서버: `http://mcp.sginfra.net/confluence-wiki-mcp`
- 공간 키: `QASGP`
- Claude AI (`claude-haiku-4-5-20251001`) 로 내용 요약

#### 페이지별 검색 전략 예외처리 (`wiki_search_rules.json`)

`/wiki [페이지] \ [질문]` 사용 시 페이지와 질문 조건에 따라 **다른 조회 전략**을 적용할 수 있습니다.
봇 재시작 없이 파일 수정만으로 즉시 반영됩니다 (**hot reload**).

| 항목 | 내용 |
|------|------|
| 파일 | `wiki_search_rules.json` |
| 매칭 방식 | 페이지 제목(leaf) + 질문 키워드 조합으로 판단 |
| 폴백 | 규칙 없는 경우 기본 동작(페이지 직접 조회) 유지 |

**현재 등록된 예외 규칙:**

| 규칙 ID | 페이지 | 트리거 키워드 | 적용 전략 | 이유 |
|---------|--------|--------------|-----------|------|
| `rule-001` | `2026_MGQA` | 최근, 최신, 가장 최근, 마지막 등 | `get_latest_descendant` | 상위 페이지 본문은 1월부터 순서대로 노출 → 최신 질문 시 잘못된 답변. 하위 페이지 최신 1개만 조회해 토큰 절약 + 정확도 향상 |

**새 규칙 추가 방법 (`wiki_search_rules.json`):**
```json
{
  "id": "rule-002",
  "page_pattern": "페이지제목",
  "match_type": "exact",
  "trigger": { "keywords": ["키워드1", "키워드2"] },
  "strategy": "get_latest_descendant",
  "enabled": true,
  "added_at": "YYYY-MM-DD"
}
```
- `match_type`: `exact` / `contains` / `startswith` / `regex`
- `strategy`: `get_latest_descendant` (현재 지원)

---

### 5. `/gdi` 슬래시 커맨드 (v1.3.0~)

GDI(Game Doc Insight) 문서 데이터를 Slack에서 검색합니다.

| 커맨드 | 설명 |
|--------|------|
| `/gdi search [검색어]` | 크로스 컬렉션 통합 검색 |
| `/gdi file [파일명]` | 파일명 기반 검색 (청크 내용 포함) |
| `/gdi folder [경로]` | 폴더 내 파일 목록 조회 |
| `/gdi [검색어] \ [질문]` | 검색 결과 기반 Claude AI 답변 |
| `/gdi [폴더명] \ [파일명] \ [질문]` | 폴더+파일 지정 후 Claude AI 답변 |
| `/gdi help` | 도움말 출력 |

- MCP 서버: `http://mcp-dev.sginfra.net/game-doc-insight-mcp`
- 질문 의도 감지: 목록 질문 vs 내용 질문 자동 분기
- 3계층 캐시: 폴더 6시간, 파일 24시간

---

### 6. `/jira` 슬래시 커맨드 (v1.4.0~)

Jira 이슈/프로젝트를 Slack에서 조회합니다.

| 커맨드 | 설명 |
|--------|------|
| `/jira search [텍스트 or JQL]` | JQL 검색 (자동 변환 지원) |
| `/jira issue [PROJ-123]` | 이슈 상세 조회 |
| `/jira project [KEY]` | 프로젝트 정보 조회 |
| `/jira projects` | 전체 프로젝트 목록 |
| `/jira [이슈키] \ [질문]` | 이슈 기반 Claude AI 답변 |
| `/jira [검색어] \ [질문]` | 검색 결과 기반 Claude AI 답변 |
| `/jira help` | 도움말 출력 |

- MCP 서버: `http://mcp.sginfra.net/confluence-jira-mcp`
- 자동 JQL 변환: 단순 텍스트 → `text ~ "..." ORDER BY updated DESC`
- 점진적 확장 검색: 0건 시 키워드를 줄여가며 자동 재시도 (v1.4.1)
- 3계층 캐시: 이슈 10분, 프로젝트 1시간, 프로젝트목록 24시간

---

### 7. 미션 진행 현황 리마인더

각 채널의 미션 진행 상황을 매일 자동 알림합니다.

**발송 조건:** 평일 09:00~09:30 (채널별 랜덤 지연, 중복 방지)

**메시지 구성:**
```
📊 미션 진행 현황
━━━━━━━━━━━━━━━━
🎯 [미션명]
📅 목표일: 03.27  ⏰ D-21

전체 진행율
████░░░░░░  40%

Sub Task
▸ 서브태스크1
▸ 서브태스크2

💬 업무 마감 전, 이 메시지의 스레드에 현재 진행율(%)을 댓글로 남겨주세요!
   > 예시: 현재 진행율 35%
```

**진행율 갱신 방식:** 전날 메시지 스레드에서 `N%` 패턴 댓글 자동 파싱 → 다음 날 알림에 반영

**등록된 미션 채널:**

| 채널명 | 채널 ID | 미션 |
|--------|---------|------|
| AI-Driven QA Efficiency | C0AJK510DN1 | Slack QA - Supporter 활용 가이드 |
| Balance Engineering | C0AJNHQ74TU | 미정 |
| Data analysis | C0AJNHSUTCJ | 미정 |
| Knowledge Management | C0AJG69LC3V | 미정 |
| Roundtable | C0AKGRX2BKJ | 토론 진행 기획 |
| Tech Support | C0AKGRTU36U | Testrail TC 업로드 자동화 |

**상태 파일:** `mission_state.json` — 채널별 마지막 메시지 ts 및 진행율 저장

---

## ⚙️ 스케줄 타입 레퍼런스

### `daily` — 매일
```json
{ "type": "daily", "time": "09:00" }
```

### `weekly` — 매주 특정 요일
```json
{ "type": "weekly", "day_of_week": "friday", "time": "10:00" }
```
`day_of_week`: `monday` / `tuesday` / `wednesday` / `thursday` / `friday` / `saturday` / `sunday`

### `monthly` — 매월 특정 일
```json
{ "type": "monthly", "day_of_month": 1, "time": "09:00" }
```

### `monthly_last_weekday` — 매월 마지막 특정 요일
```json
{ "type": "monthly_last_weekday", "day_of_week": "friday", "time": "10:00" }
```

### `biweekly` — 격주
```json
{ "type": "biweekly", "day_of_week": "thursday", "time": "10:00", "start_date": "2026-03-06" }
```

### `nweekly` — N주 간격
```json
{ "type": "nweekly", "week_interval": 3, "day_of_week": "thursday", "time": "10:00", "start_date": "2026-03-12" }
```
`week_interval`: 반복 주 간격 / `start_date`: 첫 실행 날짜 (`YYYY-MM-DD`)

### `quarterly_first_monday` — 분기 첫째 주 월요일
```json
{ "type": "quarterly_first_monday", "time": "10:00" }
```
1월 / 4월 / 7월 / 10월의 첫 번째 월요일(1~7일)에 발송

### `specific` — 특정 날짜 1회
```json
{ "type": "specific", "datetime": "2026-03-15 10:00" }
```

---

## 💬 메시지 타입 레퍼런스

### `text` — 텍스트 (Slack mrkdwn)
```json
{
  "message_type": "text",
  "message": "*굵게* _기울임_ `코드`\n줄바꿈\n- Date: {date}"
}
```

### `checklist` — 정적 체크리스트 (☐ 기호)
```json
{
  "message_type": "checklist",
  "title": "📋 제목",
  "items": ["항목1", "항목2"]
}
```

### `interactive_checklist` — 인터랙티브 체크리스트 ★
```json
{
  "message_type": "interactive_checklist",
  "title": "📋 제목",
  "items": [
    {
      "type": "group",
      "group_name": "그룹명",
      "sub_items": [
        {"value": "고유값", "text": "표시명", "mentions": ["U...UID"]}
      ]
    },
    {"value": "고유값", "text": "단독항목", "mentions": ["U...UID"]}
  ]
}
```

---

## 🖥️ CLI 명령어

```bash
# 전체 실행 (스케줄 + 인터랙션)
python slack_bot.py

# 스케줄러만 (Railway 모드)
python slack_bot.py --scheduler-only

# 인터랙션(커맨드)만 (로컬 PC 모드)
python slack_bot.py --commands-only

# 채널 목록 출력 (채널 ID 확인용)
python slack_bot.py --channels

# 테스트 메시지 전송
python slack_bot.py --test C0XXXXXXXXX

# 즉시 메시지 전송
python slack_bot.py --send C0XXXXXXXXX "메시지 내용"

# 사용자 ID 검색 (mentions 설정용)
python slack_bot.py --find-user 이동현
```

---

## 🚀 개발 → 배포 워크플로우

```
1. 로컬에서 코드 수정 (D:\Vibe Dev\Slack Bot\)
       ↓
2. 로컬 봇 재시작으로 기능 확인
   (start_bot.bat 또는 WMI로 백그라운드 실행)
       ↓
3. GitHub push (모노레포 서브폴더 방식)
   ① C:\tmp\smith-proxy-tmp 에 클론
   ② 변경 파일 → Slack Bot\ 복사
   ③ git add / commit / push → main
       ↓
4. Railway 자동 배포 (~1~3분)
   → 스케줄러 봇 자동 재시작
```

### 로컬 봇 시작 (WMI 방식 — 타임아웃 우회)
```powershell
$wmi = [wmiclass]"Win32_Process"
$r = $wmi.Create("cmd.exe /c `"D:\Vibe Dev\Slack Bot\start_bot.bat`"", "D:\Vibe Dev\Slack Bot")
# PID 확인
Get-Content "D:\Vibe Dev\Slack Bot\slack_bot.pid"
# 로그 확인
Get-Content "D:\Vibe Dev\Slack Bot\slack_bot.log" -Tail 20 -Encoding UTF8
```

### 로컬 봇 종료
```powershell
$pid = Get-Content "D:\Vibe Dev\Slack Bot\slack_bot.pid" -Raw
Stop-Process -Id $pid -Force
Remove-Item "D:\Vibe Dev\Slack Bot\slack_bot.pid" -Force
```

---

## ⚠️ 토큰 설정

`.env` 파일:
```
SLACK_BOT_TOKEN=xoxb-...     # Bot Token (메시지 전송)
SLACK_APP_TOKEN=xapp-...     # App-Level Token (Socket Mode)
ANTHROPIC_API_KEY=sk-ant-... # Claude API (wiki 요약)
```

| 토큰 | Slack API 메뉴 | 필요 권한 |
|------|---------------|-----------|
| Bot Token | OAuth & Permissions | `chat:write`, `chat:write.customize`, `channels:read`, `groups:read`, `users:read` |
| App-Level Token | Basic Information → App-Level Tokens | `connections:write` |

> **Socket Mode** 및 **Interactivity** 는 Slack 앱 설정에서 ON 필요

---

## 🔖 버전 관리

| 항목 | 내용 |
|------|------|
| 버전 형식 | Semantic Versioning (`Major.Minor.Patch`) |
| 변경 이력 | [`CHANGELOG.md`](./changelog/CHANGELOG.md) |
| 롤백 방법 | `git checkout v1.1.3` → `git checkout main` 으로 복귀 |
| 태그 목록 | `git tag -l` |

**버전 규칙 요약:**
- **Major**: 기존 아키텍처와 호환 불가한 파격적 변경
- **Minor**: **새 기능 카테고리** 추가 시에만 (현재 기능: ① 알리미 ② /wiki ③ /gdi ④ /jira)
- **Patch**: 기존 기능 수정/개선 (버그 수정, 미션 채널 추가, wiki 예외처리 등 모두 Patch)

---

## 📝 운영 참고사항

| 항목 | 내용 |
|------|------|
| 로그 파일 | `slack_bot.log` |
| 체크리스트 상태 | `data/checklist_state.json` (Railway) |
| 중복 실행 방지 | `slack_bot.pid` 파일로 단일 인스턴스 보장 |
| 사용 모델 | `claude-haiku-4-5-20251001` |
| config 수정 후 | 로컬 봇 재시작 + GitHub push 필요 |
| **wiki 규칙 수정 후** | **봇 재시작 불필요 — 다음 /wiki 호출 시 자동 반영 (hot reload)** |
| 비활성 스케줄 | `"enabled": false` → 완전 무시됨 |
| 타임존 | `Asia/Seoul` (config.json 최상단) |

---

## 🤖 AI 어시스턴트(Claude)를 위한 개발 가이드

> 이 섹션은 새로운 컨텍스트에서 Claude가 시스템을 빠르게 파악하고 즉시 개발을 이어갈 수 있도록 작성된 가이드입니다.

### 📂 핵심 파일 역할 요약

| 파일 | 역할 | 주요 수정 케이스 |
|------|------|----------------|
| `slack_bot.py` | 봇 진입점, 슬래시 커맨드 핸들러 (~1700줄) | 새 커맨드 추가, 응답 로직 변경, 미션/체크리스트 수정 |
| `mcp_session.py` | MCP Streamable HTTP 세션 공용 모듈 | MCP 통신 프로토콜 변경 |
| `wiki_client.py` | Confluence Wiki MCP 클라이언트 | CQL 쿼리 변경, 검색 전략 추가 |
| `gdi_client.py` | GDI MCP 클라이언트 | 검색/파일/폴더 조회 로직 변경 |
| `jira_client.py` | Jira MCP 클라이언트 | JQL 변환, 이슈/프로젝트 조회 변경 |
| `wiki_search_rules.json` | wiki 검색 전략 예외처리 규칙 | 새 예외 규칙 추가/수정 (hot reload) |
| `scheduler.py` | APScheduler 기반 스케줄 실행 | 새 스케줄 타입 추가 |
| `interaction_handler.py` | 체크박스 인터랙션(Block Kit 동기화) | 체크리스트 UI 변경 |
| `config.json` | 스케줄 정의, 채널 ID, 메시지 템플릿 | 스케줄 추가/수정, 메시지 내용 변경 |
| `changelog/CHANGELOG.md` | 버전 이력 (Semantic Versioning) | 버전 업 시 반드시 업데이트 |

### 🔑 현재 구현된 네 가지 핵심 기능

#### ① 슬랙 알리미 (Slack Notification)
- **핵심 파일**: `slack_bot.py`, `scheduler.py`, `config.json`
- **포함 기능**: 인터랙티브 체크리스트, 미션 진행 현황 리마인더, 헤더 메시지 등
- **다중 사용자 체크**: `body[actions]` delta 방식으로 동기화 (`interaction_handler.py`)
- **미션 진행율**: 전날 스레드 댓글에서 `N%` 패턴 자동 파싱 → `mission_state.json` 업데이트

#### ② /wiki 슬래시 커맨드 (Wiki Response)
- **핵심 파일**: `slack_bot.py` (`_wiki_*` 함수들), `wiki_client.py`
- **MCP 서버**: `http://mcp.sginfra.net/confluence-wiki-mcp` (Streamable HTTP)
- **기본 흐름**:
  ```
  /wiki [페이지] \ [질문]
    → _find_matching_rule()       ← wiki_search_rules.json 규칙 매칭 (hot reload)
    → 규칙 있으면 해당 전략 실행  ← 예: get_latest_descendant()
    → 규칙 없으면 search_with_context() ← 질문 맥락(연도/키워드) 인식 검색
    → _wiki_ask_claude()          ← Claude Haiku로 답변 생성
  ```
- **페이지 조회**: CQL 3단계 폴백 + 질문 맥락 인식 스마트 검색 (v1.4.1)
- **3계층 캐시**: L1 인메모리 (5분) → L2 SQLite (24시간) → L3 MCP HTTP

#### ③ /gdi 슬래시 커맨드 (GDI Response, v1.3.0~)
- **핵심 파일**: `slack_bot.py` (`_gdi_*` 함수들), `gdi_client.py`
- **MCP 서버**: `http://mcp-dev.sginfra.net/game-doc-insight-mcp`
- **질문 의도 감지**: 목록 질문 vs 내용 질문 자동 분기 (v1.3.1)
- **3계층 캐시**: 폴더 6시간, 파일 24시간

#### ④ /jira 슬래시 커맨드 (Jira Response, v1.4.0~)
- **핵심 파일**: `slack_bot.py` (`_jira_*` 함수들), `jira_client.py`
- **MCP 서버**: `http://mcp.sginfra.net/confluence-jira-mcp`
- **자동 JQL 변환**: 단순 텍스트 → `text ~ "..."` (불용어 제거)
- **점진적 확장 검색**: 0건 시 키워드 축소 자동 재시도 (v1.4.1)
- **3계층 캐시**: 이슈 10분, 프로젝트 1시간, 프로젝트목록 24시간

### 🗂️ wiki_search_rules.json 상세 가이드

```
파일 위치: D:\Vibe Dev\Slack Bot\wiki_search_rules.json
hot reload: mtime 비교 방식, 봇 재시작 없이 자동 반영
```

**규칙 매칭 순서 (slack_bot.py: `_find_matching_rule`)**
1. `page_part`에서 leaf 제목 추출 (경로의 마지막 segment)
   - `"2026_MGQA > 2026_01_MGQA"` → leaf = `"2026_01_MGQA"`
   - `"QASGP / 2026_MGQA"` → leaf = `"2026_MGQA"`
2. `match_type`으로 leaf와 `page_pattern` 비교
3. 매칭 시 질문(소문자)에서 `trigger.keywords` 포함 여부 확인
4. 첫 번째 매칭 규칙의 `strategy` 실행

**지원 strategies**
| strategy | 동작 | 사용 케이스 |
|----------|------|------------|
| `get_latest_descendant` | `ancestor=페이지 ORDER BY created DESC LIMIT 1` CQL로 최신 하위 페이지 1개만 조회 | 상위 페이지가 목차/인덱스 역할이고, "최근" 질문 시 최신 하위 페이지가 정답인 경우 |
| (기본) | `_wiki_fetch_page()` 직접 조회 | 일반적인 경우 |

**새 규칙 추가 시 체크리스트**
- [ ] `id` 중복 없는지 확인 (rule-001, rule-002, ...)
- [ ] `page_pattern`이 Confluence 페이지 제목과 정확히 일치하는지 확인
- [ ] `match_type` 선택: 정확한 제목 → `exact`, 부분 포함 → `contains`
- [ ] `trigger.keywords`에 질문에 자주 쓰이는 단어 포함
- [ ] `enabled: true` 확인
- [ ] CHANGELOG.md 업데이트 (Patch 버전)

### 🔖 버전 관리 및 롤백 상세 가이드

**현재 버전: v1.5.6** | 기능 4개 (알리미, /wiki, /gdi, /jira)

**버전 규칙 재확인**
```
Major (x.0.0): 아키텍처 전면 개편
Minor (0.x.0): 새 기능 카테고리 추가 시에만 (다섯 번째 기능 → v1.5.0)
Patch (0.0.x): 그 외 모든 변경사항
  - 기존 기능 개선, 버그 수정, 설정 변경
```

**새 버전 릴리즈 절차**
```powershell
# 1. CHANGELOG.md에 새 버전 섹션 추가
# 2. README.md 상단 버전 배지 업데이트
# 3. 커밋
git add CHANGELOG.md README.md
git commit -F <message_file>   # BOM 없는 UTF-8 파일로 메시지 전달

# 4. 태그 등록
git tag v1.1.5 HEAD

# 5. Push (Railway 자동 배포)
git push origin main
git push origin --tags
```

**롤백 절차**
```powershell
# 특정 버전 코드 확인 (read-only)
git checkout v1.1.3

# 최신으로 복귀
git checkout main

# 특정 버전으로 완전 롤백 (branch에서 작업 후 PR)
git checkout -b rollback/v1.1.3 v1.1.3
```

**태그 → 커밋 매핑**
| 태그 | 커밋 | 내용 |
|------|------|------|
| `v1.0.0` | `f82f7a9` | 초기 알림봇 (체크리스트 기반) |
| `v1.1.0` | `9b8f2b3` | /wiki 슬래시 커맨드 추가 |
| `v1.1.1` | `92ea3ec` | wiki + 시스템 버그 수정 |
| `v1.1.2` | `672acde` | 미션 리마인더 추가 |
| `v1.1.3` | `7535f2a` | wiki 안정화 + 미션 채널 추가 |
| `v1.1.4` | `774445c` | wiki 페이지별 예외처리 + CHANGELOG |
| `v1.1.5` | `b614e58` | 미션 미정 채널 선정 독려 포맷 |
| `v1.2.0` | `19022a4` | 미션 넘버링 시스템 + 레포 정리 |
| `v1.3.0` | `e5e696c` | /gdi 슬래시 커맨드 추가 |
| `v1.3.1` | `01aa03c` | GDI 질문 의도 감지 + 안정화 |
| `v1.3.2` | `86c50b4` | Railway 재시작 감지 강화 |
| `v1.3.3` | `552720f` | daily/weekly 발송 반복 방지 |
| `v1.3.4` | `de59d61` | Wiki 캐시 통합 + 구분자 변경 |
| `v1.3.5` | `d0c1420` | GDI 캐시 통합 (L1+L2) |
| `v1.4.0` | `dcfacf0` | /jira 슬래시 커맨드 + Jira 캐시 통합 |
| `v1.4.1` | — | 검색 정확도 개선 (Wiki/Jira/GDI) |

### 🚀 봇 재시작 방법 (로컬 PC)

```powershell
# ① 기존 봇 종료 (PID 파일 확인)
$pid = Get-Content "D:\Vibe Dev\Slack Bot\slack_bot.pid"
Stop-Process -Id $pid -Force

# ② PID 파일 삭제
Remove-Item "D:\Vibe Dev\Slack Bot\slack_bot.pid"

# ③ 봇 시작 (WMI 방식 - Start-Process 대신 사용)
$wmi = [wmiclass]"Win32_Process"
$r = $wmi.Create("cmd.exe /c `"D:\Vibe Dev\Slack Bot\start_bot.bat`"", "D:\Vibe Dev\Slack Bot")

# ④ PID 확인
Start-Sleep 3
Get-Content "D:\Vibe Dev\Slack Bot\slack_bot.pid"
```

> **주의**: `Start-Process`는 MCP Shell에서 타임아웃 발생 → 반드시 WMI 방식 사용

### ⚠️ 알려진 주의사항

| 항목 | 내용 |
|------|------|
| Claude 모델 | `claude-haiku-4-5-20251001` (구버전 모델 2026-02-19 EOL → 404 오류) |
| MCP `get_page_by_title` | 서버 버그로 사용 불가 → `cql_search`로 대체됨 |
| SSE 인코딩 | `r.text` 사용 금지 (ISO-8859-1) → `r.content.decode('utf-8')` 사용 |
| CQL ancestor | `[ ] { } ( )` 포함 제목은 CQL 파싱 오류 → 자동 제외 처리 |
| git 실행 | Windows-MCP Shell에서 파이프 불가 → WMI + 파일 리디렉션 방식 사용 |
