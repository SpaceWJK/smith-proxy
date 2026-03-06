"""
interaction_handler.py - 인터랙티브 체크리스트 상태 관리

체크/언체크 상태를 data/checklist_state.json 에 저장합니다.
메시지 ts(타임스탬프)를 키로 사용하여 상태를 관리합니다.
"""

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

# 상태 파일 경로 (스크립트 기준 data/ 폴더)
_BASE       = os.path.dirname(os.path.abspath(__file__))
STATE_FILE  = os.path.join(_BASE, "data", "checklist_state.json")


# ── 내부 유틸 ──────────────────────────────────────────────────────────

def _load() -> dict:
    """상태 파일 로드 (없으면 빈 dict 반환)"""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"상태 파일 로드 실패: {e}")
        return {}


def _save(state: dict):
    """상태 파일 저장 (data/ 폴더 없으면 생성)"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _key(channel: str, ts: str) -> str:
    """채널 + ts 로 고유 키 생성"""
    return f"{channel}:{ts}"


# ── 공개 인터페이스 ────────────────────────────────────────────────────

def register(
    channel: str,
    ts: str,
    schedule_id: str,
    title: str,
    items: list,
    schedule_type: str = "",
):
    """
    새 인터랙티브 체크리스트 메시지를 상태 파일에 등록합니다.

    Parameters
    ----------
    channel       : Slack 채널 ID (예: "C0XXXXXXXXX")
    ts            : 메시지 타임스탬프 (chat.postMessage 응답의 ts)
    schedule_id   : config.json 의 스케줄 id
    title         : 체크리스트 제목
    items         : 체크리스트 항목 목록
                    예: [{"value": "item_0", "text": "작업명", "mentions": ["U12345"]}, ...]
    schedule_type : config.json 의 type 값 (예: "daily", "weekly", "monthly" 등)
                    period_label(주차 표시 등) 복원에 사용됩니다.
    """
    state   = _load()
    k       = _key(channel, ts)
    sent_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    state[k] = {
        "channel":       channel,
        "ts":            ts,
        "schedule_id":   schedule_id,
        "schedule_type": schedule_type,
        "title":         title,
        "sent_at":       sent_at,
        "registered":    datetime.now().isoformat(),
        "items":         items,
        "checked":       [],
    }
    _save(state)
    logger.info(f"체크리스트 등록 완료: {k}  ({len(items)}개 항목)")


def get_by_ts(channel: str, ts: str):
    """
    channel + ts 로 체크리스트 상태를 조회합니다.

    Returns
    -------
    dict  : 상태 정보 (없으면 None)
    """
    return _load().get(_key(channel, ts))


def update_checked(channel: str, ts: str, checked_values: list):
    """
    체크된 항목 목록을 갱신하고 갱신된 상태를 반환합니다.

    Parameters
    ----------
    channel        : Slack 채널 ID
    ts             : 메시지 타임스탬프
    checked_values : 현재 선택된 option value 목록 (예: ["item_0", "item_2"])
                     Slack checkboxes 의 selected_options[*].value 를 전달합니다.

    Returns
    -------
    dict  : 갱신된 상태 (키 없으면 None)
    """
    state = _load()
    k     = _key(channel, ts)

    if k not in state:
        logger.warning(f"상태 없음 - 업데이트 불가: {k}")
        return None

    state[k]["checked"] = checked_values
    state[k]["updated"] = datetime.now().isoformat()
    _save(state)

    logger.info(f"체크리스트 갱신: {k}  checked_values={len(checked_values)}개")
    return state[k]


def get_all() -> dict:
    """전체 상태 반환 (디버그/모니터링용)"""
    return _load()
