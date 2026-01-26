#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
수동 입력 데이터 처리 및 Slack 알림 시스템
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
import urllib3

# SSL 경고 비활성화 (회사 네트워크 환경용)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Windows 콘솔 인코딩 설정
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


def load_env_file():
    """Load environment variables from .env file"""
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()


# Load .env file at startup
load_env_file()


class ManualDataProcessor:
    """수동 입력 데이터를 처리하고 Slack 알림을 보내는 클래스"""

    def __init__(self):
        self.project_root = Path(__file__).parent
        self.data_dir = self.project_root / "data"

        # Slack 설정
        self.slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")
        self.slack_bot_token = os.getenv("SLACK_BOT_TOKEN")
        self.slack_channel = os.getenv("SLACK_CHANNEL", "sgpqa_epiczero")

        # 국가별 플래그 이모지
        self.flag_emojis = {
            "KR": "🇰🇷",
            "JP": "🇯🇵",
            "US": "🇺🇸",
            "TW": "🇹🇼"
        }

    def load_manual_data(self):
        """수동 입력 데이터 로드"""
        manual_file = self.data_dir / "manual_input.json"

        if not manual_file.exists():
            print(f"❌ 수동 입력 파일을 찾을 수 없습니다: {manual_file}")
            print(f"💡 manual_input_template.json을 복사해서 manual_input.json으로 저장하고 데이터를 입력하세요")
            return None

        try:
            with open(manual_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            print(f"✅ 수동 입력 데이터 로드 완료")
            print(f"   날짜: {data.get('ranking_date')}")
            print(f"   국가 수: {len(data.get('countries', []))}")

            return data
        except Exception as e:
            print(f"❌ 데이터 로드 실패: {e}")
            return None

    def validate_data(self, data):
        """데이터 검증"""
        print("\n📊 데이터 검증 중...")

        if not data:
            print("❌ 데이터가 없습니다")
            return False

        if "ranking_date" not in data:
            print("❌ ranking_date 필드가 없습니다")
            return False

        if "countries" not in data or len(data["countries"]) == 0:
            print("❌ countries 데이터가 없습니다")
            return False

        # 각 국가별 검증
        for country_data in data["countries"]:
            country_name = country_data.get("country", "Unknown")
            games = country_data.get("games", [])

            if len(games) < 20:
                print(f"⚠️ {country_name}: 게임이 {len(games)}개로 부족합니다 (최소 20개 필요)")
                return False

            # 순위 중복 체크
            ranks = [game["rank"] for game in games]
            if len(ranks) != len(set(ranks)):
                print(f"❌ {country_name}: 중복된 순위가 있습니다")
                return False

            # 필수 필드 체크
            for game in games[:20]:
                if not game.get("title") or not game.get("publisher"):
                    print(f"❌ {country_name}: 게임 제목 또는 퍼블리셔가 누락되었습니다 (Rank {game.get('rank')})")
                    return False

            print(f"✅ {country_name}: {len(games)}개 게임 검증 완료")

        return True

    def save_to_rankings(self, data):
        """검증된 데이터를 rankings.json에 저장"""
        print("\n💾 rankings.json 저장 중...")

        rankings_file = self.data_dir / "rankings.json"

        # 이전 데이터 백업
        if rankings_file.exists():
            backup_file = self.data_dir / f"rankings_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(rankings_file, 'r', encoding='utf-8') as f:
                backup_data = json.load(f)
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2)
            print(f"📦 이전 데이터 백업: {backup_file}")

        # 새 데이터 저장
        with open(rankings_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"✅ rankings.json 저장 완료")

    def create_main_message(self, data):
        """메인 메시지 생성 (TOP 5)"""
        ranking_date = data["ranking_date"]

        message = f"🎮 *Google Play Store 게임 매출 랭킹 TOP 5*\n"
        message += f"📅 날짜: {ranking_date}\n\n"

        for country_data in data["countries"]:
            flag = self.flag_emojis.get(country_data["flag"], "🏳️")
            country_name = country_data["country"]
            games = country_data["games"][:5]

            message += f"{flag} *{country_name}*\n"
            for game in games:
                message += f"{game['rank']}. {game['title']} - {game['publisher']}\n"
            message += "\n"

        return message

    def create_country_detail(self, country_data):
        """국가별 상세 메시지 생성 (TOP 1-20 + Insights)"""
        flag = self.flag_emojis.get(country_data["flag"], "🏳️")
        country_name = country_data["country"]
        games = country_data["games"][:20]
        insights = country_data.get("insights", "인사이트 정보 없음")

        message = f"{flag} *{country_name} TOP 20 상세*\n\n"

        # TOP 1-20
        for game in games:
            message += f"{game['rank']}. {game['title']} - {game['publisher']}\n"

        # Insights
        message += f"\n📊 *Market Insights*\n{insights}"

        return message

    def load_previous_rankings(self):
        """이전 랭킹 데이터 로드 (변동사항 비교용)"""
        rankings_file = self.data_dir / "rankings.json"

        if not rankings_file.exists():
            return None

        try:
            with open(rankings_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return None

    def analyze_changes(self, current_data, previous_data):
        """랭킹 변동사항 분석"""
        if not previous_data:
            return "📊 *랭킹 변동사항 요약*\n\n이전 데이터가 없어 변동사항을 비교할 수 없습니다."

        changes_summary = "📊 *랭킹 변동사항 요약*\n\n"

        for current_country in current_data["countries"]:
            country_name = current_country["country"]
            flag = self.flag_emojis.get(current_country["flag"], "🏳️")

            # 이전 데이터에서 해당 국가 찾기
            previous_country = None
            for c in previous_data.get("countries", []):
                if c["country"] == country_name:
                    previous_country = c
                    break

            if not previous_country:
                changes_summary += f"{flag} *{country_name}*: 이전 데이터 없음\n\n"
                continue

            # 랭킹 변동 분석
            current_games = {game["title"]: game["rank"] for game in current_country["games"][:20]}
            previous_games = {game["title"]: game["rank"] for game in previous_country["games"][:20]}

            # 새로 진입한 게임
            new_entries = [title for title in current_games if title not in previous_games]

            # 떨어진 게임
            dropped_out = [title for title in previous_games if title not in current_games]

            # 순위 상승/하락
            significant_changes = []
            for title in current_games:
                if title in previous_games:
                    rank_diff = previous_games[title] - current_games[title]
                    if abs(rank_diff) >= 3:  # 3칸 이상 변동
                        if rank_diff > 0:
                            significant_changes.append(f"{title} ⬆️ {rank_diff}칸 상승")
                        else:
                            significant_changes.append(f"{title} ⬇️ {abs(rank_diff)}칸 하락")

            # 요약 메시지 생성
            country_summary = f"{flag} *{country_name}*\n"
            if new_entries or dropped_out or significant_changes:
                if new_entries:
                    country_summary += f"  • 신규 진입: {', '.join(new_entries[:3])}"
                    if len(new_entries) > 3:
                        country_summary += f" 외 {len(new_entries)-3}개"
                    country_summary += "\n"
                if dropped_out:
                    country_summary += f"  • 순위 이탈: {', '.join(dropped_out[:3])}"
                    if len(dropped_out) > 3:
                        country_summary += f" 외 {len(dropped_out)-3}개"
                    country_summary += "\n"
                if significant_changes:
                    country_summary += f"  • 주요 변동: {', '.join(significant_changes[:3])}"
                    if len(significant_changes) > 3:
                        country_summary += f" 외 {len(significant_changes)-3}개"
                    country_summary += "\n"
            else:
                country_summary += "  변동 없음\n"

            changes_summary += country_summary + "\n"

        return changes_summary

    def create_insights_summary(self, data):
        """국가별 시장 인사이트 요약"""
        insights_summary = "💡 *국가별 시장 인사이트*\n\n"

        for country_data in data["countries"]:
            flag = self.flag_emojis.get(country_data["flag"], "🏳️")
            country_name = country_data["country"]
            insights = country_data.get("insights", "인사이트 없음")

            insights_summary += f"{flag} *{country_name}*\n{insights}\n\n"

        return insights_summary

    def create_changes_and_insights_message(self, data, previous_data):
        """변동사항 + 인사이트 통합 메시지 생성"""
        message = ""

        # 1. 변동사항 요약
        if not previous_data:
            message += "📊 *랭킹 변동사항 요약*\n\n이전 데이터가 없어 변동사항을 비교할 수 없습니다.\n\n"
        else:
            changes_message = "📊 *랭킹 변동사항 요약*\n\n"
            has_any_changes = False

            for current_country in data["countries"]:
                country_name = current_country["country"]
                flag = self.flag_emojis.get(current_country["flag"], "🏳️")

                # 이전 데이터에서 해당 국가 찾기
                previous_country = None
                for c in previous_data.get("countries", []):
                    if c["country"] == country_name:
                        previous_country = c
                        break

                if not previous_country:
                    continue

                # 랭킹 변동 분석
                current_games = {game["title"]: game["rank"] for game in current_country["games"][:20]}
                previous_games = {game["title"]: game["rank"] for game in previous_country["games"][:20]}

                # 새로 진입한 게임
                new_entries = [title for title in current_games if title not in previous_games]

                # 떨어진 게임
                dropped_out = [title for title in previous_games if title not in current_games]

                # 순위 상승/하락
                significant_changes = []
                for title in current_games:
                    if title in previous_games:
                        rank_diff = previous_games[title] - current_games[title]
                        if abs(rank_diff) >= 3:  # 3칸 이상 변동
                            if rank_diff > 0:
                                significant_changes.append(f"{title} ⬆️ {rank_diff}칸 상승")
                            else:
                                significant_changes.append(f"{title} ⬇️ {abs(rank_diff)}칸 하락")

                # 변동사항이 있는 경우에만 메시지 추가
                if new_entries or dropped_out or significant_changes:
                    has_any_changes = True
                    country_summary = f"{flag} *{country_name}*\n"
                    if new_entries:
                        country_summary += f"  • 신규 진입: {', '.join(new_entries[:3])}"
                        if len(new_entries) > 3:
                            country_summary += f" 외 {len(new_entries)-3}개"
                        country_summary += "\n"
                    if dropped_out:
                        country_summary += f"  • 순위 이탈: {', '.join(dropped_out[:3])}"
                        if len(dropped_out) > 3:
                            country_summary += f" 외 {len(dropped_out)-3}개"
                        country_summary += "\n"
                    if significant_changes:
                        country_summary += f"  • 주요 변동: {', '.join(significant_changes[:3])}"
                        if len(significant_changes) > 3:
                            country_summary += f" 외 {len(significant_changes)-3}개"
                        country_summary += "\n"
                    changes_message += country_summary + "\n"

            # 변동사항이 하나라도 있는 경우에만 변동사항 섹션 추가
            if has_any_changes:
                message += changes_message
                # 구분선
                message += "━━━━━━━━━━━━━━━━━━━━\n\n"
            else:
                # 변동사항이 전혀 없으면 변동사항 섹션 자체를 생략
                pass

        # 2. 인사이트 요약
        message += "💡 *국가별 시장 인사이트*\n\n"

        for country_data in data["countries"]:
            flag = self.flag_emojis.get(country_data["flag"], "🏳️")
            country_name = country_data["country"]
            insights = country_data.get("insights", "인사이트 없음")

            message += f"{flag} *{country_name}*\n{insights}\n\n"

        return message

    def send_slack_notification(self, data):
        """Slack 알림 전송 (메인 메시지 TOP 5 + 변동사항/인사이트 통합)"""
        print("\n📤 Slack 알림 전송 중...")

        if not self.slack_webhook_url:
            print("❌ SLACK_WEBHOOK_URL이 설정되지 않았습니다")
            return False

        try:
            # 1. 메인 메시지 전송 (TOP 5)
            main_message = self.create_main_message(data)

            payload = {
                "text": main_message
            }

            response = requests.post(
                self.slack_webhook_url,
                json=payload,
                verify=False  # SSL 검증 비활성화 (회사 네트워크 환경용)
            )

            if response.status_code != 200 or response.text != "ok":
                print(f"❌ 메인 메시지 전송 실패: {response.text}")
                return False

            print("✅ 메인 메시지 (TOP 5) 전송 완료")

            # 2. 변동사항 + 인사이트 통합 메시지 전송
            previous_data = self.load_previous_rankings()
            combined_message = self.create_changes_and_insights_message(data, previous_data)

            combined_payload = {
                "text": combined_message
            }

            combined_response = requests.post(
                self.slack_webhook_url,
                json=combined_payload,
                verify=False  # SSL 검증 비활성화 (회사 네트워크 환경용)
            )

            if combined_response.status_code == 200 and combined_response.text == "ok":
                print("✅ 변동사항 + 인사이트 통합 메시지 전송 완료")
            else:
                print(f"⚠️ 변동사항 + 인사이트 메시지 전송 실패: {combined_response.text}")

            return True

        except Exception as e:
            print(f"❌ Slack 알림 전송 실패: {e}")
            import traceback
            traceback.print_exc()
            return False

    def run(self):
        """메인 실행 함수"""
        print("="*60)
        print("🎮 수동 데이터 처리 및 Slack 알림 시스템")
        print("="*60)

        # 1. 데이터 로드
        data = self.load_manual_data()
        if not data:
            sys.exit(1)

        # 2. 데이터 검증
        if not self.validate_data(data):
            print("\n❌ 데이터 검증 실패")
            sys.exit(1)

        # 3. rankings.json에 저장
        self.save_to_rankings(data)

        # 4. Slack 알림 전송
        success = self.send_slack_notification(data)

        if success:
            print("\n" + "="*60)
            print("✅ 모든 작업 완료!")
            print("="*60)
        else:
            print("\n❌ Slack 알림 전송 실패")
            sys.exit(1)


if __name__ == "__main__":
    processor = ManualDataProcessor()
    processor.run()
