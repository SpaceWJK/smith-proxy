"""
gdi_client.py - GDI(Game Doc Insight) MCP 클라이언트

MCP 프록시(mcp-dev.sginfra.net)를 통해 GDI 문서 저장소에 접근합니다.
wiki_client.py 와 동일한 패턴으로, mcp_session.McpSession 을 공유합니다.

캐시 계층 (Phase 2):
  L1: 인메모리 dict (_GDI_MEM_CACHE) — 5분 TTL
  L2: SQLite (mcp-cache-layer) — 폴더 6시간, 파일 24시간 TTL
  L3: MCP HTTP 호출 (폴백)

사용 가능한 GDI MCP 도구 (읽기 전용):
  unified_search, search_by_filename, list_files_in_folder,
  fetch_row_documents, search_vector_candidates,
  get_document_version_diff, compare_two_files, compare_folders, help

⚠️ GDI MCP 안전 원칙:
  - MCP 경유: 읽기(검색/조회) 전용 — 쓰기/업로드/삭제 원천 차단
  - MCP는 공유 서버이므로 데이터 변경 경로 완전 차단
  - S3 원본 데이터 변경은 로컬 AWS CLI 직접 접근으로만 가능
    (업로드: 사용자 승인 1회 / 삭제: 사용자 승인 2회 필요)

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
    # scripts/ 경로도 추가 (folder_taxonomy 임포트용)
    _scripts_path = _cache_path + "/scripts"
    if _scripts_path not in _sys.path:
        _sys.path.insert(0, _scripts_path)
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
    logger.info("[gdi] 캐시 레이어 로드 완료 (folder TTL=%dh, file TTL=%dh, mem TTL=%ds, mode=%s)",
                _GDI_FOLDER_TTL, _GDI_FILE_TTL, _GDI_MEM_TTL, GDI_MODE)
except Exception as _e:
    logger.info("[gdi] 캐시 레이어 미사용: %s", _e)

# ── 폴더 택소노미 인덱스 (옵셔널) ─────────────────────────────────────────
_TAXONOMY_ENABLED = False
_folder_index = None

try:
    from folder_taxonomy import FolderIndex as _FolderIndex, QueryParser as _QueryParser
    _folder_index = _FolderIndex()
    _TAXONOMY_ENABLED = True
    logger.info("[gdi] 폴더 택소노미 로드 완료")
except Exception as _te:
    logger.info("[gdi] 폴더 택소노미 미사용: %s", _te)

# ── GDI MCP 읽기 전용 허용 도구 (쓰기/삭제 원천 차단) ──────────────────
# MCP는 공유 서버 → 데이터 변경 경로 완전 차단
# S3 데이터 변경은 로컬 AWS CLI 직접 접근으로만 가능
GDI_MCP_READONLY_TOOLS = frozenset({
    "unified_search", "search_by_filename", "list_files_in_folder",
    "fetch_row_documents", "search_vector_candidates",
    "get_document_version_diff", "compare_two_files", "compare_folders",
    "list_files_in_folder", "help", "test_game_doc_insight_connection",
})

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

# ── GDI 모드 스위치 ──────────────────────────────────────────────────────
# "local"  : 캐시(SQLite) 전용, MCP 폴백 차단 (gdi-repo/ 로컬 파일 기반)
# "cloud"  : 기존 동작 유지 (캐시 → MCP 폴백)
GDI_MODE = os.getenv("GDI_MODE", "local")

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

# PPTX/XLSX 메타데이터 접두사 패턴
_PPTX_PREFIX_RE = re.compile(
    r"^Mode: generic_pptx > FileType: .+? > ContentType: generic_pptx > Slide: (\d+) > "
)
_PPTX_EMPTY_NOTES_RE = re.compile(r"\n?### Notes:\s*$")
_XLSX_PREFIX = "Mode: generic_xlsx"

# 시트/테이블당 최대 행 수
MAX_TABLE_ROWS = 500


def _clean_chunk_text(text: str) -> str:
    """GDI 청크의 메타데이터 접두사(index_mode/file_type/content_type)를 제거한다."""
    if not text:
        return text
    return _CHUNK_META_RE.sub("", text).strip()


def _clean_any_chunk(text: str) -> str:
    """모든 GDI 청크 형식의 메타데이터를 제거한다 (단일 청크용)."""
    if not text:
        return text
    # TSV 메타데이터
    text = _CHUNK_META_RE.sub("", text)
    # PPTX 접두사 → 슬라이드 번호만 유지
    m = _PPTX_PREFIX_RE.match(text)
    if m:
        text = f"[Slide {m.group(1)}] {text[m.end():]}"
        text = _PPTX_EMPTY_NOTES_RE.sub("", text)
    # XLSX 접두사 → 시트+행 정보만 유지
    elif text.startswith(_XLSX_PREFIX):
        parts = text.split(" > ")
        sheet = ""
        data_start = 0
        for i, part in enumerate(parts):
            if part.startswith("Sheet: "):
                sheet = part[7:]
            elif part.startswith("Row: "):
                data_start = i + 1
                break
        if data_start > 0:
            data_fields = " > ".join(parts[data_start:])
            text = f"[{sheet}] {data_fields}"
    return text.strip()


# ── 파서: 파일 형식별 재구성 (사람이 보는 형태) ──────────────────────────

def _parse_xlsx_chunk(text: str):
    """XLSX 청크 → (sheet, row_num, {col: val})"""
    lines = text.split("\n")
    first_line = lines[0]

    if not first_line.startswith(_XLSX_PREFIX):
        return None, -1, {}

    parts = first_line.split(" > ")
    sheet = ""
    row_num = -1
    data_start = 0

    for i, part in enumerate(parts):
        if part.startswith("Sheet: "):
            sheet = part[7:]
        elif part.startswith("Row: "):
            try:
                row_num = int(part[5:])
            except ValueError:
                pass
            data_start = i + 1
            break

    cols = {}
    data_parts = parts[data_start:]
    for j, part in enumerate(data_parts):
        idx = part.find(": ")
        if idx > 0:
            key = part[:idx].strip()
            val = part[idx + 2:].strip()
            if j == len(data_parts) - 1 and len(lines) > 1:
                extra = " ".join(l.strip() for l in lines[1:] if l.strip())
                if extra:
                    val += " " + extra
            cols[key] = val

    return sheet, row_num, cols


def _reconstruct_xlsx(chunks: list[str]) -> str:
    """XLSX 청크 → 시트별 마크다운 테이블."""
    from collections import OrderedDict

    sheets = OrderedDict()
    sheet_headers = OrderedDict()

    for chunk in chunks:
        sheet, row_num, cols = _parse_xlsx_chunk(chunk)
        if sheet is None or not cols:
            continue
        if sheet not in sheets:
            sheets[sheet] = []
            sheet_headers[sheet] = list(cols.keys())
        else:
            for k in cols.keys():
                if k not in sheet_headers[sheet]:
                    sheet_headers[sheet].append(k)
        sheets[sheet].append(cols)

    if not sheets:
        return "\n".join(chunks)

    result = []
    for sheet_name, rows in sheets.items():
        headers = sheet_headers[sheet_name]
        result.append(f"## Sheet: {sheet_name}\n")
        result.append("| " + " | ".join(headers) + " |")
        result.append("|" + "|".join("---" for _ in headers) + "|")
        for i, row in enumerate(rows):
            if i >= MAX_TABLE_ROWS:
                result.append(f"\n_(... 외 {len(rows) - MAX_TABLE_ROWS}행 생략)_")
                break
            vals = [row.get(h, "").replace("|", "\\|").replace("\n", " ")
                    for h in headers]
            result.append("| " + " | ".join(vals) + " |")
        result.append("")

    return "\n".join(result)


def _reconstruct_pptx(chunks: list[str]) -> str:
    """PPTX 청크 → 슬라이드별 정제 문서."""
    parts = []
    for chunk in chunks:
        m = _PPTX_PREFIX_RE.match(chunk)
        if m:
            slide_num = m.group(1)
            content = chunk[m.end():]
        else:
            content = chunk
            slide_num = None
        content = _PPTX_EMPTY_NOTES_RE.sub("", content).strip()
        if not content:
            continue
        if slide_num:
            parts.append(f"## Slide {slide_num}\n{content}")
        else:
            parts.append(content)
    return "\n\n".join(parts)


def _reconstruct_tsv(chunks: list[str]) -> str:
    """TSV 청크 → 마크다운 테이블."""
    all_rows = []
    all_headers = []

    for chunk in chunks:
        cleaned = _CHUNK_META_RE.sub("", chunk).strip()
        if not cleaned:
            continue
        cols = {}
        for line in cleaned.split("\n"):
            line = line.strip()
            if not line:
                continue
            idx = line.find(": ")
            if idx > 0:
                key = line[:idx]
                val = line[idx + 2:]
                cols[key] = val
                if key not in all_headers:
                    all_headers.append(key)
        if cols:
            all_rows.append(cols)

    if not all_rows or not all_headers:
        return "\n".join(chunks)

    result = []
    result.append("| " + " | ".join(all_headers) + " |")
    result.append("|" + "|".join("---" for _ in all_headers) + "|")
    for i, row in enumerate(all_rows):
        if i >= MAX_TABLE_ROWS:
            result.append(f"\n_(... 외 {len(all_rows) - MAX_TABLE_ROWS}행 생략)_")
            break
        vals = [row.get(h, "").replace("|", "\\|").replace("\n", " ")
                for h in all_headers]
        result.append("| " + " | ".join(vals) + " |")
    return "\n".join(result)


def _reconstruct_body(chunks: list[str], source_type: str) -> str:
    """파일 형식에 맞게 청크를 사람이 보는 형태로 재구성."""
    if not chunks:
        return ""
    if source_type == "generic_xlsx":
        return _reconstruct_xlsx(chunks)
    elif source_type == "generic_pptx":
        return _reconstruct_pptx(chunks)
    elif source_type == "generic_tsv":
        return _reconstruct_tsv(chunks)
    return "\n".join(_clean_chunk_text(c) for c in chunks if c.strip())

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
    """GDI MCP 클라이언트 (3계층 캐시 통합).

    ⚠️ MCP 안전: 읽기 전용 도구만 호출 가능.
    GDI_MCP_READONLY_TOOLS에 없는 도구 호출 시 차단 + 에러 로그.
    """

    def __init__(self):
        self._mcp = _get_mcp()

    def _safe_call_tool(self, tool_name: str, args: dict):
        """MCP 도구 호출 — 읽기 전용 허용 목록 검증 후 실행.

        허용되지 않은 도구 호출 시 차단하고 에러를 반환한다.
        (MCP는 공유 서버 → 쓰기/삭제 원천 차단)
        """
        if tool_name not in GDI_MCP_READONLY_TOOLS:
            logger.error(
                "[gdi] ⛔ MCP 쓰기 차단: tool=%s (허용 목록 외)", tool_name)
            return None, f"BLOCKED: '{tool_name}' is not a read-only tool"
        return self._mcp.call_tool(tool_name, args)

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
        - local 모드: SQLite 캐시 DB에서 LIKE 검색
        - cloud 모드: MCP unified_search 호출

        Returns: (parsed_data, error_str)
        """
        # ── local 모드: SQLite 캐시에서 직접 검색 ──
        if GDI_MODE == "local":
            return self._local_unified_search(query_text, game_name, top_k)

        # ── cloud 모드: MCP 호출 ──
        args = {"query_text": query_text, "top_k": top_k}
        if game_name:
            args["game_name"] = game_name

        raw, err = self._safe_call_tool("unified_search", args)
        if err:
            return None, err
        return self._parse_raw(raw), None

    def _local_unified_search(self, query_text: str, game_name: str = None,
                              top_k: int = 10) -> tuple:
        """SQLite 캐시 DB에서 키워드 LIKE 검색 (local 모드 전용).

        nodes + doc_content JOIN으로 body_text 검색 후
        MCP unified_search와 동일한 dict 포맷으로 반환.
        """
        if not _GDI_CACHE_ENABLED or not _gdi_cache:
            return None, "캐시 레이어 미사용 (local 모드에서는 캐시 필수)"

        try:
            conn = _gdi_cache._conn()
            # 키워드 분리 (공백 구분)
            keywords = [kw.strip() for kw in query_text.split() if kw.strip()]
            if not keywords:
                return {"success": True, "results": [], "total_count": 0}, None

            # WHERE 절: 모든 키워드가 body_text에 포함
            where_clauses = []
            params = []
            for kw in keywords:
                where_clauses.append("dc.body_text LIKE ?")
                params.append(f"%{kw}%")

            # game_name 필터 (path 예: "Chaoszero/TSV/20260225b/file.tsv")
            if game_name:
                where_clauses.append("LOWER(n.path) LIKE ?")
                params.append(f"%{game_name.lower()}%")

            where_sql = " AND ".join(where_clauses)
            params.append(top_k)

            sql = f"""
                SELECT n.title, n.path, n.node_type,
                       SUBSTR(dc.body_text, 1, 500) AS snippet
                FROM nodes n
                JOIN doc_content dc ON dc.node_id = n.id
                WHERE n.source_type = 'gdi'
                  AND {where_sql}
                ORDER BY n.updated_at DESC
                LIMIT ?
            """
            rows = conn.execute(sql, params).fetchall()
            conn.close()

            results = []
            for row in rows:
                title, path, node_type, snippet = row
                # 스니펫에서 첫 매칭 키워드 주변 텍스트 추출
                preview = snippet[:200] if snippet else ""
                results.append({
                    "file_name": title or "",
                    "file_path": path or "",
                    "source_type": node_type or "gdi",
                    "content_preview": preview,
                    "_collection": "gdi_local_cache",
                })

            data = {
                "success": True,
                "results": results,
                "total_count": len(results),
                "breakdown": {"gdi_local_cache": len(results)},
                "_mode": "local",
            }
            return data, None

        except Exception as e:
            logger.error("[gdi] local unified_search 오류: %s", e)
            return None, f"local 검색 오류: {e}"

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

        # local 모드: 캐시 미스 시 MCP 폴백 없이 None 반환
        if GDI_MODE == "local":
            logger.debug("[gdi] search_by_filename: local 모드 — 캐시 미스 (%s)", filename_query)
            return None, None

        # cloud 모드: MCP 호출
        args = {"file_name_query": filename_query, "page": page,
                "page_size": page_size}
        if game_name:
            args["game_name"] = game_name
        if exact_match:
            args["exact_match"] = True

        raw, err = self._safe_call_tool("search_by_filename", args)
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

        # local 모드: 캐시 미스 시 MCP 폴백 없이 None 반환
        if GDI_MODE == "local":
            logger.debug("[gdi] list_files_in_folder: local 모드 — 캐시 미스 (%s)", folder_path)
            return None, None

        # cloud 모드: MCP 호출
        raw, err = self._safe_call_tool("list_files_in_folder", {
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

        # 청크 내용 요약 (메타데이터 정제 + 첫 150자)
        chunk = _clean_any_chunk(r.get("chunk_content", ""))
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

    # 청크 내용 표시 (최대 5개, 메타데이터 정제)
    if chunks:
        lines.append(f"\n*내용 ({len(chunks)}개 청크 중 최대 5개):*")
        for c in chunks[:5]:
            content = _clean_any_chunk(c.get("chunk_content", c.get("content", "")))
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
    파일 형식(xlsx/pptx/tsv)에 따라 마크다운 테이블/슬라이드 문서로 재구성합니다.

    Returns: 파일 내용 텍스트 (없으면 빈 문자열)
    """
    if not data or not data.get("success"):
        return ""

    chunks = data.get("chunks", [])
    if not chunks:
        return ""

    # source_type 감지 (file 메타데이터 또는 첫 청크 내용에서)
    source_type = ""
    file_info = data.get("file", {})
    if file_info:
        source_type = file_info.get("source_type", "")
    if not source_type and chunks:
        first = chunks[0].get("chunk_content", chunks[0].get("content", ""))
        if first.startswith(_XLSX_PREFIX):
            source_type = "generic_xlsx"
        elif _PPTX_PREFIX_RE.match(first):
            source_type = "generic_pptx"

    # raw 청크 텍스트 수집
    raw_chunks = []
    for c in chunks:
        text = c.get("chunk_content", c.get("content", ""))
        if text and text.strip():
            raw_chunks.append(text)

    # 형식별 재구성
    if source_type and raw_chunks:
        return _reconstruct_body(raw_chunks, source_type)

    # 폴백: 단순 정제
    return "\n".join(_clean_chunk_text(t) for t in raw_chunks if t.strip())


def get_file_content_full(file_name: str, game_name: str = "",
                          mcp: "McpSession | None" = None) -> str:
    """파일 전체 텍스트 반환 (캐시 우선 → MCP 폴백).

    1) SQLite doc_content.body_text 조회 (일괄 적재 데이터 — 이미 재구성됨)
    2) 없으면 MCP search_by_filename 전체 페이지 수집 → 형식별 재구성

    Returns: 파일 전체 텍스트 (없으면 빈 문자열)
    """
    # ── 1단계: 캐시 조회 (일괄 적재 데이터 — load_gdi.py에서 이미 재구성됨) ──
    if _GDI_CACHE_ENABLED and _gdi_cache:
        try:
            node = _gdi_cache.get_node_by_title(file_name, source_type="gdi")
            if node:
                content = _gdi_cache.get_content(node["id"])
                if content and content.get("body_text"):
                    logger.debug("[gdi] get_file_content_full: 캐시 HIT (%s)", file_name)
                    return content["body_text"]  # 이미 재구성된 데이터
        except Exception as e:
            logger.debug("[gdi] 캐시 조회 오류: %s", e)

    # ── 2단계: local 모드에서는 MCP 폴백 없이 빈 문자열 반환 ──
    if GDI_MODE == "local":
        logger.debug("[gdi] get_file_content_full: local 모드 — 캐시 미스 (%s)", file_name)
        return ""

    # ── 3단계: cloud 모드 — MCP 전체 청크 수집 (폴백) → 형식별 재구성 ──
    if mcp is None:
        mcp = McpSession(url=GDI_MCP_URL, label="gdi")

    raw_chunks = []
    source_type = ""
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

        # MCP 읽기 전용 검증
        if "search_by_filename" not in GDI_MCP_READONLY_TOOLS:
            logger.error("[gdi] ⛔ MCP 쓰기 차단: search_by_filename")
            break
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

        # source_type 감지 (첫 페이지에서만)
        if not source_type:
            file_info = data.get("file", {})
            if file_info:
                source_type = file_info.get("source_type", "")

        chunks = data.get("chunks", [])
        for c in chunks:
            text = c.get("chunk_content", "")
            if text and text.strip():
                raw_chunks.append(text)

        pagination = data.get("pagination", {})
        if not pagination.get("has_next"):
            break
        page += 1
        time.sleep(0.2)

    if not raw_chunks:
        return ""

    # source_type 자동 감지 (메타데이터 없을 때 첫 청크로 추론)
    if not source_type and raw_chunks:
        first = raw_chunks[0]
        if first.startswith(_XLSX_PREFIX):
            source_type = "generic_xlsx"
        elif _PPTX_PREFIX_RE.match(first):
            source_type = "generic_pptx"

    # 형식별 재구성
    return _reconstruct_body(raw_chunks, source_type)


# ── 폴더 택소노미 검색 ──────────────────────────────────────────────────

def taxonomy_search(
    query: str,
    question: str = "",
    max_files: int = 20,
) -> dict | None:
    """자연어 질의를 폴더 택소노미로 해석하여 캐시 DB에서 직접 결과를 반환한다.

    키워드(query)와 질문(question)을 결합하여 파싱한다.
    예) query="카제나 2/4 3차", question="테스트 결과에서 FAIL 이슈?"
      → 결합: "카제나 2/4 3차 테스트 결과에서 FAIL 이슈?"
      → game=Chaoszero, date=0204, build=3차, category=Test Result

    택소노미가 비활성이거나, 게임명이 파싱되지 않으면 None 반환 (MCP 폴백).

    Returns:
        {"folders": list[dict], "files": list[dict], "parsed": dict}
        또는 None (해석 실패)
    """
    if not _TAXONOMY_ENABLED or not _folder_index:
        return None

    try:
        # 키워드 + 질문 결합하여 파싱 (카테고리 등 질문에서도 추출)
        combined = f"{query} {question}".strip() if question else query
        parsed = _QueryParser.parse(combined)

        # 최소 게임명이 있어야 택소노미 적용
        if not parsed.get("game"):
            return None

        # 결합 텍스트로 폴더/파일 조회
        folders = _folder_index.resolve_query(combined)
        if not folders:
            return None

        files = _folder_index.get_files_with_content(combined, max_files=max_files)

        logger.info(
            "[gdi] 택소노미 해석 성공: game=%s, cat=%s, date=%s, "
            "build=%s → folders=%d, files=%d",
            parsed.get("game"), parsed.get("category"),
            parsed.get("date_mmdd"), parsed.get("build"),
            len(folders), len(files),
        )

        return {
            "folders": folders,
            "files": files,
            "parsed": parsed,
        }
    except Exception as e:
        logger.warning("[gdi] 택소노미 검색 오류: %s", e)
        return None


def format_taxonomy_results(tax_data: dict, query: str) -> str:
    """taxonomy_search() 결과 → Slack 포맷 텍스트."""
    if not tax_data:
        return ""

    folders = tax_data.get("folders", [])
    files = tax_data.get("files", [])
    parsed = tax_data.get("parsed", {})

    lines = [f"*🗂️ '{query}' 택소노미 검색 결과*\n"]

    # 파싱 정보
    info_parts = []
    if parsed.get("game"):
        info_parts.append(f"게임: {parsed['game']}")
    if parsed.get("category"):
        info_parts.append(f"카테고리: {parsed['category']}")
    if parsed.get("date_mmdd"):
        mmdd = parsed["date_mmdd"]
        info_parts.append(f"날짜: {mmdd[:2]}/{mmdd[2:]}")
    if parsed.get("build"):
        b = parsed["build"]
        info_parts.append(f"빌드: {b.get('type', '')} {b.get('numbers', [])}")
    if info_parts:
        lines.append(f"📌 {' | '.join(info_parts)}\n")

    # 폴더 목록 (최대 10개)
    lines.append(f"*📁 매칭 폴더 ({len(folders)}개):*")
    for f in folders[:10]:
        fc = f.get("file_count", 0)
        lines.append(f"• `{f['full_path']}` ({fc}파일)")
    if len(folders) > 10:
        lines.append(f"  _... 외 {len(folders) - 10}개_")

    # 파일 목록 (최대 15개)
    if files:
        lines.append(f"\n*📄 파일 ({len(files)}개):*")
        for i, f in enumerate(files[:15], 1):
            title = f.get("title", "?")
            cc = f.get("char_count", 0)
            lines.append(f"{i}. *{title}* ({cc:,}자)")
        if len(files) > 15:
            lines.append(f"  _... 외 {len(files) - 15}개_")

    return "\n".join(lines)


def get_taxonomy_context_text(tax_data: dict, max_chars: int = 50000) -> str:
    """taxonomy_search() 결과에서 Claude AI용 컨텍스트 텍스트를 추출한다."""
    if not tax_data:
        return ""

    files = tax_data.get("files", [])
    if not files:
        return ""

    parts = []
    total_chars = 0
    for f in files:
        title = f.get("title", "?")
        body = f.get("body_text", "")
        source_id = f.get("source_id", "")
        if not body:
            continue
        section = f"[파일: {title}]\n경로: {source_id}\n내용:\n{body}"
        if total_chars + len(section) > max_chars:
            remaining = max_chars - total_chars
            if remaining > 200:
                parts.append(section[:remaining] + "\n\n_(본문 잘림)_")
            break
        parts.append(section)
        total_chars += len(section)

    return "\n\n---\n\n".join(parts)


def get_search_context_text(data: dict) -> str:
    """
    unified_search 결과에서 컨텍스트 텍스트를 추출합니다.
    Claude AI 답변 생성에 사용됩니다.
    각 청크의 형식(xlsx/pptx/tsv)에 맞게 메타데이터를 정제합니다.

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
        chunk   = _clean_any_chunk(r.get("chunk_content", ""))
        parts.append(f"[파일: {fname}]\n경로: {fpath}\n내용: {chunk}")

    return "\n\n---\n\n".join(parts)
