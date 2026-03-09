"""
update_mission_progress.py — 기존 미션 메시지를 chat.update로 즉시 수정

사용법:
  cd "D:\Vibe Dev\Slack Bot\Slack Bot"
  ..\venv\Scripts\python update_mission_progress.py
"""

import json
import os
import sys

# 프로젝트 경로 설정
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from dotenv import load_dotenv
# .env 는 프로젝트 루트(Slack Bot/)에 위치
load_dotenv(os.path.join(BASE, "..", ".env"))

from slack_sender import SlackSender

# ── 업데이트 대상 ──────────────────────────────────────────
UPDATES = [
    {
        "mission_id": "mission-ai-driven-qa",
        "channel": "C0AJK510DN1",
        "ts": "1773022750.204399",
        "progress": 5,
    },
    {
        "mission_id": "mission-tech-support",
        "channel": "C0AKGRTU36U",
        "ts": "1773022754.438739",
        "progress": 80,
    },
    {
        "mission_id": "mission-roundtable",
        "channel": "C0AKGRX2BKJ",
        "ts": "1773022753.655949",
        "progress": 5,
    },
]


def main():
    token = os.getenv("SLACK_BOT_TOKEN")
    if not token:
        print("ERROR: SLACK_BOT_TOKEN not found in .env")
        sys.exit(1)

    # config.json 에서 미션 정보 로드
    cfg_path = os.path.join(BASE, "config.json")
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # schedule id → mission dict 매핑
    mission_map = {}
    for s in cfg.get("schedules", []):
        if s.get("type") == "mission":
            mission_map[s["id"]] = s.get("mission", {})

    sender = SlackSender(token)

    # mission_state.json 로드
    state_path = os.path.join(BASE, "mission_state.json")
    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)

    for upd in UPDATES:
        mid      = upd["mission_id"]
        channel  = upd["channel"]
        ts       = upd["ts"]
        progress = upd["progress"]

        mission = mission_map.get(mid, {})
        if not mission:
            print(f"SKIP: {mid} not found in config.json")
            continue

        # 블록 빌드 (새 진행율 + [M-XX] 접두사)
        blocks = sender._build_mission_blocks(mission, progress)

        # fallback text
        mn   = mission.get("mission_number", "")
        name = mission.get("name", "")
        num  = f"[{mn}] " if mn else ""
        fallback = (
            f"\ud83d\udcca {num}\ubbf8\uc158 \uc9c4\ud589 \ud604\ud669 (\ubbf8\uc120\uc815)"
            if not name or name.strip() in ("\ubbf8\uc815",)
            else f"{num}{name}"
        )

        try:
            res = sender.client.chat_update(
                channel=channel,
                ts=ts,
                text=fallback,
                blocks=blocks,
            )
            print(f"OK: [{mn}] {name} -> {progress}% (ts: {ts})")

            # mission_state.json 업데이트
            state[mid] = {
                "channel": channel,
                "mission_number": mn,
                "last_ts": ts,
                "progress": progress,
            }

        except Exception as e:
            print(f"FAIL: [{mn}] {name} -> {e}")

    # 상태 저장
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(f"\nmission_state.json updated.")


if __name__ == "__main__":
    main()
