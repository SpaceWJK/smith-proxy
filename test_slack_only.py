#!/usr/bin/env python3
"""
Slack 알림만 테스트 - 샘플 게임 랭킹 데이터 사용
"""

import os
import requests
from datetime import datetime
import pytz
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()

SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')

def send_test_notification():
    """샘플 데이터로 Slack 알림 테스트"""

    # KST 시간
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.now(kst)
    date_str = now.strftime('%Y-%m-%d')

    # 샘플 게임 랭킹 데이터
    sample_data = {
        "ranking_date": date_str,
        "countries": [
            {
                "country": "South Korea",
                "flag": "🇰🇷",
                "games": [
                    {"rank": 1, "title": "리니지M", "publisher": "NCSOFT"},
                    {"rank": 2, "title": "메이플스토리", "publisher": "넥슨"},
                    {"rank": 3, "title": "원신", "publisher": "호요버스"},
                    {"rank": 4, "title": "배틀그라운드 모바일", "publisher": "KRAFTON"},
                    {"rank": 5, "title": "로스트아크", "publisher": "Smilegate RPG"}
                ]
            },
            {
                "country": "Japan",
                "flag": "🇯🇵",
                "games": [
                    {"rank": 1, "title": "Fate/Grand Order", "publisher": "Aniplex"},
                    {"rank": 2, "title": "Monster Strike", "publisher": "MIXI"},
                    {"rank": 3, "title": "Puzzle & Dragons", "publisher": "GungHo"},
                    {"rank": 4, "title": "Dragon Quest Walk", "publisher": "Square Enix"},
                    {"rank": 5, "title": "Uma Musume Pretty Derby", "publisher": "Cygames"}
                ]
            },
            {
                "country": "United States",
                "flag": "🇺🇸",
                "games": [
                    {"rank": 1, "title": "MONOPOLY GO!", "publisher": "Scopely"},
                    {"rank": 2, "title": "Royal Match", "publisher": "Dream Games"},
                    {"rank": 3, "title": "Candy Crush Saga", "publisher": "King"},
                    {"rank": 4, "title": "Coin Master", "publisher": "Moon Active"},
                    {"rank": 5, "title": "Roblox", "publisher": "Roblox Corporation"}
                ]
            },
            {
                "country": "Taiwan",
                "flag": "🇹🇼",
                "games": [
                    {"rank": 1, "title": "Lineage M", "publisher": "NCSOFT"},
                    {"rank": 2, "title": "Lineage W", "publisher": "NCSOFT"},
                    {"rank": 3, "title": "Ragnarok X: Next Generation", "publisher": "Gravity"},
                    {"rank": 4, "title": "Garena 傳說對決", "publisher": "Garena"},
                    {"rank": 5, "title": "Fate/Grand Order", "publisher": "Aniplex"}
                ]
            }
        ]
    }

    # 메시지 텍스트 구성
    message_lines = [f"*Game Rankings(Android) • {date_str}* [TEST]\n"]

    # 각 국가별 랭킹 추가
    for country_data in sample_data.get('countries', []):
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

    print("=" * 60)
    print("🧪 Slack 알림 테스트 (샘플 데이터)")
    print("=" * 60)

    if not SLACK_WEBHOOK_URL:
        print("❌ SLACK_WEBHOOK_URL이 설정되지 않았습니다.")
        print("\n.env 파일에 다음을 추가하세요:")
        print("SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...")
        return False

    print(f"\n📤 Slack Webhook URL: {SLACK_WEBHOOK_URL[:50]}...")
    print("\n📱 전송할 메시지:")
    print("-" * 60)
    print(full_message[:500])
    print("-" * 60)

    try:
        print("\n📡 Slack으로 전송 중...")
        response = requests.post(
            SLACK_WEBHOOK_URL,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )

        print(f"📊 HTTP Status: {response.status_code}")
        print(f"📋 응답: {response.text}")

        if response.status_code == 200:
            print("\n✅ Slack 알림 전송 성공!")
            print("💬 #sgpqa_epiczero 채널을 확인하세요!")
            return True
        else:
            print(f"\n❌ Slack 전송 실패: {response.status_code}")
            return False

    except requests.exceptions.RequestException as e:
        print(f"\n❌ Slack 알림 전송 실패: {e}")
        return False

if __name__ == "__main__":
    success = send_test_notification()

    print("\n" + "=" * 60)
    if success:
        print("✅ 테스트 완료 - Slack 알림이 정상 작동합니다!")
    else:
        print("❌ 테스트 실패 - Slack 설정을 확인하세요.")
    print("=" * 60)
