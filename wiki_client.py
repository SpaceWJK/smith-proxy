"""
wiki_client.py - MCP 프록시(mcp.sginfra.net)를 통해 Confluence 접근

직접 wiki.smilegate.net 호출은 SAML SSO 리다이렉트로 차단되므로,
Claude Desktop이 사용하는 것과 동일한 MCP 프록시를 이용합니다.

사용 가능한 MCP 도구:
  page_exists, get_page_by_title, get_page_by_id, get_page_id,
  get_all_pages_from_space, create_page, update_page, get_all_spaces,
  cql_search, get_page_comments, add_comment, test_confluence_connection

※ Team Calendar 도구는 MCP 서버에서 제공하지 않아 /calendar 기능 비활성화.

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

logger = logging.getLogger(__name__)

MCP_URL            = "http://mcp.sginfra.net/confluence-wiki-mcp"
_DEFAULT_SPACE_KEY = "QASGP"
_DEFAULT_USERNAME  = "es-wjkim"
_DEFAULT_WIKI_URL  = "https://wiki.smilegate.net"

# ── 페이지 콘텐츠 TTL 캐시 ────────────────────────────────────────────────
_PAGE_CACHE: dict = {}   # {page_id: (plain_text, timestamp)}
_PAGE_CACHE_TTL   = 300  # 5분 (초)

# 슬랙 명령어 캘린더 유형 → 환경변수 키 & 표시명 매핑 (하위 호환 유지)
CALENDAR_TYPES = {
    "플잭": ("CONFLUENCE_CALENDAR_PROJECT",  "프로젝트 일정"),
    "개인": ("CONFLUENCE_CALENDAR_PERSONAL", "개인/팀 일정"),
}


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


# ── MCP 세션 (Streamable HTTP 프로토콜) ───────────────────────────────────

class _McpSession:
    """
    MCP Streamable HTTP 세션.

    프로토콜 요약:
      1. POST /mcp-endpoint  {initialize}  → 세션 ID 발급, SSE 응답
      2. POST /mcp-endpoint  {notifications/initialized}  → 202
      3. POST /mcp-endpoint  {tools/call}  + Mcp-Session-Id 헤더 → SSE 응답
    """

    def __init__(self, url: str, username: str, token: str):
        self._url         = url
        self._session_id  = None
        self._initialized = False
        self._req_id      = 0

        self._http = requests.Session()
        self._http.headers.update({
            "x-confluence-wiki-username": username,
            "x-confluence-wiki-token"  : token,
            "Content-Type"             : "application/json",
            "Accept"                   : "application/json, text/event-stream",
        })

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _extra_headers(self) -> dict:
        return {"Mcp-Session-Id": self._session_id} if self._session_id else {}

    @staticmethod
    def _is_session_error(err: str) -> bool:
        """세션 만료/인증 오류 여부 판단 — 재연결 트리거용"""
        low = (err or "").lower()
        return any(kw in low for kw in (
            "session", "http 400", "http 401", "http 403", "unauthorized",
        ))

    @staticmethod
    def _parse_sse(text: str):
        """SSE 스트림 텍스트에서 첫 번째 data 라인의 JSON 반환"""
        for line in text.split('\n'):
            line = line.strip()
            if line.startswith('data: '):
                try:
                    return json.loads(line[6:])
                except Exception:
                    pass
        return None

    def _post(self, payload: dict, timeout: int = 30) -> tuple:
        """
        JSON-RPC 2.0 POST 요청 → (rpc_result_or_none, error_str_or_none)
        """
        try:
            r = self._http.post(
                self._url, json=payload,
                headers=self._extra_headers(), timeout=timeout,
            )

            # 세션 ID 갱신
            sid = (r.headers.get("Mcp-Session-Id")
                   or r.headers.get("mcp-session-id"))
            if sid:
                self._session_id = sid

            if r.status_code == 202:          # 알림에 대한 정상 응답
                return None, None
            if r.status_code >= 400:
                # 세션 만료/인증 오류 → 세션 상태 초기화 (call_tool 재연결 대비)
                if r.status_code in (400, 401, 403):
                    self._initialized = False
                    self._session_id  = None
                return None, f"HTTP {r.status_code}: {r.text[:300]}"

            ct = r.headers.get("Content-Type", "")
            if "text/event-stream" in ct:
                # r.text 는 Content-Type 에 charset 미선언 시 ISO-8859-1 로 디코딩됨
                # (requests HTTP/1.1 기본값) → 한글 등 멀티바이트 문자 깨짐 발생
                # SSE 응답은 실제로 UTF-8 이므로 r.content 를 명시적으로 UTF-8 디코딩
                sse_text = r.content.decode('utf-8', errors='replace')
                data = self._parse_sse(sse_text)
            else:
                try:
                    data = r.json()
                except Exception:
                    return None, f"응답 파싱 실패: {r.text[:300]}"

            if data is None:
                return None, "빈 응답"
            if "error" in data:
                err = data["error"]
                return None, err.get("message", str(err))
            return data.get("result"), None

        except requests.RequestException as e:
            return None, str(e)

    # ── 공개 메서드 ───────────────────────────────────────────────────────

    def initialize(self) -> tuple:
        """MCP 세션 초기화 (최초 1회). → (True/False, error_str)"""
        if self._initialized:
            return True, None

        result, err = self._post({
            "jsonrpc": "2.0",
            "method" : "initialize",
            "id"     : self._next_id(),
            "params" : {
                "protocolVersion": "2024-11-05",
                "capabilities"   : {},
                "clientInfo"     : {"name": "slack-bot", "version": "1.0"},
            },
        })
        if err:
            logger.error(f"[wiki] MCP 초기화 실패: {err}")
            return False, f"MCP 초기화 실패: {err}"

        # notifications/initialized (응답 무시)
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"},
                   timeout=10)

        self._initialized = True
        logger.info(f"[wiki] MCP 세션 초기화 완료. session_id={self._session_id}")
        return True, None

    def call_tool(self, name: str, arguments: dict,
                  _retry: bool = True) -> tuple:
        """
        MCP 도구 호출. 세션 만료 감지 시 자동 재연결 후 1회 재시도.

        Returns
        -------
        (raw_content, error_str)
          raw_content : 도구가 반환한 텍스트 (JSON 문자열인 경우 많음)
        """
        ok, err = self.initialize()
        if not ok:
            return None, err

        result, err = self._post({
            "jsonrpc": "2.0",
            "method" : "tools/call",
            "id"     : self._next_id(),
            "params" : {"name": name, "arguments": arguments},
        })

        # 세션 만료 감지 → 세션 리셋 후 1회 재시도
        if err and _retry and self._is_session_error(err):
            logger.warning(
                f"[wiki] 세션 만료 감지, 재연결 후 재시도 ({name}): {err[:80]}"
            )
            self._initialized = False
            self._session_id  = None
            return self.call_tool(name, arguments, _retry=False)

        if err:
            logger.error(f"[wiki] MCP 도구 호출 오류 ({name}): {err}")
            return None, err

        # result = {"content": [{"type":"text","text":"..."}], "isError": false}
        if isinstance(result, dict):
            is_err = result.get("isError", False)
            content = result.get("content", [])
            parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            text = "\n".join(parts)
            if is_err:
                logger.warning(f"[wiki] MCP 도구 오류 ({name}): {text[:200]}")
                return None, text or "도구 오류"
            return text, None

        return str(result) if result is not None else None, None


# ── 싱글톤 세션 ──────────────────────────────────────────────────────────

_mcp_session: "_McpSession | None" = None

def _get_mcp() -> _McpSession:
    global _mcp_session
    if _mcp_session is None:
        _mcp_session = _McpSession(
            url      = MCP_URL,
            username = os.getenv("CONFLUENCE_USERNAME", _DEFAULT_USERNAME),
            token    = os.getenv("CONFLUENCE_TOKEN", ""),
        )
    return _mcp_session


# ── ConfluenceCalendarClient (기존 인터페이스 유지) ────────────────────────

class ConfluenceCalendarClient:
    """
    Slack Bot에서 사용하는 Confluence 클라이언트.

    내부적으로 MCP 프록시(mcp.sginfra.net)를 통해 Confluence에 접근합니다.
    Team Calendar 기능은 MCP 서버가 지원하지 않아 비활성화되었습니다.
    """

    def __init__(self):
        self._space_key = os.getenv("CONFLUENCE_SPACE_KEY", _DEFAULT_SPACE_KEY)
        self._wiki_url  = os.getenv("CONFLUENCE_URL", _DEFAULT_WIKI_URL).rstrip("/")
        self._mcp       = _get_mcp()

    # ── Team Calendar (미지원) ────────────────────────────────────────────

    def list_calendars(self, space_key: str = None):
        """캘린더 목록 조회 — MCP 서버 미지원"""
        return None, (
            "Team Calendar 기능은 현재 MCP 서버에서 지원되지 않습니다.\n"
            "직접 Confluence 캘린더 페이지를 이용해 주세요: "
            f"{self._wiki_url}/spaces/{self._space_key or self._space_key}"
        )

    def create_event(self, calendar_id: str, title: str,
                     start_date: str, end_date: str = None):
        """이벤트 등록 — MCP 서버 미지원"""
        return None, "Team Calendar 기능은 현재 MCP 서버에서 지원되지 않습니다."

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
        결과는 _PAGE_CACHE_TTL 초 동안 캐시되어 반복 조회 시 재사용됩니다.

        Returns: (plain_text | None, error_str | None)
        """
        # ── 캐시 적중 확인 ──────────────────────────────────────────────
        cached = _PAGE_CACHE.get(page_id)
        if cached and (time.time() - cached[1]) < _PAGE_CACHE_TTL:
            logger.info(f"[wiki] 캐시 적중 (TTL {_PAGE_CACHE_TTL}s): id={page_id}")
            return cached[0], None

        # ── MCP 호출 ────────────────────────────────────────────────────
        raw, err = self._mcp.call_tool(
            "get_page_by_id",
            {"page_id": page_id, "expand": "body.view"},
        )
        if err:
            logger.warning(f"[wiki] get_page_by_id 실패 (id={page_id}): {err}")
            return None, err

        data = self._parse_raw(raw)
        if not isinstance(data, dict):
            return None, "페이지 데이터 형식 오류"

        body_val  = data.get("body", {})
        html_body = (body_val.get("view", {}).get("value", "")
                     if isinstance(body_val, dict) else "")

        if html_body:
            text = _strip_html(html_body)
            # ── 캐시 저장 ──────────────────────────────────────────────
            _PAGE_CACHE[page_id] = (text, time.time())
            logger.info(
                f"[wiki] 전체 본문 캐시 저장: id={page_id}, "
                f"html_len={len(html_body)}, text_len={len(text)}"
            )
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

        logger.debug(f"[wiki] 페이지 파싱: id={page_id}, title={page_title}, "
                     f"fetch_full={fetch_full}, text_len={len(str(text))}")
        return {"id": page_id, "title": page_title, "url": page_url, "text": text}
