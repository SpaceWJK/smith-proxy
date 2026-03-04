#!/usr/bin/env python3
"""
slack_bot.py - Slack 알림 봇 메인 진입점

사용법:
  python slack_bot.py                           # 봇 실행 (스케줄 + 인터랙션)
  python slack_bot.py --test     CHANNEL        # 테스트 메시지 전송
  python slack_bot.py --channels                # 접근 가능한 채널 목록 출력
  python slack_bot.py --send     CHANNEL "MSG"  # 즉시 메시지 전송
  python slack_bot.py --find-user NAME          # 사용자 ID 검색 (mention 설정용)

환경변수 (.env):
  SLACK_BOT_TOKEN = xoxb-...   (Bot Token — 메시지 전송)
  SLACK_APP_TOKEN = xapp-...   (App-Level Token — Socket Mode 인터랙션)
"""

import os
import sys
import logging
import argparse

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

import interaction_handler as ih
from slack_sender import SlackSender
from scheduler    import NotificationScheduler

# ── 로그 설정 ──────────────────────────────────────────────────
logging.basicConfig(
    level    = logging.INFO,
    format   = "%(asctime)s [%(levelname)s] %(message)s",
    datefmt  = "%Y-%m-%d %H:%M:%S",
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("slack_bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ── Bolt App 생성 + 액션 핸들러 등록 ──────────────────────────

def create_bolt_app(bot_token: str, slack_sender: SlackSender) -> App:
    """
    Slack Bolt App 을 생성하고 인터랙션 핸들러를 등록합니다.

    Parameters
    ----------
    bot_token    : Bot Token (xoxb-...)
    slack_sender : SlackSender 인스턴스 (메시지 업데이트에 사용)
    """
    app = App(token=bot_token)

    @app.action("checklist_toggle")
    def handle_checklist_toggle(ack, body):
        """
        사용자가 체크리스트를 체크/언체크할 때 호출됩니다.
        - ack() 로 Slack 에 즉시 응답 (3초 이내 필수)
        - 상태 파일 갱신 후 chat.update 로 메시지 동기화
        """
        ack()   # Slack 에 즉시 응답

        channel  = body["channel"]["id"]
        ts       = body["message"]["ts"]
        selected = body["actions"][0].get("selected_options", [])
        checked  = [opt["value"] for opt in selected]

        logger.info(
            f"체크리스트 토글 | 채널: {channel} | ts: {ts} | "
            f"체크된 항목: {checked}"
        )

        # 상태 갱신
        state = ih.update_checked(channel, ts, checked)
        if state is None:
            logger.warning("체크리스트 상태를 찾을 수 없습니다. (state.json 미등록)")
            return

        # 메시지 업데이트
        slack_sender.update_interactive_checklist(channel, ts, state)

    return app


# ── CLI 명령 핸들러 ────────────────────────────────────────────

def cmd_test(sender: SlackSender, channel: str):
    """지정 채널로 테스트 메시지 전송"""
    schedule = {
        "name":         "연결 테스트",
        "message_type": "checklist",
        "title":        "🧪 슬랙 봇 연결 테스트",
        "items":        [
            "Slack Bot Token 연결 확인",
            "채널 메시지 전송 확인",
            "Block Kit 렌더링 확인",
        ],
        "bot_name":  "알림 봇 테스트",
        "bot_emoji": ":bell:",
    }
    logger.info(f"테스트 메시지 전송 → 채널: {channel}")
    ok = sender.send(channel=channel, schedule=schedule)
    if ok:
        print("✅ 테스트 성공! Slack 채널을 확인하세요.")
    else:
        print("❌ 테스트 실패. 토큰과 채널 ID를 다시 확인하세요.")


def cmd_channels(sender: SlackSender):
    """접근 가능한 채널 목록 출력"""
    print("\n채널 목록 조회 중...")
    channels = sender.list_channels()
    if not channels:
        print("채널을 찾을 수 없습니다. (channels:read / groups:read 권한 확인)")
        return
    sep = "─" * 58
    print(f"\n{sep}")
    print(f"  총 {len(channels)}개 채널")
    print(sep)
    for ch in channels:
        lock = "🔒" if ch["is_private"] else "🔓"
        print(f"  {lock}  #{ch['name']:<30}  ID: {ch['id']}")
    print(sep)
    print("  → config.json 의 'channel' 필드에 ID 값을 넣으세요\n")


def cmd_send(sender: SlackSender, channel: str, message: str):
    """즉시 단일 메시지 전송"""
    ok = sender.send(
        channel  = channel,
        schedule = {
            "name":         "즉시 전송",
            "message_type": "text",
            "message":      message,
            "bot_name":     "알림 봇",
            "bot_emoji":    ":loudspeaker:",
        },
    )
    print(f"{'✅ 메시지 전송 완료' if ok else '❌ 전송 실패'} → {channel}")


def cmd_find_user(sender: SlackSender, query: str):
    """
    사용자 ID 검색 — config.json 의 mentions 필드에 넣을 U... ID 확인용
    권한: users:read
    """
    print(f"\n'{query}' 사용자 검색 중 (users:read 권한 필요)...")
    users = sender.find_users(query)
    if not users:
        print(f"  '{query}' 에 해당하는 사용자를 찾을 수 없습니다.")
        print("  (표시명·사용자명·실명 모두 일치하지 않음)")
        return
    sep = "─" * 76
    print(f"\n{sep}")
    print(f"  총 {len(users)}명 검색됨")
    print(sep)
    for u in users:
        print(
            f"  ID: {u['id']:<12}  이름: {u['real_name']:<16}  "
            f"사용자명: {u['name']:<20}  표시명: {u['display_name']}"
        )
    print(sep)
    print("  → config.json 의 'mentions' 필드에 ID(U...) 값을 넣으세요\n")


def cmd_run(sender: SlackSender, bolt_app: App, app_token: str):
    """
    스케줄러(BackgroundScheduler) 시작 후 Socket Mode 핸들러를 실행합니다.
    - 스케줄러는 백그라운드 스레드에서 실행 (논블로킹)
    - Socket Mode 핸들러는 메인 스레드를 점유 (블로킹)
    """
    # 스케줄러 백그라운드 시작
    scheduler = NotificationScheduler(sender, config_path="config.json")
    scheduler.start()   # 논블로킹

    # Socket Mode 핸들러 (블로킹 — 메인 스레드)
    logger.info("🔌 Socket Mode 연결 중... (종료: Ctrl+C)")
    handler = SocketModeHandler(bolt_app, app_token)
    try:
        handler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("봇이 정상 종료되었습니다.")
        scheduler.shutdown()


# ── 메인 ──────────────────────────────────────────────────────

def main():
    load_dotenv()

    # ── 토큰 확인 ──
    bot_token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    app_token = os.getenv("SLACK_APP_TOKEN", "").strip()

    if not bot_token or bot_token.startswith("xoxb-your"):
        logger.error("SLACK_BOT_TOKEN 이 설정되지 않았습니다.")
        logger.error(".env 파일에서 SLACK_BOT_TOKEN=xoxb-... 를 설정하세요.")
        logger.error("Slack API > OAuth & Permissions > Bot User OAuth Token 에서 복사하세요.")
        sys.exit(1)

    # ── 클라이언트 초기화 ──
    sender   = SlackSender(bot_token)
    bolt_app = create_bolt_app(bot_token, sender)

    # ── 연결 확인 ──
    result = sender.test_connection()
    if not result["success"]:
        logger.error(f"Slack 연결 실패: {result.get('error')}")
        logger.error("Bot Token(xoxb-)이 올바른지, 앱이 워크스페이스에 설치되었는지 확인하세요.")
        sys.exit(1)

    logger.info(
        f"✅ Slack 연결 성공  |  봇: @{result['bot']}  |  "
        f"워크스페이스: {result['team']}"
    )

    # ── CLI 인자 파싱 ──
    parser = argparse.ArgumentParser(
        description     = "Slack 알림 봇",
        formatter_class = argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--test",      metavar="CHANNEL",
        help="지정 채널로 테스트 메시지 전송 (채널 ID)",
    )
    parser.add_argument(
        "--channels",  action="store_true",
        help="접근 가능한 채널 목록 출력 (채널 ID 확인용)",
    )
    parser.add_argument(
        "--send",      nargs=2, metavar=("CHANNEL", "MESSAGE"),
        help='즉시 메시지 전송:  --send C0XXX "메시지 내용"',
    )
    parser.add_argument(
        "--find-user", metavar="NAME",
        help="사용자 ID 검색 (config.json mentions 설정용)\n예: --find-user 이동현",
    )
    args = parser.parse_args()

    # ── 명령 분기 ──
    if args.test:
        cmd_test(sender, args.test)

    elif args.channels:
        cmd_channels(sender)

    elif args.send:
        cmd_send(sender, args.send[0], args.send[1])

    elif args.find_user:
        cmd_find_user(sender, args.find_user)

    else:
        # 봇 실행 — Socket Mode 필요
        if not app_token or not app_token.startswith("xapp-"):
            logger.error("Socket Mode 실행에는 SLACK_APP_TOKEN(xapp-...) 이 필요합니다.")
            logger.error(".env 파일에서 SLACK_APP_TOKEN 을 설정하세요.")
            logger.error("(채널 목록/테스트만 사용할 경우: --channels / --test 옵션 사용)")
            sys.exit(1)
        cmd_run(sender, bolt_app, app_token)


if __name__ == "__main__":
    main()
