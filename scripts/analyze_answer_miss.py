"""
답변 실패(answer miss) 로그 분석 스크립트.

사용법:
  python scripts/analyze_answer_miss.py              # 전체 분석
  python scripts/analyze_answer_miss.py --days 7     # 최근 7일
  python scripts/analyze_answer_miss.py --csv        # CSV 내보내기

로그 위치: logs/answer_miss.log
로그 포맷: 2026-03-11 16:30:00 | MISS | user=... | page=... | question=... | stages=...
"""

import argparse
import csv
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
LOG_PATH = os.path.join(PROJECT_ROOT, "logs", "answer_miss.log")


def parse_log_line(line: str) -> dict | None:
    """answer_miss.log 한 줄을 파싱."""
    m = re.match(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| MISS \| "
        r"user=(.+?) \| page=(.+?) \(id=(.+?)\) \| "
        r"question=(.+?) \| stages=(.+)",
        line.strip(),
    )
    if not m:
        return None
    return {
        "timestamp": datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"),
        "user": m.group(2),
        "page_title": m.group(3),
        "page_id": m.group(4),
        "question": m.group(5),
        "stages": m.group(6),
    }


def load_entries(days: int = 0) -> list[dict]:
    """로그 파일에서 엔트리를 로드."""
    if not os.path.exists(LOG_PATH):
        print(f"로그 파일 없음: {LOG_PATH}")
        return []

    cutoff = datetime.now() - timedelta(days=days) if days > 0 else None
    entries = []
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            entry = parse_log_line(line)
            if entry is None:
                continue
            if cutoff and entry["timestamp"] < cutoff:
                continue
            entries.append(entry)
    return entries


def analyze(entries: list[dict]):
    """분석 결과 출력."""
    if not entries:
        print("분석할 데이터가 없습니다.")
        return

    print(f"\n{'='*60}")
    print(f"  답변 실패(Answer Miss) 분석 리포트")
    print(f"  기간: {entries[0]['timestamp']} ~ {entries[-1]['timestamp']}")
    print(f"  총 건수: {len(entries)}")
    print(f"{'='*60}\n")

    # 1. 페이지별 실패 빈도
    page_counter = Counter(e["page_title"] for e in entries)
    print("■ 페이지별 실패 빈도 (상위 10)")
    print("-" * 40)
    for title, cnt in page_counter.most_common(10):
        print(f"  {cnt:3d}건 | {title}")

    # 2. 사용자별 실패 빈도
    user_counter = Counter(e["user"] for e in entries)
    print(f"\n■ 사용자별 실패 빈도")
    print("-" * 40)
    for user, cnt in user_counter.most_common(10):
        print(f"  {cnt:3d}건 | {user}")

    # 3. 질문 키워드 빈도
    all_words = []
    for e in entries:
        words = re.findall(r"[가-힣]{2,}|[a-zA-Z]{3,}", e["question"])
        all_words.extend(w.lower() for w in words)
    # 불용어 제거
    stopwords = {"알려줘", "뭐야", "있어", "없어", "어떻게", "무엇",
                 "가르쳐", "해줘", "줘", "the", "and", "for"}
    word_counter = Counter(w for w in all_words if w not in stopwords)
    print(f"\n■ 질문 키워드 빈도 (상위 15)")
    print("-" * 40)
    for word, cnt in word_counter.most_common(15):
        print(f"  {cnt:3d}건 | {word}")

    # 4. 일별 추이
    daily = Counter(e["timestamp"].strftime("%Y-%m-%d") for e in entries)
    print(f"\n■ 일별 실패 건수")
    print("-" * 40)
    for day in sorted(daily.keys()):
        bar = "█" * daily[day]
        print(f"  {day} | {daily[day]:3d}건 {bar}")

    # 5. 개선 제안
    print(f"\n■ 개선 제안")
    print("-" * 40)
    for title, cnt in page_counter.most_common(5):
        if cnt >= 2:
            # 해당 페이지의 질문 패턴 수집
            qs = [e["question"] for e in entries if e["page_title"] == title]
            print(f"\n  [{title}] ({cnt}건 실패)")
            for q in qs[:3]:
                print(f"    - {q}")
            if cnt > 3:
                print(f"    ... 외 {cnt-3}건")
            print(f"  → 하위 페이지 구조 점검 또는 keyword_rules 추가 권장")


def export_csv(entries: list[dict], output_path: str = ""):
    """CSV 내보내기."""
    if not output_path:
        output_path = os.path.join(PROJECT_ROOT, "logs", "answer_miss_report.csv")
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "timestamp", "user", "page_title", "page_id", "question", "stages"
        ])
        writer.writeheader()
        for e in entries:
            row = dict(e)
            row["timestamp"] = row["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
            writer.writerow(row)
    print(f"CSV 내보내기 완료: {output_path} ({len(entries)}건)")


def main():
    parser = argparse.ArgumentParser(description="답변 실패 로그 분석")
    parser.add_argument("--days", type=int, default=0,
                        help="최근 N일만 분석 (0=전체)")
    parser.add_argument("--csv", action="store_true",
                        help="CSV 파일로 내보내기")
    args = parser.parse_args()

    entries = load_entries(days=args.days)
    if args.csv:
        export_csv(entries)
    else:
        analyze(entries)


if __name__ == "__main__":
    main()
