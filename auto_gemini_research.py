#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
게임 랭킹 자동 리서치 시스템
Selenium을 사용하여 Gemini 웹에서 게임 랭킹을 수집하고 GitHub에 자동 커밋
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# Windows 콘솔 인코딩 설정
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


class GeminiRankingCollector:
    """Gemini 웹을 통해 게임 랭킹을 수집하는 클래스"""

    def __init__(self, headless=True):
        """
        초기화

        Args:
            headless (bool): Headless 모드 활성화 여부
        """
        self.headless = headless
        self.driver = None
        self.project_root = Path(__file__).parent
        self.data_dir = self.project_root / "data"
        self.logs_dir = self.project_root / "logs" / "screenshots"

        # 디렉토리 생성
        self.data_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def setup_driver(self):
        """Chrome WebDriver 설정"""
        print("🚀 Chrome WebDriver 초기화 중...")

        chrome_options = Options()

        # 사용자 프로필 사용 (로그인 세션 유지)
        user_data_dir = self.project_root / "chrome_profile"
        user_data_dir.mkdir(exist_ok=True)
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")

        print(f"📁 Chrome 프로필 디렉토리: {user_data_dir}")
        print("💡 첫 실행 시 Gemini에 로그인해주세요. 다음부터는 자동으로 로그인됩니다.")

        if self.headless:
            chrome_options.add_argument("--headless=new")

        # 기본 옵션
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")

        # User-Agent 설정 (Bot 감지 회피)
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

        # 자동화 감지 비활성화
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        try:
            # Chrome 바로 실행 (ChromeDriver 자동 관리)
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.implicitly_wait(10)
            print("✅ WebDriver 초기화 완료")
        except Exception as e:
            print(f"❌ WebDriver 초기화 실패: {e}")
            print("💡 Chrome 브라우저와 ChromeDriver가 설치되어 있는지 확인하세요")
            print("💡 또는 PATH 환경변수에 ChromeDriver가 등록되어 있는지 확인하세요")
            raise

    def save_screenshot(self, filename):
        """스크린샷 저장"""
        if self.driver:
            filepath = self.logs_dir / f"{filename}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            self.driver.save_screenshot(str(filepath))
            print(f"📸 스크린샷 저장: {filepath}")

    def navigate_to_gemini(self):
        """Gemini 웹사이트로 이동"""
        print("🌐 Gemini 웹사이트 접속 중...")

        try:
            self.driver.get("https://gemini.google.com")
            time.sleep(5)  # 페이지 로딩 대기

            print(f"✅ 현재 URL: {self.driver.current_url}")
            self.save_screenshot("01_gemini_loaded")

        except Exception as e:
            print(f"❌ Gemini 접속 실패: {e}")
            self.save_screenshot("error_navigation")
            raise

    def find_input_element(self):
        """입력창 찾기 (다중 selector fallback)"""
        print("🔍 입력창 찾는 중...")

        # 시도할 selector 목록
        selectors = [
            (By.CSS_SELECTOR, "textarea[placeholder*='Ask']"),
            (By.CSS_SELECTOR, "textarea[aria-label*='prompt']"),
            (By.CSS_SELECTOR, "div[contenteditable='true']"),
            (By.CSS_SELECTOR, "textarea"),
            (By.XPATH, "//textarea"),
            (By.XPATH, "//div[@contenteditable='true']"),
        ]

        for by, selector in selectors:
            try:
                element = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((by, selector))
                )
                print(f"✅ 입력창 발견: {selector}")
                return element
            except:
                continue

        # 모든 시도 실패
        self.save_screenshot("error_no_input")
        raise Exception("입력창을 찾을 수 없습니다")

    def send_prompt(self, input_element):
        """프롬프트 전송"""
        print("📝 프롬프트 입력 중...")

        prompt = """I need you to search the web RIGHT NOW for the latest Google Play Store top-grossing game rankings.

Please visit AppBrain, Sensor Tower, or similar mobile market analytics websites and find the TOP 20 highest revenue games for ALL 4 countries below.

Countries (MUST include ALL 4):
1. South Korea (use Korean game titles)
2. Japan (use Japanese game titles)
3. United States (use English game titles)
4. Taiwan (use Traditional Chinese game titles)

Each country MUST have exactly 20 games with rank 1-20, game title in local language, and publisher name.

Return as JSON with this EXACT structure:
{
  "ranking_date": "2026-01-21",
  "countries": [
    {
      "country": "South Korea",
      "flag": "KR",
      "games": [
        {"rank": 1, "title": "game in Korean", "publisher": "publisher name"},
        {"rank": 2, "title": "game in Korean", "publisher": "publisher name"},
        ... (continue to rank 20)
      ]
    },
    {
      "country": "Japan",
      "flag": "JP",
      "games": [
        {"rank": 1, "title": "game in Japanese", "publisher": "publisher name"},
        ... (continue to rank 20)
      ]
    },
    {
      "country": "United States",
      "flag": "US",
      "games": [
        {"rank": 1, "title": "game in English", "publisher": "publisher name"},
        ... (continue to rank 20)
      ]
    },
    {
      "country": "Taiwan",
      "flag": "TW",
      "games": [
        {"rank": 1, "title": "game in Chinese", "publisher": "publisher name"},
        ... (continue to rank 20)
      ]
    }
  ]
}

DO NOT give me an example. Search the web and provide REAL current data. Each country needs 20 games.
"""

        try:
            # 입력창 클릭 및 포커스
            input_element.click()
            time.sleep(1)

            # 텍스트 입력
            input_element.send_keys(prompt)
            time.sleep(2)

            self.save_screenshot("02_prompt_entered")

            # Enter 키로 전송
            input_element.send_keys(Keys.RETURN)
            print("✅ 프롬프트 전송 완료")

        except Exception as e:
            print(f"❌ 프롬프트 전송 실패: {e}")
            self.save_screenshot("error_send_prompt")
            raise

    def wait_for_response(self):
        """Gemini 응답 대기"""
        print("⏳ Gemini 응답 대기 중 (충분한 시간 제공)...")

        try:
            # 초기 응답 시작 대기
            print("⏳ 1단계: 응답 시작 대기 (20초)...")
            time.sleep(20)

            # 웹 검색 시간 대기
            print("⏳ 2단계: 웹 검색 수행 대기 (60초)...")
            time.sleep(60)

            # 응답 생성 완료 대기
            print("⏳ 3단계: 4개 국가 x 20개 게임 응답 생성 대기 (60초)...")
            time.sleep(60)

            # 추가 안전 마진
            print("⏳ 4단계: 응답 완료 확인 (30초)...")
            time.sleep(30)

            self.save_screenshot("03_response_received")
            print("✅ 응답 수신 완료 (총 대기: 170초)")

        except Exception as e:
            print(f"❌ 응답 대기 실패: {e}")
            self.save_screenshot("error_wait_response")
            raise

    def parse_table_to_json(self, page_text):
        """테이블 형식의 데이터를 JSON으로 변환"""
        print("📊 테이블 데이터 파싱 중...")

        # 한국 데이터 추출
        # 형식: "1 메이플 키우기 (MapleStory : Idle RPG) NEXON Company"
        games = []
        lines = page_text.split('\n')

        for line in lines:
            line = line.strip()
            if not line or not line[0].isdigit():
                continue

            # 패턴: [Rank] [Local Title] ([English Title]) [Publisher]
            pattern = r'^(\d+)\s+(.+?)\s+\(([^)]+)\)\s+(.+)$'
            match = re.match(pattern, line)

            if match:
                rank = int(match.group(1))
                title = match.group(2).strip()  # 한글 제목
                # english_title = match.group(3).strip()  # 영문 제목 (사용 안 함)
                publisher = match.group(4).strip()

                if 1 <= rank <= 20:
                    games.append({
                        "rank": rank,
                        "title": title,
                        "publisher": publisher
                    })
                    print(f"  {rank}. {title} - {publisher}")

        if len(games) >= 10:  # 최소 10개는 있어야 유효한 데이터
            print(f"✅ 테이블에서 {len(games)}개 게임 파싱 성공")
            return {
                "ranking_date": datetime.now().strftime("%Y-%m-%d"),
                "countries": [{
                    "country": "South Korea",
                    "flag": "KR",
                    "games": sorted(games, key=lambda x: x['rank'])[:20]
                }]
            }

        print(f"⚠️ 파싱된 게임이 {len(games)}개로 부족합니다")
        return None

    def extract_json_from_page(self):
        """페이지에서 JSON 추출"""
        print("🔍 JSON 데이터 추출 중...")

        try:
            # 페이지 전체 텍스트 가져오기
            page_text = self.driver.find_element(By.TAG_NAME, "body").text

            # 디버깅: 받은 텍스트의 일부 출력
            print(f"📄 페이지 텍스트 길이: {len(page_text)} 문자")
            print(f"📄 페이지 텍스트 미리보기 (처음 500자):\n{page_text[:500]}\n")

            # JSON 찾기 - 중괄호 밸런싱 방식
            json_text = None

            # 첫 번째 '{' 찾기
            start = page_text.find('{')
            if start != -1:
                # 중괄호 밸런싱으로 끝 찾기
                brace_count = 0
                for i in range(start, len(page_text)):
                    if page_text[i] == '{':
                        brace_count += 1
                    elif page_text[i] == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            json_text = page_text[start:i+1]
                            print("✅ JSON 블록 발견 (중괄호 밸런싱)")
                            break

            # JSON이 없으면 테이블 파싱 시도
            if not json_text:
                print("⚠️ JSON을 찾을 수 없음. 테이블 파싱 시도...")
                data = self.parse_table_to_json(page_text)
                if data:
                    return data

                # 테이블 파싱도 실패하면 저장
                debug_file = self.logs_dir / f"page_text_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(page_text)
                print(f"📝 전체 페이지 텍스트 저장: {debug_file}")
                raise Exception("JSON 데이터를 찾을 수 없습니다")

            print(f"📄 추출된 JSON 길이: {len(json_text)} 문자")

            # JSON 파싱
            data = json.loads(json_text)

            # 유효성 검증
            if "countries" not in data:
                raise ValueError("countries 키가 없습니다")

            if len(data["countries"]) < 1:
                raise ValueError("최소 1개 국가 데이터가 필요합니다")

            # 날짜 업데이트
            data["ranking_date"] = datetime.now().strftime("%Y-%m-%d")

            # 데이터 통계 출력
            print(f"✅ 데이터 추출 완료: {len(data['countries'])}개 국가")
            for country_data in data["countries"]:
                country = country_data.get("country", "Unknown")
                game_count = len(country_data.get("games", []))
                print(f"   - {country}: {game_count}개 게임")

            return data

        except json.JSONDecodeError as e:
            print(f"❌ JSON 파싱 실패: {e}")
            print(f"추출된 텍스트: {json_text[:500]}...")
            self.save_screenshot("error_json_parse")
            raise
        except Exception as e:
            print(f"❌ 데이터 추출 실패: {e}")
            self.save_screenshot("error_extract_json")
            raise

    def save_rankings(self, data):
        """랭킹 데이터 저장"""
        print("💾 데이터 저장 중...")

        try:
            output_file = self.data_dir / "rankings.json"

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"✅ 저장 완료: {output_file}")

            # 저장된 데이터 요약 출력
            for country_data in data["countries"]:
                country = country_data["country"]
                flag = country_data["flag"]
                game_count = len(country_data["games"])
                print(f"  {flag} {country}: {game_count}개 게임")

        except Exception as e:
            print(f"❌ 데이터 저장 실패: {e}")
            raise

    def git_commit_and_push(self):
        """Git 자동 커밋 및 푸시"""
        print("📤 Git 커밋 및 푸시 중...")

        try:
            # Git 작업 디렉토리로 이동
            os.chdir(self.project_root)

            # Git add
            os.system("git add data/rankings.json")

            # Git commit
            commit_message = f"Update game rankings for {datetime.now().strftime('%Y-%m-%d')}"
            os.system(f'git commit -m "{commit_message}"')

            # Git push
            result = os.system("git push")

            if result == 0:
                print("✅ Git 푸시 완료")
            else:
                print("⚠️ Git 푸시 실패 (수동으로 푸시해주세요)")

        except Exception as e:
            print(f"❌ Git 작업 실패: {e}")
            print("💡 수동으로 다음 명령어를 실행하세요:")
            print("   git add data/rankings.json")
            print(f'   git commit -m "Update rankings"')
            print("   git push")

    def cleanup(self):
        """리소스 정리"""
        if self.driver:
            print("🧹 브라우저 종료 중...")
            self.driver.quit()
            print("✅ 정리 완료")

    def run(self):
        """전체 프로세스 실행"""
        print("=" * 60)
        print("🎮 게임 랭킹 자동 수집 시스템 시작")
        print("=" * 60)

        try:
            # 1. WebDriver 설정
            self.setup_driver()

            # 2. Gemini 접속
            self.navigate_to_gemini()

            # 3. 입력창 찾기
            input_element = self.find_input_element()

            # 4. 프롬프트 전송
            self.send_prompt(input_element)

            # 5. 응답 대기
            self.wait_for_response()

            # 6. JSON 추출
            data = self.extract_json_from_page()

            # 7. 데이터 저장
            self.save_rankings(data)

            # 8. Git 커밋 및 푸시
            self.git_commit_and_push()

            print("=" * 60)
            print("✅ 모든 작업 완료!")
            print("=" * 60)

        except Exception as e:
            print("=" * 60)
            print(f"❌ 오류 발생: {e}")
            print("=" * 60)
            raise

        finally:
            # 9. 리소스 정리
            self.cleanup()


if __name__ == "__main__":
    # 디버깅 시 headless=False로 설정
    collector = GeminiRankingCollector(headless=False)
    collector.run()
