#!/usr/bin/env python3
"""
Google Play Store TOP 5 Game Ranking Crawler
Gemini API를 사용하여 매일 오전 9시(KST)에 랭킹 수집 후 Slack 알림
"""

import os
import json
import requests
from datetime import datetime
import pytz

# Gemini API 설정
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_API_URL = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={GEMINI_API_KEY}'

# Slack Webhook 설정
SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')

def get_game_rankings():
    """Gemini API를 통해 여러 국가의 Google Play Store TOP 5 게임 랭킹 수집"""

    prompt = """
Please provide the current TOP 5 games from Google Play Store for multiple regions in the following JSON format:

```json
{
  "ranking_date": "2024-01-20",
  "countries": [
    {
      "country": "South Korea",
      "flag": "🇰🇷",
      "games": [
        {
          "rank": 1,
          "title": "Game Name",
          "publisher": "Publisher Name"
        }
      ]
    }
  ]
}
```

Requirements:
- Include rankings for: South Korea, Japan, United States, Taiwan
- Provide TOP 5 games for each country
- Use local language for game titles (Korean for Korea, Japanese for Japan, etc.)
- Keep format simple: rank, title, publisher only
- Return only valid JSON without any markdown or extra text
"""

    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "topP": 0.8,
            "topK": 10
        }
    }

    try:
        response = requests.post(
            GEMINI_API_URL,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        response.raise_for_status()

        result = response.json()

        # Gemini 응답에서 텍스트 추출
        if 'candidates' in result and len(result['candidates']) > 0:
            text = result['candidates'][0]['content']['parts'][0]['text']

            # JSON 코드 블록 제거
            text = text.replace('```json', '').replace('```', '').strip()

            # JSON 파싱
            data = json.loads(text)
            return data
        else:
            raise Exception("No valid response from Gemini API")

    except requests.exceptions.RequestException as e:
        print(f"❌ Gemini API 요청 실패: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ JSON 파싱 실패: {e}")
        return None
    except Exception as e:
        print(f"❌ 예상치 못한 오류: {e}")
        return None


def send_slack_notification(ranking_data):
    """Slack으로 랭킹 정보 전송"""

    if not ranking_data or 'countries' not in ranking_data:
        send_error_notification("랭킹 데이터를 가져오지 못했습니다.")
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
                    "text": "⚠️ 게임 랭킹 크롤링 실패",
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
    print("🎮 Google Play Store TOP 5 게임 랭킹 크롤러 시작")
    print("=" * 60)

    # API 키 확인
    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY 환경변수가 설정되지 않았습니다.")
        send_error_notification("GEMINI_API_KEY가 설정되지 않음")
        return

    if not SLACK_WEBHOOK_URL:
        print("❌ SLACK_WEBHOOK_URL 환경변수가 설정되지 않았습니다.")
        return

    print("\n📡 Gemini API를 통해 랭킹 수집 중...")
    ranking_data = get_game_rankings()

    if ranking_data:
        countries = ranking_data.get('countries', [])
        total_games = sum(len(c.get('games', [])) for c in countries)
        print(f"\n✅ 랭킹 수집 완료: {len(countries)}개 국가, {total_games}개 게임")
        print("\n📤 Slack으로 알림 전송 중...")
        send_slack_notification(ranking_data)
    else:
        print("\n❌ 랭킹 수집 실패")
        send_error_notification("Gemini API 응답 오류")

    print("\n" + "=" * 60)
    print("✅ 작업 완료")
    print("=" * 60)


if __name__ == "__main__":
    main()
