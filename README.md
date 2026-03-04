# 🤖 Slack 알림 봇

스케줄 기반 Slack 자동 알림 시스템
일일 / 주간 / 월간 / 격주 / 특정 날짜 알림을 체크리스트 또는 텍스트 형식으로 전송합니다.
인터랙티브 체크리스트를 지원하여 담당자가 직접 체크하면 메시지가 실시간으로 업데이트됩니다.

---

## 📁 파일 구조

```
Slack Bot/
├── slack_bot.py          # 메인 진입점 (CLI)
├── scheduler.py          # APScheduler 스케줄 관리
├── slack_sender.py       # Slack Web API 래퍼
├── interaction_handler.py # 인터랙티브 체크리스트 상태 관리
├── config.json           # 스케줄 설정 파일 (여기를 수정)
├── data/
│   └── checklist_state.json  # 체크리스트 상태 저장 (자동 생성)
├── .env                  # 토큰 설정 (비공개)
├── .env.example          # 토큰 템플릿
├── requirements.txt
├── setup.bat             # 최초 설치
└── run.bat               # 봇 실행
```

---

## ⚠️ 토큰 안내 (중요)

| 토큰 종류 | 형식 | 용도 |
|-----------|------|------|
| **Bot Token** ✅ 필수 | `xoxb-...` | 메시지 전송 (chat.postMessage) |
| **App-Level Token** ✅ 인터랙션에 필요 | `xapp-...` | Socket Mode (체크박스 클릭 수신) |

### Bot Token 발급 방법

1. [Slack API](https://api.slack.com/apps) → 앱 선택 → **OAuth & Permissions**
2. **Bot Token Scopes** 에 아래 권한 추가:
   - `chat:write` (메시지 전송) ← **필수**
   - `chat:write.customize` (봇 이름/이모지 커스터마이즈)
   - `channels:read` (채널 목록)
   - `groups:read` (비공개 채널 목록)
   - `users:read` (사용자 검색 — `--find-user` 용)
3. **Install to Workspace** 클릭 → 설치 승인
4. **Bot User OAuth Token** (`xoxb-...`) 복사 → `.env` 에 입력

### App-Level Token 발급 방법 (인터랙티브 체크리스트 필요)

1. [Slack API](https://api.slack.com/apps) → 앱 선택 → **Basic Information**
2. **App-Level Tokens** → **Generate Token and Scopes**
3. Scope: `connections:write` 추가
4. 생성된 `xapp-...` 토큰 복사 → `.env` 에 입력

### Socket Mode 활성화

1. 앱 설정 → **Socket Mode** → **Enable Socket Mode** ON

### Interactivity 활성화

1. 앱 설정 → **Interactivity & Shortcuts** → **Interactivity** ON

---

## 🚀 설치 및 실행

### 1. 최초 설치

```
setup.bat  더블클릭
```

또는 수동:
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 토큰 설정

`.env` 파일을 열어 두 토큰 모두 입력:

```
SLACK_BOT_TOKEN=xoxb-복사한-봇-토큰
SLACK_APP_TOKEN=xapp-복사한-앱레벨-토큰
```

### 3. 채널 ID 확인

```bash
python slack_bot.py --channels
```
출력된 채널 ID를 config.json 에 넣으세요

### 4. 담당자 사용자 ID 확인 (인터랙티브 체크리스트용)

```bash
python slack_bot.py --find-user 이동현
python slack_bot.py --find-user 류석호
```
출력된 `U...` ID를 config.json 의 `mentions` 필드에 넣으세요

### 5. config.json 설정

```json
{
  "channel": "C0XXXXXXXXX",  ← 채널 ID
  "items": [
    {
      "value": "item_0",
      "text": "작업명",
      "mentions": ["U0XXXXXXXX"]  ← --find-user 로 확인한 ID
    }
  ]
}
```

### 6. 테스트

```bash
python slack_bot.py --test C0XXXXXXXXX
```

### 7. 봇 실행

```
run.bat  더블클릭
```
또는:
```bash
python slack_bot.py
```

---

## ⚙️ 스케줄 타입 설정

### `daily` - 매일

```json
{
  "type": "daily",
  "time": "09:00",
  "message_type": "checklist",
  "title": "📋 오늘의 체크리스트",
  "items": ["항목1", "항목2"]
}
```

### `weekly` - 매주 특정 요일

```json
{
  "type": "weekly",
  "day_of_week": "monday",
  "time": "09:00",
  "message_type": "text",
  "message": "주간 회의 안내입니다!"
}
```

### `monthly` - 매월 특정 일

```json
{
  "type": "monthly",
  "day_of_month": 1,
  "time": "09:00"
}
```

### `monthly_last_weekday` - 매월 마지막 특정 요일 ★

```json
{
  "type": "monthly_last_weekday",
  "day_of_week": "friday",
  "time": "10:00",
  "message_type": "interactive_checklist",
  "title": "📋 팀 월간 체크리스트",
  "items": [
    {
      "value": "item_0",
      "text": "작업 이름",
      "mentions": ["U0XXXXXXXX"]
    }
  ]
}
```

### `biweekly` - 격주

```json
{
  "type": "biweekly",
  "day_of_week": "wednesday",
  "time": "14:00",
  "start_date": "2026-03-05"
}
```

### `nweekly` - N주 간격

```json
{
  "type": "nweekly",
  "week_interval": 3,
  "day_of_week": "thursday",
  "time": "10:00",
  "start_date": "2026-03-12",
  "message_type": "interactive_checklist",
  "title": "📋 업데이트 차수 체크리스트",
  "items": [
    {"value": "item_0", "text": "작업명", "mentions": ["U0XXXXXXXX"]}
  ]
}
```

> `week_interval`: 반복 주 간격 (예: 3 = 3주마다)
> `start_date`: 첫 실행 날짜 `YYYY-MM-DD` (생략 시 가장 가까운 해당 요일)

### `specific` - 특정 날짜 1회

```json
{
  "type": "specific",
  "datetime": "2026-03-15 10:00",
  "message_type": "text",
  "message": "오늘 중요한 이벤트가 있습니다!"
}
```

---

## 💬 메시지 타입

### `checklist` - 정적 체크리스트 (☐ 기호)

```json
{
  "message_type": "checklist",
  "title": "📋 체크리스트 제목",
  "items": ["항목1", "항목2", "항목3"]
}
```

### `text` - 텍스트 (Markdown 지원)

```json
{
  "message_type": "text",
  "message": "*굵은 글씨* _기울임_ `코드`\n줄바꿈도 가능합니다"
}
```

### `interactive_checklist` - 인터랙티브 체크리스트 ★

```json
{
  "message_type": "interactive_checklist",
  "title": "📋 인터랙티브 체크리스트",
  "items": [
    {"value": "item_0", "text": "작업명", "mentions": ["U0XXXXXXXX"]}
  ]
}
```

Slack 출력 예시:
```
📋 퍼블리싱QA1팀 월간 체크리스트
━━━━━━━━━━━━━━━━━━━━━━━━━━━
2026년 3월  ▓▓▓░░░░░░░  3/8 완료
━━━━━━━━━━━━━━━━━━━━━━━━━━━
☑  [에픽세븐] 프로젝트 월간 캘린더 최신화  담당: @이동현
☐  [카제나] 프로젝트 월간 캘린더 최신화   담당: @류석호
...
```
→ 담당자가 직접 체크하면 진행률이 실시간 업데이트됩니다.

---

## 🖥️ CLI 명령어

| 명령 | 설명 |
|------|------|
| `python slack_bot.py` | 봇 실행 (스케줄 + 인터랙션) |
| `python slack_bot.py --channels` | 채널 목록 출력 |
| `python slack_bot.py --test C0XXX` | 테스트 메시지 전송 |
| `python slack_bot.py --send C0XXX "메시지"` | 즉시 메시지 전송 |
| `python slack_bot.py --find-user 이름` | 사용자 ID 검색 (mentions 설정용) |

---

## 📝 참고

- 봇 실행 중 종료: **Ctrl+C**
- 로그 파일: `slack_bot.log`
- 체크리스트 상태: `data/checklist_state.json`
- 스케줄 수정 후에는 봇을 재시작해야 적용됩니다
- `enabled: false` 인 스케줄은 무시됩니다
