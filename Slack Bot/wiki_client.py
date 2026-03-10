"""
wiki_client.py - MCP 프록시(mcp.sginfra.net)를 통해 Confluence 접근

직접 wiki.smilegate.net 호출은 SAML SSO 리다이렉트로 차단되므로,
Claude Desktop이 사용하는 것과 동일한 MCP 프록시를 이용합니다.

사용 가능한 MCP 도구:
  page_exists, get_page_by_title, get_page_by_id, get_page_id,
  get_all_pages_from_space, create_page, update_page, get_all_spaces,
  cql_search, get_page_comments, add_comment, test_confluence_connection


환경변수:
  CONFLUENCE_URL        : https://wiki.smilegate.net (페이지 URL 생성용)
  CONFLUENCE_TOKEN      : MCP 프록시 토큰 (x-confluence-wiki-token)
  CONFLUENCE_USERNAME   : MCP 사용자명 (x-confluence-wiki-username, 기본: es-wjkim)
  CONFLUENCE_SPACE_KEY  : 공간 키 (기본: QASGP)
"""

import os
import re
import json
import html as _html
import logging
import time
import requests

from mcp_session import McpSession

# ── MCP 캐시 레이어 (optional — import 실패 시 캐시 없이 동작) ──────────────
try:
    import sys as _sys
    _sys.path.insert(0, "D:/Vibe Dev/QA Ops/mcp-cache-layer")
    from src.cache_manager import CacheManager as _CacheManager
    from src.cache_logger import ops_log as _ops_log, perf as _perf
    _wiki_cache = _CacheManager()
    _CACHE_ENABLED = True
except Exception:
    _wiki_cache = None
    _ops_log = None
    _perf = None
    _CACHE_ENABLED = False

logger = logging.getLogger(__name__)

# ── wiki 조회 전용 로거 (logs/wiki_query.log) ──────────────────────────────
_wiki_query_logger: "logging.Logger | None" = None

def _get_wiki_query_logger() -> logging.Logger:
    """wiki 조회 전용 로거를 반환합니다. 최초 호출 시 파일 핸들러를 설정합니다."""
    global _wiki_query_logger
    if _wiki_query_logger is not None:
        return _wiki_query_logger

    _wiki_query_logger = logging.getLogger("wiki_query")
    _wiki_query_logger.setLevel(logging.INFO)
    _wiki_query_logger.propagate = False  # 루트 로거로 전파 방지

    # logs/ 디렉토리 (프로젝트 루트 기준)
    bot_dir  = os.path.dirname(os.path.abspath(__file__))
    logs_dir = os.path.join(os.path.dirname(bot_dir), "logs")
    os.makedirs(logs_dir, exist_ok=True)

    log_path = os.path.join(logs_dir, "wiki_query.log")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    _wiki_query_logger.addHandler(fh)
    return _wiki_query_logger


def log_wiki_query(*, user_id: str = "", user_name: str = "",
                   action: str, query: str, result: str = "",
                   error: str = "", elapsed_ms: int = 0,
                   cache_status: str = ""):
    """
    /wiki 조회 내역을 logs/wiki_query.log 에 기록합니다.

    Parameters
    ----------
    user_id      : Slack 사용자 ID (예: U07PHCE4RCM)
    user_name    : Slack 사용자명 (예: es-wjkim)
    action       : 동작 종류 (search / get_page / ask_claude / get_latest 등)
    query        : 검색어 또는 페이지 제목
    result       : 결과 요약 (예: "페이지 발견: Game Service 1")
    error        : 에러 메시지 (없으면 빈 문자열)
    elapsed_ms   : 소요 시간 (밀리초)
    cache_status : 캐시 상태 (hit / miss / stale / disabled, 빈 문자열=미사용)
    """
    wl = _get_wiki_query_logger()
    status = "ERROR" if error else "OK"
    user   = f"{user_name}({user_id})" if user_id else (user_name or "unknown")

    msg = f"{status} | {action} | user={user} | query={query}"
    if cache_status:
        msg += f" | cache={cache_status}"
    if result:
        msg += f" | result={result}"
    if error:
        msg += f" | error={error}"
    if elapsed_ms > 0:
        msg += f" | {elapsed_ms}ms"

    if error:
        wl.error(msg)
    else:
        wl.info(msg)

MCP_URL            = "http://mcp.sginfra.net/confluence-wiki-mcp"
_DEFAULT_SPACE_KEY = "QASGP"
_DEFAULT_USERNAME  = "es-wjkim"
_DEFAULT_WIKI_URL  = "https://wiki.smilegate.net"

# ── 페이지 콘텐츠 TTL 캐시 ────────────────────────────────────────────────
_PAGE_CACHE: dict = {}   # {page_id: (plain_text, timestamp)}
_PAGE_CACHE_TTL   = 300  # 5분 (초)

# ── HTML 처리 헬퍼 ─────────────────────────────────────────────────────────

def _strip_html(html_text: str) -> str:
    """HTML 태그 제거 + 엔티티 디코딩 → 읽기 쉬운 일반 텍스트

    - script/style 태그와 내용 전체 제거 (JS·CSS 코드 잡음 방지)
    - 테이블 행/열 구조를 | 구분자로 보존 (셀 간 관계 유지)
    - 나머지 HTML 태그 제거 후 공백 정규화
    """
    # 1. script / style 태그 + 내용 전체 제거
    text = re.sub(
        r'<(script|style)[^>]*>.*?</\1>', '',
        html_text or '', flags=re.DOTALL | re.IGNORECASE,
    )
    # 2. 테이블 구조 보존: 셀 경계 → ' | ', 행 경계 → '\n'
    text = re.sub(r'</t[dh]>\s*<t[dh][^>]*>', ' | ', text, flags=re.IGNORECASE)
    text = re.sub(r'</?tr[^>]*>', '\n', text, flags=re.IGNORECASE)
    # 3. 나머지 HTML 태그 제거
    text = re.sub(r'<[^>]+>', ' ', text)
    # 4. HTML 엔티티 디코딩
    text = _html.unescape(text)
    # 5. 공백 정규화
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n[ \t]+', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _clean_title(title: str) -> str:
    """검색 결과 제목에서 하이라이트 마커 제거 (@@@hl@@@...@@@endhl@@@)"""
    return re.sub(r'@@@hl@@@|@@@endhl@@@', '', title or '').strip()


# ── 싱글톤 MCP 세션 (mcp_session.McpSession 사용) ────────────────────────

_mcp_session: "McpSession | None" = None

def _get_mcp() -> McpSession:
    global _mcp_session
    if _mcp_session is None:
        _mcp_session = McpSession(
            url=MCP_URL,
            headers={
                "x-confluence-wiki-username": os.getenv("CONFLUENCE_USERNAME", _DEFAULT_USERNAME),
                "x-confluence-wiki-token"   : os.getenv("CONFLUENCE_TOKEN", ""),
            },
            label="wiki",
        )
    return _mcp_session


# ── ConfluenceWikiClient ──────────────────────────────────────────────────

class ConfluenceWikiClient:
    """
    Slack Bot에서 사용하는 Confluence 클라이언트.

    내부적으로 MCP 프록시(mcp.sginfra.net)를 통해 Confluence에 접근합니다.
    """

    def __init__(self):
        self._space_key = os.getenv("CONFLUENCE_SPACE_KEY", _DEFAULT_SPACE_KEY)
        self._wiki_url  = os.getenv("CONFLUENCE_URL", _DEFAULT_WIKI_URL).rstrip("/")
        self._mcp       = _get_mcp()

    # ── 페이지 조회 ───────────────────────────────────────────────────────

    def get_page_by_title(self, title: str, space_key: str = None,
                          fetch_full: bool = True):
        """
        페이지 제목으로 Confluence 페이지 조회.
        (get_page_by_title MCP 도구는 서버 버그로 cql_search로 대체)

        Parameters
        ----------
        fetch_full : bool
            True  → get_page_by_id 로 전체 본문 조회 (AI 질의용)
            False → cql_search 의 body.view excerpt 만 사용 (표시 전용, 빠름)

        Returns
        -------
        (page_dict | None, error_str | None)
          page_dict = {"id", "title", "url", "text"}
        """
        sk  = space_key or self._space_key
        # title ~ "..." : 부분 일치 (제목에 키워드 포함)
        cql = (f'title ~ "{title}" AND space = "{sk}"'
               f' AND type=page ORDER BY lastmodified DESC')
        logger.info(f"[wiki] 제목 검색 CQL: {cql} (fetch_full={fetch_full})")

        raw, err = self._mcp.call_tool(
            "cql_search",
            {"cql": cql, "limit": 5, "expand": "body.view"},
        )
        if err:
            return None, err

        results = self._parse_cql_results(raw)
        if not results:
            return None, f"'{title}' 페이지를 찾을 수 없습니다. (공간: {sk})"
        return self._cql_result_to_page_dict(results[0], title,
                                             fetch_full=fetch_full), None

    def get_page_by_path(self, ancestors: list, leaf_title: str,
                         space_key: str = None, fetch_full: bool = True):
        """
        조상 페이지 경로 포함 검색.
        ancestor 조건 CQL이 파싱 실패하면 제목만으로 재시도합니다.

        Parameters
        ----------
        fetch_full : bool
            True  → get_page_by_id 로 전체 본문 조회 (AI 질의용)
            False → cql_search 의 body.view excerpt 만 사용 (표시 전용, 빠름)

        Returns
        -------
        (page_dict | None, error_str | None)
        """
        import re as _re
        sk = space_key or self._space_key

        # fetch_full=False 면 body.view 를 cql_search 에서 함께 가져옴
        expand_param = {} if fetch_full else {"expand": "body.view"}

        # CQL 파싱 오류를 일으키는 특수문자([]{}) 포함 ancestor는 제외
        _CQL_SPECIAL = _re.compile(r'[\[\]{}()\^\\]')
        safe_ancestors = [a.strip() for a in ancestors
                          if a.strip() and not _CQL_SPECIAL.search(a.strip())]
        skipped = [a.strip() for a in ancestors
                   if a.strip() and _CQL_SPECIAL.search(a.strip())]
        if skipped:
            logger.info(f"[wiki][경로검색] CQL 특수문자 포함 ancestor 제외: {skipped}")

        ancestor_conditions = " AND ".join(
            f'ancestor = "{a}"' for a in safe_ancestors
        )

        # ── 1차: (안전한) ancestor 조건 포함 CQL ─────────────────────────────
        cql = f'title ~ "{leaf_title}" AND space = "{sk}" AND type=page'
        if ancestor_conditions:
            cql += f" AND {ancestor_conditions}"
        cql += " ORDER BY lastmodified DESC"

        logger.info(f"[wiki][1차] CQL: {cql}")
        raw, err = self._mcp.call_tool(
            "cql_search", {"cql": cql, "limit": 5, **expand_param}
        )

        # ── 2차: CQL 파싱 오류 시 ancestor 없이 재시도 ───────────────────────
        if err and "cannot be parsed" in err.lower():
            logger.warning(f"[wiki][1차] CQL 파싱 오류 → 2차 폴백 (ancestor 제거)")
            cql2 = (f'title ~ "{leaf_title}" AND space = "{sk}"'
                    f' AND type=page ORDER BY lastmodified DESC')
            logger.info(f"[wiki][2차] CQL: {cql2}")
            raw, err = self._mcp.call_tool(
                "cql_search", {"cql": cql2, "limit": 5, **expand_param}
            )

        if err:
            logger.error(f"[wiki][검색실패] MCP 오류: {err}")
            return None, err

        results = self._parse_cql_results(raw)
        logger.info(f"[wiki][결과] 1~2차 검색 결과: {len(results)}건")

        # ── 3차: 결과 없을 때 → ancestor 없이 재시도 (1차가 ancestor로 실패한 경우) ──
        if not results and ancestor_conditions:
            logger.warning(f"[wiki][2차] 결과 없음 → 3차 폴백 (ancestor 완전 제거)")
            cql3 = (f'title ~ "{leaf_title}" AND space = "{sk}"'
                    f' AND type=page ORDER BY lastmodified DESC')
            logger.info(f"[wiki][3차] CQL: {cql3}")
            raw2, err2 = self._mcp.call_tool(
                "cql_search", {"cql": cql3, "limit": 5, **expand_param}
            )
            if not err2:
                results = self._parse_cql_results(raw2)
                logger.info(f"[wiki][결과] 3차 검색 결과: {len(results)}건")
            else:
                logger.error(f"[wiki][3차] MCP 오류: {err2}")

        if not results:
            path_str = " > ".join(list(ancestors) + [leaf_title])
            logger.warning(f"[wiki][최종실패] 경로 '{path_str}' — 페이지 없음")
            return None, (
                f"'{path_str}' 경로의 페이지를 찾을 수 없습니다. (공간: {sk})\n"
                f"💡 힌트: `/wiki {leaf_title}` 로 제목만 검색하거나 `/wiki search {leaf_title}` 로 유사 페이지를 확인해보세요."
            )

        return self._cql_result_to_page_dict(results[0], leaf_title,
                                             fetch_full=fetch_full), None

    def get_latest_descendant(self, page_title: str, space_key: str = None,
                              fetch_full: bool = True):
        """
        지정 페이지의 하위 페이지 중 가장 최근 생성된 페이지를 조회합니다.

        '최근/최신' 키워드 쿼리 최적화 전략:
          - 상위 페이지 전체 본문(예: 2026_MGQA) 대신 하위 페이지 1개만 가져와
            토큰 소모를 최소화합니다.
          - 상위 페이지 본문에는 월별 하위 링크가 가장 오래된 것부터 노출되어
            '가장 최근' 질문에 1월 데이터를 답변하는 오류를 방지합니다.

        Parameters
        ----------
        page_title : str
            부모/조상 페이지 제목 (예: "2026_MGQA", "에픽세븐")
        space_key  : str, optional
            Confluence 공간 키 (미지정 시 _space_key 사용)
        fetch_full : bool
            True  → get_page_by_id 로 전체 본문 조회 (AI 질의용)
            False → cql_search body.view 만 사용 (표시 전용, 빠름)

        Returns
        -------
        (page_dict | None, error_str | None)
          page_dict = {"id", "title", "url", "text"}
        """
        sk  = space_key or self._space_key
        cql = (f'ancestor = "{page_title}" AND space = "{sk}"'
               f' AND type=page ORDER BY created DESC')
        logger.info(f"[wiki][최신하위] CQL: {cql}")

        raw, err = self._mcp.call_tool(
            "cql_search",
            {"cql": cql, "limit": 1, "expand": "body.view"},
        )
        if err:
            logger.error(f"[wiki][최신하위] MCP 오류: {err}")
            return None, err

        results = self._parse_cql_results(raw)
        logger.info(f"[wiki][최신하위] 결과: {len(results)}건")

        if not results:
            return None, (
                f"'{page_title}' 의 하위 페이지를 찾을 수 없습니다. (공간: {sk})\n"
                f"💡 힌트: 페이지 제목을 정확히 입력했는지 확인하세요."
            )

        return self._cql_result_to_page_dict(
            results[0], page_title, fetch_full=fetch_full
        ), None

    def search_pages(self, query: str, space_key: str = None):
        """
        텍스트 검색으로 페이지 목록 반환.

        Returns
        -------
        (list[{"id", "title"}] | None, error_str | None)
        """
        sk  = space_key or self._space_key
        cql = (f'space="{sk}" AND text ~ "{query}"'
               f' AND type=page ORDER BY lastmodified DESC')
        raw, err = self._mcp.call_tool("cql_search", {"cql": cql, "limit": 10})
        if err:
            return None, err

        results = self._parse_cql_results(raw)
        pages = []
        for r in results:
            content = r.get("content", {}) if isinstance(r, dict) else {}
            pages.append({
                "id"   : content.get("id", ""),
                "title": _clean_title(r.get("title") or content.get("title") or ""),
            })
        return pages, None

    def get_page_content(self, page_id: str) -> tuple:
        """
        페이지 ID로 전체 본문 조회 (get_page_by_id MCP 도구).
        cql_search 의 excerpt 대신 실제 페이지 전체 내용을 가져옵니다.

        캐시 순서: L1 인메모리(_PAGE_CACHE) → L2 SQLite → L3 MCP 호출

        Returns: (plain_text | None, error_str | None)
        """
        t0 = _perf.now_ms() if _perf else 0

        # ── L1: 인메모리 캐시 적중 확인 ─────────────────────────────────
        cached = _PAGE_CACHE.get(page_id)
        if cached and (time.time() - cached[1]) < _PAGE_CACHE_TTL:
            elapsed = _perf.elapsed_ms(t0) if _perf else 0
            logger.info(f"[wiki] 인메모리 캐시 적중 (TTL {_PAGE_CACHE_TTL}s): id={page_id}")
            if _ops_log:
                _ops_log.cache_hit(f"page#{page_id}", source="memory",
                                   elapsed_ms=elapsed)
            return cached[0], None

        # ── L2: SQLite 캐시 적중 확인 ───────────────────────────────────
        if _CACHE_ENABLED:
            try:
                node = _wiki_cache.get_node("wiki", page_id)
                if node and not _wiki_cache.is_stale(node["id"]):
                    content = _wiki_cache.get_content(node["id"])
                    if content and content["body_text"]:
                        _PAGE_CACHE[page_id] = (content["body_text"], time.time())
                        elapsed = _perf.elapsed_ms(t0) if _perf else 0
                        logger.info(f"[wiki] SQLite 캐시 적중: id={page_id}, chars={content['char_count']}")
                        if _ops_log:
                            _ops_log.cache_hit(
                                node.get("title", f"page#{page_id}"),
                                source="sqlite", node_id=node["id"],
                                elapsed_ms=elapsed,
                            )
                        return content["body_text"], None
            except Exception as e:
                logger.warning(f"[wiki] SQLite 캐시 조회 실패 (무시): {e}")

        # ── L3: MCP 호출 ────────────────────────────────────────────────
        mcp_t0 = _perf.now_ms() if _perf else 0
        raw, err = self._mcp.call_tool(
            "get_page_by_id",
            {"page_id": page_id, "expand": "body.view"},
        )
        mcp_elapsed = _perf.elapsed_ms(mcp_t0) if _perf else 0

        if err:
            logger.warning(f"[wiki] get_page_by_id 실패 (id={page_id}): {err}")
            if _ops_log:
                _ops_log.cache_miss(f"page#{page_id}", reason="mcp_error",
                                    elapsed_ms=_perf.elapsed_ms(t0) if _perf else 0)
            return None, err

        data = self._parse_raw(raw)
        if not isinstance(data, dict):
            return None, "페이지 데이터 형식 오류"

        body_val  = data.get("body", {})
        html_body = (body_val.get("view", {}).get("value", "")
                     if isinstance(body_val, dict) else "")

        if html_body:
            text = _strip_html(html_body)
            title = data.get("title", f"page#{page_id}")
            total_elapsed = _perf.elapsed_ms(t0) if _perf else 0

            # ── 인메모리 캐시 저장 ─────────────────────────────────────
            _PAGE_CACHE[page_id] = (text, time.time())
            logger.info(
                f"[wiki] 전체 본문 캐시 저장: id={page_id}, "
                f"html_len={len(html_body)}, text_len={len(text)}"
            )

            if _ops_log:
                _ops_log.cache_miss(title, reason="not_cached",
                                    elapsed_ms=total_elapsed)

            # ── SQLite 캐시 저장 ───────────────────────────────────────
            if _CACHE_ENABLED:
                try:
                    version_data = data.get("version", {})
                    _wiki_cache.put_page(
                        "wiki", page_id, title or f"page_{page_id}",
                        space_key=self._space_key,
                        last_modified=version_data.get("when") if isinstance(version_data, dict) else None,
                        version=version_data.get("number") if isinstance(version_data, dict) else None,
                        author=(version_data.get("by", {}).get("displayName")
                                if isinstance(version_data, dict) else None),
                        body_raw=html_body,
                        body_text=text,
                    )
                    logger.info(f"[wiki] SQLite 캐시 저장: id={page_id}, title={title}")
                except Exception as e:
                    logger.warning(f"[wiki] SQLite 캐시 저장 실패 (무시): {e}")

            return text, None

        return None, "본문(body.view)을 찾을 수 없습니다"

    # ── 내부 파싱 헬퍼 ────────────────────────────────────────────────────

    def _parse_raw(self, raw) -> object:
        """raw(str 또는 dict) → Python 객체"""
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except Exception:
                return raw     # 순수 텍스트
        return raw

    def _parse_cql_results(self, raw) -> list:
        """cql_search 응답에서 results 목록 추출"""
        data = self._parse_raw(raw)
        if isinstance(data, dict):
            return data.get("results", [])
        elif isinstance(data, list):
            return data
        return []

    def _cql_result_to_page_dict(self, result: dict, fallback_title: str,
                                 fetch_full: bool = True) -> dict:
        """
        cql_search 결과의 단일 항목 → 표준 page_dict 변환.

        Parameters
        ----------
        fetch_full : bool
            True  → get_page_by_id 로 전체 본문 추가 조회 (AI 질의에 필요)
            False → cql_search 응답의 body.view / excerpt 만 사용 (빠른 표시 전용)

        cql_search 응답 구조:
          {
            "content": {"id": "...", "title": "...", "_links": {"webui": "/pages/..."}, "body": {...}},
            "title"  : "...",
            "excerpt": "...",
            "url"    : "/pages/...",
            ...
          }
        """
        content    = result.get("content", {}) if isinstance(result, dict) else {}
        page_id    = content.get("id", "")
        page_title = _clean_title(
            result.get("title") or content.get("title") or fallback_title
        )

        # URL 구성 (상대 경로 → 절대 경로)
        rel_url = (result.get("url")
                   or content.get("_links", {}).get("webui")
                   or (f"/pages/viewpage.action?pageId={page_id}" if page_id else ""))
        page_url = (f"{self._wiki_url}{rel_url}"
                    if rel_url.startswith("/") else
                    (rel_url or f"{self._wiki_url}/search?q={fallback_title}"))

        # excerpt 추출 (하이라이트 마커 제거 후 HTML 엔티티 디코딩)
        # @@@hl@@@...@@@endhl@@@ 패턴 제거
        excerpt_raw  = result.get("excerpt", "")
        excerpt_text = _html.unescape(
            re.sub(r'@@@\w+@@@', '', excerpt_raw)
        ).strip()

        # 전체 본문 조회: fetch_full=True 이고 page_id 있을 때만 get_page_by_id 호출
        # fetch_full=False (표시 전용) → MCP 추가 호출 없이 cql 응답 body.view 사용
        text = ""
        if fetch_full and page_id:
            full_text, ferr = self.get_page_content(page_id)
            if full_text:
                # excerpt가 있으면 관련 섹션 힌트로 전체 내용 앞에 포함
                # → Claude 가 검색에서 가장 연관된 섹션을 우선 참고할 수 있도록
                # (예: 다년도 데이터 페이지에서 특정 연도 데이터에 집중)
                if excerpt_text:
                    text = (
                        f"[검색 관련 섹션]\n{excerpt_text}\n\n"
                        f"[전체 페이지 내용]\n{full_text}"
                    )
                else:
                    text = full_text
            else:
                logger.warning(f"[wiki] 전체 본문 조회 실패, excerpt 사용: {ferr}")

        # fetch_full=False 이거나 전체 본문 조회 실패 시 → body.view 또는 excerpt 사용
        if not text:
            body_val  = content.get("body", {})
            html_body = (body_val.get("view", {}).get("value", "")
                         if isinstance(body_val, dict) else "")
            text = (_strip_html(html_body)
                    if html_body
                    else (excerpt_text or _html.unescape(excerpt_raw)))

        # ── SQLite 캐시에 메타데이터 저장 (본문 조회 여부와 무관) ──────────
        if _CACHE_ENABLED and page_id:
            try:
                version_data = content.get("version", {})
                _wiki_cache.upsert_node(
                    "wiki", page_id, page_title,
                    space_key=self._space_key, url=page_url,
                )
                node = _wiki_cache.get_node("wiki", page_id)
                if node:
                    _wiki_cache.upsert_meta(
                        node["id"],
                        last_modified=version_data.get("when") if isinstance(version_data, dict) else None,
                        version=version_data.get("number") if isinstance(version_data, dict) else None,
                    )
            except Exception as e:
                logger.debug(f"[wiki] CQL 결과 캐시 저장 실패 (무시): {e}")

        logger.debug(f"[wiki] 페이지 파싱: id={page_id}, title={page_title}, "
                     f"fetch_full={fetch_full}, text_len={len(str(text))}")
        return {"id": page_id, "title": page_title, "url": page_url, "text": text}
