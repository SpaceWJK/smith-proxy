#!/usr/bin/env python3
"""
Selenium 기반 Google Play Store 게임 랭킹 크롤러
"""

import os
import json
import time
from datetime import datetime, date
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def setup_driver():
    """Chrome WebDriver 설정"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')  # 브라우저 UI 없이 실행
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def crawl_play_store(country_code, language_code, country_name, flag):
    """
    특정 국가의 Google Play Store 게임 랭킹 크롤링

    Args:
        country_code: 국가 코드 (KR, JP, US, TW)
        language_code: 언어 코드 (ko, ja, en, zh-TW)
        country_name: 국가 이름 (표시용)
        flag: 국기 이모지

    Returns:
        dict: 게임 랭킹 데이터
    """
    driver = None

    try:
        print(f"\n🌍 {flag} {country_name} 크롤링 시작...")

        driver = setup_driver()

        # Google Play Store 무료 게임 TOP 차트
        url = f"https://play.google.com/store/apps/category/GAME/collection/topselling_free?hl={language_code}&gl={country_code}"
        print(f"📡 URL 접속: {url}")

        driver.get(url)

        # 페이지 로딩 대기 (JavaScript 렌더링)
        time.sleep(5)

        # 게임 카드 찾기 - Play Store의 구조에 따라 selector가 다를 수 있음
        # 여러 selector 시도
        games = []

        try:
            # 방법 1: a 태그 찾기
            game_cards = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/store/apps/details"]')
            print(f"✅ {len(game_cards)}개의 게임 카드 발견")

            for i, card in enumerate(game_cards[:5]):  # TOP 5만
                try:
                    # 게임 제목
                    title_elem = card.find_element(By.CSS_SELECTOR, 'span')
                    title = title_elem.text if title_elem else "Unknown"

                    # 퍼블리셔는 다른 방법으로 찾아야 함
                    # Play Store 구조상 정확한 퍼블리셔 추출이 어려울 수 있음
                    publisher = "Unknown"

                    if title and title != "Unknown":
                        games.append({
                            "rank": i + 1,
                            "title": title.strip(),
                            "publisher": publisher
                        })
                        print(f"  {i+1}. {title}")
                except Exception as e:
                    print(f"  ⚠️ 게임 {i+1} 파싱 실패: {e}")
                    continue

        except Exception as e:
            print(f"❌ 게임 카드 찾기 실패: {e}")

        # 최소 5개의 게임이 없으면 실패로 간주
        if len(games) < 5:
            print(f"⚠️ 충분한 게임 데이터를 가져오지 못함 ({len(games)}/5)")
            return None

        return {
            "country": country_name,
            "flag": flag,
            "games": games[:5]
        }

    except Exception as e:
        print(f"❌ {country_name} 크롤링 오류: {e}")
        import traceback
        traceback.print_exc()
        return None

    finally:
        if driver:
            driver.quit()

def get_game_rankings_selenium():
    """Selenium으로 여러 국가의 게임 랭킹 수집"""

    countries = [
        ("KR", "ko", "South Korea", "🇰🇷"),
        ("JP", "ja", "Japan", "🇯🇵"),
        ("US", "en", "United States", "🇺🇸"),
        ("TW", "zh-TW", "Taiwan", "🇹🇼"),
    ]

    ranking_data = {
        "ranking_date": str(date.today()),
        "countries": []
    }

    for country_code, language_code, country_name, flag in countries:
        country_data = crawl_play_store(country_code, language_code, country_name, flag)

        if country_data:
            ranking_data["countries"].append(country_data)
        else:
            print(f"⚠️ {country_name} 데이터 수집 실패")

        # 요청 간 대기 (너무 빠르게 요청하면 차단될 수 있음)
        time.sleep(3)

    return ranking_data if len(ranking_data["countries"]) > 0 else None

if __name__ == "__main__":
    print("=" * 60)
    print("🎮 Selenium 기반 게임 랭킹 크롤러 테스트")
    print("=" * 60)

    data = get_game_rankings_selenium()

    if data:
        print("\n✅ 크롤링 성공!")
        print("\n" + json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print("\n❌ 크롤링 실패")
