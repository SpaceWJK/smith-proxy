#!/usr/bin/env python3
"""
rankings.json 파일을 읽어서 Slack 알림 전송
GitHub Actions에서 매일 오전 9시(KST) 실행
"""

import os
import json
import requests
from datetime import datetime
import pytz

# Slack Webhook 설정
SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')

def load_rankings():
    """data/rankings.json 파일 읽기"""

    rankings_file = "data/rankings.json"

    try:
        with open(rankings_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        print(f"✅ 랭킹 파일 로드 성공: {rankings_file}")
        return data

    except FileNotFoundError:
        print(f"❌ 랭킹 파일을 찾을 수 없습니다: {rankings_file}")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ JSON 파싱 오류: {e}")
        return None
    except Exception as e:
        print(f"❌ 파일 읽기 오류: {e}")
        return None

def send_slack_notification(ranking_data):
    """Slack으로 랭킹 정보 전송"""

    if not ranking_data or 'countries' not in ranking_data:
        print("❌ 유효하지 않은 랭킹 데이터")
        return False

    # KST 시간
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.now(kst)
    date_str = now.strftime('%Y-%m-%d')

    # 메시지 텍스트 구성
    message_lines = [f"*Game Rankings(Android) • {date_str}*\n"]

    # 각 국가별 랭킹 추가
    for country_data in ranking_data.get('countries', []):
        country_name = country_data.get('country', 'Unknown')
        flag = country_data.get('flag', '🌍')
        games = country_data.get('games', [])

        message_lines.append(f"\n{flag} *{country_name}*")

        for game in games[:5]:
            rank = game.get('rank', '?')
            title = game.get('title', 'Unknown')
            publisher = game.get('publisher', 'Unknown')
            message_lines.append(f"{rank} {title} • {publisher}")

    # 전체 메시지 조합
    full_message = "\n".join(message_lines)

    payload = {
        "text": full_message,
        "mrkdwn": True
    }

    try:
        response = requests.post(
            SLACK_WEBHOOK_URL,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        response.raise_for_status()
        print("✅ Slack 알림 전송 성공!")
        return True
    except requests.exceptions.RequestException as e:
        print(f"❌ Slack 알림 전송 실패: {e}")
        return False

def send_error_notification(error_message):
    """에러 발생 시 Slack 알림"""

    kst = pytz.timezone('Asia/Seoul')
    now = datetime.now(kst)

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "⚠️ 게임 랭킹 알림 실패",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*에러 메시지:*\n```{error_message}```"
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"📅 {now.strftime('%Y-%m-%d %H:%M:%S')} (KST)"
                    }
                ]
            }
        ]
    }

    try:
        requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e:
        print(f"❌ 에러 알림 전송 실패: {e}")

def main():
    """메인 실행 함수"""

    print("=" * 60)
    print("📤 게임 랭킹 Slack 알림 전송")
    print("=" * 60)

    # Slack Webhook URL 확인
    if not SLACK_WEBHOOK_URL:
        print("❌ SLACK_WEBHOOK_URL 환경변수가 설정되지 않았습니다.")
        return

    # 랭킹 데이터 로드
    print("\n📂 랭킹 데이터 로드 중...")
    ranking_data = load_rankings()

    if ranking_data:
        countries = ranking_data.get('countries', [])
        total_games = sum(len(c.get('games', [])) for c in countries)
        print(f"✅ {len(countries)}개 국가, {total_games}개 게임")

        print("\n📤 Slack으로 알림 전송 중...")
        send_slack_notification(ranking_data)
    else:
        print("\n❌ 랭킹 데이터 로드 실패")
        send_error_notification("rankings.json 파일을 읽을 수 없습니다.")

    print("\n" + "=" * 60)
    print("✅ 작업 완료")
    print("=" * 60)

if __name__ == "__main__":
    main()
