# -*- coding: utf-8 -*-
"""
ttl_policy.py — 쿼리 타입별 L1/L2 TTL 정책 (task-107)
외부 의존성 없음 (re, enum, dataclasses 표준 라이브러리만).

QueryType 분류 우선순위:
  1. date_ranges 비어있지 않음 → TIME_BOUNDED
  2. volatile 키워드(이슈/버그/장애...) → NORMAL  (STATIC 오분류 방지)
  3. static 키워드(기획/설계/게임명...) → STATIC
  4. 기본값 → NORMAL
"""
import re
from enum import Enum
from dataclasses import dataclass

__all__ = ["QueryType", "TTLPolicy", "TTL_TABLE", "classify_query", "get_ttl"]


class QueryType(Enum):
    TIME_BOUNDED = "time_bounded"
    NORMAL = "normal"
    STATIC = "static"


@dataclass(frozen=True)
class TTLPolicy:
    l1_ttl_sec: int       # L1 메모리 캐시 TTL (초)
    l2_skip_cache: bool   # True: L2 저장 skip (TIME_BOUNDED용)
    l2_ttl_hours: int     # L2 SQLite 캐시 TTL (시간, l2_skip_cache=False일 때만 사용)


TTL_TABLE: dict = {
    QueryType.TIME_BOUNDED: TTLPolicy(l1_ttl_sec=60,  l2_skip_cache=True,  l2_ttl_hours=0),
    QueryType.NORMAL:       TTLPolicy(l1_ttl_sec=300, l2_skip_cache=False, l2_ttl_hours=24),
    QueryType.STATIC:       TTLPolicy(l1_ttl_sec=300, l2_skip_cache=False, l2_ttl_hours=168),
}

# volatile 키워드: STATIC 오분류 방지 — 우선 체크
_VOLATILE_PATTERN = re.compile(r'이슈|버그|티켓|장애|담당|스프린트|진행|대기|처리')
# static 키워드: 안정적 게임 문서
_STATIC_PATTERN = re.compile(
    r'기획[서문안]?|설계[서문]?|정책|가이드|에픽세븐|카제나|이터널|[Ee]pic|카오스|[Cc]haos'
)


def classify_query(query: str, date_ranges: list) -> QueryType:
    """쿼리 타입 분류. 우선순위: TIME_BOUNDED > NORMAL(volatile) > STATIC > NORMAL(기본)

    Args:
        query: 검색 쿼리 텍스트
        date_ranges: DateRange 리스트 (task-106). 비어있지 않으면 TIME_BOUNDED.

    Returns:
        QueryType 열거형
    """
    if date_ranges:
        return QueryType.TIME_BOUNDED
    if _VOLATILE_PATTERN.search(query):
        return QueryType.NORMAL
    if _STATIC_PATTERN.search(query):
        return QueryType.STATIC
    return QueryType.NORMAL


def get_ttl(query_type: QueryType) -> tuple:
    """(l1_ttl_sec, l2_skip_cache, l2_ttl_hours) 반환.

    알 수 없는 타입 → NORMAL 기본값으로 안전 폴백.

    Args:
        query_type: QueryType 열거형

    Returns:
        (l1_ttl_sec: int, l2_skip_cache: bool, l2_ttl_hours: int)
    """
    policy = TTL_TABLE.get(query_type, TTL_TABLE[QueryType.NORMAL])
    return policy.l1_ttl_sec, policy.l2_skip_cache, policy.l2_ttl_hours
