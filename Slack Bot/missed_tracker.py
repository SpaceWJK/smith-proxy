"""
missed_tracker.py - 전일 누락 체크리스트 항목 추적

Railway 스케줄러가 interactive_checklist 메시지를 전송할 때 로그를 기록하고,
다음날 일일 체크리스트 전송 시 전일 미완료 항목을 조회해 반환합니다.

저장 파일: data/sent_checklist_log.json
```json
{
  "2026-03-04": [
    {
      "ts": "1741234567.123456",
      "channel": "C12345",
      "schedule_id": "daily-qa-checklist",
      "label": "[일일] 03/04(화)",
      "items": [
        {"value": "item_0", "text": "업무명", "mentions": ["U123"]}
      ]
    }
  ]
}
```

아키텍처 메모:
  Railway 파일시스템은 재배포 시 초기화됩니다.
  로그 파일이 없는 경우 당일 누락 체크는 건너뜁니다.
"""

import json
import logging
import os
import re

import pytz
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_BASE     = os.path.dirname(os.path.abspath(__file__))
_LOG_FILE = os.path.join(_BASE, "data", "sent_checklist_log.json")
_KST      = pytz.timezone("Asia/Seoul")

_DAY_KR = ["월", "화", "수", "목", "금", "토", "일"]

_TYPE_LABEL = {
    "daily":                  "일일",
    "weekly":                 "주간",
    "monthly":                "월간",
    "monthly_last_weekday":   "월간",
    "biweekly":               "격주",
    "nweekly":                "업데이트",
    "quarterly_first_monday": "분기",
}


# ── 내부 유틸 ──────────────────────────────────────────────────────────────

def _load_log() -> dict:
    if not os.path.exists(_LOG_FILE):
        return {}
    try:
        with open(_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"[missed] 로그 파일 로드 실패: {e}")
        return {}


def _save_log(data: dict):
    os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)
    with open(_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 공개 유틸 ──────────────────────────────────────────────────────────────

def make_label(schedule: dict) -> str:
    """스케줄 dict → 누락 섹션용 표시 레이블 (예: '[일일] 03/04(화)')"""
    today      = datetime.now(_KST)
    day_kr     = _DAY_KR[today.weekday()]
    type_label = _TYPE_LABEL.get(schedule.get("type", ""), "기타")
    return f"[{type_label}] {today.strftime('%m/%d')}({day_kr})"


def extract_flat_items(items: list) -> list:
    """
    config.json items (group 포함) → flat list
    반환: [{"value": str, "text": str, "mentions": list}, ...]

    group 항목은 group_name 에서 "[각 프로젝트] " 등 접두사를 제거한 업무명을
    sub_item text 와 결합하여 표시합니다.
    예: group_name="[각 프로젝트] 서비스 장애", sub text="[에픽세븐]"
        → combined text="[에픽세븐] 서비스 장애"
    """
    flat = []
    for item in items:
        if item.get("type") == "group":
            group_name  = item.get("group_name", "")
            # "[각 프로젝트] " 등 대괄호 접두사 제거
            clean_group = re.sub(r"^\[[^\]]+\]\s*", "", group_name).strip()
            for sub in item.get("sub_items", []):
                sub_text = sub.get("text", "")
                combined = f"{sub_text} {clean_group}" if clean_group else sub_text
                flat.append({
                    "value":    sub["value"],
                    "text":     combined,
                    "mentions": sub.get("mentions", []),
                })
        else:
            flat.append({
                "value":    item["value"],
                "text":     item.get("text", ""),
                "mentions": item.get("mentions", []),
            })
    return flat


# ── 로그 기록 ──────────────────────────────────────────────────────────────

def log_sent(
    channel:     str,
    ts:          str,
    schedule_id: str,
    label:       str,
    items:       list,
    date_str:    str = None,
):
    """
    전송 완료된 interactive_checklist 메시지를 로그에 기록합니다.

    Parameters
    ----------
    channel     : Slack 채널 ID
    ts          : 전송된 메시지 ts
    schedule_id : config.json schedule id
    label       : 누락 섹션 표시용 레이블 (예: '[일일] 03/05(목)')
    items       : flat 항목 목록 (extract_flat_items 결과)
    date_str    : 로그 날짜 키 'YYYY-MM-DD' (생략 시 오늘)
    """
    data     = _load_log()
    date_key = date_str or datetime.now(_KST).strftime("%Y-%m-%d")

    if date_key not in data:
        data[date_key] = []

    data[date_key].append({
        "ts":          ts,
        "channel":     channel,
        "schedule_id": schedule_id,
        "label":       label,
        "items":       items,
    })
    _save_log(data)
    logger.info(
        f"[missed] 전송 로그 기록: {schedule_id} / {label} / ts={ts} / "
        f"항목={len(items)}개 → {date_key}"
    )


# ── 누락 항목 조회 ─────────────────────────────────────────────────────────

def _fetch_checked_values(slack_client, channel: str, ts: str):
    """
    Slack conversations.history 로 메시지를 가져와 체크된 값(initial_options) 집합 반환.
    missed_ 접두사 블록(누락 섹션 자체)은 제외합니다.

    Returns: set[str] | None (조회 실패 시)
    """
    try:
        result = slack_client.conversations_history(
            channel   = channel,
            latest    = ts,
            oldest    = ts,
            inclusive = True,
            limit     = 1,
        )
        messages = result.get("messages", [])
        if not messages:
            logger.warning(f"[missed] 메시지를 찾을 수 없음: ch={channel} ts={ts}")
            return None

        checked = set()
        for block in messages[0].get("blocks", []):
            if block.get("type") != "actions":
                continue
            # 누락 섹션 자체의 블록은 건너뜀 (block_id가 "missed_"로 시작)
            if block.get("block_id", "").startswith("missed_"):
                continue
            for elem in block.get("elements", []):
                if elem.get("type") == "checkboxes":
                    for opt in elem.get("initial_options", []):
                        checked.add(opt["value"])
        return checked

    except Exception as e:
        logger.warning(f"[missed] 메시지 조회 실패 ({ts}): {e}")
        return None


def _prev_weekday_dates(max_days: int = 3) -> list:
    """
    오늘 기준 직전 평일 날짜를 최대 max_days 개 반환합니다 (최근순).
    예: 월요일 → ['2026-03-06', '2026-03-05', '2026-03-04']
    """
    dates   = []
    cur     = datetime.now(_KST)
    i       = 1
    while len(dates) < max_days:
        d = (cur - timedelta(days=i)).date()
        if d.weekday() < 5:          # 월~금만
            dates.append(d.strftime("%Y-%m-%d"))
        i += 1
        if i > max_days + 4:         # 무한 루프 방지
            break
    return dates


def get_missed_items_from_channel(
    slack_client,
    channel:      str,
    config_items: list,
    date_str:     str = None,
) -> list:
    """
    Slack 채널 히스토리를 직접 스캔하여 전일 체크리스트 누락 항목을 반환합니다.

    Railway 재시작으로 로컬 로그 파일이 없을 때 사용하는 폴백입니다.
    date_str 생략 시 가장 최근 평일(최대 3 평일 전)을 순서대로 탐색합니다.

    반환 형식은 get_missed_items 와 동일합니다.
    """
    flat_config = extract_flat_items(config_items)
    if not flat_config:
        return []

    search_dates = [date_str] if date_str else _prev_weekday_dates(max_days=3)

    for target in search_dates:
        try:
            target_dt = datetime.strptime(target, "%Y-%m-%d")
        except ValueError:
            continue

        start_ts = _KST.localize(target_dt.replace(
            hour=0, minute=0, second=0, microsecond=0
        )).timestamp()
        end_ts = _KST.localize(target_dt.replace(
            hour=23, minute=59, second=59, microsecond=0
        )).timestamp()

        try:
            resp = slack_client.conversations_history(
                channel   = channel,
                oldest    = str(start_ts),
                latest    = str(end_ts),
                inclusive = True,
                limit     = 50,
            )
        except Exception as e:
            logger.warning(
                f"[missed-fallback] 채널 히스토리 조회 실패 ({channel}/{target}): {e}"
            )
            continue

        for msg in resp.get("messages", []):
            blocks = msg.get("blocks", [])

            # 인터랙티브 체크리스트 메시지 식별
            # (action_id 가 "checklist_toggle" 으로 시작하는 checkboxes 블록)
            is_checklist = any(
                elem.get("type") == "checkboxes"
                and elem.get("action_id", "").startswith("checklist_toggle")
                for block in blocks
                if block.get("type") == "actions"
                   and not block.get("block_id", "").startswith("missed_")
                for elem in block.get("elements", [])
            )
            if not is_checklist:
                continue

            # 체크된 항목 수집 (initial_options)
            checked_values: set = set()
            for block in blocks:
                if block.get("type") != "actions":
                    continue
                if block.get("block_id", "").startswith("missed_"):
                    continue
                for elem in block.get("elements", []):
                    if elem.get("type") == "checkboxes":
                        for opt in elem.get("initial_options", []):
                            checked_values.add(opt["value"])

            # 미완료 항목 계산
            unchecked = [
                item for item in flat_config
                if item["value"] not in checked_values
            ]

            if not unchecked:
                logger.info(f"[missed-fallback] {target} 체크리스트 누락 없음 ✅")
                return []

            day_kr  = _DAY_KR[target_dt.weekday()]
            label   = f"[일일] {target_dt.strftime('%m/%d')}({day_kr})"
            remapped = [
                {
                    "value":    f"missed_0_{item['value']}",
                    "text":     item["text"],
                    "mentions": item.get("mentions", []),
                }
                for item in unchecked
            ]
            logger.info(
                f"[missed-fallback] {target} 채널 스캔으로 누락 {len(remapped)}개 발견"
            )
            return [{"label": label, "items": remapped}]

    logger.info(f"[missed-fallback] 채널 히스토리에서 전일 체크리스트 없음: {channel}")
    return []


def get_missed_items(slack_client, date_str: str = None) -> list:
    """
    전일 전송된 체크리스트 메시지에서 미완료(체크 안 된) 항목을 조회합니다.

    Parameters
    ----------
    slack_client : Slack WebClient (conversations_history 권한 필요)
    date_str     : 조회 대상 날짜 'YYYY-MM-DD' (생략 시 어제)

    Returns
    -------
    list[dict]:
        [
            {
                "label": "[일일] 03/04(화)",
                "items": [
                    {"value": "missed_0_item_0", "text": "업무명",
                     "mentions": ["U123"]},
                    ...
                ]
            },
            ...
        ]
        누락 없으면 빈 리스트.
    """
    yesterday  = (datetime.now(_KST) - timedelta(days=1)).strftime("%Y-%m-%d")
    target     = date_str or yesterday

    log_entries = _load_log().get(target, [])
    if not log_entries:
        logger.info(f"[missed] 전일({target}) 로그 없음 → 누락 체크 건너뜀")
        return []

    missed_groups: list = []

    for group_idx, entry in enumerate(log_entries):
        ts          = entry["ts"]
        channel     = entry["channel"]
        items       = entry.get("items", [])
        label       = entry.get("label", "")
        schedule_id = entry.get("schedule_id", "?")

        if not items:
            continue

        checked_values = _fetch_checked_values(slack_client, channel, ts)
        if checked_values is None:
            logger.warning(f"[missed] {schedule_id} 메시지 조회 실패, 건너뜀")
            continue

        # 미완료 항목 = 전체 - 체크된 것
        unchecked = [
            item for item in items
            if item["value"] not in checked_values
        ]

        if not unchecked:
            logger.info(f"[missed] {schedule_id} ({label}) 전일 누락 없음 ✅")
            continue

        # value를 "missed_{group_idx}_{원래값}" 으로 리매핑
        # → 당일 체크리스트 항목 value와 충돌 방지
        remapped = [
            {
                "value":    f"missed_{group_idx}_{item['value']}",
                "text":     item["text"],
                "mentions": item.get("mentions", []),
            }
            for item in unchecked
        ]

        logger.info(
            f"[missed] {schedule_id} ({label}) 누락 {len(remapped)}개: "
            f"{[r['value'] for r in remapped]}"
        )
        missed_groups.append({"label": label, "items": remapped})

    return missed_groups
