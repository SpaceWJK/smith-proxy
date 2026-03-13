"""
response_formatter.py — 통합 응답 포맷터 (v1.5.3)

/wiki, /gdi, /jira AI 답변을 일관된 3단 구조로 출력.

구조:
  📋 질문
  💬 답변  (핵심 결론)
  📎 근거  (판단 이유 — 없으면 생략)
  🔗 출처  (원본 링크)
"""

import re


# ── Claude 프롬프트에 추가할 응답 형식 지시문 ────────────────────

ANSWER_FORMAT_INSTRUCTION = (
    "\n\n[응답 형식]\n"
    "반드시 아래 형식으로 답변하세요:\n\n"
    "[답변]\n"
    "(질문에 대한 핵심 결론을 간결하게)\n\n"
    "[근거]\n"
    "(답변의 근거가 되는 원문 내용이나 판단 이유를 설명)"
)


# ── 파서 ─────────────────────────────────────────────────────────

def parse_answer_sections(raw: str) -> tuple:
    """Claude 응답에서 [답변]과 [근거] 섹션을 분리.

    반환: (answer, evidence)
    파싱 실패 시 (raw, "") — 안전 폴백.
    """
    m = re.search(
        r"\[답변\]\s*\n(.*?)\n\s*\[근거\]\s*\n(.*)",
        raw, re.DOTALL,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return raw.strip(), ""


# ── 포맷터 ───────────────────────────────────────────────────────

def format_ai_response(
    question: str,
    raw_answer: str,
    source_type: str,       # "wiki" | "jira" | "gdi"
    source_label: str,      # 페이지 제목 / 이슈키 / 파일명
    source_url: str = "",   # 원본 링크 (없으면 빈 문자열)
    display_question: str = "",  # 표시용 전체 커맨드 (없으면 question 사용)
) -> str:
    """3단 구조 통합 포맷 mrkdwn 문자열을 반환."""
    answer, evidence = parse_answer_sections(raw_answer)

    shown_question = display_question or question
    parts = [
        f"📋 *질문*\n{shown_question}",
        f"💬 *답변*\n{answer}",
    ]

    if evidence:
        parts.append(f"📎 *근거*\n{evidence}")

    # ── 출처 라인 ──
    type_label = {"wiki": "Wiki", "jira": "Jira", "gdi": "GDI"}.get(
        source_type, source_type
    )
    if source_url:
        parts.append(
            f"🔗 *출처*: {type_label} · <{source_url}|{source_label} 바로가기>"
        )
    else:
        parts.append(f"🔗 *출처*: {type_label} · {source_label}")

    return "\n\n".join(parts)
