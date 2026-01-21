# 🔐 GitHub Secrets 설정 가이드

## ✅ 완료된 작업
- ✅ 코드가 GitHub에 푸시되었습니다!
- ✅ 브랜치: `feature/game-ranking-system`
- ✅ 레포지토리: https://github.com/SpaceWJK/smith-proxy

## 📝 마지막 단계: GitHub Secrets 설정

GitHub Actions가 Slack으로 알림을 보내려면 Webhook URL을 Secret으로 등록해야 합니다.

### 단계별 설정 방법

1. **GitHub 레포지토리 페이지로 이동**
   ```
   https://github.com/SpaceWJK/smith-proxy/settings/secrets/actions
   ```

2. **New repository secret 클릭**
   - 오른쪽 상단의 "New repository secret" 버튼 클릭

3. **Secret 정보 입력**
   ```
   Name: SLACK_WEBHOOK_URL

   Secret: (아래 참조)
   ```

   💡 **Webhook URL 찾기**:
   - 로컬의 `.env` 파일을 열면 `SLACK_WEBHOOK_URL=` 뒤에 값이 있습니다
   - 또는 처음에 받은 Slack Webhook URL을 복사

4. **Add secret 클릭**
   - 저장 완료!

## 🎉 설정 완료!

이제 다음과 같이 작동합니다:

### 로컬 실행 (수동)
```bash
cd "D:\Vibe Dev\Maker Store Rank"
python auto_gemini_research.py
```
- Chrome이 자동으로 열림
- Gemini에서 게임 랭킹 수집
- `data/rankings.json` 업데이트
- Git 자동 커밋 및 푸시

### GitHub Actions (자동 - 매일 오전 9시)
- `data/rankings.json` 파일 읽기
- Slack으로 포맷된 메시지 전송
- 지정된 Slack 채널에 알림

## 🧪 테스트 방법

### 1. 로컬에서 Slack 알림 테스트

가장 쉬운 방법 (.env 파일이 이미 설정되어 있음):

```bash
cd "D:\Vibe Dev\Maker Store Rank"
python send_ranking_notification.py
```

### 2. GitHub Actions 수동 실행
1. https://github.com/SpaceWJK/smith-proxy/actions
2. "Daily Game Ranking Notification" 워크플로우 선택
3. "Run workflow" 드롭다운 클릭
4. 브랜치 선택: `feature/game-ranking-system`
5. "Run workflow" 버튼 클릭

## 📊 예상 Slack 메시지 형식

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
...
```

## ❓ 문제 해결

### Secret이 작동하지 않는다면?
- Secret 이름이 정확히 `SLACK_WEBHOOK_URL`인지 확인
- Webhook URL이 올바른지 확인 (로컬 .env 파일과 비교)
- GitHub Actions에서 브랜치가 올바른지 확인

### 워크플로우가 실행되지 않는다면?
- `.github/workflows/daily-ranking.yml` 파일이 푸시되었는지 확인
- Actions 탭에서 워크플로우가 활성화되어 있는지 확인

## 🔄 main 브랜치로 머지하기

테스트가 완료되면 main 브랜치로 머지하세요:

1. Pull Request 생성: https://github.com/SpaceWJK/smith-proxy/compare/main...feature/game-ranking-system
2. 코드 리뷰 및 승인
3. Merge to main
4. main 브랜치에서 매일 오전 9시 자동 실행!
