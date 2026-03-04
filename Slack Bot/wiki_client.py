"""
wiki_client.py - Confluence Team Calendar REST API 클라이언트

환경변수:
  CONFLUENCE_URL              : https://wiki.smilegate.net
  CONFLUENCE_TOKEN            : 개인용 액세스 토큰 (PAT)
  CONFLUENCE_SPACE_KEY        : 공간 키 (기본: QASGP)
  CONFLUENCE_CALENDAR_PROJECT : 프로젝트 일정 캘린더 ID
  CONFLUENCE_CALENDAR_PERSONAL: 개인/팀 일정 캘린더 ID
"""

import os
import re
import html as _html
import logging
import requests

logger = logging.getLogger(__name__)


def _strip_html(html_text: str) -> str:
    """HTML 태그 제거 + 엔티티 디코딩 → 읽기 쉬운 일반 텍스트"""
    text = re.sub(r'<[^>]+>', '\n', html_text or '')
    text = _html.unescape(text)           # &amp; &lt; &gt; &nbsp; 등 처리
    text = re.sub(r'[ \t]+', ' ', text)   # 가로 공백 정리
    text = re.sub(r'\n[ \t]+', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

_DEFAULT_SPACE_KEY = "QASGP"

# 슬랙 명령어 캘린더 유형 → 환경변수 키 & 표시명 매핑
CALENDAR_TYPES = {
    "플잭": ("CONFLUENCE_CALENDAR_PROJECT",  "프로젝트 일정"),
    "개인": ("CONFLUENCE_CALENDAR_PERSONAL", "개인/팀 일정"),
}


class ConfluenceCalendarClient:
    """Confluence Team Calendars REST API 래퍼"""

    def __init__(self):
        self.base_url = os.getenv("CONFLUENCE_URL", "").rstrip("/")
        token         = os.getenv("CONFLUENCE_TOKEN", "")
        self.session  = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept":        "application/json",
            "Content-Type":  "application/json",
        })

    # ── 내부 HTTP 헬퍼 ─────────────────────────────────────────────

    def _get(self, path: str, params: dict = None):
        """GET 요청 → (data, error_str)"""
        url = f"{self.base_url}{path}"
        try:
            r = self.session.get(url, params=params, timeout=10, allow_redirects=False)
            return self._handle_response(r)
        except requests.RequestException as e:
            logger.error(f"[wiki] GET 오류: {e}")
            return None, str(e)

    def _post(self, path: str, payload: dict):
        """POST 요청 → (data, error_str)"""
        url = f"{self.base_url}{path}"
        try:
            r = self.session.post(url, json=payload, timeout=10, allow_redirects=False)
            return self._handle_response(r)
        except requests.RequestException as e:
            logger.error(f"[wiki] POST 오류: {e}")
            return None, str(e)

    @staticmethod
    def _handle_response(r: requests.Response):
        """HTTP 응답 처리 → (data, error_str)"""
        if r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("Location", "?")
            msg = (
                "SSO 리다이렉트가 발생했습니다 — PAT가 SAML SSO를 우회하지 못했습니다.\n"
                f"리다이렉트 대상: {loc}"
            )
            logger.error(f"[wiki] {msg}")
            return None, msg
        if r.status_code == 401:
            return None, "인증 실패 (401) — CONFLUENCE_TOKEN 값을 확인하세요."
        if r.status_code == 403:
            return None, "접근 권한 없음 (403)"
        if r.status_code == 404:
            return None, "리소스를 찾을 수 없습니다 (404)"
        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            return None, f"HTTP 오류: {e}"
        try:
            return r.json(), None
        except ValueError:
            return r.text, None

    # ── 공개 API ──────────────────────────────────────────────────

    def list_calendars(self, space_key: str = None):
        """
        공간의 팀 캘린더 목록 조회

        Returns
        -------
        (list[dict] | None, error_str | None)
        """
        sk = space_key or os.getenv("CONFLUENCE_SPACE_KEY", _DEFAULT_SPACE_KEY)
        data, err = self._get(
            "/rest/teamcalendars/1.0/calendars",
            params={"spaceKey": sk},
        )
        if err:
            return None, err

        # 응답 형식: {"payload": [...]} 또는 직접 리스트
        if isinstance(data, dict):
            calendars = data.get("payload", data.get("calendars", []))
        elif isinstance(data, list):
            calendars = data
        else:
            calendars = []

        return calendars, None

    def create_event(
        self,
        calendar_id: str,
        title:       str,
        start_date:  str,        # 'YYYY-MM-DD'
        end_date:    str = None, # 생략 시 start_date 와 동일 (하루짜리)
    ):
        """
        캘린더에 하루짜리(all-day) 이벤트 등록

        Returns
        -------
        (response_dict | None, error_str | None)
        """
        end = end_date or start_date
        payload = {
            "calendarId": calendar_id,
            "title":      title,
            "allDay":     True,
            "start":      start_date,
            "end":        end,
        }
        logger.info(f"[wiki] 이벤트 등록 요청: calendarId={calendar_id}, date={start_date}, title={title}")
        return self._post("/rest/teamcalendars/1.0/events", payload)

    def get_page_by_title(self, title: str, space_key: str = None):
        """
        페이지 제목으로 Confluence 페이지 내용 조회.
        여러 결과가 있으면 첫 번째 반환.

        Returns
        -------
        (page_dict | None, error_str | None)
        page_dict = {"id", "title", "url", "text"}
        """
        sk = space_key or os.getenv("CONFLUENCE_SPACE_KEY", _DEFAULT_SPACE_KEY)
        data, err = self._get(
            "/rest/api/content",
            params={
                "title":    title,
                "spaceKey": sk,
                "expand":   "body.view",
                "limit":    5,
            },
        )
        if err:
            return None, err

        results = data.get("results", []) if isinstance(data, dict) else []
        if not results:
            return None, f"'{title}' 페이지를 찾을 수 없습니다. (공간: {sk})"

        page       = results[0]
        page_id    = page.get("id", "")
        page_title = page.get("title", title)
        page_url   = f"{self.base_url}/pages/viewpage.action?pageId={page_id}"
        html_body  = page.get("body", {}).get("view", {}).get("value", "")
        text       = _strip_html(html_body)

        return {"id": page_id, "title": page_title, "url": page_url, "text": text}, None

    def search_pages(self, query: str, space_key: str = None):
        """
        CQL 텍스트 검색으로 페이지 목록 반환 (제목 목록 용도).

        Returns
        -------
        (list[{"id", "title"}] | None, error_str | None)
        """
        sk = space_key or os.getenv("CONFLUENCE_SPACE_KEY", _DEFAULT_SPACE_KEY)
        cql = f'space="{sk}" AND text ~ "{query}" AND type=page ORDER BY lastmodified DESC'
        data, err = self._get(
            "/rest/api/content/search",
            params={"cql": cql, "limit": 10, "expand": ""},
        )
        if err:
            return None, err

        results = data.get("results", []) if isinstance(data, dict) else []
        pages = [{"id": p.get("id", ""), "title": p.get("title", "")} for p in results]
        return pages, None
