"""
safety_guard.py — 읽기 전용 안전 가드

슬랙봇을 통한 모든 AI 질의에서 원본 수정/삭제 요청을 차단합니다.
조회·검색·분석·요약은 허용하되, Wiki/Jira/GDI 원본 데이터의
수정·삭제·생성 요청은 사전에 감지하여 차단합니다.

사용법:
    from safety_guard import detect_write_intent, format_block_message, READ_ONLY_INSTRUCTION

    keyword = detect_write_intent("이슈 삭제해줘")
    if keyword:
        respond(text=format_block_message(keyword))
        return
"""

import re


# ── 쓰기 의도 감지 정규식 ────────────────────────────────────────
# 한국어: ~해줘, ~해, ~하자 등 요청형 어미와 결합되는 동작 키워드
# 영어: 동사 원형 (imperative)
_WRITE_PATTERNS = re.compile(
    r'(삭제해|제거해|지워줘|지워|없애|변경해|수정해|바꿔|편집해|'
    r'생성해|만들어|추가해|등록해|업데이트해|올려|작성해|입력해|넣어|'
    r'이동해|옮겨|닫아줘|닫아|닫어|할당해|배정해|'
    r'delete|remove|modify|change|update|create|add|edit|move|close|assign|write)',
    re.IGNORECASE,
)

# 과거형/명사형 — 읽기 의도 (이력 조회, 변경 내역 확인 등)
_READ_EXCEPTIONS = re.compile(
    r'(삭제된|변경된|수정된|생성된|추가된|업데이트된|이동된|'
    r'변경\s*이력|변경\s*내역|변경\s*사항|변경\s*로그|'
    r'수정\s*이력|수정\s*내역|수정\s*사항|'
    r'업데이트\s*내역|업데이트\s*이력|업데이트\s*사항|'
    r'삭제\s*이력|삭제\s*내역|'
    r'deleted|removed|modified|changed|updated|created|added|edited|moved|closed)',
    re.IGNORECASE,
)


def detect_write_intent(question: str) -> "str | None":
    """질문에서 쓰기 의도를 감지합니다.

    Parameters
    ----------
    question : str
        사용자의 질문 텍스트

    Returns
    -------
    str | None
        감지된 쓰기 키워드 (예: "삭제해") 또는 None (읽기 의도)
    """
    if not question:
        return None

    # 과거형/이력 조회 패턴이 먼저 매칭되면 읽기 의도로 판단
    if _READ_EXCEPTIONS.search(question):
        return None

    m = _WRITE_PATTERNS.search(question)
    return m.group(0) if m else None


# ── Claude 프롬프트용 읽기 전용 안내 ─────────────────────────────
READ_ONLY_INSTRUCTION = (
    "\n\n[중요] 이 봇은 읽기 전용입니다. "
    "데이터 수정·삭제·생성 요청이 포함되어 있다면, "
    "'이 봇은 조회/분석만 가능하며, 직접 수정/삭제는 지원하지 않습니다'라고 안내하세요."
)


def format_block_message(keyword: str) -> str:
    """쓰기 의도 차단 시 사용자에게 표시할 메시지를 생성합니다."""
    return (
        f":no_entry: *허용되지 않는 요청입니다*\n\n"
        f"감지된 키워드: `{keyword}`\n\n"
        f"이 봇은 *조회·검색·분석·요약*만 지원합니다.\n"
        f"Wiki/Jira/GDI 원본의 수정·삭제·생성은 직접 해당 시스템에서 수행하세요."
    )
