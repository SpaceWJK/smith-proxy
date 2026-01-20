#!/usr/bin/env python3
"""
Gemini API 테스트 스크립트 - 게임 랭킹만 수집하여 출력
"""

import os
import json
import requests
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()

# Gemini API 설정
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_API_URL = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={GEMINI_API_KEY}'

def test_gemini_api():
    """Gemini API 테스트"""

    print("=" * 60)
    print("🧪 Gemini API 테스트 시작")
    print("=" * 60)

    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY가 설정되지 않았습니다.")
        return None

    print(f"\n🔑 API Key: {GEMINI_API_KEY[:20]}...")

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

    try:
        print("\n📡 Gemini API 요청 중...")
        response = requests.post(
            GEMINI_API_URL,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )

        print(f"📊 HTTP Status: {response.status_code}")

        if response.status_code != 200:
            print(f"❌ API 요청 실패: {response.status_code}")
            print(f"응답: {response.text[:500]}")
            return None

        response.raise_for_status()
        result = response.json()

        # Gemini 응답 출력
        print("\n✅ API 응답 성공!")
        print("\n📋 원본 응답:")
        print(json.dumps(result, indent=2, ensure_ascii=False)[:1000])

        # 텍스트 추출
        if 'candidates' in result and len(result['candidates']) > 0:
            text = result['candidates'][0]['content']['parts'][0]['text']

            print("\n📝 추출된 텍스트:")
            print(text[:500])

            # JSON 코드 블록 제거
            text = text.replace('```json', '').replace('```', '').strip()

            # JSON 파싱
            data = json.loads(text)

            print("\n✅ JSON 파싱 성공!")
            print("\n🎮 게임 랭킹 데이터:")
            print("=" * 60)

            # 결과 출력
            for country_data in data.get('countries', []):
                country = country_data.get('country', 'Unknown')
                flag = country_data.get('flag', '🌍')
                games = country_data.get('games', [])

                print(f"\n{flag} {country}")
                for game in games[:5]:
                    rank = game.get('rank', '?')
                    title = game.get('title', 'Unknown')
                    publisher = game.get('publisher', 'Unknown')
                    print(f"{rank}. {title} • {publisher}")

            print("\n" + "=" * 60)
            return data
        else:
            print("❌ API 응답에 유효한 데이터가 없습니다.")
            return None

    except requests.exceptions.Timeout:
        print("❌ API 요청 타임아웃 (30초 초과)")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ API 요청 오류: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ JSON 파싱 오류: {e}")
        print(f"받은 텍스트: {text[:500]}")
        return None
    except Exception as e:
        print(f"❌ 예상치 못한 오류: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    result = test_gemini_api()

    if result:
        print("\n🎉 Gemini API 테스트 성공!")
        print("✅ 게임 랭킹 데이터를 정상적으로 가져왔습니다.")
    else:
        print("\n❌ Gemini API 테스트 실패")
