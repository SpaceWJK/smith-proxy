"""
keyword_rules.py — 규칙 기반 키워드→페이지/쿼리 매핑 로더

Wiki, Jira, GDI 각각의 키워드 규칙 파일을 로드하고
질문 텍스트에서 매칭되는 규칙을 반환합니다.
Hot reload 지원 (봇 재시작 없이 규칙 파일 변경 즉시 반영).

사용법:
    from keyword_rules import match_wiki_keyword_rule, match_jira_keyword_rule, match_gdi_keyword_rule

    # Wiki: 게임명 + 키워드 → 페이지 제목
    rule = match_wiki_keyword_rule("에픽세븐 핫픽스 내역", game_canonical="에픽세븐")
    # → {"page_title": "2026_Hot Fix", "rule_id": "wkr-001"}

    # Jira: 키워드 → JQL 추가 조건
    rule = match_jira_keyword_rule("긴급 이슈 알려줘")
    # → {"jql_append": "AND priority IN (Critical, Blocker, Highest)", "rule_id": "jkr-001"}

    # GDI: 키워드 → 검색 파라미터 전환
    rule = match_gdi_keyword_rule("밸런스 변경사항")
    # → {"type": "search_by_filename", "filename_pattern": "balance", "rule_id": "gkr-001"}
"""

import os
import json
import logging

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_WIKI_RULES_PATH = os.path.join(_BASE_DIR, "wiki_keyword_rules.json")
_JIRA_RULES_PATH = os.path.join(_BASE_DIR, "jira_keyword_rules.json")
_GDI_RULES_PATH = os.path.join(_BASE_DIR, "gdi_keyword_rules.json")

# ── Hot reload 캐시 (파일별) ─────────────────────────────────────
_cache: dict[str, dict] = {}
# 각 파일 경로를 키로: {"rules": [...], "mtime": float}


def _load_rules(file_path: str) -> list:
    """규칙 JSON 파일 로드 + mtime 기반 hot reload.

    파일이 없거나 오류 시 빈 리스트 반환.
    """
    # mtime 확인
    try:
        cur_mtime = os.path.getmtime(file_path)
    except FileNotFoundError:
        if file_path not in _cache:
            logger.info(f"[규칙로더] 파일 없음: {os.path.basename(file_path)}")
            _cache[file_path] = {"rules": [], "mtime": 0}
        return _cache[file_path]["rules"]

    # 캐시 유효 → 바로 반환
    cached = _cache.get(file_path)
    if cached and cached["mtime"] == cur_mtime:
        return cached["rules"]

    # 파일 로드
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        rules = [r for r in data.get("rules", []) if r.get("enabled", True)]
        _cache[file_path] = {"rules": rules, "mtime": cur_mtime}
        fname = os.path.basename(file_path)
        logger.info(
            f"[규칙로더] {fname}: {len(rules)}개 규칙 로드"
            f"{' (hot reload)' if cached else ''}"
        )
    except Exception as e:
        logger.warning(f"[규칙로더] 로드 실패 ({os.path.basename(file_path)}): {e}")
        _cache[file_path] = {"rules": [], "mtime": cur_mtime}

    return _cache[file_path]["rules"]


# ── Wiki 규칙 매칭 ───────────────────────────────────────────────

def match_wiki_keyword_rule(
    question: str,
    game_canonical: "str | None" = None,
) -> "dict | None":
    """질문 키워드 + 게임명으로 Wiki 페이지 제목 매핑.

    Parameters
    ----------
    question        : 사용자 질문 텍스트
    game_canonical  : 감지된 게임 canonical명 (예: "에픽세븐")

    Returns
    -------
    dict | None
        매칭 시: {"page_title": "...", "rule_id": "..."}
        미매칭 시: None → 기존 검색 로직 사용
    """
    rules = _load_rules(_WIKI_RULES_PATH)
    if not rules:
        return None

    q_lower = question.lower()

    for rule in rules:
        keywords = rule.get("keywords", [])
        if not any(kw in q_lower for kw in keywords):
            continue

        # game_page_map에서 게임별 페이지 제목 조회
        game_map = rule.get("game_page_map", {})
        if game_canonical and game_canonical in game_map:
            page_title = game_map[game_canonical]
            logger.info(
                f"[wiki][규칙매칭] {rule.get('id')} → "
                f"'{page_title}' (game={game_canonical})"
            )
            return {"page_title": page_title, "rule_id": rule.get("id", "")}

    return None


# ── Jira 규칙 매칭 ──────────────────────────────────────────────

def match_jira_keyword_rule(
    question: str,
    project_key: "str | None" = None,
) -> "dict | None":
    """질문 키워드로 Jira JQL 추가 조건 매핑.

    Parameters
    ----------
    question    : 사용자 질문 텍스트
    project_key : Jira 프로젝트 키 (선택적 스코프 체크)

    Returns
    -------
    dict | None
        매칭 시: {"jql_append": "AND ...", "rule_id": "..."}
        미매칭 시: None → 기존 로직 사용
    """
    rules = _load_rules(_JIRA_RULES_PATH)
    if not rules:
        return None

    q_lower = question.lower()

    for rule in rules:
        keywords = rule.get("keywords", [])
        if not any(kw in q_lower for kw in keywords):
            continue

        # 프로젝트 스코프 체크 (규칙에 project_key가 있으면 일치 필요)
        rule_proj = rule.get("project_key")
        if rule_proj and project_key and rule_proj != project_key:
            continue

        jql_append = rule.get("jql_append", "")
        if jql_append:
            logger.info(
                f"[jira][규칙매칭] {rule.get('id')} → "
                f"'{jql_append}'"
            )
            return {"jql_append": jql_append, "rule_id": rule.get("id", "")}

    return None


# ── GDI 규칙 매칭 ───────────────────────────────────────────────

def match_gdi_keyword_rule(question: str) -> "dict | None":
    """질문 키워드로 GDI 검색 파라미터 매핑.

    Parameters
    ----------
    question : 사용자 질문 텍스트

    Returns
    -------
    dict | None
        매칭 시: {"type": "search_by_filename", "filename_pattern": "...",
                  "game_name": ..., "rule_id": "..."}
        미매칭 시: None → 기존 unified_search 사용
    """
    rules = _load_rules(_GDI_RULES_PATH)
    if not rules:
        return None

    q_lower = question.lower()

    for rule in rules:
        keywords = rule.get("keywords", [])
        if not any(kw in q_lower for kw in keywords):
            continue

        override = rule.get("search_override", {})
        if override:
            result = {
                "type": override.get("type", "unified_search"),
                "filename_pattern": override.get("filename_pattern", ""),
                "game_name": override.get("game_name"),
                "rule_id": rule.get("id", ""),
            }
            logger.info(
                f"[gdi][규칙매칭] {rule.get('id')} → "
                f"type={result['type']}, pattern='{result['filename_pattern']}'"
            )
            return result

    return None
