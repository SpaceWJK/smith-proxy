"""
gdi_client.py - GDI(Game Doc Insight) MCP 클라이언트

MCP 프록시(mcp-dev.sginfra.net)를 통해 GDI 문서 저장소에 접근합니다.
wiki_client.py 와 동일한 패턴으로, mcp_session.McpSession 을 공유합니다.

사용 가능한 GDI MCP 도구:
  unified_search, search_by_filename, list_files_in_folder,
  fetch_row_documents, search_vector_candidates,
  get_document_version_diff, compare_two_files, compare_folders, help

환경변수:
  GDI_MCP_URL  : MCP 서버 URL (기본: http://mcp-dev.sginfra.net/game-doc-insight-mcp)
"""

import os
import json
import logging
import time

from mcp_session import McpSession

logger = logging.getLogger(__name__)

GDI_MCP_URL = os.getenv(
    "GDI_MCP_URL", "http://mcp-dev.sginfra.net/game-doc-insight-mcp"
)

# ── GDI 조회 전용 로거 (logs/gdi_query.log) ──────────────────────────────
_gdi_query_logger: "logging.Logger | None" = None


def _get_gdi_query_logger() -> logging.Logger:
    """GDI 조회 전용 로거를 반환합니다."""
    global _gdi_query_logger
    if _gdi_query_logger is not None:
        return _gdi_query_logger

    _gdi_query_logger = logging.getLogger("gdi_query")
    _gdi_query_logger.setLevel(logging.INFO)
    _gdi_query_logger.propagate = False

    bot_dir  = os.path.dirname(os.path.abspath(__file__))
    logs_dir = os.path.join(os.path.dirname(bot_dir), "logs")
    os.makedirs(logs_dir, exist_ok=True)

    log_path = os.path.join(logs_dir, "gdi_query.log")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    _gdi_query_logger.addHandler(fh)
    return _gdi_query_logger


def log_gdi_query(*, user_id: str = "", user_name: str = "",
                  action: str, query: str, result: str = "",
                  error: str = "", elapsed_ms: int = 0):
    """
    /gdi 조회 내역을 logs/gdi_query.log 에 기록합니다.
    wiki_client.log_wiki_query() 와 동일 인터페이스.
    """
    gl     = _get_gdi_query_logger()
    status = "ERROR" if error else "OK"
    user   = f"{user_name}({user_id})" if user_id else (user_name or "unknown")

    msg = f"{status} | {action} | user={user} | query={query}"
    if result:
        msg += f" | result={result}"
    if error:
        msg += f" | error={error}"
    if elapsed_ms > 0:
        msg += f" | {elapsed_ms}ms"

    if error:
        gl.error(msg)
    else:
        gl.info(msg)


# ── 싱글톤 MCP 세션 ─────────────────────────────────────────────────────

_mcp_session: "McpSession | None" = None


def _get_mcp() -> McpSession:
    global _mcp_session
    if _mcp_session is None:
        _mcp_session = McpSession(
            url=GDI_MCP_URL,
            label="gdi",
        )
    return _mcp_session


# ── GdiClient ────────────────────────────────────────────────────────────

class GdiClient:
    """GDI MCP 클라이언트."""

    def __init__(self):
        self._mcp = _get_mcp()

    def _parse_raw(self, raw) -> object:
        """raw(str 또는 dict) -> Python 객체"""
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except Exception:
                return raw
        return raw

    def unified_search(self, query_text: str, game_name: str = None,
                       top_k: int = 10) -> tuple:
        """
        크로스 컬렉션 통합 검색.

        Returns: (parsed_data, error_str)
        """
        args = {"query_text": query_text, "top_k": top_k}
        if game_name:
            args["game_name"] = game_name

        raw, err = self._mcp.call_tool("unified_search", args)
        if err:
            return None, err
        return self._parse_raw(raw), None

    def search_by_filename(self, filename_query: str, page: int = 1,
                           game_name: str = None,
                           page_size: int = 10,
                           exact_match: bool = False) -> tuple:
        """
        파일명 기반 검색 (청크 내용 포함, 페이지네이션).

        Returns: (parsed_data, error_str)
        """
        args = {"file_name_query": filename_query, "page": page,
                "page_size": page_size}
        if game_name:
            args["game_name"] = game_name
        if exact_match:
            args["exact_match"] = True

        raw, err = self._mcp.call_tool("search_by_filename", args)
        if err:
            return None, err
        return self._parse_raw(raw), None

    def list_files_in_folder(self, folder_path: str, page: int = 1,
                             page_size: int = 20) -> tuple:
        """
        폴더 내 파일 목록 조회.

        Returns: (parsed_data, error_str)
        """
        raw, err = self._mcp.call_tool("list_files_in_folder", {
            "folder_path": folder_path,
            "page": page,
            "page_size": page_size,
        })
        if err:
            return None, err
        return self._parse_raw(raw), None


# ── Slack 포맷 헬퍼 ──────────────────────────────────────────────────────

def format_search_results(data: dict, query: str) -> str:
    """unified_search 결과 -> Slack 텍스트"""
    if not data or not data.get("success"):
        return f"ℹ️ `{query}` 검색 결과가 없습니다."

    results = data.get("results", [])
    total   = data.get("total_count", len(results))

    if not results:
        return f"ℹ️ `{query}` 에 해당하는 문서가 없습니다."

    lines = [f"*🔍 '{query}' 검색 결과 ({total}건)*\n"]
    for i, r in enumerate(results[:10], 1):
        fname = r.get("file_name", "?")
        fpath = r.get("file_path", "")
        gname = r.get("game_name", "")
        coll  = r.get("_collection", "")
        score = r.get("_score", 0)

        # 청크 내용 요약 (첫 150자)
        chunk = r.get("chunk_content", "")
        if len(chunk) > 150:
            chunk = chunk[:150] + "..."

        line = f"{i}. *{fname}*"
        if gname:
            line += f"  [{gname}]"
        if fpath:
            line += f"\n    📁 `{fpath}`"
        if chunk:
            line += f"\n    📝 {chunk}"
        lines.append(line)

    return "\n".join(lines)


def format_file_search(data: dict, query: str) -> str:
    """search_by_filename 결과 -> Slack 텍스트"""
    if not data or not data.get("success"):
        msg = data.get("message", "") if data else ""
        return f"ℹ️ `{query}` 파일을 찾을 수 없습니다.{(' (' + msg + ')') if msg else ''}"

    file_info = data.get("file", {})
    chunks    = data.get("chunks", [])
    pagination = data.get("pagination", {})
    others    = data.get("other_matching_files", [])

    if not file_info:
        return f"ℹ️ `{query}` 파일을 찾을 수 없습니다."

    fname = file_info.get("file_name", "?")
    fpath = file_info.get("file_path", "")
    gname = file_info.get("game_name", "")

    lines = [f"*📄 {fname}*"]
    if gname:
        lines[0] += f"  [{gname}]"
    if fpath:
        lines.append(f"📁 `{fpath}`")

    # 청크 내용 표시 (최대 5개)
    if chunks:
        lines.append(f"\n*내용 ({len(chunks)}개 청크 중 최대 5개):*")
        for c in chunks[:5]:
            content = c.get("chunk_content", c.get("content", ""))
            if len(content) > 200:
                content = content[:200] + "..."
            lines.append(f"```\n{content}\n```")

    # 페이지네이션 정보
    if pagination and pagination.get("has_next"):
        cur  = pagination.get("current_page", 1)
        total_pages = pagination.get("total_pages", "?")
        lines.append(f"\n📖 페이지 {cur}/{total_pages}")

    # 다른 매칭 파일
    if others:
        lines.append(f"\n*유사 파일 ({len(others)}건):*")
        for o in others[:5]:
            oname = o.get("file_name", "?")
            opath = o.get("file_path", "")
            lines.append(f"• {oname}  (`{opath}`)" if opath else f"• {oname}")

    return "\n".join(lines)


def format_folder_list(data: dict, path: str) -> str:
    """list_files_in_folder 결과 -> Slack 텍스트"""
    if not data or not data.get("success"):
        msg = data.get("message", "") if data else ""
        return f"ℹ️ `{path}` 폴더를 찾을 수 없습니다.{(' (' + msg + ')') if msg else ''}"

    files      = data.get("files", [])
    total      = data.get("total_files", len(files))
    pagination = data.get("pagination", {})

    if not files:
        return f"ℹ️ `{path}` 폴더에 파일이 없습니다."

    lines = [f"*📁 {path}* ({total}개 파일)\n"]
    for f in files[:15]:
        fname  = f.get("file_name", "?")
        stype  = f.get("source_type", "")
        gname  = f.get("game_name", "")
        chunks = f.get("chunk_count", 0)
        idate  = (f.get("indexed_date") or "")[:10]

        line = f"• *{fname}*"
        extras = []
        if gname:
            extras.append(gname)
        if stype:
            extras.append(stype)
        if idate:
            extras.append(idate)
        if extras:
            line += f"  ({', '.join(extras)})"
        lines.append(line)

    if pagination and pagination.get("has_next"):
        cur   = pagination.get("current_page", 1)
        total_pages = pagination.get("total_pages", "?")
        lines.append(f"\n📖 페이지 {cur}/{total_pages} — 더 보려면 `/gdi folder {path} page:2`")

    return "\n".join(lines)


def get_file_content_text(data: dict) -> str:
    """
    search_by_filename 결과에서 파일 내용 텍스트를 추출합니다.
    Claude AI 답변 생성에 사용됩니다.

    Returns: 파일 내용 텍스트 (없으면 빈 문자열)
    """
    if not data or not data.get("success"):
        return ""

    chunks = data.get("chunks", [])
    if not chunks:
        return ""

    parts = []
    for c in chunks:
        content = c.get("chunk_content", c.get("content", ""))
        if content:
            parts.append(content)

    return "\n".join(parts)


def get_search_context_text(data: dict) -> str:
    """
    unified_search 결과에서 컨텍스트 텍스트를 추출합니다.
    Claude AI 답변 생성에 사용됩니다.

    Returns: 검색 결과 컨텍스트 텍스트 (없으면 빈 문자열)
    """
    if not data or not data.get("success"):
        return ""

    results = data.get("results", [])
    if not results:
        return ""

    parts = []
    for r in results[:5]:
        fname   = r.get("file_name", "?")
        fpath   = r.get("file_path", "")
        chunk   = r.get("chunk_content", "")
        parts.append(f"[파일: {fname}]\n경로: {fpath}\n내용: {chunk}")

    return "\n\n---\n\n".join(parts)
