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
import logging
import requests

logger = logging.getLogger(__name__)

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
