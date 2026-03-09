"""
schedule_monitor.py - 스케줄 실행 모니터링

각 스케줄 job이 실행될 때 log_fired()를 호출하여 당일 실행 기록을 남깁니다.
check_and_alert()는 매일 18:00(KST) 평일에 실행되며,
예정 시각 + 유예시간(grace) 이 지났음에도 실행 기록이 없는 스케줄을
config['monitor_alert_channel'] 채널에 알림 메시지로 발송합니다.

저장 파일: data/job_fire_log.json
{
  "2026-03-09": {
    "daily-qa-checklist": "10:00:23",
    "daily-work-header": "09:00:07",
    ...
  }
}

아키텍처 메모:
  Railway 파일시스템은 재배포 시 초기화됩니다.
  로그 파일이 없더라도 check_and_alert 는 당일 조회 기준으로만 동작하므로
  재배포 직후 false positive 가 발생할 수 있습니다 (메시지 내 안내 문구 포함).
"""

import json
import logging
import os
from datetime import datetime, timedelta

import pytz
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)

_BASE     = os.path.dirname(os.path.abspath(__file__))
_LOG_FILE = os.path.join(_BASE, "data", "job_fire_log.json")
_KST      = pytz.timezone("Asia/Seoul")

# 복잡한 간격 타입은 당일 실행 여부 판단이 어려워 모니터링 제외
_SKIP_TYPES = {"biweekly", "nweekly", "specific"}

# 미션 job: 09:00 + jitter 최대 30분 + 여유 60분 = 11:00 이후 체크
_MISSION_GRACE_HOUR   = 11
_DEFAULT_GRACE_MINUTES = 90   # 일반 스케줄 유예 시간 (분)


# ── 내부 유틸 ───────────────────────────────────────────────────────────────

def _load() -> dict:
    if not os.path.exists(_LOG_FILE):
        return {}
    try:
        with open(_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"[monitor] 로그 파일 로드 실패: {e}")
        return {}


def _save(data: dict):
    os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)
    with open(_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 공개 인터페이스 ──────────────────────────────────────────────────────────

def log_fired(schedule_id: str, date_str: str = None):
    """
    스케줄 job이 실행될 때 호출합니다. 당일 실행 시각을 기록합니다.

    Parameters
    ----------
    schedule_id : config.json schedule id
    date_str    : 로그 날짜 키 'YYYY-MM-DD' (생략 시 오늘 KST)
    """
    data     = _load()
    date_key = date_str or datetime.now(_KST).strftime("%Y-%m-%d")

    if date_key not in data:
        data[date_key] = {}

    fired_at = datetime.now(_KST).strftime("%H:%M:%S")
    data[date_key][schedule_id] = fired_at
    _save(data)
    logger.debug(f"[monitor] 실행 기록: {schedule_id} @ {fired_at}")


def get_fired_today(date_str: str = None) -> dict:
    """
    당일 실행된 schedule_id → fired_time 딕셔너리를 반환합니다.

    Returns
    -------
    dict : {"schedule-id": "HH:MM:SS", ...}  실행 기록 없으면 빈 dict
    """
    date_key = date_str or datetime.now(_KST).strftime("%Y-%m-%d")
    return _load().get(date_key, {})


# ── 당일 실행 여부 판단 ──────────────────────────────────────────────────────

_DAY_ABBR_MAP = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed",
    "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun",
    "mon": "mon", "tue": "tue", "wed": "wed",
    "thu": "thu", "fri": "fri", "sat": "sat", "sun": "sun",
    "월요일": "mon", "화요일": "tue", "수요일": "wed",
    "목요일": "thu", "금요일": "fri", "토요일": "sat", "일요일": "sun",
    "월": "mon", "화": "tue", "수": "wed",
    "목": "thu", "금": "fri", "토": "sat", "일": "sun",
}
_DAY_WD_IDX = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3,
    "fri": 4, "sat": 5, "sun": 6,
}


def should_fire_today(schedule: dict) -> bool:
    """
    오늘 이 스케줄이 실행되어야 하는지 판단합니다.

    복잡한 간격 타입(biweekly / nweekly / specific)은 False 반환.
    quarterly_first_monday 는 당일 날짜 조건을 직접 확인합니다.
    """
    stype   = schedule.get("type", "")
    today   = datetime.now(_KST)
    weekday = today.weekday()   # 0=월 ... 6=일

    if stype in _SKIP_TYPES:
        return False

    if stype in ("daily", "mission"):
        return weekday < 5   # 평일만

    if stype in ("weekly", "monthly_last_weekday"):
        raw   = schedule.get("day_of_week", "")
        abbr  = _DAY_ABBR_MAP.get(raw.lower().strip(), "")
        target_wd = _DAY_WD_IDX.get(abbr, -1)
        return weekday == target_wd

    if stype == "monthly":
        day_of_month = schedule.get("day_of_month", 1)
        return today.day == day_of_month

    if stype == "quarterly_first_monday":
        # 1·4·7·10월의 1~7일 중 월요일
        return (
            today.month in (1, 4, 7, 10)
            and 1 <= today.day <= 7
            and weekday == 0
        )

    return False


def scheduled_time_passed(schedule: dict, grace_minutes: int = _DEFAULT_GRACE_MINUTES) -> bool:
    """
    '스케줄 예정 시각 + grace_minutes' 가 현재 시각보다 이른지 확인합니다.
    이 조건을 만족해야 '충분한 시간이 지났음에도 미실행'으로 판단합니다.

    - 미션(mission): 09:00 + jitter 30분 + grace 60분 → 11:00 이후
    - 그 외: schedule['time'] + grace_minutes 이후
    """
    now   = datetime.now(_KST)
    stype = schedule.get("type", "")

    if stype == "mission":
        check_time = now.replace(
            hour=_MISSION_GRACE_HOUR, minute=0, second=0, microsecond=0
        )
        return now >= check_time

    time_str = schedule.get("time", "")
    if not time_str:
        return False

    try:
        h, m = map(int, time_str.strip().split(":"))
    except ValueError:
        return False

    scheduled_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
    check_dt     = scheduled_dt + timedelta(minutes=grace_minutes)
    return now >= check_dt


# ── 모니터링 체크 + 알림 ────────────────────────────────────────────────────

def check_and_alert(config: dict, slack_client):
    """
    당일 실행되어야 했던 스케줄 중 미실행 건을 Slack으로 알립니다.

    조건:
      1) enabled=True 인 스케줄
      2) should_fire_today() → True
      3) scheduled_time_passed() → True  (유예 시간 경과)
      4) get_fired_today() 에 실행 기록 없음

    Parameters
    ----------
    config       : config.json 전체 dict
    slack_client : Slack WebClient (chat:write 권한 필요)
    """
    alert_channel = config.get("monitor_alert_channel")
    if not alert_channel:
        logger.warning("[monitor] monitor_alert_channel 미설정 → 알림 건너뜀")
        return

    today = datetime.now(_KST)
    if today.weekday() >= 5:
        logger.info("[monitor] 주말 → 모니터링 건너뜀")
        return

    fired_today      = get_fired_today()
    missed_schedules = []

    for s in config.get("schedules", []):
        if not s.get("enabled", True):
            continue
        if not should_fire_today(s):
            continue
        if not scheduled_time_passed(s):
            continue
        if s["id"] in fired_today:
            continue
        missed_schedules.append(s)

    if not missed_schedules:
        logger.info("[monitor] ✅ 모든 스케줄 정상 실행 확인")
        return

    # ── 알림 메시지 구성 ────────────────────────────────────────────────────
    date_str = today.strftime("%Y-%m-%d")
    lines    = [
        f"🚨 *스케줄 미실행 감지* — {date_str} {today.strftime('%H:%M')} KST 기준\n"
    ]

    for s in missed_schedules:
        stype      = s.get("type", "?")
        sched_time = "09:00~09:30 (랜덤)" if stype == "mission" else s.get("time", "?")
        fired_time = fired_today.get(s["id"], "미기록")
        lines.append(
            f"• *{s.get('name', s['id'])}* (`{s['id']}`)\n"
            f"  └ 타입: `{stype}` | 예정: {sched_time} | 실행: {fired_time}"
        )

    lines.append(
        "\n_⚠ Railway 재배포 직후 발생한 경우 false positive일 수 있습니다._"
    )

    text = "\n".join(lines)
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
    ]

    try:
        slack_client.chat_postMessage(
            channel = alert_channel,
            text    = f"스케줄 미실행 감지 ({len(missed_schedules)}건) — {date_str}",
            blocks  = blocks,
        )
        logger.info(
            f"[monitor] 미실행 알림 전송: {len(missed_schedules)}건 → {alert_channel}"
        )
    except SlackApiError as e:
        logger.error(f"[monitor] 알림 전송 실패: {e.response['error']}")
