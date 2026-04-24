"""
mcp_session.py - MCP Streamable HTTP 세션 공용 모듈

wiki_client.py, gdi_client.py 등 여러 MCP 클라이언트에서 공유하는
MCP Streamable HTTP 프로토콜 세션 관리 클래스.

프로토콜 요약:
  1. POST /mcp-endpoint  {initialize}  -> 세션 ID 발급, SSE 응답
  2. POST /mcp-endpoint  {notifications/initialized}  -> 202
  3. POST /mcp-endpoint  {tools/call}  + Mcp-Session-Id 헤더 -> SSE 응답
"""

import json
import logging
import threading
import requests

logger = logging.getLogger(__name__)


class McpSession:
    """
    MCP Streamable HTTP 세션.

    Parameters
    ----------
    url     : MCP 서버 엔드포인트 URL
    headers : 추가 HTTP 헤더 dict (예: wiki 인증 헤더). None이면 기본 헤더만 사용.
    label   : 로그 접두사 (예: "wiki", "gdi")
    """

    def __init__(self, url: str, headers: dict = None, label: str = "mcp"):
        self._url         = url
        self._label       = label
        self._session_id  = None
        self._initialized = False
        self._initializing = False
        self._req_id      = 0

        self._http = requests.Session()
        self._http.headers.update({
            "Content-Type": "application/json",
            "Accept"      : "application/json, text/event-stream",
        })
        if headers:
            self._http.headers.update(headers)

        self._lock = threading.Lock()

    # -- 내부 헬퍼 ----------------------------------------------------------

    def _next_id(self) -> int:
        with self._lock:
            self._req_id += 1
            return self._req_id

    def _extra_headers(self) -> dict:
        return {"Mcp-Session-Id": self._session_id} if self._session_id else {}

    @staticmethod
    def _is_session_error(err: str) -> bool:
        """세션 만료/인증 오류 여부 판단 -- 재연결 트리거용"""
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
        JSON-RPC 2.0 POST 요청 -> (rpc_result_or_none, error_str_or_none)
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
                with self._lock:
                    self._session_id = sid

            if r.status_code == 202:          # 알림에 대한 정상 응답
                return None, None
            if r.status_code >= 400:
                # 세션 만료/인증 오류 -> 세션 상태 초기화 (call_tool 재연결 대비)
                if r.status_code in (400, 401, 403):
                    with self._lock:
                        self._initialized = False
                        self._session_id  = None
                return None, f"HTTP {r.status_code}: {r.text[:300]}"

            ct = r.headers.get("Content-Type", "")
            if "text/event-stream" in ct:
                # r.text 는 Content-Type 에 charset 미선언 시 ISO-8859-1 로 디코딩됨
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

    # -- 공개 메서드 --------------------------------------------------------

    def initialize(self) -> tuple:
        """MCP 세션 초기화 (최초 1회). -> (True/False, error_str)"""
        with self._lock:
            if self._initialized:
                return True, None
            if self._initializing:
                return False, "초기화 진행 중"  # 이중 초기화 방지
            self._initializing = True

        try:
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
                logger.error(f"[{self._label}] MCP 초기화 실패: {err}")
                with self._lock:
                    self._initializing = False
                return False, f"MCP 초기화 실패: {err}"

            # notifications/initialized (응답 무시)
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"},
                       timeout=10)

            with self._lock:
                self._initialized = True
                self._initializing = False
            logger.info(f"[{self._label}] MCP 세션 초기화 완료. session_id={self._session_id}")
            return True, None
        except Exception as e:
            with self._lock:
                self._initializing = False
            return False, str(e)

    def call_tool(self, name: str, arguments: dict,
                  _retry: bool = True, timeout: int = 30) -> tuple:
        """
        MCP 도구 호출. 세션 만료 감지 시 자동 재연결 후 1회 재시도.

        Parameters
        ----------
        timeout : HTTP 요청 타임아웃(초). 병렬 실행 시 5 전달 권장.

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
        }, timeout=timeout)

        # 세션 만료 감지 -> 세션 리셋 후 1회 재시도
        if err and _retry and self._is_session_error(err):
            logger.warning(
                f"[{self._label}] 세션 만료 감지, 재연결 후 재시도 ({name}): {err[:80]}"
            )
            with self._lock:
                self._initialized = False
                self._session_id  = None
            return self.call_tool(name, arguments, _retry=False, timeout=timeout)

        if err:
            logger.error(f"[{self._label}] MCP 도구 호출 오류 ({name}): {err}")
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
                logger.warning(f"[{self._label}] MCP 도구 오류 ({name}): {text[:200]}")
                return None, text or "도구 오류"
            return text, None

        return str(result) if result is not None else None, None
