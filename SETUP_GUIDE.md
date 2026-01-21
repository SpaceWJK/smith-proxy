# 🚀 빠른 시작 가이드

모든 코드와 의존성은 이미 준비되었습니다! 이제 2가지만 하면 됩니다.

## ✅ 완료된 작업
- ✅ 프로젝트 폴더 생성
- ✅ 모든 코드 파일 작성 완료
- ✅ Python 의존성 설치 완료
- ✅ Git 초기 커밋 완료

## 📝 해야 할 일 (2가지만!)

### 1️⃣ GitHub에 저장소 생성 및 푸시 (2분)

```bash
# GitHub에서 새 저장소 생성
# 1. https://github.com/new 접속
# 2. Repository name: maker-store-rank (또는 원하는 이름)
# 3. Public/Private 선택
# 4. "Create repository" 클릭
# 5. 아래 명령어 실행 (YOUR_USERNAME을 본인 GitHub 아이디로 변경)

cd "D:\Vibe Dev\Maker Store Rank"
git remote add origin https://github.com/YOUR_USERNAME/maker-store-rank.git
git branch -M main
git push -u origin main
```

### 2️⃣ Slack Webhook 설정 (3분)

#### A. Slack Webhook URL 생성
1. https://api.slack.com/apps 접속
2. "Create New App" → "From scratch" 선택
3. App Name: "Game Rankings Bot" 입력
4. Workspace 선택 → "Create App"
5. 왼쪽 메뉴에서 "Incoming Webhooks" 클릭
6. "Activate Incoming Webhooks" ON으로 변경
7. "Add New Webhook to Workspace" 클릭
8. `#sgpqa_epiczero` 채널 선택 (또는 원하는 채널)
9. "Allow" 클릭
10. Webhook URL 복사 (https://hooks.slack.com/services/... 형식)

#### B. GitHub Secrets 등록
1. GitHub 저장소 페이지 → Settings 탭
2. 왼쪽 메뉴: Secrets and variables → Actions
3. "New repository secret" 클릭
4. Name: `SLACK_WEBHOOK_URL`
5. Secret: 위에서 복사한 Webhook URL 붙여넣기
6. "Add secret" 클릭

## 🎉 완료!

이제 다음과 같이 작동합니다:

1. **로컬에서 실행** (언제든지):
   ```bash
   cd "D:\Vibe Dev\Maker Store Rank"
   python auto_gemini_research.py
   ```
   → Chrome이 자동으로 열리고 Gemini에서 데이터 수집
   → `data/rankings.json` 파일 업데이트
   → Git 자동 커밋 및 푸시

2. **GitHub Actions** (매일 오전 9시 자동):
   → `rankings.json` 파일 읽기
   → Slack으로 포맷된 메시지 전송

## 🧪 테스트 방법

### Slack 알림 테스트 (로컬)
```bash
# Windows (PowerShell)
$env:SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
python send_ranking_notification.py

# Windows (CMD)
set SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
python send_ranking_notification.py
```

### GitHub Actions 수동 실행
1. GitHub 저장소 → Actions 탭
2. "Daily Game Ranking Notification" 워크플로우 선택
3. "Run workflow" → "Run workflow" 클릭

## ❓ 문제 해결

### Chrome 브라우저가 없다면?
https://www.google.com/chrome/ 에서 설치

### Git 푸시가 안 된다면?
```bash
# Personal Access Token 필요
# GitHub → Settings → Developer settings → Personal access tokens → Generate new token
# repo 권한 선택 후 생성
# 아래 명령어에서 YOUR_TOKEN을 생성한 토큰으로 변경

git remote set-url origin https://YOUR_TOKEN@github.com/YOUR_USERNAME/maker-store-rank.git
git push
```

### Gemini 로그인이 필요하다면?
- 첫 실행 시 Chrome 브라우저에서 수동으로 Gemini 로그인
- 로그인 후 쿠키가 저장되어 다음부터는 자동 실행

## 📞 도움이 필요하면?
README.md 파일을 참고하거나 GitHub Issues에 질문해주세요!
