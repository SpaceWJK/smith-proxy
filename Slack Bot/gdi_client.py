"""
gdi_client.py - GDI(Game Doc Insight) MCP 클라이언트

MCP 프록시(mcp-dev.sginfra.net)를 통해 GDI 문서 저장소에 접근합니다.
wiki_client.py 와 동일한 패턴으로, mcp_session.McpSession 을 공유합니다.

캐시 계층 (Phase 2):
  L1: 인메모리 dict (_GDI_MEM_CACHE) — 5분 TTL
  L2: SQLite (mcp-cache-layer) — 폴더 6시간, 파일 24시간 TTL
  L3: MCP HTTP 호출 (폴백)

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
import re
import time

from mcp_session import McpSession

logger = logging.getLogger(__name__)

# ── MCP 캐시 레이어 (옵셔널 — 임포트 실패 시 캐시 없이 동작) ──────────
_GDI_CACHE_ENABLED = False
_gdi_cache = None
_ops_log = None
_perf = None
_GDI_FOLDER_TTL = 6     # 기본값 (config 로드 실패 시)
_GDI_FILE_TTL = 24
_GDI_MEM_TTL = 300

try:
    import sys as _sys
    _cache_path = "D:/Vibe Dev/QA Ops/mcp-cache-layer"
    if _cache_path not in _sys.path:
        _sys.path.insert(0, _cache_path)
    from src.cache_manager import CacheManager as _CacheManager
    from src.cache_logger import ops_log as _ops_log_mod, perf as _perf_mod
    from src import config as _cache_config
    _gdi_cache = _CacheManager()
    _ops_log = _ops_log_mod
    _perf = _perf_mod
    _GDI_FOLDER_TTL = getattr(_cache_config, "GDI_FOLDER_TTL_HOURS", 6)
    _GDI_FILE_TTL = getattr(_cache_config, "GDI_FILE_TTL_HOURS", 24)
    _GDI_MEM_TTL = getattr(_cache_config, "GDI_MEM_TTL_SEC", 300)
    _GDI_CACHE_ENABLED = True
    logger.info("[gdi] 캐시 레이어 로드 완료 (folder TTL=%dh, file TTL=%dh, mem TTL=%ds)",
                _GDI_FOLDER_TTL, _GDI_FILE_TTL, _GDI_MEM_TTL)
except Exception as _e:
    logger.info("[gdi] 캐시 레이어 미사용: %s", _e)

# ── L1 인메모리 캐시 ─────────────────────────────────────────────────────
_GDI_MEM_CACHE: dict = {}  # {key: (data, timestamp)}


def _mem_get(key: str):
    """L1 메모리 캐시 조회. TTL 초과 시 None."""
    entry = _GDI_MEM_CACHE.get(key)
    if entry and (time.time() - entry[1]) < _GDI_MEM_TTL:
        return entry[0]
    return None


def _mem_set(key: str, data):
    """L1 메모리 캐시 저장."""
    _GDI_MEM_CACHE[key] = (data, time.time())

GDI_MCP_URL = os.getenv(
    "GDI_MCP_URL", "http://mcp-dev.sginfra.net/game-doc-insight-mcp"
)

# ── GDI 청크 메타데이터 정제 ──────────────────────────────────────────────
# GDI MCP가 반환하는 각 청크에는 인덱싱용 메타데이터 접두사가 붙는다:
#   index_mode: generic_tsv
#   file_type: <파일명>
#   content_type: generic_tsv
# 이 메타데이터를 제거하여 Claude 토큰을 절약한다.
_CHUNK_META_RE = re.compile(
    r"^(?:index_mode|file_type|content_type): .+\n?",
    re.MULTILINE,
)


def _clean_chunk_text(text: str) -> str:
    """GDI 청크의 메타데이터 접두사(index_mode/file_type/content_type)를 제거한다."""
    if not text:
        return text
    return _CHUNK_META_RE.sub("", text).strip()

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
                  error: str = "", elapsed_ms: int = 0,
                  cache_status: str = ""):
    """
    /gdi 조회 내역을 logs/gdi_query.log 에 기록합니다.
    wiki_client.log_wiki_query() 와 동일 인터페이스.

    cache_status: HIT_MEM, HIT_DB, MISS, MISS_STALE, STORE, DISABLED
    """
    gl     = _get_gdi_query_logger()
    status = "ERROR" if error else "OK"
    user   = f"{user_name}({user_id})" if user_id else (user_name or "unknown")

    msg = f"{status} | {action} | user={user} | query={query}"
    if result:
        msg += f" | result={result}"
    if error:
        msg += f" | error={error}"
    if cache_status:
        msg += f" | cache={cache_status}"
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
    """GDI MCP 클라이언트 (3계층 캐시 통합)."""

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

    # ── 캐시 내부 헬퍼 ────────────────────────────────────────

    @staticmethod
    def _cache_key_folder(folder_path: str) -> str:
        return f"folder:{folder_path}"

    @staticmethod
    def _cache_key_file(filename: str) -> str:
        return f"file:{filename}"

    def _try_cache_get(self, cache_key: str) -> tuple:
        """L1→L2 캐시 조회. (data, cache_status) 반환. 미스 시 (None, status)."""
        if not _GDI_CACHE_ENABLED:
            return None, "DISABLED"

        # L1: 메모리
        mem = _mem_get(cache_key)
        if mem is not None:
            if _ops_log:
                _ops_log.cache_hit(cache_key, source="memory")
            return mem, "HIT_MEM"

        # L2: SQLite
        t0 = _perf.now_ms() if _perf else 0
        node = _gdi_cache.get_node("gdi", cache_key)
        if node:
            if _gdi_cache.is_stale(node["id"]):
                return None, "MISS_STALE"
            content = _gdi_cache.get_content(node["id"])
            if content and content.get("body_text"):
                try:
                    data = json.loads(content["body_text"])
                    _mem_set(cache_key, data)  # L2 → L1 승격
                    if _ops_log:
                        elapsed = _perf.elapsed_ms(t0) if _perf else 0
                        _ops_log.cache_hit(cache_key, source="sqlite",
                                           node_id=node["id"], elapsed_ms=elapsed)
                    return data, "HIT_DB"
                except (json.JSONDecodeError, TypeError):
                    pass

        if _ops_log:
            elapsed = _perf.elapsed_ms(t0) if _perf else 0
            _ops_log.cache_miss(cache_key, reason="not_found", elapsed_ms=elapsed)
        return None, "MISS"

    def _cache_store(self, cache_key: str, title: str, data, *,
                     node_type: str = "file", ttl_hours: int = 24,
                     path: str | None = None):
        """L2 SQLite + L1 메모리에 캐시 저장."""
        if not _GDI_CACHE_ENABLED or data is None:
            return
        t0 = _perf.now_ms() if _perf else 0
        try:
            body_text = json.dumps(data, ensure_ascii=False)
            node_id = _gdi_cache.put_page(
                "gdi", cache_key, title,
                node_type=node_type, path=path,
                body_text=body_text,
            )
            _gdi_cache.upsert_meta(node_id, ttl_hours=ttl_hours)
            _mem_set(cache_key, data)
            if _ops_log:
                elapsed = _perf.elapsed_ms(t0) if _perf else 0
                _ops_log.cache_store(title, node_id=node_id,
                                     source_id=cache_key,
                                     char_count=len(body_text),
                                     has_body=True, elapsed_ms=elapsed)
        except Exception as e:
            logger.warning("[gdi] 캐시 저장 실패 (%s): %s", cache_key, e)

    # ── MCP 호출 메서드 (캐시 통합) ───────────────────────────

    def unified_search(self, query_text: str, game_name: str = None,
                       top_k: int = 10) -> tuple:
        """
        크로스 컬렉션 통합 검색.
        (캐시 미적용 — 검색 결과는 매번 달라질 수 있음)

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
        page=1 + page_size ≤ 20 일 때만 캐시 적용.

        Returns: (parsed_data, error_str, cache_status)
        """
        cache_status = ""

        # 캐시 조회 (첫 페이지 + 소규모만)
        use_cache = (page == 1 and page_size <= 20)
        if use_cache:
            cache_key = self._cache_key_file(filename_query)
            cached, cache_status = self._try_cache_get(cache_key)
            if cached is not None:
                return cached, None

        # MCP 호출
        args = {"file_name_query": filename_query, "page": page,
                "page_size": page_size}
        if game_name:
            args["game_name"] = game_name
        if exact_match:
            args["exact_match"] = True

        raw, err = self._mcp.call_tool("search_by_filename", args)
        if err:
            return None, err
        data = self._parse_raw(raw)

        # 캐시 저장 (성공 + 파일 정보 있을 때)
        if use_cache and data and isinstance(data, dict) and data.get("file"):
            file_info = data["file"]
            title = file_info.get("file_name", filename_query)
            fpath = file_info.get("file_path", "")
            self._cache_store(
                self._cache_key_file(filename_query), title, data,
                node_type="file", ttl_hours=_GDI_FILE_TTL, path=fpath,
            )
            if not cache_status:
                cache_status = "STORE"

        return data, None

    def list_files_in_folder(self, folder_path: str, page: int = 1,
                             page_size: int = 20) -> tuple:
        """
        폴더 내 파일 목록 조회.
        page=1 일 때만 캐시 적용.

        Returns: (parsed_data, error_str)
        """
        cache_status = ""

        # 캐시 조회 (첫 페이지만)
        use_cache = (page == 1)
        if use_cache:
            cache_key = self._cache_key_folder(folder_path)
            cached, cache_status = self._try_cache_get(cache_key)
            if cached is not None:
                return cached, None

        # MCP 호출
        raw, err = self._mcp.call_tool("list_files_in_folder", {
            "folder_path": folder_path,
            "page": page,
            "page_size": page_size,
        })
        if err:
            return None, err
        data = self._parse_raw(raw)

        # 캐시 저장
        if use_cache and data and isinstance(data, dict) and data.get("success"):
            self._cache_store(
                self._cache_key_folder(folder_path), folder_path, data,
                node_type="folder", ttl_hours=_GDI_FOLDER_TTL, path=folder_path,
            )
            if not cache_status:
                cache_status = "STORE"

        return data, None


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
        content = _clean_chunk_text(c.get("chunk_content", c.get("content", "")))
        if content:
            parts.append(content)

    return "\n".join(parts)


def get_file_content_full(file_name: str, game_name: str = "",
                          mcp: "McpSession | None" = None) -> str:
    """파일 전체 텍스트 반환 (캐시 우선 → MCP 폴백).

    1) SQLite doc_content.body_text 조회 (일괄 적재 데이터)
    2) 없으면 MCP search_by_filename 전체 페이지 수집

    Returns: 파일 전체 텍스트 (없으면 빈 문자열)
    """
    # ── 1단계: 캐시 조회 (일괄 적재 데이터) ──
    if _GDI_CACHE_ENABLED and _gdi_cache:
        try:
            node = _gdi_cache.get_node_by_title(file_name, source_type="gdi")
            if node:
                content = _gdi_cache.get_content(node["id"])
                if content and content.get("body_text"):
                    logger.debug("[gdi] get_file_content_full: 캐시 HIT (%s)", file_name)
                    return _clean_chunk_text(content["body_text"])
        except Exception as e:
            logger.debug("[gdi] 캐시 조회 오류: %s", e)

    # ── 2단계: MCP 전체 청크 수집 (폴백) ──
    if mcp is None:
        mcp = McpSession(url=GDI_MCP_URL, label="gdi")

    all_text = []
    page = 1
    while True:
        args = {
            "file_name_query": file_name,
            "exact_match": True,
            "page": page,
            "page_size": 20,
        }
        if game_name:
            args["game_name"] = game_name

        raw, err = mcp.call_tool("search_by_filename", args)
        if err:
            break

        data = raw
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                break
        if not isinstance(data, dict):
            break

        chunks = data.get("chunks", [])
        for c in chunks:
            text = _clean_chunk_text(c.get("chunk_content", ""))
            if text:
                all_text.append(text)

        pagination = data.get("pagination", {})
        if not pagination.get("has_next"):
            break
        page += 1
        time.sleep(0.2)

    return "\n".join(all_text)


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
        chunk   = _clean_chunk_text(r.get("chunk_content", ""))
        parts.append(f"[파일: {fname}]\n경로: {fpath}\n내용: {chunk}")

    return "\n\n---\n\n".join(parts)
