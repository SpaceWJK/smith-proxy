# -*- coding: utf-8 -*-
"""
temporal_resolver.py — 자연어 시간 표현 → DateRange 변환 (task-106)

외부 API/LLM 호출 없음. Python 표준 라이브러리만 사용.
패턴 7종 (우선순위 순):
  1. YYYY년 N분기 / Q{N} YYYY / YYYY년 Q{N}  (연도 명시, 3-브랜치)
  2. N분기 / Q{N}  (연도 없음 → ref_date.year 기준)
  3. N월 M째주  (ISO 8601 월요일 시작)
  4. N월 단독  (calendar.monthrange 말일)
  5. 최근 N일/주/달/개월
  6. 이번/저번/지난/전 주·달
  7. 오늘/어제
"""

import re
import calendar
from datetime import date, timedelta
from dataclasses import dataclass

__all__ = ["DateRange", "TemporalResolver"]


_DATE_FMT = re.compile(r'^\d{4}-\d{2}-\d{2}$')


@dataclass
class DateRange:
    start: str        # YYYY-MM-DD
    end: str          # YYYY-MM-DD
    label: str        # 원문 표현 (예: "3월 둘째주")
    confidence: float # 0.0~1.0 (명시적 날짜 1.0, 상대 0.8, 근사 0.5)

    def __post_init__(self):
        if not _DATE_FMT.match(self.start):
            raise ValueError(f"DateRange.start must be YYYY-MM-DD, got: {self.start!r}")
        if not _DATE_FMT.match(self.end):
            raise ValueError(f"DateRange.end must be YYYY-MM-DD, got: {self.end!r}")


# ── 패턴 정의 (우선순위 순) ───────────────────────────────────────────────

# 1. YYYY년 N분기 / Q{N} YYYY / YYYY년 Q{N}  — 연도 명시형 (3개 브랜치)
#    브랜치 a: "2025년 4분기" / "2025년4분기"
#    브랜치 b: "Q4 2025"
#    브랜치 c: "2025년 Q4" / "2025년Q4"
_RE_YEAR_QUARTER = re.compile(
    r'(20\d{2})년?\s*([1-4])\s*분기'       # 브랜치 a
    r'|Q([1-4])\s*(20\d{2})'              # 브랜치 b
    r'|(20\d{2})년\s*Q([1-4])'            # 브랜치 c: YYYY년 QN
)

# 2. N분기 / Q{N} (연도 없음 → 올해 기준) — 패턴 1 처리 후 잔여만 매칭
_RE_QUARTER = re.compile(r'(?<!\d)([1-4])\s*분기|[Qq]([1-4])(?!\d)')

# 3. N월 M째주
_RE_MONTH_WEEK = re.compile(
    r'(1[0-2]|[1-9])월\s*(첫|둘|셋|넷|다섯|마지막|1|2|3|4|5)째\s*주'
)

# 4. N월 (단독) — 패턴 3 처리 후 잔여만 매칭
_RE_MONTH = re.compile(r'(?<!\d)(1[0-2]|[1-9])월(?!\s*[0-9])')

# 5. 최근 N일/주/달/개월
_RE_RECENT = re.compile(
    r'최근\s*(\d+|일|이|삼|사|오|육|칠|팔|구|십)?\s*(일|주|달|개월|주일|한달)'
)

# 6. 이번/저번/지난/전 주·달
_RE_THIS_LAST = re.compile(
    r'(이번|저번|지난|전)\s*(주|달|월)'
)

# 7. 오늘/어제
_RE_TODAY_YEST = re.compile(r'(오늘|어제)')


# ── 헬퍼 함수 ─────────────────────────────────────────────────────────────

def _nth_weekday_of_month(year: int, month: int, n: int) -> date:
    """n번째 월요일 반환 (n=1: 첫째주). ISO 8601 주 시작=월요일."""
    first = date(year, month, 1)
    offset = (0 - first.weekday()) % 7  # 첫 번째 월요일까지 오프셋
    first_monday = first + timedelta(days=offset)
    return first_monday + timedelta(weeks=n - 1)


_WEEK_ORDINAL: dict = {
    "첫": 1, "1": 1, "둘": 2, "2": 2, "셋": 3, "3": 3,
    "넷": 4, "4": 4, "다섯": 5, "5": 5, "마지막": -1,
}


def _korean_num(s: str) -> int:
    """한국어 숫자 → int. '일'=1 ... '십'=10. 숫자 문자열도 처리."""
    _MAP = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5,
            "육": 6, "칠": 7, "팔": 8, "구": 9, "십": 10}
    if s.isdigit():
        return int(s)
    return _MAP.get(s, 1)


def _quarter_range(year: int, q: int) -> tuple:
    """분기 번호(1~4) → (start, end) date 반환."""
    starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
    ends   = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    return date(year, *starts[q]), date(year, *ends[q])


def _month_range(year: int, month: int) -> tuple:
    """월 → (1일, 말일) date 반환. calendar.monthrange 사용."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


# ── TemporalResolver ──────────────────────────────────────────────────────

class TemporalResolver:
    """자연어 텍스트에서 시간 범위 표현을 추출하여 DateRange list로 반환."""

    def resolve(self, text: str, ref_date=None) -> list:
        """텍스트에서 시간 범위 표현 추출 → DateRange list.

        처리 순서: 구체(YYYY년분기) → 연도없는분기 → N월M째주 → N월 → 최근N → 이번/저번 → 오늘/어제.
        seen_spans: 이미 처리된 (start, end) 오프셋 범위는 하위 패턴에서 skip.

        Args:
            text: 자연어 쿼리 텍스트
            ref_date: 기준 날짜 (None이면 date.today() 사용)

        Returns:
            DateRange list. 시간 표현 없으면 빈 list.
        """
        if ref_date is None:
            ref_date = date.today()
        results: list = []
        seen_spans: list = []  # (match.start(), match.end())
        year = ref_date.year

        def _skip(m) -> bool:
            """현재 match가 이미 처리된 span과 겹치면 True."""
            for s, e in seen_spans:
                if m.start() < e and m.end() > s:  # 교집합 존재
                    return True
            return False

        def _register(m, dr: DateRange):
            seen_spans.append((m.start(), m.end()))
            results.append(dr)

        # ── 1. YYYY년 N분기 / Q{N} YYYY / YYYY년 Q{N} ─────────────────────
        for m in _RE_YEAR_QUARTER.finditer(text):
            if _skip(m):
                continue
            # 브랜치 판별: group(1,2) / group(3,4) / group(5,6)
            if m.group(1) and m.group(2):          # 브랜치 a: YYYY년 N분기
                y, q = int(m.group(1)), int(m.group(2))
            elif m.group(3) and m.group(4):         # 브랜치 b: Q{N} YYYY
                q, y = int(m.group(3)), int(m.group(4))
            else:                                   # 브랜치 c: YYYY년 Q{N}
                y, q = int(m.group(5)), int(m.group(6))
            s, e = _quarter_range(y, q)
            _register(m, DateRange(s.isoformat(), e.isoformat(), m.group(), 1.0))

        # ── 2. N분기 / Q{N} (연도 없음 → ref_date.year 기준) ──────────────
        for m in _RE_QUARTER.finditer(text):
            if _skip(m):
                continue
            q = int(m.group(1) or m.group(2))
            s, e = _quarter_range(year, q)
            _register(m, DateRange(s.isoformat(), e.isoformat(), m.group(), 0.9))

        # ── 3. N월 M째주 ───────────────────────────────────────────────────
        for m in _RE_MONTH_WEEK.finditer(text):
            if _skip(m):
                continue
            month = int(m.group(1))
            n = _WEEK_ORDINAL.get(m.group(2), 1)
            if n == -1:
                last_day = date(year, month, calendar.monthrange(year, month)[1])
                monday = last_day - timedelta(days=last_day.weekday())
            else:
                monday = _nth_weekday_of_month(year, month, n)
            sunday = monday + timedelta(days=6)
            _register(m, DateRange(monday.isoformat(), sunday.isoformat(), m.group(), 0.85))

        # ── 4. N월 단독 ────────────────────────────────────────────────────
        for m in _RE_MONTH.finditer(text):
            if _skip(m):
                continue
            month = int(m.group(1))
            s, e = _month_range(year, month)
            _register(m, DateRange(s.isoformat(), e.isoformat(), m.group(), 0.8))

        # ── 5. 최근 N일/주/달/개월 ────────────────────────────────────────
        # 달 단위: timedelta(days=30*N) 사용. ISO 달 경계 미보장 (표준 라이브러리 제약).
        for m in _RE_RECENT.finditer(text):
            if _skip(m):
                continue
            raw_n = m.group(1)
            unit = m.group(2)
            n = _korean_num(raw_n) if raw_n else 1
            if unit == "일":
                delta = timedelta(days=n)
            elif unit in ("주", "주일"):
                delta = timedelta(weeks=n)
            elif unit in ("달", "개월", "한달"):
                delta = timedelta(days=30 * n)
            else:
                delta = timedelta(days=n)
            s = ref_date - delta + timedelta(days=1)
            _register(m, DateRange(s.isoformat(), ref_date.isoformat(), m.group(), 0.8))

        # ── 6. 이번/저번/지난/전 주·달 ────────────────────────────────────
        for m in _RE_THIS_LAST.finditer(text):
            if _skip(m):
                continue
            modifier, unit = m.group(1), m.group(2)
            is_last = modifier in ("저번", "지난", "전")
            if unit == "주":
                dow = ref_date.weekday()  # 0=월요일
                this_mon = ref_date - timedelta(days=dow)
                if is_last:
                    mon = this_mon - timedelta(weeks=1)
                else:
                    mon = this_mon
                sun = mon + timedelta(days=6)
                _register(m, DateRange(mon.isoformat(), sun.isoformat(), m.group(), 0.9))
            else:  # 달/월
                if is_last:
                    first_this = ref_date.replace(day=1)
                    last_month_end = first_this - timedelta(days=1)
                    s, e = _month_range(last_month_end.year, last_month_end.month)
                else:
                    s, e = _month_range(ref_date.year, ref_date.month)
                _register(m, DateRange(s.isoformat(), e.isoformat(), m.group(), 0.9))

        # ── 7. 오늘/어제 ───────────────────────────────────────────────────
        for m in _RE_TODAY_YEST.finditer(text):
            if _skip(m):
                continue
            d = ref_date if m.group(1) == "오늘" else ref_date - timedelta(days=1)
            _register(m, DateRange(d.isoformat(), d.isoformat(), m.group(), 1.0))

        return results
