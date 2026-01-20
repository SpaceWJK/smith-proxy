# 🎮 Game Ranking Crawler

매일 오전 9시(KST)에 한국, 일본, 미국, 대만 시장의 모바일 게임 매출 순위 Top 20을 수집하고 Slack으로 알림을 보내는 자동화 시스템입니다.

## 📋 Features

- **자동 크롤링**: 매일 9:00 AM (KST) GitHub Actions로 자동 실행
- **다국가 지원**: KR 🇰🇷, JP 🇯🇵, US 🇺🇸, TW 🇹🇼
- **Slack 알림**: 국가별 Top 20 게임 리스트를 Slack으로 전송
- **데이터 저장**: JSON 형식으로 히스토리 관리

## 🏗️ Architecture

```
┌──────────────┐
│  Scheduler   │ GitHub Actions (Daily 9AM KST)
└──────┬───────┘
       ↓
┌──────────────┐
│  Collector   │ 게임 랭킹 데이터 수집
└──────┬───────┘
       ↓
┌──────────────┐
│   Storage    │ snapshots/{date}/{country}.json
└──────┬───────┘
       ↓
┌──────────────┐
│   Notifier   │ Slack 알림 전송
└──────────────┘
```

## 🚀 Quick Start

### 1. Clone Repository

```bash
git clone <repository-url>
cd smith-proxy
```

### 2. Install Dependencies

```bash
pip install -r game_ranking_crawler/requirements.txt
```

### 3. Configure Slack Webhook

`.env` 파일을 생성하고 Slack Webhook URL을 설정하세요:

```bash
cp .env.example .env
# Edit .env and add your Slack webhook URL
```

`.env` 파일:
```
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

**Slack Webhook URL 받는 방법**:
1. https://api.slack.com/messaging/webhooks 방문
2. "Create your Slack app" 클릭
3. "Incoming Webhooks" 활성화
4. Webhook URL 복사

### 4. Run Manually

```bash
python -m game_ranking_crawler.main
```

## 📁 Project Structure

```
game_ranking_crawler/
├── collectors/              # 데이터 수집
│   ├── dummy_collector.py  # 테스트용 더미 데이터
│   └── ...                 # (향후) 실제 크롤러
├── storage/                # 데이터 저장
│   └── json_storage.py    # JSON 파일 저장소
├── notifiers/              # 알림
│   └── slack_notifier.py  # Slack 알림
├── models.py              # 데이터 모델
├── config.py              # 설정
├── main.py                # 메인 파이프라인
└── requirements.txt       # 의존성

snapshots/                  # 수집된 데이터
└── 2026-01-20/
    ├── KR.json
    ├── JP.json
    ├── US.json
    └── TW.json
```

## 📊 Data Format

각 국가별 JSON 파일 구조:

```json
{
  "country_code": "KR",
  "country_name": "South Korea",
  "date": "2026-01-20",
  "timestamp": "2026-01-20T00:00:00.000000",
  "games": [
    {
      "rank": 1,
      "title": "게임 제목",
      "publisher": "퍼블리셔",
      "package_id": "com.example.game",
      "app_url": "https://play.google.com/...",
      "icon_url": null
    }
  ]
}
```

## ⚙️ Configuration

### GitHub Actions Setup

1. **Slack Webhook Secret 설정**:
   - Repository → Settings → Secrets and variables → Actions
   - `New repository secret` 클릭
   - Name: `SLACK_WEBHOOK_URL`
   - Value: Your Slack webhook URL

2. **스케줄 변경** (`.github/workflows/daily-ranking-crawl.yml`):
   ```yaml
   schedule:
     - cron: '0 0 * * *'  # 00:00 UTC = 09:00 KST
   ```

3. **수동 실행**:
   - Actions 탭 → Daily Game Ranking Crawl → Run workflow

### Country Configuration

`game_ranking_crawler/config.py`에서 국가 추가/수정:

```python
COUNTRIES = {
    "KR": CountryConfig(
        code="KR",
        name="South Korea",
        flag_emoji="🇰🇷",
        language_code="ko"
    ),
    # ...
}
```

## 📝 TODO / Roadmap

### Phase 1: 기본 시스템 ✅
- [x] 프로젝트 구조 생성
- [x] 더미 데이터 크롤러
- [x] JSON 저장소
- [x] Slack 알림
- [x] GitHub Actions 스케줄러

### Phase 2: 실제 크롤링 🚧
- [ ] Google Play Store 크롤링 (Playwright)
- [ ] 백업 데이터 소스
- [ ] 에러 핸들링 강화

### Phase 3: 분석 기능 📅
- [ ] 전일 대비 순위 변동
- [ ] 장르 분석
- [ ] 퍼블리셔 집중도
- [ ] 국가별 시장 특징

### Phase 4: 고도화 💡
- [ ] SQLite 데이터베이스
- [ ] 웹 대시보드
- [ ] 장기 트렌드 분석

## 🛠️ Development

### Run Tests

```bash
python test_crawl.py
```

### Change Collector

`game_ranking_crawler/main.py`:

```python
# Dummy data
from game_ranking_crawler.collectors.dummy_collector import DummyCollector
collector = DummyCollector()

# Real crawler (when implemented)
# from game_ranking_crawler.collectors.playstore_collector import PlayStoreCollector
# collector = PlayStoreCollector()
```

## 📧 Slack Message Format

```
📊 Game Ranking Report - 2026-01-20
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🇰🇷 South Korea (KR)
🥇 게임 A _퍼블리셔 A_
🥈 게임 B _퍼블리셔 B_
🥉 게임 C _퍼블리셔 C_
...

🇯🇵 Japan (JP)
...
```

## 🐛 Troubleshooting

### Slack 알림이 오지 않을 때

1. `.env` 파일에 `SLACK_WEBHOOK_URL`이 설정되어 있는지 확인
2. GitHub Actions: Secrets에 `SLACK_WEBHOOK_URL`이 설정되어 있는지 확인
3. Webhook URL이 유효한지 테스트:
   ```bash
   curl -X POST -H 'Content-type: application/json' \
     --data '{"text":"Test message"}' \
     YOUR_WEBHOOK_URL
   ```

### GitHub Actions가 실행되지 않을 때

1. Actions 탭에서 워크플로우가 활성화되어 있는지 확인
2. `.github/workflows/` 디렉토리가 main 브랜치에 있는지 확인
3. Repository 권한 확인: Settings → Actions → General → Workflow permissions

## 📄 License

MIT License

## 🤝 Contributing

Issues와 Pull Requests를 환영합니다!

## 📞 Contact

프로젝트 관련 문의사항은 Issues를 통해 남겨주세요.
