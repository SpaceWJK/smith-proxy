"""
failure_analyzer.py — Wiki/GDI 실패 로그 파싱 및 KPI 분석 모듈

answer_miss.log + gdi_query.log 파싱 → 카테고리 분류 → 베이스라인 KPI JSON 생성.
설계 기준: step2_design.md v2 (QA MAJOR 8건 반영)
"""

from __future__ import annotations

import csv
import difflib
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 로그 파일 기본 경로
# ---------------------------------------------------------------------------
_LOG_DIR = Path(__file__).parent.parent.parent / "logs"
ANSWER_MISS_LOG = _LOG_DIR / "answer_miss.log"
GDI_QUERY_LOG = _LOG_DIR / "gdi_query.log"

# ---------------------------------------------------------------------------
# 데이터 모델
# ---------------------------------------------------------------------------

@dataclass
class MissEntry:
    """answer_miss.log 파싱 결과 한 레코드."""
    timestamp: datetime
    miss_type: str          # CACHE_MISS | ALL_MISS
    user: str
    page_id: str
    page_name: str
    question: str
    stages: str
    category: str           # CACHE_MISS | ALL_MISS | TIME_RANGE
    time_range_flag: bool


@dataclass
class GdiEntry:
    """gdi_query.log 파싱 결과 한 레코드."""
    timestamp: datetime
    status: str             # OK | ERROR
    handler: str            # ask_claude | folder_ai | folder_ai_list | search
    user: str
    query: str              # folder_path 또는 통합 쿼리
    keyword: Optional[str]  # 9-field 형식에서만 존재
    question: Optional[str] # 9-field 형식에서만 존재
    result_or_error: str    # result=.../error=... 접두사 제거 후 저장
    cache: Optional[str]    # ask_claude OK 중 cache=TAXONOMY 등
    duration_ms: int        # "7335ms" → 7335
    category: str           # OK | CONTENT_EMPTY | KEYWORD_MISS | FOLDER_MISS |
                            # DATE_FORMAT | TYPO | SEARCH_MISS

# ---------------------------------------------------------------------------
# TIME_RANGE 감지 패턴 (MAJOR-6 반영 — 8개)
# ---------------------------------------------------------------------------
_TIME_RANGE_PATTERNS = [
    re.compile(r'\d+월\s*(첫째|둘째|셋째|넷째|마지막)\s*주'),   # N월 N째주
    re.compile(r'(이번|지난|저번)\s*(주|달|월|분기)'),
    re.compile(r'Q[1-4]|[1-4]분기'),
    re.compile(r'\d+월\s+업무|업무\s+\d+월'),
    re.compile(r'(최근|지난)\s*\d+\s*(일|주|개월)'),
    re.compile(r'월별|주별|주차별'),                              # MAJOR-6 추가
    re.compile(r'\d+년\s*\d+월'),                                # MAJOR-6: 연도+월
    re.compile(r'\d+월(?:\s*\d+일)?(?!\s*(?:첫째|둘째|셋째|넷째|마지막))'),  # MAJOR-6: N월/N월 N일
]

# ---------------------------------------------------------------------------
# GDI 에러 카테고리 패턴 (MAJOR-3/7 반영)
# ---------------------------------------------------------------------------
_GDI_ERROR_PATTERNS = [
    (re.compile(r'파일 내용 없음'),    'CONTENT_EMPTY'),
    (re.compile(r'키워드.*파일 없음'), 'KEYWORD_MISS'),
    (re.compile(r'폴더에 파일 없음'), 'FOLDER_MISS'),
    (re.compile(r'검색 결과 없음'),    'SEARCH_MISS_CANDIDATE'),
]

# TYPO 판별에 사용할 알려진 게임명 목록 (MAJOR-7)
_KNOWN_GAME_NAMES = [
    'Chaoszero', 'Epicseven', 'Kazena', 'Kazen', 'Sevenknights',
    'ChaosZero', 'EpicSeven',
]

# answer_miss.log 정규식
_MISS_LINE_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})'   # [1] timestamp
    r' \| (CACHE_MISS|ALL_MISS)'                  # [2] miss_type
    r' \| user=(\S+)'                             # [3] user
    r' \| page=(.+?) \(id=(\d+)\)'               # [4] page_name, [5] page_id
    r' \| question=(.+?)'                         # [6] question
    r' \| stages=(.+)$'                           # [7] stages
)

# ---------------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------------

def _detect_time_range(text: str) -> bool:
    """텍스트에 TIME_RANGE 패턴이 포함되어 있으면 True."""
    for pattern in _TIME_RANGE_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _parse_duration_ms(raw: str) -> int:
    """'7335ms' → 7335. 변환 실패 시 0 반환."""
    raw = raw.strip()
    if raw.endswith('ms'):
        try:
            return int(raw[:-2])
        except ValueError:
            logger.warning("duration_ms 파싱 실패: %r", raw)
            return 0
    try:
        return int(raw)
    except ValueError:
        logger.warning("duration_ms 파싱 실패: %r", raw)
        return 0

# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def classify_gdi_error(error_text: str, query: str) -> str:
    """GDI 에러 텍스트 + 쿼리 → 카테고리 문자열 반환.

    우선순위:
    1. 명시적 에러 패턴 매칭 (CONTENT_EMPTY / KEYWORD_MISS / FOLDER_MISS)
    2. SEARCH_MISS_CANDIDATE → DATE_FORMAT / TYPO / SEARCH_MISS 세분화 (MAJOR-3)
    """
    for pattern, category in _GDI_ERROR_PATTERNS:
        if pattern.search(error_text):
            if category == 'SEARCH_MISS_CANDIDATE':
                return _classify_search_miss(query)
            return category

    # 패턴 미매칭 → SEARCH_MISS 폴백
    return 'SEARCH_MISS'


def _classify_search_miss(query: str) -> str:
    """SEARCH_MISS_CANDIDATE를 DATE_FORMAT / TYPO / SEARCH_MISS로 세분화."""
    # DATE_FORMAT: query에 r'\d+/\d+' 포함 (예: 2/25타겟)
    if re.search(r'\d+/\d+', query):
        return 'DATE_FORMAT'

    # TYPO: 쿼리 단어가 알려진 게임명과 SequenceMatcher ratio >= 0.8 이면서 다른 경우
    for word in re.split(r'[\s\\,]+', query):
        w = word.strip("'\"").strip()
        if not w:
            continue
        for game in _KNOWN_GAME_NAMES:
            ratio = difflib.SequenceMatcher(None, w.lower(), game.lower()).ratio()
            if ratio >= 0.8 and w.lower() != game.lower():
                return 'TYPO'

    return 'SEARCH_MISS'


def parse_answer_miss_log(path: str | Path = ANSWER_MISS_LOG) -> list[MissEntry]:
    """answer_miss.log 파싱 → MissEntry 리스트.

    - 파일 없음 / 빈 파일: 예외 없이 빈 리스트 반환 (T-10)
    - 파싱 불가 라인: 경고 로그 후 skip
    """
    path = Path(path)
    entries: list[MissEntry] = []

    if not path.exists():
        logger.warning("answer_miss.log 파일 없음: %s", path)
        return entries

    try:
        with open(path, encoding='utf-8') as f:
            raw_lines = f.readlines()
    except OSError as e:
        logger.warning("answer_miss.log 읽기 실패: %s", e)
        return entries

    for lineno, line in enumerate(raw_lines, 1):
        line = line.strip()
        if not line:
            continue

        m = _MISS_LINE_RE.match(line)
        if not m:
            logger.warning("answer_miss.log 파싱 불가 (line %d): 필드=%d", lineno, len(line.split(' | ')))
            continue

        ts_str, miss_type, user, page_name, page_id, question, stages = m.groups()

        try:
            timestamp = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            logger.warning("타임스탬프 파싱 실패 (line %d): %s", lineno, ts_str)
            continue

        time_range_flag = _detect_time_range(question)

        if time_range_flag:
            category = 'TIME_RANGE'
        else:
            category = miss_type  # CACHE_MISS | ALL_MISS

        entries.append(MissEntry(
            timestamp=timestamp,
            miss_type=miss_type,
            user=user,
            page_id=page_id,
            page_name=page_name,
            question=question,
            stages=stages,
            category=category,
            time_range_flag=time_range_flag,
        ))

    return entries


def parse_gdi_query_log(path: str | Path = GDI_QUERY_LOG) -> list[GdiEntry]:
    """gdi_query.log 파싱 → GdiEntry 리스트.

    필드 수 가변 처리 (MAJOR-1):
    - 7-field: ts | status | handler | user | query | result_or_error | duration
    - 8-field: ts | status | handler | user | query | result_or_error | cache_field | duration
    - 9-field: ts | status | handler | user | query | keyword | question | result_or_error | duration

    - 파일 없음 / 빈 파일: 예외 없이 빈 리스트 반환 (T-10)
    """
    path = Path(path)
    entries: list[GdiEntry] = []

    if not path.exists():
        logger.warning("gdi_query.log 파일 없음: %s", path)
        return entries

    try:
        with open(path, encoding='utf-8') as f:
            raw_lines = f.readlines()
    except OSError as e:
        logger.warning("gdi_query.log 읽기 실패: %s", e)
        return entries

    for lineno, line in enumerate(raw_lines, 1):
        line = line.strip()
        if not line:
            continue

        fields = line.split(' | ')
        n = len(fields)

        # 필드 수에 따라 분기
        if n == 7:
            ts_str, status, handler, user, query_f, result_or_error, duration_raw = fields
            keyword, question, cache = None, None, None
        elif n == 8:
            ts_str, status, handler, user, query_f, result_or_error, cache_field, duration_raw = fields
            keyword, question = None, None
            cache = cache_field.split('=', 1)[1] if '=' in cache_field else None
        elif n == 9:
            ts_str, status, handler, user, query_f, keyword, question, result_or_error, duration_raw = fields
            cache = None
        else:
            logger.warning("gdi_query.log 파싱 불가 (line %d, n=%d)", lineno, n)
            continue

        # query 접두사 제거
        query = query_f[6:] if query_f.startswith('query=') else query_f

        # result_or_error 접두사 제거 (MAJOR-2 반영) + escape 해제 (task-114 R-1 호환)
        result_or_error = result_or_error.replace('\\n', '\n')
        if result_or_error.startswith('result='):
            rval = result_or_error[7:]
        elif result_or_error.startswith('error='):
            rval = result_or_error[6:]
        else:
            rval = result_or_error

        # duration_ms 파싱 (MAJOR-2)
        duration_ms = _parse_duration_ms(duration_raw)

        # 타임스탬프 파싱
        try:
            timestamp = datetime.strptime(ts_str.strip(), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            logger.warning("타임스탬프 파싱 실패 (line %d): %r", lineno, ts_str)
            continue

        # 카테고리 결정
        if status == 'OK':
            category = 'OK'
        else:
            category = classify_gdi_error(rval, query)

        entries.append(GdiEntry(
            timestamp=timestamp,
            status=status,
            handler=handler,
            user=user,
            query=query,
            keyword=keyword,
            question=question,
            result_or_error=rval,
            cache=cache,
            duration_ms=duration_ms,
            category=category,
        ))

    return entries


def get_top_patterns(entries: list[MissEntry], n: int = 10) -> list[dict]:
    """page_name 완전일치 Counter 기준 상위 n개 반환 (MAJOR-8 반영).

    Returns:
        [{"page": "페이지명", "count": N}, ...]
    """
    counter = Counter(e.page_name for e in entries)
    return [{"page": page, "count": cnt} for page, cnt in counter.most_common(n)]


def generate_baseline_kpi(
    miss_entries: list[MissEntry],
    gdi_entries: list[GdiEntry],
) -> dict:
    """베이스라인 KPI 딕셔너리 생성 (step2_design.md v2 스펙 기준).

    구조:
      - generated_at: ISO8601
      - wiki: {total, cache_miss, all_miss, time_range_flagged,
               cache_miss_rate, all_miss_rate, top_miss_pages}
      - gdi: {total, ok, error, error_rate, by_category}
    """
    # Wiki KPI
    wiki_total = len(miss_entries)
    cache_miss_count = sum(1 for e in miss_entries if e.miss_type == 'CACHE_MISS')
    all_miss_count = sum(1 for e in miss_entries if e.miss_type == 'ALL_MISS')
    time_range_flagged = sum(1 for e in miss_entries if e.time_range_flag)
    cache_miss_rate = round(cache_miss_count / wiki_total, 3) if wiki_total else 0.0
    all_miss_rate = round(all_miss_count / wiki_total, 3) if wiki_total else 0.0
    top_miss_pages = get_top_patterns(miss_entries, n=10)

    # GDI KPI
    gdi_total = len(gdi_entries)
    gdi_ok = sum(1 for e in gdi_entries if e.status == 'OK')
    gdi_error = sum(1 for e in gdi_entries if e.status == 'ERROR')
    gdi_error_rate = round(gdi_error / gdi_total, 3) if gdi_total else 0.0

    error_categories = [
        'CONTENT_EMPTY', 'KEYWORD_MISS', 'FOLDER_MISS',
        'DATE_FORMAT', 'TYPO', 'SEARCH_MISS',
    ]
    by_category: dict[str, int] = {cat: 0 for cat in error_categories}
    for e in gdi_entries:
        if e.status == 'ERROR' and e.category in by_category:
            by_category[e.category] += 1

    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "wiki": {
            "total": wiki_total,
            "cache_miss": cache_miss_count,
            "all_miss": all_miss_count,
            "time_range_flagged": time_range_flagged,
            "cache_miss_rate": cache_miss_rate,
            "all_miss_rate": all_miss_rate,
            "top_miss_pages": top_miss_pages,
        },
        "gdi": {
            "total": gdi_total,
            "ok": gdi_ok,
            "error": gdi_error,
            "error_rate": gdi_error_rate,
            "by_category": by_category,
        },
    }


# CSV 인젝션 방어 (OWASP A03 — sec-code MAJOR-2)
_CSV_INJECTION_CHARS = ('=', '+', '-', '@', '\t', '\r')

def _sanitize_csv_field(value: object) -> object:
    """CSV 수식 인젝션 방어 — 선행 특수문자에 아포스트로피 접두사."""
    if isinstance(value, str) and value and value[0] in _CSV_INJECTION_CHARS:
        return "'" + value
    return value


# export_csv 허용 디렉토리 (Path Traversal 방어 — sec-code MAJOR-1)
_ALLOWED_EXPORT_DIRS = (
    Path(__file__).parent.resolve(),           # analytics/
    (Path(__file__).parent.parent / "logs").resolve(),  # logs/
)


def export_csv(entries: list[MissEntry] | list[GdiEntry], path: str | Path) -> None:
    """엔트리 리스트를 CSV로 저장.

    MissEntry / GdiEntry 모두 지원 (dataclass fields 기반).
    path는 허용 디렉토리(_ALLOWED_EXPORT_DIRS) 하위여야 함.
    """
    import dataclasses

    resolved = Path(path).resolve()
    if not any(str(resolved).startswith(str(d)) for d in _ALLOWED_EXPORT_DIRS):
        raise ValueError(f"export_csv: 허용되지 않은 출력 경로 — {resolved}")

    if not entries:
        logger.warning("export_csv: 엔트리가 비어있어 파일을 생성하지 않습니다.")
        return

    fieldnames = [f.name for f in dataclasses.fields(entries[0])]

    with open(resolved, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            row = dataclasses.asdict(entry)
            for k, v in row.items():
                if isinstance(v, datetime):
                    row[k] = v.isoformat()
            row = {k: _sanitize_csv_field(v) for k, v in row.items()}
            writer.writerow(row)

    logger.info("CSV 저장 완료: %s (%d rows)", resolved, len(entries))


def generate_daily_report(
    miss_entries: list[MissEntry],
    gdi_entries: list[GdiEntry],
    target_date: date | None = None,
) -> str:
    """지정 날짜의 실패 건수 요약 텍스트 반환.

    Args:
        miss_entries: 전체 MissEntry 리스트
        gdi_entries:  전체 GdiEntry 리스트
        target_date:  날짜 필터 (None이면 오늘)
    Returns:
        텍스트 리포트 문자열
    """
    if target_date is None:
        target_date = date.today()

    day_miss = [e for e in miss_entries if e.timestamp.date() == target_date]
    day_gdi = [e for e in gdi_entries if e.timestamp.date() == target_date]

    cache_miss = sum(1 for e in day_miss if e.miss_type == 'CACHE_MISS')
    all_miss = sum(1 for e in day_miss if e.miss_type == 'ALL_MISS')
    gdi_err = sum(1 for e in day_gdi if e.status == 'ERROR')
    time_range = sum(1 for e in day_miss if e.time_range_flag)

    lines = [
        f"[{target_date.isoformat()}] 일일 실패 리포트",
        f"Wiki: 총 {len(day_miss)}건 "
        f"(CACHE_MISS={cache_miss}, ALL_MISS={all_miss}, TIME_RANGE={time_range})",
        f"GDI: 총 {len(day_gdi)}건 (ERROR={gdi_err})",
    ]

    if day_miss:
        top3 = get_top_patterns(day_miss, n=3)
        lines.append("상위 실패 페이지: " + ", ".join(
            f"{d['page']}({d['count']})" for d in top3
        ))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 메인 블록 — T-1 ~ T-10 전수 검증 + baseline_kpi.json 저장
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s | %(name)s | %(message)s',
        stream=sys.stdout,
    )

    # 실제 로그 파일 파싱
    miss_entries = parse_answer_miss_log(ANSWER_MISS_LOG)
    gdi_entries = parse_gdi_query_log(GDI_QUERY_LOG)

    print("=" * 60)
    print("[ T-1 ] answer_miss.log 전수 파싱")
    t1_ok = len(miss_entries) == 174
    print(f"  len(miss_entries) = {len(miss_entries)}  →  {'PASS' if t1_ok else 'FAIL (기대: 174)'}")

    print()
    print("[ T-2 ] CACHE_MISS / ALL_MISS 분류")
    cache_miss_count = sum(1 for e in miss_entries if e.miss_type == 'CACHE_MISS')
    all_miss_count = sum(1 for e in miss_entries if e.miss_type == 'ALL_MISS')
    t2_ok = cache_miss_count == 124 and all_miss_count == 50
    print(f"  CACHE_MISS={cache_miss_count} (기대:124), ALL_MISS={all_miss_count} (기대:50)"
          f"  →  {'PASS' if t2_ok else 'FAIL'}")

    print()
    print("[ T-3 ] GDI ERROR 5건 파싱")
    gdi_error_entries = [e for e in gdi_entries if e.status == 'ERROR']
    gdi_error_count = len(gdi_error_entries)
    t3_ok = gdi_error_count == 5
    print(f"  ERROR 건수 = {gdi_error_count}  →  {'PASS' if t3_ok else 'FAIL (기대: 5)'}")
    for e in gdi_error_entries:
        print(f"    [{e.timestamp.date()}] handler={e.handler}, "
              f"query={e.query[:40]!r}, category={e.category}")

    print()
    print("[ T-4 ] Choaszero query → TYPO")
    choaszero_entries = [e for e in gdi_entries if 'Choaszero' in e.query]
    t4_ok = all(e.category == 'TYPO' for e in choaszero_entries if e.status == 'ERROR')
    typo_found = [e for e in choaszero_entries if e.status == 'ERROR']
    if typo_found:
        for e in typo_found:
            print(f"  query={e.query[:50]!r}, category={e.category}")
        print(f"  →  {'PASS' if t4_ok else 'FAIL (기대: TYPO)'}")
    else:
        print("  Choaszero ERROR 엔트리를 찾지 못했습니다.")
        t4_ok = False

    print()
    print("[ T-5 ] 2/25타겟 query → DATE_FORMAT")
    date_fmt_entries = [
        e for e in gdi_entries
        if e.status == 'ERROR' and re.search(r'\d+/\d+', e.query)
    ]
    t5_ok = all(e.category == 'DATE_FORMAT' for e in date_fmt_entries)
    if date_fmt_entries:
        for e in date_fmt_entries:
            print(f"  query={e.query[:60]!r}, category={e.category}")
        print(f"  →  {'PASS' if t5_ok else 'FAIL (기대: DATE_FORMAT)'}")
    else:
        print("  날짜 포맷 에러 엔트리를 찾지 못했습니다.")
        t5_ok = False

    print()
    print("[ T-6 ] TIME_RANGE 패턴 감지")
    time_range_entries = [e for e in miss_entries if e.time_range_flag]
    monthly_pattern = [e for e in time_range_entries if '월별' in e.question]
    weekly_둘째_pattern = [e for e in time_range_entries if '둘째' in e.question]
    t6_ok = len(time_range_entries) > 0 and len(monthly_pattern) > 0 and len(weekly_둘째_pattern) > 0
    print(f"  TIME_RANGE 플래그 건수: {len(time_range_entries)}")
    print(f"  '월별' 포함: {len(monthly_pattern)}건")
    print(f"  '둘째주/둘째 주' 포함: {len(weekly_둘째_pattern)}건")
    print(f"  →  {'PASS' if t6_ok else 'FAIL'}")

    print()
    print("[ T-7 ] TOP10 page_name 정렬 확인")
    top10 = get_top_patterns(miss_entries, n=10)
    print(f"  TOP10:")
    for i, item in enumerate(top10, 1):
        print(f"    {i:2d}. {item['page']!r}  ({item['count']}건)")
    t7_ok = len(top10) > 0 and top10[0]['count'] >= top10[-1]['count']
    print(f"  →  {'PASS (정렬 확인)' if t7_ok else 'FAIL'}")

    print()
    print("[ T-8 ] baseline_kpi.json 생성")
    kpi = generate_baseline_kpi(miss_entries, gdi_entries)
    kpi_path = Path(
        r"D:\Vibe Dev\AI Brain\_workspace\tasks\task-100\baseline_kpi.json"
    )
    kpi_path.parent.mkdir(parents=True, exist_ok=True)
    with open(kpi_path, 'w', encoding='utf-8') as f:
        json.dump(kpi, f, ensure_ascii=False, indent=2)
    # 재로드 검증
    with open(kpi_path, encoding='utf-8') as f:
        loaded = json.load(f)
    t8_ok = (
        kpi_path.exists()
        and 'generated_at' in loaded
        and 'wiki' in loaded
        and 'gdi' in loaded
    )
    print(f"  파일: {kpi_path}")
    print(f"  json.load 성공: {loaded.keys()}")
    print(f"  wiki.total={loaded['wiki']['total']}, gdi.error={loaded['gdi']['error']}")
    print(f"  →  {'PASS' if t8_ok else 'FAIL'}")

    print()
    print("[ T-9 ] 일일 리포트 날짜 필터 확인")
    report_date = date(2026, 3, 13)
    daily_report = generate_daily_report(miss_entries, gdi_entries, report_date)
    day_miss_count = sum(1 for e in miss_entries if e.timestamp.date() == report_date)
    t9_ok = str(report_date.isoformat()) in daily_report and day_miss_count > 0
    print(f"  날짜={report_date}, 해당일 miss={day_miss_count}건")
    print(f"  리포트:\n    " + daily_report.replace('\n', '\n    '))
    print(f"  →  {'PASS' if t9_ok else 'FAIL'}")

    print()
    print("[ T-10 ] 빈 파일 예외 없이 처리")
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.log', delete=False, encoding='utf-8'
    ) as tmp:
        tmp_path = tmp.name
    try:
        empty_miss = parse_answer_miss_log(tmp_path)
        empty_gdi = parse_gdi_query_log(tmp_path)
        t10_ok = empty_miss == [] and empty_gdi == []
    except Exception as exc:
        t10_ok = False
        print(f"  예외 발생: {exc}")
    finally:
        os.unlink(tmp_path)
    print(f"  빈 파일 → miss={empty_miss}, gdi={empty_gdi}")
    print(f"  →  {'PASS' if t10_ok else 'FAIL'}")

    # 최종 결과 요약
    results = {
        'T-1': t1_ok, 'T-2': t2_ok, 'T-3': t3_ok, 'T-4': t4_ok,
        'T-5': t5_ok, 'T-6': t6_ok, 'T-7': t7_ok, 'T-8': t8_ok,
        'T-9': t9_ok, 'T-10': t10_ok,
    }
    passed = sum(results.values())
    failed = [k for k, v in results.items() if not v]

    print()
    print("=" * 60)
    print(f"최종: {passed}/10 PASS")
    if failed:
        print(f"FAIL 항목: {failed}")
    else:
        print("전 항목 PASS")
    print("=" * 60)
