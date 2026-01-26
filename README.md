# 🎮 Maker Store Rank - Google Play 게임 랭킹 알림 시스템

매일 Google Play Store의 국가별 TOP 게임 랭킹을 Slack으로 알림받는 시스템입니다.

## 📌 주요 기능

- **국가별 TOP 5 랭킹**: 한국🇰🇷, 일본🇯🇵, 미국🇺🇸, 대만🇹🇼
- **랭킹 변동사항 자동 분석**: 신규 진입, 순위 이탈, 주요 변동 자동 추적 (변동 없으면 생략)
- **시장 인사이트 요약**: 각 국가별 시장 트렌드 및 특징
- **자동 백업**: 이전 데이터 자동 백업 및 히스토리 관리
- **🆕 GUI 데이터 입력**: 사용자 친화적인 그래픽 인터페이스
- **🆕 자동 스케줄러**: 매일 오전 9시에 자동으로 데이터 입력 창 실행

## 🔄 워크플로우 (자동화 버전)

```
1. 오전 9시 자동으로 GUI 창 실행 (자동)
   ↓
2. GUI에서 4개 국가 데이터 입력 (수동 - 5분)
   ↓
3. "저장" 버튼 클릭 (1초)
   ↓
4. 데이터 검증 및 저장 (자동)
   ↓
5. Slack 알림 자동 발송 (자동)
   • TOP 5 랭킹
   • 변동사항 + 인사이트 통합
```

**총 소요 시간: 약 5분** (자동화로 20분 절약!)

## 📁 프로젝트 구조

```
Maker Store Rank/
├── gui_data_input.py              # 🆕 GUI 데이터 입력 프로그램
├── run_daily_input.bat            # 🆕 GUI 실행 배치 파일
├── setup_scheduler.ps1            # 🆕 스케줄러 자동 등록 스크립트
├── process_manual_data.py         # 메인 처리 스크립트
├── manual_research_prompts.md     # Gemini/ChatGPT 프롬프트 모음
├── AUTO_SCHEDULER_GUIDE.md        # 🆕 자동 스케줄러 가이드
├── MANUAL_WORKFLOW_GUIDE.md       # 상세 사용 가이드
├── README.md                       # 프로젝트 개요 (본 문서)
├── .env                            # Slack 설정 (자동 로드)
└── data/
    ├── manual_input_template.json # 입력 템플릿
    ├── manual_input.json          # 실제 입력 데이터
    ├── rankings.json              # 현재 랭킹 데이터
    └── rankings_backup_*.json     # 자동 백업 파일들
```

## 🚀 빠른 시작 (자동화 버전)

### 1. 환경 설정 (최초 1회)

.env 파일은 이미 설정되어 있습니다!
- ✅ SLACK_WEBHOOK_URL
- ✅ SLACK_BOT_TOKEN
- ✅ SLACK_CHANNEL

### 2. 스케줄러 등록 (최초 1회)

**관리자 권한으로 PowerShell 실행:**

```powershell
cd "D:\Vibe Dev\Maker Store Rank"
.\setup_scheduler.ps1
```

이제 매일 오전 9시에 자동으로 데이터 입력 GUI가 실행됩니다!

### 3. 매일 사용 방법

1. **오전 9시에 GUI 자동 실행** (자동)
2. **4개 국가 탭에 데이터 입력** (5분)
   - 🇰🇷 South Korea
   - 🇯🇵 Japan
   - 🇺🇸 United States
   - 🇹🇼 Taiwan
3. **💾 저장 후 Slack 알림 전송** 버튼 클릭
4. **Slack 확인** (자동)

### 4. 수동 실행 (테스트용)

GUI를 즉시 실행하려면:

```bash
# 방법 1: 배치 파일 더블클릭
run_daily_input.bat

# 방법 2: Python 직접 실행
python gui_data_input.py
```

## 📊 Slack 알림 예시

### 메인 메시지 (TOP 5)
```
🎮 Google Play Store 게임 매출 랭킹 TOP 5
📅 날짜: 2026-01-22

🇰🇷 South Korea
1. 리니지2M - 엔씨소프트
2. 리니지M - 엔씨소프트
3. 원신 - COGNOSPHERE
4. 승리의 여신: 니케 - LEVEL INFINITE
5. 블루 아카이브 - NEXON Company

🇯🇵 Japan
1. モンスターストライク - XFLAG
...
```

### 변동사항 요약
```
📊 랭킹 변동사항 요약

🇰🇷 South Korea
  • 신규 진입: 프로젝트 무한
  • 순위 이탈: 세븐나이츠 컨퀘스트
  • 주요 변동: 쿠키런: 킹덤 ⬆️ 3칸 상승

🇯🇵 Japan
  변동 없음
...
```

### 인사이트 요약
```
💡 국가별 시장 인사이트

🇰🇷 South Korea
한국 시장에서 리니지 시리즈가 여전히 1, 2위를 차지하며 강세를 보이고 있습니다...

🇯🇵 Japan
일본 시장에서는 몬스트와 프로스피가 여전히 TOP 2를 차지하고 있습니다...
```

## 🔧 주요 기능 상세

### 1. 데이터 검증
- 각 국가당 정확히 20개 게임 확인
- 필수 필드 (제목, 퍼블리셔) 체크
- 순위 중복 검사

### 2. 자동 백업
- 실행 시 이전 `rankings.json` 자동 백업
- 백업 파일명: `rankings_backup_YYYYMMDD_HHMMSS.json`
- 히스토리 관리 용이

### 3. 변동사항 분석
- **신규 진입**: 이전 TOP 20에 없던 게임
- **순위 이탈**: TOP 20에서 벗어난 게임
- **주요 변동**: 3칸 이상 순위 변동

### 4. Slack 알림
- **메인 메시지**: 4개 국가 TOP 5
- **변동사항**: 국가별 랭킹 변화 요약
- **인사이트**: 시장 분석 및 트렌드
- **상세 스레드**: 국가별 TOP 1-20 전체 리스트

## ⏰ 일일 운영 가이드

**권장 시간: 매일 오전 8:30 - 9:00**

1. **08:30** - Gemini로 4개 국가 데이터 리서치 (15분)
2. **08:45** - `manual_input.json` 파일에 데이터 입력 (10분)
3. **08:55** - `python process_manual_data.py` 실행 (1분)
4. **09:00** - Slack 알림 자동 발송 완료 ✅

## ⚠️ 문제 해결

### "manual_input.json을 찾을 수 없습니다"
→ `data/manual_input_template.json`을 복사해서 `data/manual_input.json`으로 저장

### "게임이 XX개로 부족합니다"
→ 각 국가별로 정확히 20개 게임을 입력했는지 확인

### "SLACK_BOT_TOKEN이 설정되지 않았습니다"
→ 환경변수 설정: `set SLACK_BOT_TOKEN=xoxb-your-token-here`

### JSON 파싱 에러
→ JSON 형식 검증: https://jsonlint.com

## 📚 상세 문서

- [AUTO_SCHEDULER_GUIDE.md](./AUTO_SCHEDULER_GUIDE.md) - 🆕 자동 스케줄러 설정 가이드 (추천)
- [MANUAL_WORKFLOW_GUIDE.md](./MANUAL_WORKFLOW_GUIDE.md) - 단계별 상세 가이드
- [manual_research_prompts.md](./manual_research_prompts.md) - 리서치 프롬프트 모음

## 💡 팁

1. **일관된 시간**: 매일 같은 시간에 데이터 수집 → 추세 파악 용이
2. **백업 활용**: `data/rankings_backup_*.json`에서 과거 데이터 확인 가능
3. **인사이트 작성**: 구체적일수록 좋음 (예: "신규 XX게임 5일만에 TOP 10 진입")
4. **템플릿 재사용**: `manual_input.json`을 매일 재사용하고 날짜/데이터만 수정

## 🎯 시스템 특징

### 장점
- ✅ **완전 자동화된 Slack 알림**: 데이터만 입력하면 자동 전송
- ✅ **변동사항 자동 추적**: 이전 데이터와 자동 비교 (변동 없으면 생략)
- ✅ **데이터 안전성**: 자동 백업으로 데이터 손실 방지
- ✅ **구조화된 메시지**: TOP 5 + 변동사항 + 인사이트 통합
- ✅ **🆕 GUI 기반 입력**: 직관적인 그래픽 인터페이스
- ✅ **🆕 자동 스케줄**: 매일 오전 9시에 자동으로 창이 뜸
- ✅ **🆕 시간 절약**: 기존 25분 → 5분으로 단축

### 한계
- ⚠️ 데이터 리서치는 수동 (Gemini/ChatGPT 활용)
- ⚠️ Windows 작업 스케줄러 사용 (PC가 켜져있어야 함)

## 📞 지원

문제가 있거나 개선 제안이 있으면 이슈를 등록해주세요.

---

**마지막 업데이트**: 2026-01-22
**버전**: 2.0.0 (Automated GUI + Scheduler)

## 🆕 v2.0.0 업데이트 내용

- ✨ GUI 기반 데이터 입력 프로그램 추가
- ✨ Windows 작업 스케줄러 자동 등록 기능
- ✨ 매일 오전 9시 자동 실행
- 🔧 변동사항 없는 국가는 메시지에서 제외
- 🔧 변동사항 + 인사이트를 하나의 메시지로 통합
- 🔧 Webhook URL 사용으로 채널 권한 문제 해결
- 🔧 .env 파일 자동 로드 기능 추가
