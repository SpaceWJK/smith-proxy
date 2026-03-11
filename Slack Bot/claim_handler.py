"""
claim_handler.py — /claim 슬래시 커맨드 비즈니스 로직

개선·건의·이슈 등 사용자 제보를 체계적으로 분류하고
로컬 JSON 파일로 데일리 기록을 관리합니다.

커맨드 형식:
    /claim [카테고리] [내용]   → 클레임 접수
    /claim list               → 오늘 접수 목록
    /claim list [날짜]        → 해당 날짜 접수 목록
    /claim stats              → 오늘 카테고리별 통계

저장소: data/claims.json
로그:   logs/claim.log
"""

import os
import json
import logging
import time
from datetime import datetime

# ── 경로 설정 ─────────────────────────────────────────────────
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BASE_DIR, "data")
_CLAIMS_FILE = os.path.join(_DATA_DIR, "claims.json")
_LOG_DIR = os.path.join(_BASE_DIR, "..", "logs")

logger = logging.getLogger(__name__)


# ── 카테고리 정의 ─────────────────────────────────────────────
CATEGORIES = {
    "개선": ["개선", "improvement", "enhance", "개선사항"],
    "건의": ["건의", "suggestion", "suggest", "요청", "제안"],
    "이슈": ["이슈", "issue", "bug", "버그", "오류", "에러", "결함"],
    "기타": ["기타", "other", "etc"],
}

# 별칭 → 정규 카테고리 역매핑
_ALIAS_TO_CATEGORY: dict[str, str] = {}
for _cat, _aliases in CATEGORIES.items():
    for _alias in _aliases:
        _ALIAS_TO_CATEGORY[_alias.lower()] = _cat


# ── 저장소 I/O ────────────────────────────────────────────────

def _load_claims() -> dict:
    """claims.json 로드. 없으면 빈 dict 반환."""
    if not os.path.exists(_CLAIMS_FILE):
        return {}
    try:
        with open(_CLAIMS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"[claim] claims.json 로드 실패: {e}")
        return {}


def _save_claims(data: dict):
    """claims.json 저장."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    try:
        with open(_CLAIMS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"[claim] claims.json 저장 실패: {e}")


# ── 핵심 함수 ─────────────────────────────────────────────────

def parse_claim_input(text: str) -> tuple[str, str]:
    """입력 텍스트에서 (카테고리, 내용) 분리.

    첫 번째 단어가 카테고리 별칭이면 해당 카테고리로 분류.
    아니면 '기타'로 분류하고 전체 텍스트를 내용으로 사용.

    Returns
    -------
    tuple[str, str]
        (카테고리명, 내용)
    """
    parts = text.strip().split(None, 1)
    if not parts:
        return "기타", ""

    first_word = parts[0].lower()
    category = _ALIAS_TO_CATEGORY.get(first_word)

    if category:
        content = parts[1].strip() if len(parts) > 1 else ""
        return category, content
    else:
        return "기타", text.strip()


def submit_claim(user_id: str, user_name: str,
                 category: str, content: str) -> dict:
    """클레임 접수 → 저장 → CLM ID 반환.

    Returns
    -------
    dict
        {"id": "CLM-20260310-001", "category": ..., "content": ..., ...}
    """
    now = datetime.now()
    date_key = now.strftime("%Y-%m-%d")

    data = _load_claims()
    day_claims = data.get(date_key, [])

    # 순번 생성
    seq = len(day_claims) + 1
    claim_id = f"CLM-{now.strftime('%Y%m%d')}-{seq:03d}"

    claim = {
        "id": claim_id,
        "category": category,
        "content": content,
        "user_id": user_id,
        "user_name": user_name,
        "timestamp": now.isoformat(),
    }

    day_claims.append(claim)
    data[date_key] = day_claims
    _save_claims(data)

    log_claim(user_id=user_id, user_name=user_name,
              action="submit", content=f"[{category}] {content}")

    logger.info(f"[claim] 접수: {claim_id} [{category}] {content[:50]}")
    return claim


def get_claims_by_date(date_str: str = None) -> list:
    """날짜별 접수 목록 (기본: 오늘).

    Parameters
    ----------
    date_str : str, optional
        "2026-03-10" 또는 "20260310" 형식. None이면 오늘.
    """
    if date_str is None:
        date_key = datetime.now().strftime("%Y-%m-%d")
    else:
        # 날짜 형식 정규화
        clean = date_str.strip().replace("/", "-").replace(".", "-")
        if len(clean) == 8 and clean.isdigit():
            clean = f"{clean[:4]}-{clean[4:6]}-{clean[6:8]}"
        date_key = clean

    data = _load_claims()
    return data.get(date_key, [])


# ── Slack 포맷 헬퍼 ───────────────────────────────────────────

def format_claim_list(claims: list, date_label: str) -> str:
    """Slack 포맷 접수 목록."""
    if not claims:
        return f":clipboard: *{date_label}* 접수된 클레임이 없습니다."

    lines = [f":clipboard: *{date_label} 클레임 목록* ({len(claims)}건)\n"]

    # 카테고리 이모지 매핑
    emoji = {"개선": ":bulb:", "건의": ":speech_balloon:", "이슈": ":warning:", "기타": ":label:"}

    for c in claims:
        cat_emoji = emoji.get(c["category"], ":label:")
        ts = c.get("timestamp", "")
        time_str = ts[11:16] if len(ts) >= 16 else ""
        lines.append(
            f"{cat_emoji} `{c['id']}` [{c['category']}] "
            f"{c['content'][:80]}"
            f"{'...' if len(c.get('content', '')) > 80 else ''}"
            f"  — {c.get('user_name', '?')} {time_str}"
        )

    return "\n".join(lines)


def format_claim_stats(claims: list) -> str:
    """카테고리별 통계."""
    if not claims:
        return ":bar_chart: 오늘 접수된 클레임이 없습니다."

    counts: dict[str, int] = {}
    for c in claims:
        cat = c.get("category", "기타")
        counts[cat] = counts.get(cat, 0) + 1

    lines = [f":bar_chart: *오늘 클레임 통계* (총 {len(claims)}건)\n"]
    emoji = {"개선": ":bulb:", "건의": ":speech_balloon:", "이슈": ":warning:", "기타": ":label:"}

    for cat in ["이슈", "개선", "건의", "기타"]:
        cnt = counts.get(cat, 0)
        if cnt > 0:
            lines.append(f"{emoji.get(cat, ':label:')} {cat}: {cnt}건")

    return "\n".join(lines)


# ── 로깅 ──────────────────────────────────────────────────────

def log_claim(*, user_id: str, user_name: str, action: str,
              content: str = "", error: str = ""):
    """logs/claim.log에 파이프 구분 형식으로 기록."""
    os.makedirs(_LOG_DIR, exist_ok=True)
    log_file = os.path.join(_LOG_DIR, "claim.log")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    line = (
        f"{ts} | {user_id} | {user_name} | "
        f"{action} | {content[:200]} | {error}\n"
    )
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
