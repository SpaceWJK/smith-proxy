"""
jira_client.py - Jira MCP 클라이언트

MCP 프록시(mcp.sginfra.net)를 통해 Jira에 접근합니다.
wiki_client.py, gdi_client.py 와 동일한 패턴으로, mcp_session.McpSession 을 공유합니다.

캐시 계층 (Phase 3):
  L1: 인메모리 dict (_JIRA_MEM_CACHE) — 5분 TTL
  L2: SQLite (mcp-cache-layer) — 이슈 10분, 프로젝트 1시간, 목록 24시간 TTL
  L3: MCP HTTP 호출 (폴백)

사용 가능한 Jira MCP 도구:
  jql_search, get_issue, get_all_projects, get_project,
  get_project_components, get_project_versions, get_all_project_issues,
  get_issue_transitions, get_issue_status, issue_get_comments, myself

환경변수:
  JIRA_MCP_URL  : MCP 서버 URL (기본: http://mcp.sginfra.net/confluence-jira-mcp)
  JIRA_USERNAME : Jira 사용자명
  JIRA_TOKEN    : Jira API 토큰
"""

import os
import re
import json
import logging
import time

from mcp_session import McpSession

logger = logging.getLogger(__name__)

# ── MCP 캐시 레이어 (옵셔널 — 임포트 실패 시 캐시 없이 동작) ──────────
_JIRA_CACHE_ENABLED = False
_jira_cache = None
_ops_log = None
_perf = None
_JIRA_ISSUE_TTL = 0.17      # 기본값 (~10분)
_JIRA_PROJECT_TTL = 1        # 기본값 (1시간)
_JIRA_PROJECTS_TTL = 24      # 기본값 (24시간)
_JIRA_MEM_TTL = 300           # 기본값 (5분)

try:
    import sys as _sys
    _cache_path = "D:/Vibe Dev/QA Ops/mcp-cache-layer"
    if _cache_path not in _sys.path:
        _sys.path.insert(0, _cache_path)
    from src.cache_manager import CacheManager as _CacheManager
    from src.cache_logger import ops_log as _ops_log_mod, perf as _perf_mod
    from src import config as _cache_config
    _jira_cache = _CacheManager()
    _ops_log = _ops_log_mod
    _perf = _perf_mod
    _JIRA_ISSUE_TTL = getattr(_cache_config, "JIRA_ISSUE_TTL_HOURS", 0.17)
    _JIRA_PROJECT_TTL = getattr(_cache_config, "JIRA_PROJECT_TTL_HOURS", 1)
    _JIRA_PROJECTS_TTL = getattr(_cache_config, "JIRA_PROJECTS_TTL_HOURS", 24)
    _JIRA_MEM_TTL = getattr(_cache_config, "JIRA_MEM_TTL_SEC", 300)
    _JIRA_CACHE_ENABLED = True
    logger.info("[jira] 캐시 레이어 로드 완료 (issue TTL=%.2fh, project TTL=%dh, "
                "projects TTL=%dh, mem TTL=%ds)",
                _JIRA_ISSUE_TTL, _JIRA_PROJECT_TTL, _JIRA_PROJECTS_TTL, _JIRA_MEM_TTL)
except Exception as _e:
    logger.info("[jira] 캐시 레이어 미사용: %s", _e)

# ── L1 인메모리 캐시 ─────────────────────────────────────────────────────
_JIRA_MEM_CACHE: dict = {}  # {key: (data, timestamp)}


def _mem_get(key: str):
    """L1 메모리 캐시 조회. TTL 초과 시 None."""
    entry = _JIRA_MEM_CACHE.get(key)
    if entry and (time.time() - entry[1]) < _JIRA_MEM_TTL:
        return entry[0]
    return None


def _mem_set(key: str, data):
    """L1 메모리 캐시 저장."""
    _JIRA_MEM_CACHE[key] = (data, time.time())


JIRA_MCP_URL = os.getenv(
    "JIRA_MCP_URL", "http://mcp.sginfra.net/confluence-jira-mcp"
)
_DEFAULT_USERNAME = "es-wjkim"

# ── Jira 조회 전용 로거 (logs/jira_query.log) ────────────────────────────
_jira_query_logger: "logging.Logger | None" = None


def _get_jira_query_logger() -> logging.Logger:
    """Jira 조회 전용 로거를 반환합니다."""
    global _jira_query_logger
    if _jira_query_logger is not None:
        return _jira_query_logger

    _jira_query_logger = logging.getLogger("jira_query")
    _jira_query_logger.setLevel(logging.INFO)
    _jira_query_logger.propagate = False

    bot_dir  = os.path.dirname(os.path.abspath(__file__))
    logs_dir = os.path.join(os.path.dirname(bot_dir), "logs")
    os.makedirs(logs_dir, exist_ok=True)

    log_path = os.path.join(logs_dir, "jira_query.log")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    _jira_query_logger.addHandler(fh)
    return _jira_query_logger


def log_jira_query(*, user_id: str = "", user_name: str = "",
                   action: str, query: str, result: str = "",
                   error: str = "", elapsed_ms: int = 0,
                   cache_status: str = ""):
    """
    /jira 조회 내역을 logs/jira_query.log 에 기록합니다.

    cache_status: HIT_MEM, HIT_DB, MISS, MISS_STALE, STORE, DISABLED
    """
    gl     = _get_jira_query_logger()
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
            url=JIRA_MCP_URL,
            headers={
                "x-confluence-jira-username": os.getenv("JIRA_USERNAME", _DEFAULT_USERNAME),
                "x-confluence-jira-token": os.getenv("JIRA_TOKEN", ""),
            },
            label="jira",
        )
    return _mcp_session


# ── JQL 자동 변환 헬퍼 ───────────────────────────────────────────────────

_JQL_KEYWORDS = re.compile(
    r'\b(project|status|assignee|reporter|priority|issuetype|created|updated|'
    r'resolution|fixversion|component|label|sprint|text|summary|description|'
    r'AND|OR|ORDER\s+BY|NOT\s+IN|IN|IS|WAS|CHANGED)\b',
    re.IGNORECASE,
)

_ISSUE_KEY_RE = re.compile(r'^[A-Z][A-Z0-9]+-\d+$')


def is_jql(text: str) -> bool:
    """텍스트가 JQL 구문인지 판별합니다."""
    return bool(_JQL_KEYWORDS.search(text))


def to_jql(text: str) -> str:
    """단순 텍스트를 JQL로 변환합니다. 이미 JQL이면 그대로 반환."""
    if is_jql(text):
        return text
    safe = text.replace('"', '\\"')
    return f'summary ~ "{safe}" ORDER BY updated DESC'


def looks_like_issue_key(text: str) -> bool:
    """이슈 키 패턴(PROJ-123)인지 판별합니다."""
    return bool(_ISSUE_KEY_RE.match(text.strip().upper()))


# ── JiraClient ───────────────────────────────────────────────────────────

class JiraClient:
    """Jira MCP 클라이언트 (3계층 캐시 통합)."""

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
    def _cache_key_issue(key: str) -> str:
        return f"jira:issue:{key.upper()}"

    @staticmethod
    def _cache_key_project(key: str) -> str:
        return f"jira:project:{key.upper()}"

    @staticmethod
    def _cache_key_projects() -> str:
        return "jira:projects"

    def _try_cache_get(self, cache_key: str) -> tuple:
        """L1→L2 캐시 조회. (data, cache_status) 반환. 미스 시 (None, status)."""
        if not _JIRA_CACHE_ENABLED:
            return None, "DISABLED"

        # L1: 메모리
        mem = _mem_get(cache_key)
        if mem is not None:
            if _ops_log:
                _ops_log.cache_hit(cache_key, source="memory")
            return mem, "HIT_MEM"

        # L2: SQLite
        t0 = _perf.now_ms() if _perf else 0
        node = _jira_cache.get_node("jira", cache_key)
        if node:
            if _jira_cache.is_stale(node["id"]):
                return None, "MISS_STALE"
            content = _jira_cache.get_content(node["id"])
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
                     node_type: str = "issue", ttl_hours: float = 0.17):
        """L2 SQLite + L1 메모리에 캐시 저장."""
        if not _JIRA_CACHE_ENABLED or data is None:
            return
        t0 = _perf.now_ms() if _perf else 0
        try:
            body_text = json.dumps(data, ensure_ascii=False)
            node_id = _jira_cache.put_page(
                "jira", cache_key, title,
                node_type=node_type,
                body_text=body_text,
            )
            _jira_cache.upsert_meta(node_id, ttl_hours=ttl_hours)
            _mem_set(cache_key, data)
            if _ops_log:
                elapsed = _perf.elapsed_ms(t0) if _perf else 0
                _ops_log.cache_store(title, node_id=node_id,
                                     source_id=cache_key,
                                     char_count=len(body_text),
                                     has_body=True, elapsed_ms=elapsed)
        except Exception as e:
            logger.warning("[jira] 캐시 저장 실패 (%s): %s", cache_key, e)

    # ── MCP 호출 메서드 (캐시 통합) ───────────────────────────

    def search_issues(self, jql: str, max_results: int = 10) -> tuple:
        """
        JQL 검색 (캐시 미적용 — 검색 결과는 매번 달라질 수 있음).

        Returns: (parsed_data, error_str)
        """
        raw, err = self._mcp.call_tool("jql_search", {
            "jql_request": jql,
            "limit": max_results,
        })
        if err:
            return None, err
        return self._parse_raw(raw), None

    def get_issue(self, key: str) -> tuple:
        """
        이슈 상세 조회. 캐시 TTL ~10분.

        Returns: (parsed_data, error_str)
        """
        key = key.upper()
        cache_key = self._cache_key_issue(key)
        cache_status = ""

        # 캐시 조회
        cached, cache_status = self._try_cache_get(cache_key)
        if cached is not None:
            return cached, None

        # MCP 호출
        raw, err = self._mcp.call_tool("get_issue", {"key": key})
        if err:
            return None, err
        data = self._parse_raw(raw)

        # 캐시 저장
        if data:
            title = key
            if isinstance(data, dict):
                fields = data.get("fields", {})
                if fields and fields.get("summary"):
                    title = f"{key} {fields['summary']}"
            self._cache_store(cache_key, title, data,
                              node_type="issue", ttl_hours=_JIRA_ISSUE_TTL)
            cache_status = cache_status or "STORE"

        return data, None

    def get_all_projects(self) -> tuple:
        """
        프로젝트 목록 조회. 캐시 TTL 24시간.

        Returns: (parsed_data, error_str)
        """
        cache_key = self._cache_key_projects()
        cache_status = ""

        # 캐시 조회
        cached, cache_status = self._try_cache_get(cache_key)
        if cached is not None:
            return cached, None

        # MCP 호출
        raw, err = self._mcp.call_tool("get_all_projects", {})
        if err:
            return None, err
        data = self._parse_raw(raw)

        # 캐시 저장
        if data:
            self._cache_store(cache_key, "all_projects", data,
                              node_type="project_list", ttl_hours=_JIRA_PROJECTS_TTL)

        return data, None

    def get_project(self, key: str) -> tuple:
        """
        프로젝트 상세 조회. 캐시 TTL 1시간.

        Returns: (parsed_data, error_str)
        """
        key = key.upper()
        cache_key = self._cache_key_project(key)
        cache_status = ""

        # 캐시 조회
        cached, cache_status = self._try_cache_get(cache_key)
        if cached is not None:
            return cached, None

        # MCP 호출
        raw, err = self._mcp.call_tool("get_project", {"key": key})
        if err:
            return None, err
        data = self._parse_raw(raw)

        # 캐시 저장
        if data:
            name = key
            if isinstance(data, dict) and data.get("name"):
                name = f"{key} - {data['name']}"
            self._cache_store(cache_key, name, data,
                              node_type="project", ttl_hours=_JIRA_PROJECT_TTL)

        return data, None


# ── Slack 포맷 헬퍼 ──────────────────────────────────────────────────────

def _extract_field(fields: dict, key: str, sub: str = "name") -> str:
    """fields dict에서 중첩 필드(예: status.name)를 안전하게 추출."""
    val = fields.get(key)
    if val is None:
        return ""
    if isinstance(val, dict):
        return val.get(sub, val.get("displayName", str(val)))
    return str(val)


def format_search_results(data, query: str) -> str:
    """JQL 검색 결과 -> Slack 텍스트"""
    if not data:
        return f":information_source: `{query}` 검색 결과가 없습니다."

    issues = []
    total = 0

    if isinstance(data, dict):
        issues = data.get("issues", [])
        total = data.get("total", len(issues))
    elif isinstance(data, list):
        issues = data
        total = len(data)

    if not issues:
        return f":information_source: `{query}` 에 해당하는 이슈가 없습니다."

    lines = [f"*:mag: '{query}' 검색 결과 ({total}건)*\n"]
    for i, issue in enumerate(issues[:15], 1):
        key = issue.get("key", "?")
        fields = issue.get("fields", {})
        summary = fields.get("summary", "(제목 없음)")
        status = _extract_field(fields, "status")
        assignee = _extract_field(fields, "assignee", "displayName")
        priority = _extract_field(fields, "priority")
        issuetype = _extract_field(fields, "issuetype")

        line = f"{i}. *<{_issue_url(key)}|{key}>* {summary}"
        extras = []
        if status:
            extras.append(f":white_small_square: {status}")
        if assignee:
            extras.append(f":bust_in_silhouette: {assignee}")
        if priority:
            extras.append(f":arrow_up_small: {priority}")
        if issuetype:
            extras.append(f":label: {issuetype}")
        if extras:
            line += "\n    " + "  ".join(extras)
        lines.append(line)

    if total > 15:
        lines.append(f"\n_...외 {total - 15}건_")

    return "\n".join(lines)


def format_issue(data) -> str:
    """단일 이슈 상세 -> Slack 텍스트"""
    if not data or not isinstance(data, dict):
        return ":information_source: 이슈 정보를 가져올 수 없습니다."

    key = data.get("key", "?")
    fields = data.get("fields", {})
    summary = fields.get("summary", "(제목 없음)")
    status = _extract_field(fields, "status")
    assignee = _extract_field(fields, "assignee", "displayName")
    reporter = _extract_field(fields, "reporter", "displayName")
    priority = _extract_field(fields, "priority")
    issuetype = _extract_field(fields, "issuetype")
    created = (fields.get("created") or "")[:10]
    updated = (fields.get("updated") or "")[:10]
    description = fields.get("description") or ""

    lines = [f"*:ticket: <{_issue_url(key)}|{key}> — {summary}*\n"]

    info_parts = []
    if issuetype:
        info_parts.append(f":label: *유형*: {issuetype}")
    if status:
        info_parts.append(f":white_small_square: *상태*: {status}")
    if priority:
        info_parts.append(f":arrow_up_small: *우선순위*: {priority}")
    if assignee:
        info_parts.append(f":bust_in_silhouette: *담당자*: {assignee}")
    if reporter:
        info_parts.append(f":pencil2: *보고자*: {reporter}")
    if created:
        info_parts.append(f":calendar: *생성*: {created}")
    if updated:
        info_parts.append(f":arrows_counterclockwise: *수정*: {updated}")

    if info_parts:
        lines.append("\n".join(info_parts))

    if description:
        desc_text = description if isinstance(description, str) else str(description)
        if len(desc_text) > 500:
            desc_text = desc_text[:500] + "..."
        lines.append(f"\n*설명:*\n{desc_text}")

    return "\n".join(lines)


def format_project(data) -> str:
    """프로젝트 상세 -> Slack 텍스트"""
    if not data or not isinstance(data, dict):
        return ":information_source: 프로젝트 정보를 가져올 수 없습니다."

    key = data.get("key", "?")
    name = data.get("name", "(이름 없음)")
    description = data.get("description") or ""
    lead = data.get("lead", {})
    lead_name = lead.get("displayName", lead.get("name", "")) if isinstance(lead, dict) else ""
    ptype = data.get("projectTypeKey", "")

    lines = [f"*:file_folder: {key} — {name}*\n"]
    if ptype:
        lines.append(f":label: *유형*: {ptype}")
    if lead_name:
        lines.append(f":bust_in_silhouette: *리드*: {lead_name}")
    if description:
        if len(description) > 300:
            description = description[:300] + "..."
        lines.append(f"\n*설명:*\n{description}")

    return "\n".join(lines)


def format_projects_list(data) -> str:
    """프로젝트 목록 -> Slack 텍스트"""
    projects = []
    if isinstance(data, list):
        projects = data
    elif isinstance(data, dict):
        projects = data.get("values", data.get("projects", []))
        if not projects and data.get("key"):
            projects = [data]

    if not projects:
        return ":information_source: 프로젝트 목록이 비어 있습니다."

    lines = [f"*:file_folder: 프로젝트 목록 ({len(projects)}개)*\n"]
    for p in projects[:30]:
        key = p.get("key", "?")
        name = p.get("name", "")
        ptype = p.get("projectTypeKey", "")

        line = f"• *{key}* — {name}"
        if ptype:
            line += f"  _{ptype}_"
        lines.append(line)

    if len(projects) > 30:
        lines.append(f"\n_...외 {len(projects) - 30}개_")

    return "\n".join(lines)


def _issue_url(key: str) -> str:
    """이슈 키로 Jira 웹 URL을 생성합니다."""
    base = os.getenv("JIRA_BASE_URL", "https://jira.smilegate.net")
    return f"{base}/browse/{key}"


# ── Claude AI 질의용 텍스트 추출 ──────────────────────────────────────────

def get_issue_context_text(data) -> str:
    """이슈 데이터에서 Claude AI 컨텍스트 텍스트를 추출합니다."""
    if not data or not isinstance(data, dict):
        return ""

    key = data.get("key", "?")
    fields = data.get("fields", {})
    summary = fields.get("summary", "")
    status = _extract_field(fields, "status")
    assignee = _extract_field(fields, "assignee", "displayName")
    reporter = _extract_field(fields, "reporter", "displayName")
    priority = _extract_field(fields, "priority")
    issuetype = _extract_field(fields, "issuetype")
    description = fields.get("description") or ""
    created = (fields.get("created") or "")[:10]
    updated = (fields.get("updated") or "")[:10]

    parts = [
        f"이슈: {key} - {summary}",
        f"유형: {issuetype}" if issuetype else "",
        f"상태: {status}" if status else "",
        f"우선순위: {priority}" if priority else "",
        f"담당자: {assignee}" if assignee else "",
        f"보고자: {reporter}" if reporter else "",
        f"생성일: {created}" if created else "",
        f"수정일: {updated}" if updated else "",
    ]
    if description:
        desc_text = description if isinstance(description, str) else str(description)
        if len(desc_text) > 2000:
            desc_text = desc_text[:2000] + "..."
        parts.append(f"\n설명:\n{desc_text}")

    return "\n".join(p for p in parts if p)


def get_search_context_text(data) -> str:
    """JQL 검색 결과에서 Claude AI 컨텍스트 텍스트를 추출합니다."""
    if not data:
        return ""

    issues = []
    if isinstance(data, dict):
        issues = data.get("issues", [])
    elif isinstance(data, list):
        issues = data

    if not issues:
        return ""

    parts = []
    for issue in issues[:10]:
        key = issue.get("key", "?")
        fields = issue.get("fields", {})
        summary = fields.get("summary", "")
        status = _extract_field(fields, "status")
        assignee = _extract_field(fields, "assignee", "displayName")
        description = fields.get("description") or ""

        entry = f"[{key}] {summary}\n상태: {status}, 담당자: {assignee}"
        if description:
            desc_text = description if isinstance(description, str) else str(description)
            if len(desc_text) > 300:
                desc_text = desc_text[:300] + "..."
            entry += f"\n설명: {desc_text}"
        parts.append(entry)

    return "\n\n---\n\n".join(parts)
