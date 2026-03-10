# Slack Bot 개발 규칙
> **Version**: 1.1.0
> **Last Updated**: 2026-03-09
> **Author**: Claude (AI Assistant)

---

## 1. 프로젝트 구조

```
D:\Vibe Dev\Slack Bot\              ← 프로젝트 루트 (Git 레포)
├── .claude/                        ← Claude 메모리 (개발 규칙, 작업 히스토리)
│   ├── DEV_RULES.md               ← 이 파일
│   └── WORK_LOG.md                ← 일일 작업 히스토리
├── logs/                           ← 로그 (wiki 조회, 디버그)
│   ├── wiki_query.log             ← /wiki 조회 내역 + 에러
│   ├── gdi_query.log              ← /gdi 조회 내역 + 에러
│   └── debug.log                  ← 디버그 상세 로그
├── changelog/                      ← 버전 히스토리
│   └── CHANGELOG.md               ← 패치/업데이트 이력
├── Slack Bot/                      ← 소스 코드 디렉토리
│   ├── slack_bot.py               ← 메인 진입점
│   ├── slack_sender.py            ← Slack Web API 래퍼 + Block Kit 빌더
│   ├── scheduler.py               ← APScheduler 스케줄 관리
│   ├── interaction_handler.py     ← 체크리스트 상태 관리
│   ├── mcp_session.py             ← MCP Streamable HTTP 세션 공용 모듈
│   ├── wiki_client.py             ← Confluence Wiki MCP 클라이언트
│   ├── gdi_client.py              ← GDI(Game Doc Insight) MCP 클라이언트
│   ├── missed_tracker.py          ← 전일 미체크 항목 추적
│   ├── schedule_monitor.py        ← 스케줄 모니터링
│   ├── config.json                ← 스케줄 정의 + 사용자 매핑
│   └── wiki_search_rules.json     ← 페이지별 검색 전략 예외
├── _legacy/                        ← 레거시 파일 대기소 (만료 후 삭제)
│   └── EXPIRY.md                  ← 이동일, 삭제 예정일, 파일 목록
├── venv/                           ← Python 가상환경
├── .env                            ← 환경변수 (토큰, API 키)
└── .gitignore
```

## 2. 작업 디렉토리 규칙

- **모든 소스 코드 수정은 `Slack Bot/` 디렉토리 내에서만 수행**
- 프로젝트 루트에 소스 파일을 직접 생성하지 않음
- `config.json`, `wiki_search_rules.json` 등 설정 파일도 `Slack Bot/` 내에 위치
- 예외: `.env`는 프로젝트 루트에 위치 (venv 활성화 경로와 일치시키기 위해)

## 3. 버전 관리 규칙

### Git 커밋
- **Conventional Commits** 형식 사용:
  - `feat:` 새 기능
  - `fix:` 버그 수정
  - `refactor:` 리팩토링
  - `docs:` 문서
  - `chore:` 유지보수
- 커밋 메시지는 한글 또는 영문 (기존 패턴 유지)
- 기능 단위로 커밋 (여러 파일이 하나의 기능이면 하나의 커밋)

### 앱 버전
- **Semantic Versioning** (MAJOR.MINOR.PATCH)
  - MAJOR: 아키텍처 변경, 호환성 깨짐
  - MINOR: 새 기능 추가
  - PATCH: 버그 수정, 작은 개선
- 현재 버전: **v1.3.5** (changelog/CHANGELOG.md 참조)
- 버전 변경 시 CHANGELOG.md 반드시 업데이트

## 4. 배포 규칙

### 로컬 PC (커맨드 핸들러)
- 모드: `python slack_bot.py --commands-only`
- 역할: 슬래시 커맨드(/wiki), 체크리스트 토글 핸들러
- 시작: `start_bot.bat` (venv 활성화 포함)
- 백그라운드 실행: WMI 방식 (Start-Process는 타임아웃 이슈)
  ```powershell
  $wmi = [wmiclass]"Win32_Process"
  $r = $wmi.Create("cmd.exe /c `"D:\Vibe Dev\Slack Bot\start_bot.bat`"", "D:\Vibe Dev\Slack Bot")
  ```
- 자동 시작: Windows 작업 스케줄러 `SlackQABot` (로그인 1분 후)

### Railway (스케줄러)
- 모드: `python slack_bot.py --scheduler-only`
- 역할: APScheduler로 정기 메시지 발송 (daily, weekly, monthly, mission)
- 배포: `git push origin main` → 자동 배포
- 환경변수: Railway Dashboard에서 관리

### 주의사항
- 로컬과 Railway는 `checklist_state.json`을 공유하지 않음
- 로컬 봇은 항상 `_reconstruct_checklist_state()`로 상태를 재구성함
- config.json 변경 시: 로컬 봇 재시작 + Railway 재배포 모두 필요

## 5. 코딩 규칙

- Python 3.11+ (Railway runtime.txt 기준)
- 인코딩: 모든 파일 UTF-8
- 로깅: `logging` 모듈 사용, `logger = logging.getLogger(__name__)`
- Slack API: `slack_sdk` + `slack_bolt` 라이브러리
- 환경변수: `python-dotenv`로 `.env` 로드
- 경로: `os.path.dirname(os.path.abspath(__file__))` 기준 (상대 경로 사용 금지)

## 6. 알려진 제약사항

| 제약 | 설명 | 우회 방법 |
|------|------|-----------|
| `groups:history` 미부여 | 비공개 채널 히스토리 읽기 불가 | 슬래시 커맨드 기반 입력으로 대체 (향후 구현) |
| `checklist_state.json` 비공유 | 로컬↔Railway 상태 분리 | `_reconstruct_checklist_state()` 폴백 |
| Anthropic API Key | 갑작스런 무효화 가능 | wiki_query.log에 에러 로그 기록 |
| Windows CP949 | print() 이모지 출력 불가 | `PYTHONIOENCODING=utf-8` 설정 |

## 7. 레거시 파일 정리 프로세스

프로젝트 루트에 더 이상 사용하지 않는 파일(테스트 스크립트, 디버그 로그, 임시 출력물 등)이
발견되면 아래 절차를 따릅니다.

### 절차

1. **파악** — 루트 또는 소스 디렉토리에 남은 잔여 파일을 목록화
2. **이동** — `_legacy/` 폴더를 생성(또는 기존 폴더 사용)하고, 잔여 파일을 이동
3. **메타 기록** — `_legacy/EXPIRY.md`에 이동일, 삭제 예정일(이동일 + 14일), 파일 목록 작성
4. **유예 기간** — **2주(14일)** 동안 해당 파일 참조 여부를 모니터링
5. **삭제** — 삭제 예정일 이후 사용 내역이 없으면 `_legacy/` 폴더 전체 삭제
6. **복원** — 유예 기간 중 필요한 파일 발견 시, 원래 위치로 복원 후 EXPIRY.md에서 제거

### 판단 기준 — "레거시"로 분류하는 파일

| 유형 | 예시 | 비고 |
|------|------|------|
| 1회성 디버그 로그 | `mcp_test.log`, `pip_install.log` | 진행 중인 봇 로그(`slack_bot.log`)는 제외 |
| 1회성 테스트 스크립트 | `wiki_test.py`, `check_models.py` | 정규 테스트 스위트에 포함된 것은 제외 |
| 더미 출력물 | `test_output.txt`, `mcp_out.txt` | |
| 이전 구조 잔여물 | 루트의 `CHANGELOG.md` (이미 `changelog/`에 이전) | |
| 타 프로젝트 잔재 | `Market Rank/` (별도 레포로 분리 완료) | |

### 주의사항

- `_legacy/`는 `.gitignore`에 추가하여 커밋하지 않음
- Railway 배포에 영향 없도록 소스 코드 파일은 반드시 참조 여부 확인 후 이동
- `mission_state.json` 등 런타임 상태 파일은 코드상 경로(`__file__` 기준)가 일치하는지 확인

---

## 8. 세션 시작 체크리스트

Claude가 슬랙 봇 작업 시작 시 확인할 사항:
1. `DEV_RULES.md` 읽기 (이 파일)
2. `WORK_LOG.md` 최근 3일 히스토리 확인
3. `changelog/CHANGELOG.md` 최신 버전 확인
4. 봇 프로세스 상태 확인 (`Get-Content slack_bot.pid`)
5. 최근 에러 로그 확인 (`logs/wiki_query.log` 마지막 10줄)

---

*이 문서는 개발 규칙 변경 시 버전을 올리며 업데이트합니다.*
*변경 이유는 WORK_LOG.md에 기록합니다.*
