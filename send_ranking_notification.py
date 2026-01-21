#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Slack 알림 전송 스크립트
rankings.json 파일을 읽어서 포맷된 메시지를 Slack으로 전송
"""

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# Windows 콘솔 인코딩 설정
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# .env 파일 로드 (로컬 실행 시)
load_dotenv()


def load_rankings():
    """rankings.json 파일 읽기"""
    json_path = Path(__file__).parent / "data" / "rankings.json"

    if not json_path.exists():
        print(f"❌ 파일을 찾을 수 없습니다: {json_path}")
        sys.exit(1)

    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def format_slack_message(data):
    """Slack 메시지 포맷팅"""
    ranking_date = data.get("ranking_date", "Unknown Date")

    # 헤더
    message = f"*Game Rankings(Android)* • {ranking_date}\n\n"

    # 각 국가별 랭킹
    for country_data in data["countries"]:
        country = country_data["country"]
        flag = country_data["flag"]
        games = country_data["games"]

        message += f"{flag} *{country}*\n"

        for game in games:
            rank = game["rank"]
            title = game["title"]
            publisher = game["publisher"]
            message += f"{rank} {title} • {publisher}\n"

        message += "\n"

    return message.strip()


def send_slack_notification(message):
    """Slack Webhook으로 메시지 전송"""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")

    if not webhook_url:
        print("❌ SLACK_WEBHOOK_URL 환경변수가 설정되지 않았습니다")
        sys.exit(1)

    payload = {
        "text": message,
        "mrkdwn": True
    }

    try:
        response = requests.post(webhook_url, json=payload)
        response.raise_for_status()
        print("✅ Slack 알림 전송 완료")
        return True

    except requests.exceptions.RequestException as e:
        print(f"❌ Slack 알림 전송 실패: {e}")
        return False


def main():
    """메인 함수"""
    print("=" * 60)
    print("📨 Slack 알림 전송 시작")
    print("=" * 60)

    try:
        # 1. 랭킹 데이터 로드
        print("📖 rankings.json 읽는 중...")
        data = load_rankings()
        print(f"✅ 데이터 로드 완료: {len(data['countries'])}개 국가")

        # 2. 메시지 포맷팅
        print("📝 메시지 포맷팅 중...")
        message = format_slack_message(data)
        print("✅ 메시지 포맷팅 완료")
        print("\n--- 전송할 메시지 ---")
        print(message)
        print("--- 메시지 끝 ---\n")

        # 3. Slack 전송
        print("📤 Slack으로 전송 중...")
        success = send_slack_notification(message)

        if success:
            print("=" * 60)
            print("✅ 모든 작업 완료!")
            print("=" * 60)
        else:
            sys.exit(1)

    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
