# 🤖 퍼블리싱QA1팀 Slack 알림 봇 (QA Supporter)

> **SGP 퍼블리싱QA1팀** 전용 Slack 자동화 봇
> 일일 업무 헤더, QA 체크리스트, 주간 보고, 업데이트 차수 점검, 월간·분기 체크리스트를 자동 발송하고 담당자가 직접 체크할 수 있는 인터랙티브 메시지를 제공합니다.

---

## 📐 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│  로컬 PC (D:\Vibe Dev\Slack Bot\)                           │
│  ▶ 실행 모드: --commands-only                               │
│  ▶ 역할: 슬래시 커맨드(/wiki) + 체크박스 인터랙션 처리      │
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
| 주요 역할 | 체크박스 클릭 처리, `/wiki` 커맨드 | 스케줄 메시지 발송 |
| 상태 파일 | 없음 (fallback 재구성) | `data/checklist_state.json` |
| 봇 재시작 | 수동 (`start_bot.bat`) | push 시 자동 재배포 |

---

## 📁 파일 구조

```
Slack Bot/
├── slack_bot.py            # 메인 진입점 (CLI, Bolt 앱, 인터랙션 핸들러)
├── scheduler.py            # APScheduler 스케줄 관리 (6가지 타입 지원)
├── slack_sender.py         # Slack Web API 래퍼 (블록 빌더, 템플릿 치환)
├── interaction_handler.py  # 인터랙티브 체크리스트 상태 관리 (JSON 파일)
├── wiki_client.py          # Confluence Wiki MCP 클라이언트 (/wiki 커맨드)
├── config.json             # ★ 스케줄 설정 파일 (여기를 수정)
├── data/
│   └── checklist_state.json    # 체크 상태 저장 (Railway 자동 생성)
├── .env                    # 토큰 설정 (비공개 — .gitignore 처리)
├── .env.example            # 토큰 템플릿
├── requirements.txt        # 의존 패키지
├── Procfile                # Railway 실행 명령
├── runtime.txt             # Railway Python 버전
├── start_bot.bat           # 로컬 봇 시작 스크립트
├── setup.bat               # 최초 설치 스크립트
└── run.bat                 # 단순 실행 스크립트
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

**업무 목록 (7개 항목 / 6그룹 + 1단독):**

| # | 항목 | 담당 |
|---|------|------|
| 1 | **[각 프로젝트] 서비스 장애** — [에픽세븐] / [카제나] | 이동현 / 류석호 |
| 2 | **[각 프로젝트] 핫픽스 내역** — [에픽세븐] / [카제나] | 이동현 / 류석호 |
| 3 | 마켓 검수 내역 *(단독)* | 이동현 |
| 4 | **[각 프로젝트] Next Checklist** — [에픽세븐] / [카제나] | 이동현 / 류석호 |
| 5 | **[각 프로젝트] 커뮤니티 이슈** — [에픽세븐] / [카제나] | 이동현 / 류석호 |
| 6 | **[각 프로젝트] TEST INFO** — [에픽세븐] / [카제나] | 이동현 / 류석호 |
| 7 | **[각 프로젝트] Release INFO** — [에픽세븐] / [카제나] | 이동현 / 류석호 |

> **그룹 완료 조건:** 그룹 내 모든 서브 항목([에픽세븐] + [카제나]) 체크 시 해당 그룹 완료

---

#### 3. 주간 QA 보고
| 항목 | 내용 |
|------|------|
| ID | `weekly-qa-report` |
| 주기 | 매주 |
| 발송 요일 | 금요일 |
| 발송 시각 | 오전 10:00 |
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
| 발송 시각 | 오전 10:00 |
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
| 발송 시각 | 오전 10:00 |
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
| 발송 시각 | 오전 10:00 |
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
| 발송 시각 | 오전 10:00 |
| 메시지 타입 | 인터랙티브 체크리스트 |

**업무 목록 (1개):**

| # | 항목 | 담당 |
|---|------|------|
| 1 | [호환성] 글로벌 호환성 트렌드 리포트 | 정예찬 |

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
| `/wiki [페이지 제목]` | 해당 제목의 Wiki 페이지 내용 요약 출력 |
| `/wiki search [검색어]` | 검색어로 페이지 목록 검색 |
| `/wiki help` | 도움말 출력 |

- MCP 서버: `http://mcp.sginfra.net/confluence-wiki-mcp`
- 공간 키: `QASGP`
- Claude AI (`claude-haiku-4-5-20251001`) 로 내용 요약

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

## 📝 운영 참고사항

| 항목 | 내용 |
|------|------|
| 로그 파일 | `slack_bot.log` |
| 체크리스트 상태 | `data/checklist_state.json` (Railway) |
| 중복 실행 방지 | `slack_bot.pid` 파일로 단일 인스턴스 보장 |
| 사용 모델 | `claude-haiku-4-5-20251001` |
| config 수정 후 | 로컬 봇 재시작 + GitHub push 필요 |
| 비활성 스케줄 | `"enabled": false` → 완전 무시됨 |
| 타임존 | `Asia/Seoul` (config.json 최상단) |
