"""
slack_sender.py - Slack Web API 래퍼

필요 권한:
  chat:write           - 메시지 전송 (필수)
  chat:write.customize - 봇 이름/이모지 커스터마이즈 (선택)
  channels:read        - 공개 채널 목록
  groups:read          - 비공개 채널 목록
  users:read           - 사용자 검색 (--find-user 용)
"""

import json
import logging
import os
import time
from datetime import datetime

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)


class SlackSender:

    def __init__(self, token: str):
        self.client = WebClient(token=token)

        # config.json 의 user_map 로드 (UID → 표시 이름)
        self.user_map: dict = {}
        try:
            _base     = os.path.dirname(os.path.abspath(__file__))
            _cfg_path = os.path.join(_base, "config.json")
            with open(_cfg_path, "r", encoding="utf-8") as _f:
                self.user_map = json.load(_f).get("user_map", {})
        except Exception as e:
            logger.warning(f"user_map 로드 실패 (무시): {e}")

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

    def _count_tasks(self, items: list, checked_set: set):
        """
        그룹/단독 항목 기준으로 (전체 태스크 수, 완료 태스크 수)를 반환합니다.

        - group 항목: 모든 sub_items 가 checked_set 에 있어야 완료
        - 단독 항목: value 가 checked_set 에 있으면 완료
        """
        total, done = 0, 0
        for item in items:
            total += 1
            if item.get("type") == "group":
                sub_values = [s["value"] for s in item.get("sub_items", [])]
                if sub_values and all(v in checked_set for v in sub_values):
                    done += 1
            else:
                if item.get("value", "") in checked_set:
                    done += 1
        return total, done

    def _build_missed_section_blocks(self, missed_items: list, action_id: str = "checklist_toggle") -> list:
        """
        누락 체크리스트 섹션 블록 생성.

        Parameters
        ----------
        missed_items : get_missed_items() 반환값
            [{"label": "[일일] 03/04(화)", "items": [{"value":"missed_0_x","text":"...","mentions":[...]}]}, ...]

        Returns: Slack Block Kit 블록 목록
            - block_id="missed_divider"  → 구분자 (sentinel: 로컬 봇이 섹션 위치 식별용)
            - block_id="missed_header"   → "⚠️ 전일 누락 항목" 헤더
            - block_id=f"missed_grp_{i}" → 그룹 레이블 (스케줄별)
            - block_id=f"missed_{i}"     → 해당 그룹의 체크박스
        """
        blocks = [
            {"type": "divider", "block_id": "missed_divider"},
            {
                "type":     "section",
                "block_id": "missed_header",
                "text": {"type": "mrkdwn", "text": "⚠️ *전일 누락 항목*"},
            },
        ]

        for i, group in enumerate(missed_items):
            label      = group.get("label", "")
            group_items = group.get("items", [])

            # 그룹 레이블 (예: 📋 [일일] 03/04(화))
            blocks.append({
                "type":     "section",
                "block_id": f"missed_grp_{i}",
                "text": {"type": "mrkdwn", "text": f"*📋 {label}*"},
            })

            # 체크박스 옵션 빌드
            options: list = []
            for item in group_items:
                names = [self.user_map.get(uid, "") for uid in item.get("mentions", [])]
                names = [n for n in names if n]
                mention_str = ("  담당: " + ", ".join(names)) if names else ""
                options.append({
                    "text":  {"type": "mrkdwn", "text": f"*{item['text']}*{mention_str}"},
                    "value": item["value"],
                })

            if options:
                blocks.append({
                    "type":     "actions",
                    "block_id": f"missed_{i}",
                    "elements": [{
                        "type":      "checkboxes",
                        "action_id": action_id,
                        "options":   options,
                        # initial_options 없음 (초기 전송 시 모두 미완료)
                    }],
                })

        return blocks

    def _rebuild_missed_blocks_checked(
        self, raw_blocks: list, checked_set: set, action_id: str = "checklist_toggle"
    ) -> list:
        """
        메시지에서 추출한 누락 섹션 raw blocks 의 initial_options 를
        현재 checked_set 기준으로 갱신합니다.

        Parameters
        ----------
        raw_blocks  : 현재 메시지에서 추출한 누락 섹션 블록 목록
        checked_set : 현재 전체 체크 상태 (일반 + missed_ 값 모두 포함)

        Returns: initial_options 갱신된 블록 목록
        """
        result: list = []
        for block in raw_blocks:
            if block.get("type") != "actions":
                result.append(block)
                continue

            new_elements: list = []
            for elem in block.get("elements", []):
                if elem.get("type") != "checkboxes":
                    new_elements.append(elem)
                    continue

                options = elem.get("options", [])
                initial = [opt for opt in options if opt["value"] in checked_set]
                # initial_options, action_id 제거 후 재설정 (action_id 는 동적으로 교체)
                new_elem = {k: v for k, v in elem.items() if k not in ("initial_options", "action_id")}
                new_elem["action_id"] = action_id
                if initial:
                    new_elem["initial_options"] = initial
                new_elements.append(new_elem)

            result.append({**block, "elements": new_elements})
        return result

    def _build_interactive_blocks(
        self,
        title: str,
        items: list,
        checked_values: list,
        sent_at: str = "",
        missed_section: list = None,
        action_id: str = "checklist_toggle",
    ) -> list:
        """
        Slack Block Kit 인터랙티브 체크리스트 블록 구성

        Parameters
        ----------
        title          : 헤더 제목 문자열
        items          : 체크리스트 항목 목록
                         단독: {"value": "v", "text": "작업명", "mentions": [...]}
                         그룹: {"type": "group", "group_name": "...",
                                "sub_items": [{"value": ..., "text": ..., "mentions": ...}, ...]}
        checked_values : 현재 체크된 value 목록
        sent_at        : 최초 발송 시각 문자열 (context 블록 표시용)
        """
        checked_set         = set(checked_values)
        total, done         = self._count_tasks(items, checked_set)
        filled              = int((done / total) * 10) if total > 0 else 0
        bar                 = "▓" * filled + "░" * (10 - filled)

        now          = datetime.now()
        month_label  = f"{now.year}년 {now.month}월"
        status_text  = f"*{month_label}*  {bar}  {done}/{total} 완료"
        if done == total and total > 0:
            status_text += "  🎉 *모두 완료!*"

        context_text = f"⏰ 발송: {sent_at or now.strftime('%Y-%m-%d %H:%M')}  |  자동 알림"

        # ── 담당자 멘션 수집 ────────────────────────────────────────────────
        # 체크박스 옵션 텍스트 내 <@U...> 는 시각적 표시만 되고 Slack 알림 미발송.
        # section/context 블록의 <@U...> 만 실제 멘션 알림을 트리거합니다.
        unique_mentions: list = []
        seen_uids: set        = set()
        for item in items:
            src_list = item.get("sub_items", []) if item.get("type") == "group" else [item]
            for src in src_list:
                for uid in src.get("mentions", []):
                    if uid not in seen_uids:
                        seen_uids.add(uid)
                        unique_mentions.append(f"<@{uid}>")

        # ── 헤더 + 진행 상태 블록 ────────────────────────────────────────────
        blocks: list = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": title, "emoji": True},
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": status_text},
            },
        ]

        # 담당자 멘션 블록 — chat.update 시 재알림 없으므로 중복 걱정 불필요
        if unique_mentions:
            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": "📌 담당자  " + "  ".join(unique_mentions),
                }],
            })

        blocks.append({"type": "divider"})

        # ── 항목별 블록 빌드 ─────────────────────────────────────────────────
        for i, item in enumerate(items):
            if item.get("type") == "group":
                group_name = item.get("group_name", f"그룹 {i + 1}")
                sub_items  = item.get("sub_items", [])

                # 그룹 제목 섹션
                blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*{group_name}*"},
                })

                # 서브 아이템 → 체크박스 옵션 목록
                options: list         = []
                initial_options: list = []
                for sub in sub_items:
                    val      = sub["value"]
                    text     = sub["text"]
                    names    = [self.user_map.get(uid, "") for uid in sub.get("mentions", [])]
                    names    = [n for n in names if n]
                    mention_str = ("  담당: " + ", ".join(names)) if names else ""

                    opt = {
                        "text":  {"type": "mrkdwn", "text": f"*{text}*{mention_str}"},
                        "value": val,
                    }
                    options.append(opt)
                    if val in checked_set:
                        initial_options.append(opt)

                checkbox_elem = {
                    "type":      "checkboxes",
                    "action_id": action_id,
                    "options":   options,
                }
                if initial_options:
                    checkbox_elem["initial_options"] = initial_options

                blocks.append({
                    "type":     "actions",
                    "block_id": f"chk_grp_{i}",
                    "elements": [checkbox_elem],
                })

            else:
                # 단독 항목
                val      = item["value"]
                text     = item["text"]
                names    = [self.user_map.get(uid, "") for uid in item.get("mentions", [])]
                names    = [n for n in names if n]
                mention_str = ("  담당: " + ", ".join(names)) if names else ""

                opt = {
                    "text":  {"type": "mrkdwn", "text": f"*{text}*{mention_str}"},
                    "value": val,
                }
                checkbox_elem = {
                    "type":      "checkboxes",
                    "action_id": action_id,
                    "options":   [opt],
                }
                if val in checked_set:
                    checkbox_elem["initial_options"] = [opt]

                blocks.append({
                    "type":     "actions",
                    "block_id": f"chk_solo_{i}",
                    "elements": [checkbox_elem],
                })

        # ── 전일 누락 섹션 삽입 (있을 때만) ────────────────────────────────
        if missed_section:
            blocks.extend(missed_section)

        blocks.extend([
            {"type": "divider"},
            {
                "type":     "context",
                "elements": [{"type": "mrkdwn", "text": context_text}],
            },
        ])

        return blocks

    # ──────────────────────────────────────────────────────────
    # 템플릿 변수 치환
    # ──────────────────────────────────────────────────────────

    def _resolve_templates(self, text: str) -> str:
        """
        메시지 문자열의 템플릿 변수를 현재 날짜 정보로 치환합니다.

        지원 변수
        ---------
        {date}  →  MM.DD(요일)  예: 03.05(목)
        """
        now    = datetime.now()
        day_kr = ["월", "화", "수", "목", "금", "토", "일"][now.weekday()]
        return text.replace("{date}", now.strftime("%m.%d") + f"({day_kr})")

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
            message       = self._resolve_templates(schedule.get("message", ""))
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

    def send_interactive_checklist(
        self, channel: str, schedule: dict, missed_items: list = None
    ):
        """
        인터랙티브 체크리스트 메시지를 전송합니다.

        Parameters
        ----------
        missed_items : 전일 누락 항목 목록 (missed_tracker.get_missed_items() 반환값)
                       없거나 빈 리스트면 누락 섹션 미표시.

        Returns
        -------
        str  : 전송된 메시지의 ts (타임스탬프). 실패 시 None.
        """
        sent_at = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 누락 섹션 블록 빌드 (있을 때만)
        missed_section = (
            self._build_missed_section_blocks(missed_items)
            if missed_items else None
        )

        blocks  = self._build_interactive_blocks(
            title          = schedule.get("title", "📋 체크리스트"),
            items          = schedule.get("items", []),
            checked_values = [],
            sent_at        = sent_at,
            missed_section = missed_section,
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
        self, channel: str, ts: str, state: dict, missed_section: list = None
    ) -> bool:
        """
        체크 상태 변경 후 기존 메시지를 chat.update 로 갱신합니다.

        Parameters
        ----------
        channel        : Slack 채널 ID
        ts             : 원본 메시지 타임스탬프
        state          : interaction_handler.update_checked() 의 반환값
        missed_section : 현재 메시지에서 추출한 전일 누락 섹션 raw blocks
                         (None 이면 누락 섹션 미포함)
        """
        # ── 동적 action_id 생성 ─────────────────────────────────────────────────
        # chat.update 마다 action_id 를 바꾸면 Slack 클라이언트가 해당 체크박스를
        # "새 컴포넌트"로 인식해 initial_options 기준으로 강제 재렌더링합니다.
        # → A 가 체크한 뒤 B 의 화면도 즉시 갱신되는 핵심 메커니즘.
        dyn_action_id = f"checklist_toggle_{int(time.time() * 1000)}"

        rebuilt_missed = (
            self._rebuild_missed_blocks_checked(
                missed_section, set(state.get("checked", [])), dyn_action_id
            )
            if missed_section else None
        )

        blocks = self._build_interactive_blocks(
            title          = state.get("title", "📋 체크리스트"),
            items          = state["items"],
            checked_values = state.get("checked", []),
            sent_at        = state.get("sent_at", ""),
            missed_section = rebuilt_missed,
            action_id      = dyn_action_id,
        )
        try:
            self.client.chat_update(
                channel = channel,
                ts      = ts,
                text    = state.get("title", "월간 체크리스트"),
                blocks  = blocks,
            )
            logger.info(f"✅ 메시지 업데이트 완료 | ts: {ts}  checked={len(state.get('checked', []))}개")
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
