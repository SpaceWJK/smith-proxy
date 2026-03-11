"""
message_expiry.py — 슬래시 커맨드 답변 메시지 자동 만료 (v1.5.3)

ExpiringResponder가 chat_postMessage + chat_update 패턴으로:
1. 생성 시: chat_postMessage로 "⏳ 처리 중..." 전송 → ts 확보
2. respond() 호출 시: chat_update(ts)로 답변 교체
3. N분 후: chat_update(ts)로 만료 텍스트 교체

이전 방식(response_url + replace_original)은 Slack의 response_url이
첫 POST를 "original"로 취급하지 않아 메시지가 분할되는 문제가 있었음.
chat_postMessage/chat_update는 ts 기반이므로 확실하게 동일 메시지를 교체.

적용 대상: /wiki, /gdi, /jira (모든 서브커맨드)
비적용: /claim, /wiki-sync, 스케줄러 알림
"""

import logging
import threading

logger = logging.getLogger("slack_bot")

# ── 모듈 레벨 설정 (main()에서 환경변수로 덮어씌움) ────────────
MESSAGE_EXPIRY_SECONDS = 600        # 기본 10분
MESSAGE_EXPIRY_ENABLED = True       # False면 래핑 자체를 건너뜀

EXPIRY_TEXT = "⏰ 이 메시지는 보안 정책에 따라 만료되었습니다.\n다시 조회하려면 커맨드를 재입력하세요."


class ExpiringResponder:
    """respond() 래퍼 — chat_postMessage + chat_update 패턴.

    동작 흐름:
    1. send_initial() 호출
       → client.chat_postMessage(channel, text="처리 중...") → ts 확보
    2. respond(text=답변) 호출 시:
       → client.chat_update(channel, ts, text=답변) → 동일 메시지 교체
    3. N분 후 만료 타이머 발동:
       → client.chat_update(channel, ts, text=만료) → 동일 메시지 교체
    """

    def __init__(self, original_respond, slack_client, channel_id,
                 expiry_seconds=None):
        self._respond = original_respond     # 폴백용
        self._client = slack_client          # slack_bolt client (WebClient)
        self._channel = channel_id
        self._expiry_seconds = expiry_seconds or MESSAGE_EXPIRY_SECONDS
        self._ts = None                      # 메시지 타임스탬프
        self._timer = None
        self._lock = threading.Lock()

    def send_initial(self, text="⏳ 처리 중..."):
        """chat_postMessage로 첫 메시지를 전송하고 ts를 확보."""
        if not self._client or not self._channel:
            logger.warning("[초기] client 또는 channel이 없어 폴백")
            return
        try:
            result = self._client.chat_postMessage(
                channel=self._channel,
                text=text,
            )
            self._ts = result.get("ts")
            logger.info(f"[초기] '처리 중...' 메시지 생성 (ts={self._ts})")
        except Exception as e:
            logger.warning(f"[초기] chat_postMessage 실패: {e}")

    # ── respond() 대체 호출 ──────────────────────────────
    def __call__(self, **kwargs):
        """chat_update로 '처리 중...' 메시지를 답변으로 교체."""
        if not self._ts:
            # ts가 없으면 원래 respond() 폴백
            logger.warning("[respond] ts 없음, 원래 respond 폴백")
            result = self._respond(**kwargs)
            self._reset_timer()
            return result

        try:
            update_kwargs = {
                "channel": self._channel,
                "ts": self._ts,
            }
            if "text" in kwargs:
                update_kwargs["text"] = kwargs["text"]
            if "blocks" in kwargs:
                update_kwargs["blocks"] = kwargs["blocks"]

            self._client.chat_update(**update_kwargs)
            logger.info(f"[respond] chat_update 완료 (ts={self._ts})")
            result = None
        except Exception as e:
            logger.warning(f"[respond] chat_update 실패 ({e}), 폴백 사용")
            result = self._respond(**kwargs)

        self._reset_timer()
        return result

    # ── 타이머 관리 ──────────────────────────────────────
    def _reset_timer(self):
        """매 호출마다 타이머를 리셋 (마지막 메시지 기준 N분 후 만료)."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(
                self._expiry_seconds, self._expire_message
            )
            self._timer.daemon = True
            self._timer.start()

    def _expire_message(self):
        """chat_update로 만료 텍스트를 교체."""
        if not self._ts:
            logger.warning("[만료] ts가 없어 만료 처리 불가")
            return

        try:
            self._client.chat_update(
                channel=self._channel,
                ts=self._ts,
                text=EXPIRY_TEXT,
            )
            logger.info(f"[만료] 메시지 만료 처리 완료 (ts={self._ts})")
        except Exception as e:
            logger.warning(f"[만료] 만료 처리 실패: {e}")
