#!/usr/bin/env python3
"""
Google Play Store TOP 5 Game Ranking Crawler
Gemini API를 사용하여 매일 오전 9시(KST)에 랭킹 수집 후 Slack 알림
"""

import os
import json
import requests
import time
from datetime import datetime
import pytz

# Gemini API 설정
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
# 안정적인 gemini-pro 모델 사용
GEMINI_API_URL = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}'

# Slack Webhook 설정
SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')

def get_game_rankings(max_retries=3, retry_delay=5):
    """Gemini API를 통해 여러 국가의 Google Play Store TOP 5 게임 랭킹 수집

    Args:
        max_retries: 최대 재시도 횟수 (429 에러 시)
        retry_delay: 재시도 대기 시간 (초)
    """

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
- Keep format simple: rank, title, publisher only

**Game Title Language Rules:**
- South Korea: Use Korean title if the game is officially released in Korea. If not available in Korea, use English or original language title.
- Japan: Use Japanese title (original)
- United States: Use English title (original)
- Taiwan: Use Traditional Chinese or English title (original)

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

    # Retry 로직 구현
    for attempt in range(max_retries):
        try:
            response = requests.post(
                GEMINI_API_URL,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )

            # 상태 코드와 응답 로깅
            print(f"📊 API Response Status: {response.status_code}")

            # 429 에러 (Rate Limit) 처리
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (attempt + 1)
                    print(f"⏳ Rate limit 초과. {wait_time}초 후 재시도... ({attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"❌ Rate limit 초과. 최대 재시도 횟수 도달.")
                    print(f"💡 해결 방법: 몇 분 후 다시 시도하거나 Google AI Studio에서 quota를 확인하세요.")
                    return None

            if response.status_code != 200:
                print(f"❌ API 오류 응답: {response.text[:500]}")
                response.raise_for_status()

            result = response.json()
            break  # 성공하면 루프 종료

        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                print(f"⏳ 요청 실패. {retry_delay}초 후 재시도... ({attempt + 1}/{max_retries})")
                time.sleep(retry_delay)
                continue
            else:
                print(f"❌ Gemini API 요청 실패: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    print(f"상세 오류: {e.response.text[:500]}")
                return None

    try:

        # Gemini 응답에서 텍스트 추출
        if 'candidates' in result and len(result['candidates']) > 0:
            text = result['candidates'][0]['content']['parts'][0]['text']

            print(f"✅ API 응답 텍스트 길이: {len(text)} 문자")

            # JSON 코드 블록 제거
            text = text.replace('```json', '').replace('```', '').strip()

            # JSON 파싱
            data = json.loads(text)
            return data
        else:
            error_msg = f"No valid response from Gemini API. Response: {str(result)[:200]}"
            print(f"❌ {error_msg}")
            raise Exception(error_msg)

    except json.JSONDecodeError as e:
        print(f"❌ JSON 파싱 실패: {e}")
        print(f"받은 텍스트 일부: {text[:300] if 'text' in locals() else 'N/A'}")
        return None
    except Exception as e:
        print(f"❌ 예상치 못한 오류: {e}")
        import traceback
        traceback.print_exc()
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
