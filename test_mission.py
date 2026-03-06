import sys, json, os
sys.path.insert(0, r"D:\Vibe Dev\Slack Bot")
os.chdir(r"D:\Vibe Dev\Slack Bot")

# venv 패키지 경로 추가
sys.path.insert(0, r"D:\Vibe Dev\Slack Bot\venv\Lib\site-packages")

with open("config.json", encoding="utf-8") as f:
    cfg = json.load(f)

from slack_sender import SlackSender
from dotenv import load_dotenv
load_dotenv()

token = os.environ.get("SLACK_BOT_TOKEN")
print(f"Token found: {bool(token)}")

# 테스트 전송할 미션 ID 목록 (미션명이 확정된 채널만)
TARGET_IDS = sys.argv[1:] if len(sys.argv) > 1 else [
    "mission-ai-driven-qa",
    "mission-roundtable",
    "mission-tech-support",
]

schedules = {s["id"]: s for s in cfg["schedules"] if s["type"] == "mission"}
sender = SlackSender(token)

for mission_id in TARGET_IDS:
    schedule = schedules.get(mission_id)
    if not schedule:
        print(f"[SKIP] {mission_id} - config에 없음")
        continue
    print(f"\n▶ 전송 중: {schedule['id']} → {schedule['channel']}")
    print(f"   미션명: {schedule['mission']['name']}")
    sender.send_mission_reminder(schedule)
    print(f"   완료!")

print("\n전체 전송 완료!")
