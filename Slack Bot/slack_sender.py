"""
slack_sender.py - Slack Web API 래퍼

필요 권한:
  chat:write           - 메시지 전송 (필수)
  chat:write.customize - 봇 이름/이모지 커스터마이즈 (선택)
  channels:read        - 공개 채널 목록
  groups:read          - 비공개 채널 목록
  users:read           - 사용자 검색 (--find-user 용)
"""

import logging
from datetime import datetime

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)


class SlackSender:

    def __init__(self, token: str):
        self.client = WebClient(token=token)

    # ──────────────────────────────────────────────────────────
    # Block Kit 빌더 — 일반 (text / checklist)
    # ──────────────────────────────────────────────────────────

    def _timestamp_block(self) -> dict:
        return {
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  자동 알림",
            }],
        }

    def _build_text_blocks(self, message: str) -> list:
        return [
            {"type": "section", "text": {"type": "mrkdwn", "text": message}},
            self._timestamp_block(),
        ]

    def _build_checklist_blocks(self, title: str, items: list) -> list:
        """정적(비인터랙티브) 체크리스트 — ☐ 기호 사용"""
        lines = "\n".join(f"☐  {item}" for item in items)
        return [
            {"type": "header",  "text": {"type": "plain_text", "text": title, "emoji": True}},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": lines}},
            {"type": "divider"},
            self._timestamp_block(),
        ]

    # ──────────────────────────────────────────────────────────
    # Block Kit 빌더 — 인터랙티브 체크리스트
    # ──────────────────────────────────────────────────────────

    def _build_interactive_blocks(
        self,
        title: str,
        items: list,
        checked_values: list,
        sent_at: str = "",
    ) -> list:
        """
        Slack Block Kit 인터랙티브 체크리스트 블록 구성

        Parameters
        ----------
        title          : 헤더 제목 문자열
        items          : 체크리스트 항목 목록
                         예: [{"value": "item_0", "text": "작업명",
                                "mentions": ["U12345"]}, ...]
        checked_values : 현재 체크된 value 목록 (예: ["item_0", "item_2"])
        sent_at        : 최초 발송 시각 문자열 (context 블록 표시용)
        """
        total  = len(items)
        done   = len(checked_values)
        filled = int((done / total) * 10) if total > 0 else 0
        bar    = "▓" * filled + "░" * (10 - filled)

        now          = datetime.now()
        month_label  = f"{now.year}년 {now.month}월"
        status_text  = f"*{month_label}*  {bar}  {done}/{total} 완료"
        if done == total and total > 0:
            status_text += "  🎉 *모두 완료!*"

        # ── 체크박스 옵션 빌드 ──
        options: list         = []
        initial_options: list = []

        for item in items:
            val      = item["value"]
            text     = item["text"]
            mentions = item.get("mentions", [])

            mention_str = ""
            if mentions:
                mention_str = "  담당: " + " ".join(f"<@{uid}>" for uid in mentions)

            option = {
                "text":  {"type": "mrkdwn", "text": f"*{text}*{mention_str}"},
                "value": val,
            }
            options.append(option)
            if val in checked_values:
                initial_options.append(option)

        checklist_element = {
            "type":      "checkboxes",
            "action_id": "checklist_toggle",
            "options":   options,
        }
        if initial_options:
            checklist_element["initial_options"] = initial_options

        context_text = (
            f"⏰ 발송: {sent_at or now.strftime('%Y-%m-%d %H:%M')}  |  자동 알림"
        )

        return [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": title, "emoji": True},
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": status_text},
            },
            {"type": "divider"},
            {
                "type":     "actions",
                "block_id": "checklist_block",
                "elements": [checklist_element],
            },
            {"type": "divider"},
            {
                "type":     "context",
                "elements": [{"type": "mrkdwn", "text": context_text}],
            },
        ]

    # ──────────────────────────────────────────────────────────
    # 메시지 전송 — 일반
    # ──────────────────────────────────────────────────────────

    def send(self, channel: str, schedule: dict) -> bool:
        """
        schedule dict 기반으로 메시지 전송
        message_type: 'text' | 'checklist'
        """
        msg_type = schedule.get("message_type", "text")

        if msg_type == "checklist":
            blocks        = self._build_checklist_blocks(
                title = schedule.get("title", "📋 체크리스트"),
                items = schedule.get("items", []),
            )
            fallback_text = schedule.get("title", "체크리스트 알림")
        else:
            message       = schedule.get("message", "")
            blocks        = self._build_text_blocks(message)
            fallback_text = message[:100] if message else "알림"

        kwargs = {
            "channel": channel,
            "text":    fallback_text,
            "blocks":  blocks,
        }
        if "bot_name"  in schedule: kwargs["username"]   = schedule["bot_name"]
        if "bot_emoji" in schedule: kwargs["icon_emoji"] = schedule["bot_emoji"]

        try:
            response = self.client.chat_postMessage(**kwargs)
            logger.info(
                f"✅ 전송 완료 | [{schedule.get('name', '알림')}] → "
                f"채널: {channel} | ts: {response['ts']}"
            )
            return True
        except SlackApiError as e:
            logger.error(
                f"❌ 전송 실패 | [{schedule.get('name', '알림')}] "
                f"오류: {e.response['error']}"
            )
            return False

    # ──────────────────────────────────────────────────────────
    # 메시지 전송 — 인터랙티브 체크리스트
    # ──────────────────────────────────────────────────────────

    def send_interactive_checklist(self, channel: str, schedule: dict):
        """
        인터랙티브 체크리스트 메시지를 전송합니다.

        Returns
        -------
        str  : 전송된 메시지의 ts (타임스탬프). 실패 시 None.
        """
        sent_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        blocks  = self._build_interactive_blocks(
            title          = schedule.get("title", "📋 체크리스트"),
            items          = schedule.get("items", []),
            checked_values = [],
            sent_at        = sent_at,
        )

        kwargs = {
            "channel": channel,
            "text":    schedule.get("title", "월간 체크리스트"),
            "blocks":  blocks,
        }
        if "bot_name"  in schedule: kwargs["username"]   = schedule["bot_name"]
        if "bot_emoji" in schedule: kwargs["icon_emoji"] = schedule["bot_emoji"]

        try:
            res = self.client.chat_postMessage(**kwargs)
            ts  = res["ts"]
            logger.info(
                f"✅ 인터랙티브 체크리스트 전송 | "
                f"[{schedule.get('name', '알림')}] → 채널: {channel} | ts: {ts}"
            )
            return ts
        except SlackApiError as e:
            logger.error(
                f"❌ 인터랙티브 체크리스트 전송 실패 | "
                f"[{schedule.get('name', '알림')}] 오류: {e.response['error']}"
            )
            return None

    def update_interactive_checklist(
        self, channel: str, ts: str, state: dict
    ) -> bool:
        """
        체크 상태 변경 후 기존 메시지를 chat.update 로 갱신합니다.

        Parameters
        ----------
        channel : Slack 채널 ID
        ts      : 원본 메시지 타임스탬프
        state   : interaction_handler.update_checked() 의 반환값
        """
        blocks = self._build_interactive_blocks(
            title          = state.get("title", "📋 체크리스트"),
            items          = state["items"],
            checked_values = state.get("checked", []),
            sent_at        = state.get("sent_at", ""),
        )
        try:
            self.client.chat_update(
                channel = channel,
                ts      = ts,
                text    = state.get("title", "월간 체크리스트"),
                blocks  = blocks,
            )
            done  = len(state.get("checked", []))
            total = len(state["items"])
            logger.info(f"✅ 메시지 업데이트 완료 | ts: {ts}  체크={done}/{total}")
            return True
        except SlackApiError as e:
            logger.error(f"❌ 메시지 업데이트 실패: {e.response['error']}")
            return False

    # ──────────────────────────────────────────────────────────
    # 유틸리티
    # ──────────────────────────────────────────────────────────

    def test_connection(self) -> dict:
        """Slack 연결 상태 확인 (auth.test)"""
        try:
            res = self.client.auth_test()
            return {
                "success": True,
                "bot":     res.get("user",   "unknown"),
                "team":    res.get("team",   "unknown"),
                "bot_id":  res.get("bot_id", ""),
            }
        except SlackApiError as e:
            return {"success": False, "error": e.response["error"]}

    def list_channels(self) -> list:
        """
        접근 가능한 채널 목록 반환
        권한: channels:read, groups:read
        반환: [{"id": "C...", "name": "...", "is_private": bool}, ...]
        """
        channels = []
        cursor   = None
        try:
            while True:
                kwargs = {
                    "limit":            200,
                    "types":            "public_channel,private_channel",
                    "exclude_archived": True,
                }
                if cursor:
                    kwargs["cursor"] = cursor
                res = self.client.conversations_list(**kwargs)
                for ch in res.get("channels", []):
                    channels.append({
                        "id":         ch["id"],
                        "name":       ch["name"],
                        "is_private": ch.get("is_private", False),
                    })
                cursor = res.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
        except SlackApiError as e:
            logger.error(f"채널 목록 조회 실패: {e.response['error']}")
        return sorted(channels, key=lambda x: x["name"])

    def find_users(self, query: str) -> list:
        """
        사용자 검색 (이름/표시명 부분 일치)
        권한: users:read
        반환: [{"id": "U...", "real_name": "...", "name": "...", "display_name": "..."}, ...]
        """
        matches = []
        cursor  = None
        q       = query.lower()
        try:
            while True:
                kwargs = {"limit": 200}
                if cursor:
                    kwargs["cursor"] = cursor
                res = self.client.users_list(**kwargs)
                for u in res.get("members", []):
                    if u.get("deleted") or u.get("is_bot"):
                        continue
                    real = u.get("real_name", "")
                    name = u.get("name", "")
                    disp = u.get("profile", {}).get("display_name", "")
                    if q in real.lower() or q in name.lower() or q in disp.lower():
                        matches.append({
                            "id":           u["id"],
                            "real_name":    real,
                            "name":         name,
                            "display_name": disp,
                        })
                cursor = res.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
        except SlackApiError as e:
            logger.error(f"사용자 검색 실패: {e.response['error']}")
        return matches
