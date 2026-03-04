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
import re
import sys
import logging
import argparse

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

import interaction_handler as ih
from slack_sender import SlackSender
from scheduler    import NotificationScheduler
import wiki_client as wc

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


# ── /wiki (페이지 조회) 헬퍼 ──────────────────────────────────────────────────

def _wiki_help(respond):
    """도움말"""
    respond(text=(
        "*📄 /wiki 페이지 조회 도움말*\n\n"
        "```\n"
        "/wiki [페이지 제목]                       페이지 내용 전체 조회\n"
        "/wiki [상위] > [하위] > [페이지]          계층 경로로 페이지 조회\n"
        "/wiki [페이지 제목] | [질문]              페이지 내용 기반 AI 답변 (Claude)\n"
        "/wiki [상위] > [페이지] | [질문]          경로 지정 + AI 답변\n"
        "/wiki search [검색어]                     키워드로 페이지 목록 검색\n"
        "/wiki help                                이 도움말\n"
        "```\n\n"
        "예시:\n"
        "• `/wiki Game Service 1`\n"
        "• `/wiki 프로젝트 현황 > Game Service 1`\n"
        "• `/wiki Game Service 1 | QA 일정 알려줘`\n"
        "• `/wiki 프로젝트 현황 > Game Service 1 | QA 일정이 어떻게 되나요?`\n"
        "• `/wiki search QA 일정`\n\n"
        "💡 `>` 는 Confluence 페이지 계층 구조를 나타냅니다.\n"
        "동일 제목의 페이지가 여러 곳에 있을 때 조상 경로로 구분하세요."
    ))


def _wiki_fetch_page(client, page_part: str):
    """
    '>' 구분자 유무에 따라 적합한 방식으로 Confluence 페이지를 조회합니다.

    - '>' 포함 → 조상 기반 CQL 검색 (get_page_by_path)
    - '>' 없음  → 제목 직접 검색   (get_page_by_title)

    Returns: (page_dict | None, error_str | None)
    """
    if ">" in page_part:
        segments   = [s.strip() for s in page_part.split(">")]
        leaf_title = segments[-1]
        ancestors  = segments[:-1]
        return client.get_page_by_path(ancestors, leaf_title)
    return client.get_page_by_title(page_part)


def _wiki_get_page(client, page_part: str, respond):
    """경로/페이지 제목으로 내용 조회 후 Slack 에 표시"""
    page, err = _wiki_fetch_page(client, page_part)
    if err:
        respond(text=f"❌ 페이지 조회 실패\n```\n{err}\n```")
        return

    text      = page["text"]
    MAX_LEN   = 2800
    truncated = len(text) > MAX_LEN
    if truncated:
        text = text[:MAX_LEN]

    msg = (
        f"*📄 {page['title']}*\n"
        f"🔗 <{page['url']}|전체 페이지 열기>\n\n"
        f"```\n{text}\n```"
    )
    if truncated:
        msg += "\n\n⚠️ 내용이 길어 일부만 표시됩니다. 전체 내용은 페이지 링크를 확인하세요."
    respond(text=msg)


def _wiki_ask_claude(page_title: str, page_text: str, page_url: str, question: str, respond):
    """
    Claude API 를 사용해 페이지 내용 기반으로 질문에 답변.
    환경변수 ANTHROPIC_API_KEY 필요.
    """
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        respond(
            text=(
                "❌ `ANTHROPIC_API_KEY` 환경변수가 설정되지 않았습니다.\n"
                "Railway 환경변수에 Anthropic API 키를 추가하세요."
            )
        )
        return

    # 페이지 내용이 너무 길면 앞부분만 사용 (토큰 절약)
    MAX_PAGE_CHARS = 20000
    truncated = len(page_text) > MAX_PAGE_CHARS
    content   = page_text[:MAX_PAGE_CHARS] if truncated else page_text
    trunc_note = "\n*(내용이 길어 일부만 포함됨)*\n" if truncated else ""

    prompt = (
        f"다음은 Confluence 페이지 '{page_title}'의 내용입니다:\n\n"
        f"{content}{trunc_note}\n\n"
        f"위 내용을 바탕으로 아래 질문에 한국어로 간결하게 답해주세요.\n"
        f"페이지에 관련 내용이 없으면 '해당 내용을 페이지에서 찾을 수 없습니다'라고 답하세요.\n\n"
        f"질문: {question}"
    )

    try:
        client_ai = anthropic.Anthropic(api_key=api_key)
        message   = client_ai.messages.create(
            model      = "claude-3-5-haiku-20241022",  # 빠르고 저렴한 모델
            max_tokens = 1024,
            messages   = [{"role": "user", "content": prompt}],
        )
        answer = message.content[0].text
    except Exception as e:
        logger.error(f"[wiki] Claude API 오류: {e}")
        respond(text=f"❌ Claude API 오류\n```\n{e}\n```")
        return

    respond(text=(
        f"*📄 {page_title}* — AI 답변\n"
        f"🔗 <{page_url}|원본 페이지>\n\n"
        f"*Q: {question}*\n\n"
        f"{answer}"
    ))


def _wiki_search_pages(client, query: str, respond):
    """키워드로 페이지 검색 결과 표시"""
    pages, err = client.search_pages(query)
    if err:
        respond(text=f"❌ 검색 실패\n```\n{err}\n```")
        return
    if not pages:
        respond(text=f"ℹ️ `{query}` 에 해당하는 페이지가 없습니다.")
        return

    lines = [f"*🔍 '{query}' 검색 결과 ({len(pages)}건)*\n"]
    for p in pages:
        lines.append(f"• *{p['title']}*  →  `/wiki {p['title']}`")
    respond(text="\n".join(lines))


# ── /calendar (일정 등록) 헬퍼 ────────────────────────────────────────────────

# 캘린더 유형 키워드 → 환경변수 키 매핑 (공백 제거 후 매핑)
_CALENDAR_ALIASES = {
    # 프로젝트 일정
    "플잭":         "CONFLUENCE_CALENDAR_PROJECT",
    "프로젝트":     "CONFLUENCE_CALENDAR_PROJECT",
    "프로잭트":     "CONFLUENCE_CALENDAR_PROJECT",   # 흔한 오타
    "프로젝트일정": "CONFLUENCE_CALENDAR_PROJECT",
    "프로잭트일정": "CONFLUENCE_CALENDAR_PROJECT",
    "project":      "CONFLUENCE_CALENDAR_PROJECT",
    # 개인/팀 일정
    "개인":         "CONFLUENCE_CALENDAR_PERSONAL",
    "팀":           "CONFLUENCE_CALENDAR_PERSONAL",
    "개인일정":     "CONFLUENCE_CALENDAR_PERSONAL",
    "개인팀일정":   "CONFLUENCE_CALENDAR_PERSONAL",
    "personal":     "CONFLUENCE_CALENDAR_PERSONAL",
}


def _parse_date(date_raw: str):
    """
    다양한 날짜 표현 → 'YYYY-MM-DD' 또는 None.
    지원: 2026-03-12 / 26-03-12 / 2026/3/12 / 3/12
          26년 3월 12일 / 2026년 3월 12일 / 3월 12일
    """
    from datetime import datetime
    d = date_raw.strip()

    if re.match(r'^\d{4}-\d{2}-\d{2}$', d):                           # YYYY-MM-DD
        return d
    m = re.match(r'^(\d{2})-(\d{2})-(\d{2})$', d)                     # YY-MM-DD
    if m:
        return f"20{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r'^(\d{2,4})/(\d{1,2})/(\d{1,2})$', d)               # YYYY/M/D or YY/M/D
    if m:
        y = f"20{m.group(1)}" if len(m.group(1)) == 2 else m.group(1)
        return f"{y}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r'^(\d{1,2})/(\d{1,2})$', d)                         # M/D (당해 연도)
    if m:
        return f"{datetime.now().year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    m = re.match(r'^(\d{2,4})년\s*(\d{1,2})월\s*(\d{1,2})일$', d)     # Y년 M월 D일
    if m:
        y = f"20{m.group(1)}" if len(m.group(1)) == 2 else m.group(1)
        return f"{y}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r'^(\d{1,2})월\s*(\d{1,2})일$', d)                   # M월 D일 (당해 연도)
    if m:
        return f"{datetime.now().year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return None


def _parse_calendar_args(text: str):
    """
    날짜 패턴을 기준으로 텍스트를 (캘린더 유형, 날짜, 제목) 으로 분리.
    Returns: (cal_type_raw, date_raw, title) | None
    """
    date_pats = [
        r'\d{4}-\d{2}-\d{2}',                     # 2026-03-12
        r'\d{2}-\d{2}-\d{2}',                     # 26-03-12
        r'\d{2,4}년\s*\d{1,2}월\s*\d{1,2}일',     # 26년 3월 12일
        r'\d{1,2}월\s*\d{1,2}일',                 # 3월 12일
        r'\d{4}/\d{1,2}/\d{1,2}',                 # 2026/3/12
        r'\d{1,2}/\d{1,2}',                       # 3/12
    ]
    for pat in date_pats:
        m = re.search(pat, text)
        if m:
            cal_type_raw = text[:m.start()].strip().strip("'\"")
            date_raw     = m.group(0)
            title        = text[m.end():].strip().strip("'\"")
            if cal_type_raw and title:
                return cal_type_raw, date_raw, title
    return None


def _resolve_calendar_type(cal_type_raw: str):
    """
    캘린더 유형 문자열 → (env_key, type_name) | None.
    공백을 제거한 뒤 별칭 dict 와 매핑.
    """
    key = cal_type_raw.replace(" ", "")
    env_key = _CALENDAR_ALIASES.get(key) or _CALENDAR_ALIASES.get(key.lower())
    if env_key:
        type_name = "프로젝트 일정" if "PROJECT" in env_key else "개인/팀 일정"
        return env_key, type_name
    return None


def _calendar_help(respond):
    """도움말"""
    respond(text=(
        "*📅 /calendar 일정 등록 도움말*\n\n"
        "```\n"
        "/calendar [유형] [날짜] [제목]   Confluence 캘린더에 일정 등록\n"
        "/calendar list                   캘린더 목록 & ID 확인\n"
        "/calendar help                   이 도움말\n"
        "```\n\n"
        "*유형 키워드:*\n"
        "• 프로젝트 일정: `플잭`  `프로젝트`  `프로젝트 일정`\n"
        "• 개인/팀 일정:  `개인`  `팀`  `개인 일정`\n\n"
        "*날짜 — 아래 형식 모두 지원:*\n"
        "• `2026-03-12`  `26-03-12`  `2026/3/12`\n"
        "• `26년 3월 12일`  `3월 12일`  `3/12`\n\n"
        "예시:\n"
        "• `/calendar 플잭 2026-03-12 에픽세븐 v2.1 업데이트`\n"
        "• `/calendar 프로젝트 일정 26년 3월 12일 QA 교육`\n"
        "• `/calendar 개인 3월 15일 팀 회식`"
    ))


def _calendar_list(client, respond):
    """캘린더 목록 조회"""
    calendars, err = client.list_calendars()
    if err:
        respond(text=f"❌ 캘린더 조회 실패\n```\n{err}\n```")
        return
    if not calendars:
        respond(text="ℹ️ 조회된 캘린더가 없습니다.")
        return

    lines = ["*📅 QASGP 공간 캘린더 목록*\n"]
    for cal in calendars:
        cid  = cal.get("id", "?")
        name = cal.get("title") or cal.get("name", "?")
        lines.append(f"• `{cid}`  {name}")
    lines.append(
        "\n💡 Railway 환경변수 설정:\n"
        "`CONFLUENCE_CALENDAR_PROJECT=<프로젝트 일정 ID>`\n"
        "`CONFLUENCE_CALENDAR_PERSONAL=<개인/팀 일정 ID>`"
    )
    respond(text="\n".join(lines))


def _calendar_add_event(client, text: str, respond):
    """날짜 기준 파싱 후 캘린더 일정 등록"""
    parsed = _parse_calendar_args(text)
    if not parsed:
        respond(
            text=(
                "❌ 명령어 형식을 인식하지 못했습니다.\n"
                "`/calendar help` 를 입력하면 도움말을 확인할 수 있어요."
            )
        )
        return

    cal_type_raw, date_raw, title = parsed

    resolved = _resolve_calendar_type(cal_type_raw)
    if not resolved:
        respond(
            text=(
                f"❌ 알 수 없는 캘린더 유형: `{cal_type_raw}`\n"
                "프로젝트 일정: `플잭` `프로젝트` `프로젝트 일정`\n"
                "개인/팀 일정:  `개인` `팀` `개인 일정`"
            )
        )
        return

    env_key, type_name = resolved
    calendar_id = os.getenv(env_key, "")
    if not calendar_id:
        respond(
            text=(
                f"❌ `{env_key}` 환경변수가 설정되지 않았습니다.\n"
                f"`/calendar list` 로 캘린더 ID를 확인한 뒤 Railway 환경변수에 추가하세요."
            )
        )
        return

    date_str = _parse_date(date_raw)
    if not date_str:
        respond(
            text=(
                f"❌ 날짜 형식 오류: `{date_raw}`\n"
                "지원 형식: `2026-03-12`, `26년 3월 12일`, `3월 12일`, `3/12`"
            )
        )
        return

    result, err = client.create_event(calendar_id, title, date_str)
    if err:
        respond(text=f"❌ 일정 등록 실패\n```\n{err}\n```")
        return

    respond(
        response_type="in_channel",
        text=(
            f"✅ *Confluence 캘린더에 일정이 등록되었습니다!*\n"
            f"• 캘린더: {type_name}\n"
            f"• 날짜: {date_str}\n"
            f"• 제목: {title}"
        ),
    )


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

    @app.command("/wiki")
    def handle_wiki_command(ack, respond, command):
        """
        /wiki help              → 도움말
        /wiki search [검색어]   → 페이지 목록 검색
        /wiki [페이지 제목]     → 페이지 내용 조회
        """
        ack()
        text   = (command.get("text") or "").strip()
        client = wc.ConfluenceCalendarClient()

        if not text or text.lower() == "help":
            _wiki_help(respond)
            return

        parts = text.split(None, 1)
        if parts[0].lower() == "search":
            query = parts[1].strip() if len(parts) == 2 else ""
            if query:
                _wiki_search_pages(client, query, respond)
            else:
                respond(text="❌ 검색어를 입력하세요. 예: `/wiki search QA 일정`")
            return

        # "|" 구분자 → [경로/페이지 제목] | [질문] 으로 Claude AI 답변
        if "|" in text:
            page_part, _, question = text.partition("|")
            page_part = page_part.strip()
            question  = question.strip()
            if page_part and question:
                page, err = _wiki_fetch_page(client, page_part)
                if err:
                    respond(text=f"❌ 페이지 조회 실패\n```\n{err}\n```")
                    return
                _wiki_ask_claude(page["title"], page["text"], page["url"], question, respond)
                return

        # 나머지는 모두 경로/페이지 제목으로 처리 (내용 전체 표시)
        _wiki_get_page(client, text, respond)

    @app.command("/calendar")
    def handle_calendar_command(ack, respond, command):
        """
        /calendar help                      → 도움말
        /calendar list                      → 캘린더 목록 & ID 확인
        /calendar [유형] [날짜] [제목]      → 일정 등록
          유형 예: 플잭, 프로젝트, 프로젝트 일정, 개인, 팀
          날짜 예: 2026-03-12, 26년 3월 12일, 3월 12일, 3/12
        """
        ack()
        text   = (command.get("text") or "").strip()
        client = wc.ConfluenceCalendarClient()

        if not text or text.lower() == "help":
            _calendar_help(respond)
            return

        parts = text.split(None, 1)
        if parts[0].lower() == "list":
            _calendar_list(client, respond)
            return

        # 날짜 기준 파싱으로 일정 등록
        _calendar_add_event(client, text, respond)

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
