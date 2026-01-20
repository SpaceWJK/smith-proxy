#!/usr/bin/env python3
"""
Chrome 브라우저를 제어해서 Gemini 웹에서 게임 랭킹 리서치
Claude Code가 로컬에서 실행
"""

import os
import json
import time
from datetime import date
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def setup_chrome_for_claude():
    """
    Claude Code가 사용하는 Chrome 연결
    사용자의 Chrome 브라우저를 원격 디버깅 모드로 연결
    """
    chrome_options = Options()

    # Claude Code는 이미 실행 중인 Chrome에 연결
    # Remote debugging port: 보통 9222
    chrome_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

    try:
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        print(f"❌ Chrome 연결 실패: {e}")
        print("\n💡 Chrome을 원격 디버깅 모드로 실행해주세요:")
        print("   Mac/Linux: google-chrome --remote-debugging-port=9222")
        print("   Windows: chrome.exe --remote-debugging-port=9222")
        return None

def research_game_rankings(driver):
    """
    Gemini 웹에서 게임 랭킹 리서치
    """

    print("=" * 60)
    print("🔍 Gemini 웹에서 게임 랭킹 리서치 시작")
    print("=" * 60)

    try:
        # Google AI Studio 접속
        gemini_url = "https://aistudio.google.com/app/prompts/new_chat"
        print(f"\n📡 Gemini 접속: {gemini_url}")
        driver.get(gemini_url)

        # 페이지 로딩 대기
        time.sleep(5)

        # 프롬프트 작성
        prompt = """Please provide the current TOP 5 games from Google Play Store for multiple regions in JSON format:

Requirements:
- Include rankings for: South Korea, Japan, United States, Taiwan
- Provide TOP 5 games for each country
- Format: rank, title, publisher only

Game Title Language Rules:
- South Korea: Use Korean title if officially released in Korea, otherwise English
- Japan: Use Japanese title
- United States: Use English title
- Taiwan: Use Traditional Chinese or English

Return ONLY valid JSON in this exact format:
```json
{
  "ranking_date": "2026-01-20",
  "countries": [
    {
      "country": "South Korea",
      "flag": "🇰🇷",
      "games": [
        {"rank": 1, "title": "게임명", "publisher": "퍼블리셔"}
      ]
    }
  ]
}
```"""

        print("\n📝 프롬프트 입력 대기 중...")
        print("💡 수동으로 Gemini에 다음 질문을 입력해주세요:\n")
        print(prompt)
        print("\n" + "=" * 60)

        # 사용자가 수동으로 입력하고 응답을 받을 때까지 대기
        input("\n✅ Gemini로부터 응답을 받으셨나요? 엔터를 눌러주세요...")

        print("\n📋 응답을 복사해서 붙여넣어주세요 (JSON 전체):")
        print("입력 후 빈 줄을 입력하면 종료됩니다.\n")

        lines = []
        while True:
            line = input()
            if line.strip() == "":
                break
            lines.append(line)

        response_text = "\n".join(lines)

        # JSON 파싱
        # ```json ... ``` 제거
        response_text = response_text.replace('```json', '').replace('```', '').strip()

        try:
            data = json.loads(response_text)
            data["ranking_date"] = str(date.today())

            print("\n✅ JSON 파싱 성공!")
            print(json.dumps(data, indent=2, ensure_ascii=False))

            return data

        except json.JSONDecodeError as e:
            print(f"\n❌ JSON 파싱 실패: {e}")
            print(f"받은 텍스트:\n{response_text[:500]}")
            return None

    except Exception as e:
        print(f"\n❌ 리서치 오류: {e}")
        import traceback
        traceback.print_exc()
        return None

def save_rankings(data):
    """rankings.json 파일로 저장"""

    output_file = "/home/user/smith-proxy/data/rankings.json"

    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"\n✅ 저장 완료: {output_file}")
        return True

    except Exception as e:
        print(f"\n❌ 저장 실패: {e}")
        return False

def main():
    print("=" * 60)
    print("🎮 게임 랭킹 리서치 (Chrome 브라우저 제어)")
    print("=" * 60)

    # Chrome 연결
    driver = setup_chrome_for_claude()

    if not driver:
        print("\n대체 방법: 수동으로 JSON 입력")
        print("Gemini에서 직접 질문하고 결과를 복사해주세요.\n")

        print("📋 JSON 데이터를 붙여넣어주세요:")
        print("입력 후 빈 줄을 입력하면 종료됩니다.\n")

        lines = []
        while True:
            line = input()
            if line.strip() == "":
                break
            lines.append(line)

        response_text = "\n".join(lines)
        response_text = response_text.replace('```json', '').replace('```', '').strip()

        try:
            data = json.loads(response_text)
            data["ranking_date"] = str(date.today())
        except json.JSONDecodeError as e:
            print(f"❌ JSON 파싱 실패: {e}")
            return
    else:
        # 리서치 수행
        data = research_game_rankings(driver)

        if not data:
            print("\n❌ 리서치 실패")
            driver.quit()
            return

        driver.quit()

    # 저장
    if save_rankings(data):
        print("\n🎉 완료! 이제 GitHub에 커밋하세요:")
        print("  git add data/rankings.json")
        print("  git commit -m 'Update game rankings'")
        print("  git push")

if __name__ == "__main__":
    main()
