#!/usr/bin/env python3
"""
repair_checklist.py - 깨진 체크리스트 메시지 복구 스크립트

groups:history 권한이 없어 conversations.history 를 사용할 수 없으므로,
로그에서 마지막 체크 상태를 추출하여 config.json 의 올바른 그룹 구조로
chat.update 를 직접 호출합니다.

사용법: python repair_checklist.py
"""

import sys, os, json, re, time

# ── 경로 설정 ────────────────────────────────────────────────
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BOT_DIR)
os.chdir(BOT_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(BOT_DIR), ".env"))

from slack_sdk import WebClient
from slack_sender import SlackSender

# ── Slack 클라이언트 ─────────────────────────────────────────
BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
client = WebClient(token=BOT_TOKEN)
sender = SlackSender(BOT_TOKEN)

with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)


def parse_checked_from_log(log_path: str, target_ts: str) -> list:
    """
    로그 파일에서 특정 ts 의 마지막 체크 상태를 추출합니다.
    로그 형식 예시:
      체크리스트 토글 | 채널: C07PHCE4RCM | ts: 1773018000.679019 | 체크된 항목: ['g1_epic7', ...]
    """
    last_checked = []
    pattern = re.compile(
        r"체크리스트 토글.*ts:\s*" + re.escape(target_ts) + r".*체크된 항목:\s*\[([^\]]*)\]"
    )
    for log_file in log_path if isinstance(log_path, list) else [log_path]:
        if not os.path.exists(log_file):
            continue
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pattern.search(line)
                if m:
                    raw = m.group(1)
                    items = [s.strip().strip("'\"") for s in raw.split(",") if s.strip()]
                    last_checked = items
    return last_checked


def find_schedule_by_id(schedule_id: str) -> dict:
    """config.json에서 schedule id로 검색"""
    for s in config.get("schedules", []):
        if s.get("id") == schedule_id:
            return s
    return None


def find_schedule_by_title(title: str) -> dict:
    """config.json에서 타이틀로 스케줄을 찾음"""
    def normalize(t):
        t = re.sub(r':[a-z_]+:', '', t)
        t = re.sub(r'[^\w\s\uAC00-\uD7AF\[\]\(\)]', '', t)
        return t.strip()

    target = normalize(title)
    for s in config.get("schedules", []):
        if normalize(s.get("title", "")) == target:
            return s
    return None


def repair_direct(channel: str, ts: str, schedule_id: str, checked_values: list, sent_at: str):
    """
    groups:history 없이 직접 chat.update 로 메시지를 복구합니다.

    Parameters
    ----------
    channel        : Slack 채널 ID
    ts             : 메시지 타임스탬프
    schedule_id    : config.json 의 스케줄 ID
    checked_values : 현재 체크된 value 목록 (로그에서 추출)
    sent_at        : 발송 시각 문자열 (YYYY-MM-DD HH:MM)
    """
    print(f"\n{'='*60}")
    print(f"[복구] {schedule_id}")
    print(f"  채널: {channel} | ts: {ts}")

    schedule = find_schedule_by_id(schedule_id)
    if not schedule:
        print(f"  X config.json 에서 '{schedule_id}' 를 찾을 수 없음")
        return False

    print(f"  제목: {schedule['title']}")
    print(f"  체크된 항목: {len(checked_values)}개 -> {checked_values}")
    print(f"  발송 시각: {sent_at}")

    # 올바른 블록 재빌드
    dyn_action_id = f"checklist_toggle_{int(time.time() * 1000)}"

    new_blocks = sender._build_interactive_blocks(
        title=schedule["title"],
        items=schedule["items"],
        checked_values=checked_values,
        sent_at=sent_at,
        missed_section=None,   # 누락 섹션은 제외 (원본 보존 불가)
        action_id=dyn_action_id,
        period_label=None,
    )

    # 메시지 업데이트
    try:
        client.chat_update(
            channel=channel,
            ts=ts,
            text=schedule["title"],
            blocks=new_blocks,
        )
        print(f"  >> 복구 완료!")
        return True
    except Exception as e:
        print(f"  X 업데이트 실패: {e}")
        return False


# ── 메인 실행 ────────────────────────────────────────────────
if __name__ == "__main__":
    CHANNEL = "C07PHCE4RCM"

    print("Slack checklist repair script")
    print("=" * 60)

    # ── 복구 대상 1: 일일 QA 체크리스트 (ts: 1773018000.679019) ───
    # 로그에서 마지막 체크 상태 추출
    LOG_FILES = [
        os.path.join(os.path.dirname(BOT_DIR), "slack_bot.log"),   # 구 경로 로그
        os.path.join(BOT_DIR, "slack_bot.log"),                     # 신 경로 로그
    ]

    TARGET_TS = "1773018000.679019"

    checked = parse_checked_from_log(LOG_FILES, TARGET_TS)
    if checked:
        print(f"\nLog last checked state for ts={TARGET_TS}: {checked}")
    else:
        print(f"\nWARNING: No checked state found in logs for ts={TARGET_TS}")
        print("Using empty checked list (all items unchecked)")

    repair_direct(
        channel=CHANNEL,
        ts=TARGET_TS,
        schedule_id="daily-qa-checklist",
        checked_values=checked,
        sent_at="2026-03-09 10:00",  # Railway 스케줄 발송 시각
    )

    print(f"\n{'='*60}")
    print("Done!")
