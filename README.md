# 🎮 Google Play Store Game Ranking Crawler

매일 오전 9시(KST)에 여러 국가의 Google Play Store TOP 5 게임 랭킹을 자동으로 수집하여 Slack으로 알림하는 시스템입니다.

## ✨ 주요 기능

- 🤖 **Gemini API** 활용 (완전 무료, 월 1,500 요청)
- ⏰ **매일 오전 9시(KST)** 자동 실행 (GitHub Actions)
- 🌏 **다국가 랭킹** 수집
  - 🇰🇷 South Korea
  - 🇯🇵 Japan
  - 🇺🇸 United States
  - 🇹🇼 Taiwan
- 📱 **각 국가별 TOP 5 게임** 정보
  - 게임 제목 (번역 규칙)
    - 🇰🇷 한국: 한국 출시된 게임은 한글 제목, 미출시 게임은 영어/원문
    - 🇯🇵 일본: 일본어 원문
    - 🇺🇸 미국: 영어 원문
    - 🇹🇼 대만: 중국어(번체) 또는 영어
  - 퍼블리셔
- 💬 **Slack 알림** (#sgpqa_epiczero 채널)

## 🚀 설치 및 실행

### 로컬 테스트

1. **의존성 설치**
```bash
pip install -r requirements.txt
```

2. **환경변수 설정**
`.env` 파일 생성:
```env
GEMINI_API_KEY=your_gemini_api_key
SLACK_WEBHOOK_URL=your_slack_webhook_url
```

3. **실행**
```bash
python game_ranking_crawler.py
```

## ⚙️ GitHub Actions 설정

### 1. Secrets 등록

GitHub Repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

등록할 Secrets:
- `GEMINI_API_KEY`: Gemini API 키 ([발급받기](https://aistudio.google.com/apikey))
- `SLACK_WEBHOOK_URL`: Slack Webhook URL

### 2. 자동 실행 스케줄

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
- **Gemini API** (Google AI)
- **GitHub Actions** (스케줄링)
- **Slack Webhook** (알림)

## 📝 라이선스

MIT License
