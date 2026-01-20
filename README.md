# 🎮 Google Play Store Game Ranking Notification System

매일 오전 9시(KST)에 게임 랭킹 데이터를 Slack으로 자동 알림하는 시스템입니다.

## ✨ 주요 기능

- 🔍 **로컬 리서치**: Chrome 브라우저를 통해 Gemini 웹에서 게임 랭킹 조사
- 📂 **JSON 기반**: `data/rankings.json` 파일에 데이터 저장
- ⏰ **자동 알림**: 매일 오전 9시(KST) GitHub Actions가 Slack 알림 자동 발송
- 🌏 **다국가 랭킹** 지원
  - 🇰🇷 South Korea
  - 🇯🇵 Japan
  - 🇺🇸 United States
  - 🇹🇼 Taiwan
- 📱 **각 국가별 TOP 5 게임** 정보
  - 게임 제목 (현지 언어)
  - 퍼블리셔
- 💬 **Slack 알림** (#sgpqa_epiczero 채널)

## 🔄 작동 방식

```
[로컬 PC - 수동 실행]
1. Python 스크립트 실행
2. Chrome 브라우저로 Gemini 웹 접속
3. 게임 랭킹 질문 및 응답 수신
4. data/rankings.json 저장
5. GitHub에 커밋 및 푸시

[GitHub Actions - 매일 오전 9시 자동 실행]
1. rankings.json 파일 읽기
2. Slack으로 알림 자동 발송
```

## 🚀 사용 방법

### 1단계: 게임 랭킹 리서치 (로컬)

```bash
# 의존성 설치
pip install -r requirements.txt

# 리서치 스크립트 실행
python research_with_browser.py
```

스크립트가 안내하는 대로:
1. Gemini 웹사이트에서 게임 랭킹 질문
2. 응답을 받아서 JSON으로 저장
3. `data/rankings.json` 생성 확인

### 2단계: GitHub에 커밋

```bash
git add data/rankings.json
git commit -m "Update game rankings for $(date +%Y-%m-%d)"
git push
```

### 3단계: 자동 알림 확인

- 다음날 오전 9시(KST)에 Slack 자동 알림 발송
- 또는 GitHub Actions에서 수동 실행 가능

## ⚙️ GitHub Actions 설정

### Secrets 등록

GitHub Repository → **Settings** → **Secrets and variables** → **Actions**

등록 필요:
- `SLACK_WEBHOOK_URL`: Slack Webhook URL

### 자동 실행 스케줄

- **매일 오전 9시(KST)** 자동 실행
- **수동 실행** 가능 (Actions 탭 → Run workflow)

## 📋 출력 예시

```
Game Rankings(Android) • 2026-01-20

🇰🇷 South Korea
1 메이플스토리: 아이돌 RPG • 넥슨
2 라스트 워: 서바이벌 게임 • FUNFLY
3 화이트아웃 서바이벌 • Century Games
4 라스트 Z: 서바이벌 슈터 • Florere Game
5 원신 • 호요버스

🇯🇵 Japan
1 Fate/Grand Order • Aniplex
2 Monster Strike • MIXI
3 Puzzle & Dragons • GungHo
4 Dragon Quest Walk • Square Enix
5 Uma Musume Pretty Derby • Cygames

🇺🇸 United States
1 MONOPOLY GO! • Scopely
2 Royal Match • Dream Games
3 Candy Crush Saga • King
4 Coin Master • Moon Active
5 Roblox • Roblox Corporation

🇹🇼 Taiwan
1 Lineage M • NCSOFT
2 Lineage W • NCSOFT
3 Ragnarok X: Next Generation • Gravity
4 Garena 傳說對決 • Garena
5 Fate/Grand Order • Aniplex
```

## 🔧 기술 스택

- **Python 3.11**
- **Selenium + Chrome WebDriver** (로컬 브라우저 제어)
- **Gemini 웹** (게임 랭킹 리서치)
- **JSON 파일 기반** (데이터 저장)
- **GitHub Actions** (자동 알림 스케줄링)
- **Slack Webhook** (알림 전송)

## 📁 파일 구조

```
smith-proxy/
├── data/
│   └── rankings.json          # 게임 랭킹 데이터 (수동 업데이트)
├── research_with_browser.py   # 로컬: 리서치 스크립트
├── send_ranking_notification.py # GitHub Actions: Slack 알림
├── .github/workflows/
│   └── daily-ranking.yml      # 자동 실행 설정
└── README.md
```

## 📝 라이선스

MIT License
