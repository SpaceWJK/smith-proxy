"""
ops_tracker.py — 운영 지표 추적 모듈

슬랙봇의 핵심 운영 메트릭을 SQLite에 기록합니다:
  1. 캐시 히트/미스 비율 (wiki, gdi, jira)
  2. 답변 실패 건수 및 실패 질문 내역
  3. MCP 폴백 횟수/비율
  4. 응답 시간 분포

저장 위치: logs/ops_metrics.db
"""

import os
import json
import time
import sqlite3
import logging
import threading
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# ── DB 경로 ────────────────────────────────────────────────────────────
_LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
_DB_PATH = os.path.join(_LOGS_DIR, "ops_metrics.db")

# ── KST 타임존 ────────────────────────────────────────────────────────
_KST = timezone(timedelta(hours=9))


def _now_kst() -> str:
    """현재 KST ISO 문자열."""
    return datetime.now(_KST).isoformat(timespec="seconds")


def _today_kst() -> str:
    """오늘 KST 날짜 문자열 (YYYY-MM-DD)."""
    return datetime.now(_KST).strftime("%Y-%m-%d")


class OpsTracker:
    """운영 지표 기록/조회 싱글턴."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        os.makedirs(_LOGS_DIR, exist_ok=True)
        self._init_db()
        logger.info(f"[OpsTracker] 초기화 완료: {_DB_PATH}")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(_DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        conn = self._conn()
        try:
            conn.executescript("""
                -- 캐시 히트/미스 이벤트
                CREATE TABLE IF NOT EXISTS cache_events (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts         TEXT NOT NULL,
                    source     TEXT NOT NULL,  -- wiki, gdi, jira
                    event_type TEXT NOT NULL,  -- hit, miss, fallback
                    detail     TEXT,           -- sqlite_title, mcp_cql, etc.
                    query      TEXT,           -- 검색어
                    elapsed_ms INTEGER DEFAULT 0,
                    date_key   TEXT NOT NULL    -- YYYY-MM-DD (집계용)
                );

                -- 답변 결과 (성공/실패)
                CREATE TABLE IF NOT EXISTS response_events (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts         TEXT NOT NULL,
                    source     TEXT NOT NULL,  -- wiki, gdi, jira
                    user_id    TEXT,
                    channel    TEXT,
                    query      TEXT NOT NULL,   -- 사용자 원본 질문
                    result     TEXT NOT NULL,   -- success, fail, partial
                    fail_reason TEXT,           -- page_not_found, empty_answer, etc.
                    page_title TEXT,            -- 찾은 페이지 (있으면)
                    elapsed_ms INTEGER DEFAULT 0,
                    date_key   TEXT NOT NULL
                );

                -- 일별 집계 캐시 (대시보드용 빠른 조회)
                CREATE TABLE IF NOT EXISTS daily_stats (
                    date_key   TEXT NOT NULL,
                    source     TEXT NOT NULL,
                    metric     TEXT NOT NULL,   -- cache_hit, cache_miss, mcp_fallback,
                                                -- response_success, response_fail
                    count      INTEGER DEFAULT 0,
                    PRIMARY KEY (date_key, source, metric)
                );

                CREATE INDEX IF NOT EXISTS idx_cache_events_date
                    ON cache_events(date_key, source);
                CREATE INDEX IF NOT EXISTS idx_response_events_date
                    ON response_events(date_key, source);
            """)
            conn.commit()
        finally:
            conn.close()

    # ── 캐시 이벤트 기록 ──────────────────────────────────────────────

    def cache_hit(self, source: str, query: str = "",
                  detail: str = "", elapsed_ms: int = 0):
        """캐시 적중 기록."""
        self._record_cache_event(source, "hit", query, detail, elapsed_ms)

    def cache_miss(self, source: str, query: str = "",
                   detail: str = "", elapsed_ms: int = 0):
        """캐시 미스 기록."""
        self._record_cache_event(source, "miss", query, detail, elapsed_ms)

    def mcp_fallback(self, source: str, query: str = "",
                     detail: str = "", elapsed_ms: int = 0):
        """MCP 폴백 기록 (캐시 미스 → MCP 직접 호출)."""
        self._record_cache_event(source, "fallback", query, detail, elapsed_ms)

    def _record_cache_event(self, source: str, event_type: str,
                            query: str, detail: str, elapsed_ms: int):
        dk = _today_kst()
        try:
            conn = self._conn()
            conn.execute(
                "INSERT INTO cache_events (ts, source, event_type, detail, "
                "query, elapsed_ms, date_key) VALUES (?,?,?,?,?,?,?)",
                (_now_kst(), source, event_type, detail, query, elapsed_ms, dk),
            )
            # 일별 집계 갱신
            metric = f"cache_{event_type}"
            conn.execute(
                "INSERT INTO daily_stats (date_key, source, metric, count) "
                "VALUES (?,?,?,1) ON CONFLICT(date_key, source, metric) "
                "DO UPDATE SET count = count + 1",
                (dk, source, metric),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"[OpsTracker] 캐시 이벤트 기록 실패: {e}")

    # ── 답변 결과 기록 ────────────────────────────────────────────────

    def response_success(self, source: str, query: str,
                         page_title: str = "", elapsed_ms: int = 0,
                         user_id: str = "", channel: str = ""):
        """답변 성공 기록."""
        self._record_response(source, query, "success", "",
                              page_title, elapsed_ms, user_id, channel)

    def response_fail(self, source: str, query: str,
                      fail_reason: str = "unknown",
                      page_title: str = "", elapsed_ms: int = 0,
                      user_id: str = "", channel: str = ""):
        """답변 실패 기록."""
        self._record_response(source, query, "fail", fail_reason,
                              page_title, elapsed_ms, user_id, channel)

    def response_partial(self, source: str, query: str,
                         page_title: str = "", elapsed_ms: int = 0,
                         user_id: str = "", channel: str = ""):
        """부분 답변 기록 (페이지는 찾았으나 답변 품질 낮음)."""
        self._record_response(source, query, "partial", "",
                              page_title, elapsed_ms, user_id, channel)

    def _record_response(self, source: str, query: str, result: str,
                         fail_reason: str, page_title: str,
                         elapsed_ms: int, user_id: str, channel: str):
        dk = _today_kst()
        try:
            conn = self._conn()
            conn.execute(
                "INSERT INTO response_events "
                "(ts, source, user_id, channel, query, result, fail_reason, "
                "page_title, elapsed_ms, date_key) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (_now_kst(), source, user_id, channel, query, result,
                 fail_reason, page_title, elapsed_ms, dk),
            )
            metric = f"response_{result}"
            conn.execute(
                "INSERT INTO daily_stats (date_key, source, metric, count) "
                "VALUES (?,?,?,1) ON CONFLICT(date_key, source, metric) "
                "DO UPDATE SET count = count + 1",
                (dk, source, metric),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"[OpsTracker] 응답 이벤트 기록 실패: {e}")

    # ── 통계 조회 (대시보드 API용) ────────────────────────────────────

    def get_daily_summary(self, date_key: str = None,
                          days: int = 7) -> list[dict]:
        """일별 요약 통계 조회.

        Returns: [{date_key, source, cache_hit, cache_miss, cache_fallback,
                   hit_rate, response_success, response_fail, fail_rate}, ...]
        """
        if date_key is None:
            date_key = _today_kst()
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT date_key, source, metric, count FROM daily_stats "
                "WHERE date_key >= date(?, '-' || ? || ' days') "
                "ORDER BY date_key DESC, source",
                (date_key, days),
            ).fetchall()

            # pivot: (date_key, source) → {metric: count}
            pivot = {}
            for r in rows:
                key = (r["date_key"], r["source"])
                if key not in pivot:
                    pivot[key] = {"date_key": r["date_key"], "source": r["source"]}
                pivot[key][r["metric"]] = r["count"]

            result = []
            for key, data in sorted(pivot.items(), reverse=True):
                hit = data.get("cache_hit", 0)
                miss = data.get("cache_miss", 0)
                fallback = data.get("cache_fallback", 0)
                total_cache = hit + miss + fallback
                succ = data.get("response_success", 0)
                fail = data.get("response_fail", 0)
                partial = data.get("response_partial", 0)
                total_resp = succ + fail + partial

                data["cache_hit"] = hit
                data["cache_miss"] = miss
                data["cache_fallback"] = fallback
                data["hit_rate"] = round(hit / total_cache * 100, 1) if total_cache else 0
                data["response_success"] = succ
                data["response_fail"] = fail
                data["response_partial"] = partial
                data["fail_rate"] = round(fail / total_resp * 100, 1) if total_resp else 0
                result.append(data)
            return result
        finally:
            conn.close()

    def get_recent_failures(self, limit: int = 20,
                            source: str = None) -> list[dict]:
        """최근 답변 실패 내역 조회 (대시보드 표시용)."""
        conn = self._conn()
        try:
            where = "WHERE result IN ('fail', 'partial')"
            params = []
            if source:
                where += " AND source = ?"
                params.append(source)
            params.append(limit)
            rows = conn.execute(
                f"SELECT ts, source, query, result, fail_reason, "
                f"page_title, elapsed_ms, user_id, channel "
                f"FROM response_events {where} "
                f"ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_cache_efficiency(self, days: int = 7) -> dict:
        """캐시 효율성 요약 (전체 + 소스별).

        Returns: {
            "overall": {hit, miss, fallback, total, hit_rate},
            "by_source": {"wiki": {...}, "gdi": {...}, "jira": {...}},
            "period_days": 7
        }
        """
        conn = self._conn()
        try:
            date_from = (datetime.now(_KST) - timedelta(days=days)).strftime("%Y-%m-%d")
            rows = conn.execute(
                "SELECT source, event_type, COUNT(*) as cnt "
                "FROM cache_events WHERE date_key >= ? "
                "GROUP BY source, event_type",
                (date_from,),
            ).fetchall()

            by_source = {}
            overall = {"hit": 0, "miss": 0, "fallback": 0}
            for r in rows:
                src = r["source"]
                if src not in by_source:
                    by_source[src] = {"hit": 0, "miss": 0, "fallback": 0}
                by_source[src][r["event_type"]] = r["cnt"]
                overall[r["event_type"]] = overall.get(r["event_type"], 0) + r["cnt"]

            # hit_rate 계산
            for d in [overall] + list(by_source.values()):
                total = d["hit"] + d["miss"] + d["fallback"]
                d["total"] = total
                d["hit_rate"] = round(d["hit"] / total * 100, 1) if total else 0

            return {
                "overall": overall,
                "by_source": by_source,
                "period_days": days,
            }
        finally:
            conn.close()

    def get_response_summary(self, days: int = 7) -> dict:
        """답변 성공/실패 요약.

        Returns: {
            "overall": {success, fail, partial, total, fail_rate},
            "by_source": {"wiki": {...}, ...},
            "avg_elapsed_ms": {source: avg_ms, ...}
        }
        """
        conn = self._conn()
        try:
            date_from = (datetime.now(_KST) - timedelta(days=days)).strftime("%Y-%m-%d")

            # 건수 집계
            rows = conn.execute(
                "SELECT source, result, COUNT(*) as cnt "
                "FROM response_events WHERE date_key >= ? "
                "GROUP BY source, result",
                (date_from,),
            ).fetchall()

            by_source = {}
            overall = {"success": 0, "fail": 0, "partial": 0}
            for r in rows:
                src = r["source"]
                if src not in by_source:
                    by_source[src] = {"success": 0, "fail": 0, "partial": 0}
                by_source[src][r["result"]] = r["cnt"]
                overall[r["result"]] = overall.get(r["result"], 0) + r["cnt"]

            for d in [overall] + list(by_source.values()):
                total = d["success"] + d["fail"] + d["partial"]
                d["total"] = total
                d["fail_rate"] = round(d["fail"] / total * 100, 1) if total else 0

            # 평균 응답 시간
            elapsed_rows = conn.execute(
                "SELECT source, AVG(elapsed_ms) as avg_ms "
                "FROM response_events WHERE date_key >= ? AND elapsed_ms > 0 "
                "GROUP BY source",
                (date_from,),
            ).fetchall()
            avg_elapsed = {r["source"]: round(r["avg_ms"]) for r in elapsed_rows}

            return {
                "overall": overall,
                "by_source": by_source,
                "avg_elapsed_ms": avg_elapsed,
                "period_days": days,
            }
        finally:
            conn.close()


# ── 글로벌 인스턴스 ──────────────────────────────────────────────────
_tracker: OpsTracker | None = None


def get_tracker() -> OpsTracker:
    """OpsTracker 싱글턴 반환."""
    global _tracker
    if _tracker is None:
        _tracker = OpsTracker()
    return _tracker
