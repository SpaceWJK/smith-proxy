# 🎮 Google Play Store Game Ranking Crawler

매일 오전 9시(KST)에 Google Play Store TOP 5 게임 랭킹을 자동으로 수집하여 Slack으로 알림하는 시스템입니다.

## ✨ 주요 기능

- 🤖 **Gemini API** 활용 (완전 무료, 월 1,500 요청)
- ⏰ **매일 오전 9시(KST)** 자동 실행 (GitHub Actions)
- 📱 **TOP 5 게임** 정보 수집
  - 게임 제목
  - 퍼블리셔
  - 카테고리
  - Android 패키지명
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
🎮 Google Play Store TOP 5 게임 랭킹
📅 2024-01-20 09:00 (KST) | 🤖 Gemini API
─────────────────────────────────────
🥇 게임 제목 1
📱 퍼블리셔: Publisher Name
🏷️ 카테고리: Game
📦 Package: com.example.game1

🥈 게임 제목 2
...
```

## 🔧 기술 스택

- **Python 3.11**
- **Gemini API** (Google AI)
- **GitHub Actions** (스케줄링)
- **Slack Webhook** (알림)

## 📝 라이선스

MIT License
