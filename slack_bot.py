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
import atexit
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


def _wiki_fetch_page(client, page_part: str, fetch_full: bool = True):
    """
    '>' 구분자 유무에 따라 적합한 방식으로 Confluence 페이지를 조회합니다.

    - '>' 포함 → 조상 기반 CQL 검색 (get_page_by_path)
    - '>' 없음  → 제목 직접 검색   (get_page_by_title)

    Parameters
    ----------
    fetch_full : bool
        True  → get_page_by_id 추가 MCP 호출로 전체 본문 조회 (AI 질의용)
        False → cql_search body.view 만 사용 (단순 표시용, MCP 호출 1회 절약)

    Returns: (page_dict | None, error_str | None)
    """
    if ">" in page_part:
        segments   = [s.strip() for s in page_part.split(">")]
        leaf_title = segments[-1]
        ancestors  = segments[:-1]
        return client.get_page_by_path(ancestors, leaf_title,
                                       fetch_full=fetch_full)
    return client.get_page_by_title(page_part, fetch_full=fetch_full)


def _wiki_get_page(client, page_part: str, respond):
    """경로/페이지 제목으로 내용 조회 후 Slack 에 표시 (fetch_full=False: 표시 전용)"""
    page, err = _wiki_fetch_page(client, page_part, fetch_full=False)
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
        f"위 내용을 바탕으로 아래 질문에 한국어로 간결하게 답해주세요.\n\n"
        f"[답변 지침]\n"
        f"1. 질문에 특정 연도·기간이 명시된 경우, 해당 범위의 데이터만 사용하세요. 다른 연도 데이터와 혼용하지 마세요.\n"
        f"2. 페이지에 합계가 명시되어 있으면 그 값을 인용하고, 없으면 해당 범위의 항목을 직접 세어 답하세요. '[검색 관련 섹션]'이 있으면 우선 참고하세요.\n"
        f"3. 페이지에 관련 내용이 없으면 '해당 내용을 페이지에서 찾을 수 없습니다'라고 답하세요.\n\n"
        f"질문: {question}"
    )

    try:
        client_ai = anthropic.Anthropic(api_key=api_key)
        message   = client_ai.messages.create(
            model      = "claude-haiku-4-5-20251001",  # 빠르고 저렴한 모델
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


# ── 단일 인스턴스 보장 ────────────────────────────────────────

def _ensure_single_instance(pid_file: str = "slack_bot.pid"):
    """
    PID 파일을 이용해 봇이 하나만 실행되도록 보장합니다.
    - 시작 시: 기존 PID 파일의 프로세스가 살아있으면 종료
    - 종료 시: atexit 으로 PID 파일 자동 삭제
    """
    if os.path.exists(pid_file):
        try:
            with open(pid_file) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)   # signal 0 → 프로세스 존재 여부 확인
            logger.error(
                f"이미 실행 중인 봇 프로세스가 있습니다 (PID: {old_pid}).\n"
                f"중복 실행을 원한다면 '{pid_file}' 파일을 삭제 후 재시작하세요."
            )
            sys.exit(1)
        except (ProcessLookupError, OSError):
            pass   # 프로세스 없음 → 파일만 남은 것, 덮어씀
        except ValueError:
            pass   # 파일 내용 오류 → 무시

    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

    def _cleanup():
        try:
            os.remove(pid_file)
        except Exception:
            pass

    atexit.register(_cleanup)
    logger.info(f"[PID] 단일 인스턴스 등록: PID {os.getpid()} → {pid_file}")


# ── 체크리스트 상태 재구성 헬퍼 ───────────────────────────────

def _normalize_title(t: str) -> str:
    """
    Slack :emoji: 코드와 실제 이모지 문자를 모두 제거한 비교용 제목 반환.

    Slack 은 chat.postMessage 에 보낸 실제 이모지 문자(📋)를
    action payload 의 message.text 에서 :clipboard: 콜론 코드로 변환해 돌려준다.
    config.json 의 title 은 실제 이모지 문자를 사용하므로 직접 비교하면 항상 불일치.
    양쪽을 정규화한 뒤 비교해야 한다.

    예)
      "📋 일일 QA 체크리스트"          → "일일 QA 체크리스트"
      ":clipboard: 일일 QA 체크리스트" → "일일 QA 체크리스트"
    """
    t = re.sub(r':[a-z_]+:', '', t)                # :colon: 이모지 코드 제거
    t = re.sub(r'[^\w\s가-힣\[\]\(\)]', '', t)      # 실제 이모지·특수문자 제거
    return t.strip()


def _reconstruct_checklist_state(body: dict, checked: list):
    """
    상태 파일이 없을 때 Slack 메시지 body + config.json 으로 상태를 재구성합니다.

    Railway(스케줄러) ↔ 로컬 PC(커맨드 핸들러)가 분리된 환경에서
    data/checklist_state.json 이 두 환경에 공유되지 않아 발생하는
    '체크 시 진행률 미반영' 문제를 해결합니다.

    Returns
    -------
    dict  : {"title": ..., "items": [...], "checked": [...], "sent_at": ...}
    None  : 재구성 실패
    """
    import json as _json

    msg        = body.get("message", {})
    msg_blocks = msg.get("blocks", [])

    # ── 1. 타이틀 ──────────────────────────────────────────────────────────
    # 우선순위 A: body["message"]["text"]
    #   → send_interactive_checklist() 에서 text=schedule["title"] 로 전송했으므로
    #     Slack action payload 에서 항상 신뢰할 수 있는 값
    # 우선순위 B: header 블록 (blocks 가 payload 에 포함됐을 때만 동작)
    title = (msg.get("text") or "").strip()
    if not title:
        for block in msg_blocks:
            if block.get("type") == "header":
                title = block["text"]["text"]
                break
    if not title:
        title = "📋 체크리스트"

    logger.info(
        f"[체크리스트 재구성] msg.text={msg.get('text')!r}  "
        f"→ title={title!r}  blocks={len(msg_blocks)}개"
    )

    # ── 2. sent_at ─────────────────────────────────────────────────────────
    # 마지막 context 블록에서 추출 ("발송: YYYY-MM-DD HH:MM  |  자동 알림")
    # 멘션 context 블록도 있으므로 reversed() 로 마지막(타임스탬프) 블록을 찾음
    sent_at = ""
    for block in reversed(msg_blocks):
        if block.get("type") == "context":
            ctx = block.get("elements", [{}])[0].get("text", "")
            m = re.search(r'발송:\s*(.+?)\s*\|', ctx)
            if m:
                sent_at = m.group(1).strip()
            break

    # ── 3. items: config.json 에서 title 로 스케줄 매칭 ────────────────────
    items: list      = []
    schedule_type: str = ""
    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = _json.load(f)
        config_titles = [s.get("title") for s in cfg.get("schedules", [])]
        logger.info(f"[체크리스트 재구성] config 타이틀 목록: {config_titles}")
        title_norm = _normalize_title(title)
        logger.info(f"[체크리스트 재구성] 정규화 타이틀: {title_norm!r}")
        for sched in cfg.get("schedules", []):
            if _normalize_title(sched.get("title", "")) == title_norm:
                items         = sched.get("items", [])
                schedule_type = sched.get("type", "")
                logger.info(f"[체크리스트 재구성] config 매칭 성공: {len(items)}개 / type={schedule_type!r}")
                break
    except Exception as e:
        logger.warning(f"[체크리스트 재구성] config.json 로드 실패: {e}")

    # ── 4. config 매칭 실패 시 → message blocks 의 checkboxes.options 에서 재구성
    # 신규 구조(chk_grp_*, chk_solo_*) 및 구버전(checklist_block) 모두 처리합니다.
    # (body["actions"][0]["options"] 는 Slack payload 에 포함되지 않음 — blocks 에서 찾아야 함)
    if not items:
        for block in msg_blocks:
            if block.get("type") == "actions":
                for elem in block.get("elements", []):
                    if elem.get("type") == "checkboxes":
                        for opt in elem.get("options", []):
                            val      = opt.get("value", "")
                            opt_text = opt.get("text", {}).get("text", "")
                            mentions = re.findall(r'<@([A-Z0-9]+)>', opt_text)
                            clean    = re.sub(r'\s{2,}담당:.*$', '', opt_text).strip().strip('*')
                            items.append({"value": val, "text": clean, "mentions": mentions})
        if items:
            logger.info(f"[체크리스트 재구성] message blocks에서 재구성: {len(items)}개")

    if not items:
        logger.warning(
            f"[체크리스트 재구성] items 구성 실패 — "
            f"title={title!r}, msg.text={msg.get('text')!r}, blocks={len(msg_blocks)}개"
        )
        return None

    logger.info(
        f"[체크리스트 재구성] 완료  title={title!r}  "
        f"items={len(items)}개  checked={len(checked)}개"
    )
    return {
        "title":         title,
        "items":         items,
        "checked":       checked,
        "sent_at":       sent_at,
        "schedule_type": schedule_type,
    }


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

    @app.action(re.compile(r"^checklist_toggle"))
    def handle_checklist_toggle(ack, body):
        """
        사용자가 체크리스트를 체크/언체크할 때 호출됩니다.
        - ack() 로 Slack 에 즉시 응답 (3초 이내 필수)
        - 상태 파일 갱신 후 chat.update 로 메시지 동기화

        [다중 사용자 동기화 전략]
        체크박스 action_id 는 chat.update 마다 동적으로 변경됩니다 (checklist_toggle_{ts_ms}).
        따라서 핸들러는 re.compile(r"^checklist_toggle") 로 모든 버전을 수신합니다.

        merge 전략:
          1. ih.get_by_ts() — 파일 기반 권위있는 서버 상태 (conversations.history 불필요)
          2. body["message"]["blocks"] 의 options(전체 옵션 목록) 에서
             인터랙션된 block_id 의 가능한 모든 값 제거
             (initial_options 는 stale 할 수 있으나 options 목록은 항상 고정)
          3. body["state"]["values"] 의 새 선택값 추가
        """
        ack()   # Slack 에 즉시 응답

        channel = body["channel"]["id"]
        ts      = body["message"]["ts"]

        # ── Step 1: ih.get_by_ts() 에서 권위있는 서버 최신 체크 상태 로드 ──────
        # conversations.history (groups:history 권한 필요) 를 사용하지 않고
        # interaction_handler 의 파일 기반 상태를 source of truth 로 사용합니다.
        # → ih 는 toggle 마다 갱신되므로 항상 최신 서버 상태를 반영합니다.
        existing_state = ih.get_by_ts(channel, ts)
        if existing_state:
            current_checked: set = set(existing_state.get("checked", []))
            logger.debug(f"[toggle] ih 상태 로드: checked={len(current_checked)}개")
        else:
            # ih 에 없을 때: body["message"]["blocks"] 의 initial_options 에서 초기값 복원
            current_checked = set()
            for block in body.get("message", {}).get("blocks", []):
                if block.get("type") == "actions":
                    for elem in block.get("elements", []):
                        if elem.get("type") == "checkboxes":
                            for opt in elem.get("initial_options", []):
                                current_checked.add(opt["value"])
            logger.debug(f"[toggle] ih 상태 없음 → body fallback: checked={len(current_checked)}개")

        # ── Step 2: body["actions"] 의 실제 인터랙션 delta 만 적용 ──────────────
        #
        # [왜 body["state"]["values"] 를 쓰지 않는가]
        # state.values 는 메시지 내 모든 체크박스 블록의 상태를 담고 있습니다.
        # 하지만 이 값은 B의 "클라이언트 렌더 상태"에 기반하므로 stale 할 수 있습니다.
        #   → A가 5개 체크 후 B가 즉시 클릭하면, B 화면이 아직 갱신 안 된 경우
        #     state.values 의 다른 블록들은 모두 빈 selected_options 로 전달됨
        #   → Step 3+4 에서 ih 의 A의 5개가 모두 제거되고 B의 1개만 남는 버그 발생
        #
        # [body["actions"] 를 사용하는 이유]
        # actions 는 이번 인터랙션에서 실제로 변경된 블록만 포함하며 신뢰할 수 있습니다.
        # 각 action 의 selected_options 는 해당 블록의 최신 완전한 선택 상태입니다.
        #   → ih state (A의 5개) + actions delta (B가 클릭한 블록만 교체) = 정확한 merge
        for action in body.get("actions", []):
            if action.get("type") != "checkboxes":
                continue

            action_block_id = action.get("block_id", "")

            # 해당 블록의 모든 가능한 옵션값 제거 (이 블록 전체를 새 값으로 교체)
            for block in body.get("message", {}).get("blocks", []):
                if block.get("block_id", "") == action_block_id:
                    for elem in block.get("elements", []):
                        if elem.get("type") == "checkboxes":
                            for opt in elem.get("options", []):
                                current_checked.discard(opt["value"])

            # 해당 블록의 최신 선택 상태 추가
            for opt in action.get("selected_options", []):
                current_checked.add(opt["value"])

        checked: list = list(current_checked)

        logger.info(
            f"체크리스트 토글 | 채널: {channel} | ts: {ts} | "
            f"체크된 항목: {checked}"
        )

        # 상태 갱신 (상태 파일 우선 → 없으면 body + config.json 으로 재구성)
        state = ih.update_checked(channel, ts, checked)
        if state is None:
            logger.info("상태 파일 미등록 → Slack body 에서 상태 재구성 시도")
            state = _reconstruct_checklist_state(body, checked)
            if state is None:
                logger.warning("체크리스트 상태를 재구성할 수 없습니다.")
                return

        # ── 전일 누락 섹션 추출 (block_id="missed_divider" sentinel 기준) ──────
        # body["message"]["blocks"] 에서 추출합니다.
        # 누락 섹션의 options 목록은 변하지 않으므로 stale body 여도 안전합니다.
        # (initial_options 는 _rebuild_missed_blocks_checked 에서 재계산됩니다)
        body_blocks     = body.get("message", {}).get("blocks", [])
        missed_section: list = []
        in_missed       = False
        for _blk in body_blocks:
            bid = _blk.get("block_id", "")
            if bid == "missed_divider":
                in_missed = True
            if in_missed:
                if not bid.startswith("missed_"):
                    break          # footer 구분자 — 수집 종료
                missed_section.append(_blk)

        # 메시지 업데이트
        slack_sender.update_interactive_checklist(
            channel,
            ts,
            state,
            missed_section = missed_section if missed_section else None,
        )

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
                respond(text=f"🔍 `{query}` 검색 중...")
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
                respond(text=f"🔍 *{page_part}* 페이지 조회 중...")
                page, err = _wiki_fetch_page(client, page_part)
                if err:
                    respond(text=f"❌ 페이지 조회 실패\n```\n{err}\n```")
                    return
                respond(text=f"🤖 *{page['title']}* — Claude 답변 생성 중...")
                _wiki_ask_claude(page["title"], page["text"], page["url"], question, respond)
                return

        # 나머지는 모두 경로/페이지 제목으로 처리 (내용 전체 표시)
        respond(text=f"🔍 *{text}* 페이지 조회 중...")
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
    _ensure_single_instance()
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


def cmd_scheduler_only(sender: SlackSender):
    """
    스케줄러만 실행합니다 — Socket Mode 없음 (Railway 전용 모드).
    Slack 메시지 전송은 HTTP API(chat.postMessage)만 사용하므로
    공용 클라우드에서도 동작합니다.
    """
    import time
    _ensure_single_instance("slack_bot_scheduler.pid")

    scheduler = NotificationScheduler(sender, config_path="config.json")
    scheduler.start()   # 논블로킹
    logger.info("📅 스케줄러 전용 모드 실행 중 — Socket Mode 없음 (Railway)")

    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("스케줄러가 정상 종료되었습니다.")
        scheduler.shutdown()


def cmd_commands_only(sender: SlackSender, bolt_app: App, app_token: str):
    """
    Socket Mode 핸들러만 실행합니다 — 스케줄러 없음 (로컬 PC 전용 모드).
    /wiki, /calendar 등 슬래시 커맨드를 사내망 PC에서 처리합니다.
    Railway 스케줄러와 충돌하지 않습니다.
    """
    _ensure_single_instance()
    logger.info("💬 커맨드 전용 모드 실행 중 — 스케줄러 없음 (로컬 PC)")
    logger.info("🔌 Socket Mode 연결 중... (종료: Ctrl+C)")
    handler = SocketModeHandler(bolt_app, app_token)
    try:
        handler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("봇이 정상 종료되었습니다.")


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
    parser.add_argument(
        "--scheduler-only", action="store_true",
        help="[Railway 전용] 스케줄러만 실행 — Socket Mode 없음\n"
             "공용 클라우드에서 사내망 없이 Slack 알림 전송만 담당합니다.",
    )
    parser.add_argument(
        "--commands-only", action="store_true",
        help="[로컬 PC 전용] 슬래시 커맨드만 실행 — 스케줄러 없음\n"
             "/wiki, /calendar 등 사내망 접근이 필요한 커맨드를 처리합니다.",
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

    elif args.scheduler_only:
        # ── Railway 전용: 스케줄러만 (Socket Mode 없음) ──
        logger.info("▶ 모드: 스케줄러 전용 (Railway)")
        cmd_scheduler_only(sender)

    elif args.commands_only:
        # ── 로컬 PC 전용: 슬래시 커맨드만 (스케줄러 없음) ──
        if not app_token or not app_token.startswith("xapp-"):
            logger.error("--commands-only 모드에는 SLACK_APP_TOKEN(xapp-...) 이 필요합니다.")
            sys.exit(1)
        logger.info("▶ 모드: 커맨드 전용 (로컬 PC)")
        cmd_commands_only(sender, bolt_app, app_token)

    else:
        # ── 풀 모드: 스케줄러 + Socket Mode (개발/테스트용) ──
        if not app_token or not app_token.startswith("xapp-"):
            logger.error("Socket Mode 실행에는 SLACK_APP_TOKEN(xapp-...) 이 필요합니다.")
            logger.error(".env 파일에서 SLACK_APP_TOKEN 을 설정하세요.")
            logger.error("(채널 목록/테스트만 사용할 경우: --channels / --test 옵션 사용)")
            sys.exit(1)
        logger.info("▶ 모드: 풀 모드 (스케줄러 + 커맨드)")
        cmd_run(sender, bolt_app, app_token)


if __name__ == "__main__":
    main()
