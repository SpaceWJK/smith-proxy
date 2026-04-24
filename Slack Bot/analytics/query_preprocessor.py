"""
query_preprocessor.py — GDI 쿼리 전처리 모듈 (task-101 v2)

게임명 별칭 교정 + 날짜 패턴 정규화.

순서: apply_aliases → normalize_dates
"""

import re
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_ALIAS_MAP_PATH = Path(__file__).parent / "alias_map.json"


def _load_alias_map() -> dict:
    """alias_map.json 로드. 실패 시 빈 맵 반환."""
    try:
        with open(_ALIAS_MAP_PATH, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("[query_preprocessor] alias_map.json 로드 실패: %s", e)
        return {}


_ALIAS_MAP: dict = _load_alias_map()


def _current_year() -> str:
    """현재 연도 문자열 반환. 예: '2026'"""
    return str(datetime.now().year)


def _valid_date(yy: str, mm: str, dd: str) -> bool:
    """YY, MM, DD 문자열이 유효한 날짜인지 확인.

    yy는 '26' 형태 (2자리), mm/dd는 '02'/'25' 형태.
    MM: 1~12, DD: 1~31

    이슈번호(113571 등 6자리)의 오변환 방지에 사용됨.
    예: '11', '35', '71' → MM=35 > 12 → False
    """
    try:
        m = int(mm)
        d = int(dd)
        return 1 <= m <= 12 and 1 <= d <= 31
    except (ValueError, TypeError):
        return False


# ── 오탐 방지용 단위/분류어 lookahead ───────────────────────────────────
# M/D 패턴이 날짜가 아닌 분수/분기/비율 표현에 오탐되는 경우를 차단.
# 예: "3/4분기" → 3/4 뒤에 "분기" → 차단
#     "2/3점" → 2/3 뒤에 "점" → 차단
# 단, "2/25타겟" → 25 뒤에 "타겟" → 허용 (날짜 의미)
#
# 정책: 분기·단위·비율·수량을 나타내는 한글 단어만 차단,
#       일반 목적어(타겟, 기준, 이슈 등)는 허용.
_UNIT_WORDS_PATTERN = (
    r"(?!(?:분기|월|주|일|년|점|배|위|명|개|건|회|번|차|기|판|단|절|권|장|절|원|달|층|등|쪽|부|항|절|행|열|칸|줄|자|글|곳|채|폼|뷰|모|앱|탭|버|팝))"
)


# ── DATE_PATTERNS (v2 — 7개, 우선순위 순) ────────────────────────────────
# 정규식 뒤 \b 대신 (?!\d) lookahead 사용 (CRITICAL-1 수정)
# M-D 패턴 추가 (MAJOR-1 수정)
# 오탐 방지: 분기·단위 한글 뒤따름 제외 (T-11 FAIL 해소)

DATE_PATTERNS = [
    # 1. YYYY-MM-DD or YYYY/MM/DD or YYYY.MM.DD
    (
        r'(?<!\d)(20\d{2})[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12]\d|3[01])(?!\d)',
        lambda m: f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}",
    ),

    # 2. YYYYMMDD pass-through (이미 정규 포맷 — 변환 없음)
    (
        r'(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)',
        lambda m: m.group(0),
    ),

    # 3. YY.MM.DD (예: 26.02.25)
    (
        r'(?<!\d)(\d{2})[.](\d{2})[.](\d{2})(?!\d)',
        lambda m: (
            f"20{m.group(1)}{m.group(2)}{m.group(3)}"
            if _valid_date(m.group(1), m.group(2), m.group(3))
            else m.group(0)
        ),
    ),

    # 4. YYMMDD 6자리 (예: 260225) — 이슈번호(113571) 오변환 방지 위해 _valid_date 필수
    (
        r'(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)',
        lambda m: (
            f"20{m.group(1)}{m.group(2)}{m.group(3)}"
            if _valid_date(m.group(1), m.group(2), m.group(3))
            else m.group(0)
        ),
    ),

    # 5. M/D — 오탐 방지: 분기·단위 한글이 바로 따라오면 제외
    #    T-11: "3/4분기" → 차단 (4 뒤 "분기")
    #    T-4:  "2/25타겟" → 허용 (25 뒤 "타겟" — 단위어 아님)
    (
        r'(?<!\d)(1[0-2]|0?[1-9])/(3[01]|[12]\d|0?[1-9])(?!\d)' + _UNIT_WORDS_PATTERN,
        lambda m: f"{_current_year()}{int(m.group(1)):02d}{int(m.group(2)):02d}",
    ),

    # 6. M.D — 동일 오탐 방지
    (
        r'(?<!\d)(1[0-2]|0?[1-9])[.](3[01]|[12]\d|0?[1-9])(?!\d)' + _UNIT_WORDS_PATTERN,
        lambda m: f"{_current_year()}{int(m.group(1)):02d}{int(m.group(2)):02d}",
    ),

    # 7. M-D (MAJOR-1 추가) — YYYY-MM-DD와 구분: 앞에 4자리 숫자 없을 때만
    (
        r'(?<!\d)(1[0-2]|0?[1-9])-(3[01]|[12]\d|0?[1-9])(?!\d)' + _UNIT_WORDS_PATTERN,
        lambda m: f"{_current_year()}{int(m.group(1)):02d}{int(m.group(2)):02d}",
    ),
]


def apply_aliases(text: str, alias_map: dict | None = None) -> str:
    """alias_map의 game aliases를 텍스트에 적용.

    순서:
    1. gdi_query_aliases: 구문 포함, 더 긴 항목 우선 (case-insensitive)
    2. gdi_folder_aliases: 단어 단위, case-sensitive

    Args:
        text: 처리할 텍스트
        alias_map: 사용할 alias 맵. None이면 모듈 로드 시 파싱된 맵 사용.
    """
    if alias_map is None:
        alias_map = _ALIAS_MAP
    if not alias_map or not text:
        return text

    # 1. gdi_query_aliases: 구문 포함, 더 긴 항목 우선 (case-insensitive)
    for src, dst in sorted(
        alias_map.get("gdi_query_aliases", {}).items(),
        key=lambda x: len(x[0]),
        reverse=True,
    ):
        if src.lower() in text.lower():
            text = re.sub(re.escape(src), dst, text, flags=re.IGNORECASE)

    # 2. gdi_folder_aliases: 단어 단위, case-sensitive
    for src, dst in alias_map.get("gdi_folder_aliases", {}).items():
        text = re.sub(r'\b' + re.escape(src) + r'\b', dst, text)

    return text


def normalize_dates(text: str) -> str:
    """텍스트 내 비표준 날짜 패턴을 YYYYMMDD로 변환.

    DATE_PATTERNS를 순서대로 적용.
    이미 처리된 위치는 다음 패턴에서 재처리 가능 (순차 적용).
    """
    for pattern, replacement in DATE_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text


def preprocess_query(query: str) -> str:
    """GDI 쿼리 전처리: alias 교정 → 날짜 정규화.

    순서: aliases 먼저, dates 나중.

    Args:
        query: 사용자 입력 쿼리

    Returns:
        전처리된 쿼리 문자열. 입력이 None/빈 문자열이면 그대로 반환.
    """
    if not query or not query.strip():
        return query
    query = apply_aliases(query)
    query = normalize_dates(query)
    return query


def preprocess_query_with_ranges(query: str) -> tuple:
    """전처리 쿼리 + 시간 범위 추출.

    원본 쿼리에서 DateRange를 추출하고, 전처리된 쿼리 문자열을 함께 반환.
    temporal_resolver 임포트 실패 시 (전처리 쿼리, []) 반환.

    Args:
        query: 사용자 입력 쿼리

    Returns:
        (전처리된 쿼리 str, DateRange list) 튜플.
        temporal_resolver 미사용 시 빈 list 반환.
    """
    processed = preprocess_query(query)
    try:
        from analytics.temporal_resolver import TemporalResolver
        ranges = TemporalResolver().resolve(query)  # 원본 쿼리로 범위 추출
    except ImportError:
        ranges = []
    return processed, ranges
