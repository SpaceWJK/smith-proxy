# 🎮 Game Ranking Auto-Notification System

Google Play Store의 게임 랭킹을 자동으로 수집하여 매일 Slack으로 알림을 보내는 시스템입니다.

## 📋 시스템 개요

### 목표
매일 오전 9시(KST)에 4개 국가(한국, 일본, 미국, 대만)의 Google Play Store TOP 5 게임 랭킹을 Slack으로 자동 전송

### 주요 기능
- **자동 데이터 수집**: Selenium으로 Gemini 웹을 제어하여 실시간 게임 랭킹 수집
- **GitHub 자동 커밋**: 수집된 데이터를 자동으로 저장하고 커밋
- **Slack 알림**: GitHub Actions로 매일 정해진 시간에 자동 알림 발송

## 🏗️ 시스템 아키텍처

```
[로컬 PC]
  ↓ Selenium + Chrome
[Gemini Web] → 게임 랭킹 수집
  ↓ JSON 저장
[rankings.json]
  ↓ Git push
[GitHub Repository]
  ↓ GitHub Actions (Cron: 매일 09:00 KST)
[Slack Notification] → #sgpqa_epiczero
```

## 📦 설치 방법

### 1. 저장소 클론
```bash
git clone https://github.com/YOUR_USERNAME/maker-store-rank.git
cd maker-store-rank
```

### 2. Python 의존성 설치
```bash
pip install -r requirements.txt
```

### 3. Chrome 브라우저 설치
Selenium이 Chrome을 제어하므로 Chrome 브라우저가 필요합니다.
- [Chrome 다운로드](https://www.google.com/chrome/)

## 🚀 사용 방법

### 로컬에서 데이터 수집 실행

```bash
python auto_gemini_research.py
```

**실행 과정:**
1. Chrome 브라우저 자동 실행
2. Gemini 웹 접속
3. 게임 랭킹 요청 프롬프트 전송
4. 응답 대기 및 JSON 파싱
5. `data/rankings.json` 파일 저장
6. Git 자동 커밋 및 푸시

### Slack 알림 테스트

```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
python send_ranking_notification.py
```

## ⚙️ GitHub Actions 설정

### 1. Slack Webhook URL 생성
1. Slack에서 Incoming Webhook 생성
2. `#sgpqa_epiczero` 채널 선택
3. Webhook URL 복사

### 2. GitHub Secrets 설정
GitHub 저장소 → Settings → Secrets and variables → Actions

**추가할 Secret:**
- `SLACK_WEBHOOK_URL`: Slack Webhook URL

### 3. 자동 실행 확인
- `.github/workflows/daily-ranking.yml` 파일이 자동으로 동작
- 매일 UTC 00:00 (KST 09:00)에 실행
- Actions 탭에서 실행 로그 확인 가능

## 📊 출력 형식

### Slack 메시지 예시
```
Game Rankings(Android) • 2026-01-21

🇰🇷 South Korea
1 리니지M • NCSOFT
2 메이플스토리 • 넥슨
3 원신 • 호요버스
4 배틀그라운드 모바일 • KRAFTON
5 쿠키런: 킹덤 • Devsisters

🇯🇵 Japan
1 ウマ娘 プリティーダービー • Cygames
2 モンスターストライク • MIXI
3 Fate/Grand Order • Aniplex
4 パズル&ドラゴンズ • GungHo
5 プロ野球スピリッツA • Konami

🇺🇸 United States
1 MONOPOLY GO! • Scopely
2 Royal Match • Dream Games
3 Candy Crush Saga • King
4 Roblox • Roblox Corporation
5 Coin Master • Moon Active

🇹🇼 Taiwan
1 天堂M • NCSOFT
2 天堂2M • NCSOFT
3 傳說對決 • Garena
4 Fate/Grand Order • Aniplex
5 原神 • HoYoverse
```

### JSON 파일 구조
```json
{
  "ranking_date": "2026-01-21",
  "countries": [
    {
      "country": "South Korea",
      "flag": "🇰🇷",
      "games": [
        {"rank": 1, "title": "리니지M", "publisher": "NCSOFT"},
        {"rank": 2, "title": "메이플스토리", "publisher": "넥슨"}
      ]
    }
  ]
}
```

## 🗂️ 프로젝트 구조

```
maker-store-rank/
├── auto_gemini_research.py      # 메인 데이터 수집 스크립트
├── send_ranking_notification.py # Slack 알림 스크립트
├── requirements.txt             # Python 의존성
├── .gitignore                   # Git 제외 파일
├── .env.example                 # 환경변수 예시
├── README.md                    # 프로젝트 문서
├── data/
│   └── rankings.json            # 수집된 랭킹 데이터
├── logs/
│   └── screenshots/             # 에러 발생 시 스크린샷
└── .github/
    └── workflows/
        └── daily-ranking.yml    # GitHub Actions 설정
```

## 🛠️ 기술 스택

- **Python 3.11+**
- **Selenium**: Chrome 브라우저 자동화
- **webdriver-manager**: ChromeDriver 자동 관리
- **requests**: Slack Webhook 통신
- **GitHub Actions**: 스케줄링 및 자동화

## 🔍 문제 해결

### 1. Chrome WebDriver 오류
```bash
# ChromeDriver 수동 설치
pip install --upgrade webdriver-manager
```

### 2. Gemini 로그인 필요
- 첫 실행 시 `headless=False`로 설정하고 수동 로그인
- 쿠키가 저장되면 이후 자동 실행 가능

### 3. Git 푸시 실패
```bash
# Personal Access Token 설정
git remote set-url origin https://YOUR_TOKEN@github.com/YOUR_USERNAME/maker-store-rank.git
```

### 4. Selector 변경으로 입력창 못 찾음
- `auto_gemini_research.py`의 `find_input_element()` 함수에서 selector 업데이트
- 디버깅 시 `headless=False`로 실행하여 HTML 구조 확인

## ⚠️ 주의사항

1. **Gemini 웹 구조 변경**: Gemini 웹사이트의 HTML 구조가 변경되면 selector 수정 필요
2. **응답 대기 시간**: Gemini가 웹 검색 후 응답하는 시간이 가변적이므로 충분한 대기 시간 필요
3. **Rate Limiting**: 과도한 요청 시 일시적 차단 가능성 있음 (일 1회 실행 권장)
4. **JSON 형식**: Gemini 응답 형식이 다를 수 있으므로 파싱 오류 발생 시 수동 확인 필요

## 📝 라이선스

MIT License

## 🤝 기여

이슈 및 Pull Request 환영합니다!

## 📧 문의

문제가 발생하면 GitHub Issues에 등록해주세요.
