#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Slack 메시지 표준 포맷터
- 일관된 양식으로 랭킹 데이터 전송
- 변동사항, 인사이트, 종합 리포트 포함
"""

import json
import os
import requests
import urllib3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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


load_env_file()


class SlackFormatter:
    """Slack 메시지 표준 포맷터"""

    def __init__(self):
        self.webhook_url = os.getenv("SLACK_WEBHOOK_URL")
        self.flag_emojis = {
            "KR": "🇰🇷", "JP": "🇯🇵", "US": "🇺🇸", "TW": "🇹🇼"
        }

    def send_message(self, text: str) -> bool:
        """Slack 메시지 전송"""
        if not self.webhook_url:
            print("❌ SLACK_WEBHOOK_URL이 설정되지 않았습니다")
            return False

        try:
            response = requests.post(
                self.webhook_url,
                json={"text": text},
                verify=False,
                timeout=30
            )
            return response.status_code == 200 and response.text == "ok"
        except Exception as e:
            print(f"❌ Slack 전송 실패: {e}")
            return False

    def format_header(self, ranking_date: str) -> str:
        """헤더 메시지 생성"""
        return f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎮 *Google Play 게임 매출 랭킹 리포트*
📅 {ranking_date}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    def format_top5_summary(self, data: Dict) -> str:
        """TOP 5 요약 메시지 생성"""
        lines = ["\n📊 *국가별 TOP 5*\n"]

        for country in data.get("countries", []):
            flag = self.flag_emojis.get(country["flag"], "🏳️")
            country_name = country["country"]
            games = country["games"][:5]

            lines.append(f"{flag} *{country_name}*")
            for game in games:
                publisher = game.get('publisher', '')
                if publisher:
                    lines.append(f"  {game['rank']}. {game['title']} / {publisher}")
                else:
                    lines.append(f"  {game['rank']}. {game['title']}")
            lines.append("")

        return "\n".join(lines)

    def format_changes(self, trend_analysis: Dict) -> str:
        """변동사항 요약 메시지 생성"""
        if not trend_analysis or not trend_analysis.get("countries"):
            return ""

        lines = ["📈 *랭킹 변동사항*\n"]
        has_changes = False

        for country_name, analysis in trend_analysis.get("countries", {}).items():
            flag = self.flag_emojis.get(
                {"South Korea": "KR", "United States": "US", "Japan": "JP", "Taiwan": "TW"}.get(country_name, ""),
                "🏳️"
            )

            new_entries = analysis.get("new_entries", [])
            dropped_out = analysis.get("dropped_out", [])
            trends = analysis.get("game_trends", [])

            # 3칸 이상 변동만 표시
            significant_trends = [t for t in trends if abs(t.get("change", 0)) >= 3]

            if new_entries or dropped_out or significant_trends:
                has_changes = True
                lines.append(f"{flag} *{country_name}*")

                if new_entries:
                    new_titles = [f"{e['title']} (#{e['rank']})" for e in new_entries[:3]]
                    extra = f" 외 {len(new_entries)-3}개" if len(new_entries) > 3 else ""
                    lines.append(f"  🆕 신규 진입: {', '.join(new_titles)}{extra}")

                if dropped_out:
                    dropped_titles = [e['title'] for e in dropped_out[:3]]
                    extra = f" 외 {len(dropped_out)-3}개" if len(dropped_out) > 3 else ""
                    lines.append(f"  📤 순위 이탈: {', '.join(dropped_titles)}{extra}")

                if significant_trends:
                    for t in significant_trends[:3]:
                        arrow = "⬆️" if t["change"] > 0 else "⬇️"
                        lines.append(f"  {arrow} {t['title']}: {t['previous_rank']}위 → {t['current_rank']}위 ({'+' if t['change'] > 0 else ''}{t['change']})")

                lines.append("")

        if not has_changes:
            return ""

        return "\n".join(lines)

    def format_insights(self, data: Dict) -> str:
        """국가별 인사이트 메시지 생성"""
        lines = ["━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
        lines.append("💡 *시장 인사이트*\n")

        for country in data.get("countries", []):
            flag = self.flag_emojis.get(country["flag"], "🏳️")
            country_name = country["country"]
            insights = country.get("insights", "")

            if insights and insights != "인사이트 없음" and insights != "AI 인사이트 생성 대기 중...":
                lines.append(f"{flag} *{country_name}*")
                # 인사이트를 줄바꿈으로 포맷팅
                for line in insights.split("\n"):
                    if line.strip():
                        lines.append(f"  {line.strip()}")
                lines.append("")

        return "\n".join(lines)

    def format_comprehensive_report(self, report: str) -> str:
        """종합 리포트 메시지 생성"""
        if not report or report == "종합 리포트 생성 실패":
            return ""

        return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{report}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    def send_full_report(self, data: Dict, send_separate: bool = True) -> bool:
        """
        전체 리포트 전송

        Args:
            data: 랭킹 데이터 (trend_analysis, comprehensive_report 포함)
            send_separate: True면 여러 메시지로 분리, False면 하나로 통합
        """
        print("\n📤 Slack 알림 전송 중...")

        ranking_date = data.get("ranking_date", datetime.now().strftime("%Y-%m-%d"))
        trend_analysis = data.get("_trend_analysis", {})
        comprehensive_report = data.get("comprehensive_report", "")

        if send_separate:
            # 메시지 1: 헤더 + TOP 5
            msg1 = self.format_header(ranking_date) + self.format_top5_summary(data)
            if not self.send_message(msg1):
                print("❌ TOP 5 메시지 전송 실패")
                return False
            print("✅ TOP 5 메시지 전송 완료")

            # 메시지 2: 인사이트 (변동사항 포함된 간결 버전)
            insights = self.format_insights(data)
            if insights and len(insights) > 30:
                if not self.send_message(insights):
                    print("⚠️ 인사이트 메시지 전송 실패")
                else:
                    print("✅ 인사이트 메시지 전송 완료")

            # 메시지 3: 종합 리포트 (있을 경우에만)
            if comprehensive_report:
                report_msg = self.format_comprehensive_report(comprehensive_report)
                if report_msg:
                    if not self.send_message(report_msg):
                        print("⚠️ 종합 리포트 전송 실패")
                    else:
                        print("✅ 종합 리포트 전송 완료")

        else:
            # 통합 메시지
            full_message = self.format_header(ranking_date)
            full_message += self.format_top5_summary(data)

            insights = self.format_insights(data)
            if insights and len(insights) > 30:
                full_message += "\n" + insights

            if comprehensive_report:
                full_message += self.format_comprehensive_report(comprehensive_report)

            if not self.send_message(full_message):
                print("❌ 통합 메시지 전송 실패")
                return False
            print("✅ 통합 메시지 전송 완료")

        return True

    def send_simple_notification(self, data: Dict) -> bool:
        """
        간단한 알림 전송 (TOP 5 + 주요 변동만)
        AI 기능 없이 빠르게 전송할 때 사용
        """
        ranking_date = data.get("ranking_date", datetime.now().strftime("%Y-%m-%d"))

        message = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎮 *Google Play 게임 매출 랭킹*
📅 {ranking_date}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"""
        for country in data.get("countries", []):
            flag = self.flag_emojis.get(country["flag"], "🏳️")
            message += f"{flag} *{country['country']}*\n"
            for game in country["games"][:5]:
                publisher = game.get('publisher', '')
                if publisher:
                    message += f"  {game['rank']}. {game['title']} / {publisher}\n"
                else:
                    message += f"  {game['rank']}. {game['title']}\n"
            message += "\n"

        return self.send_message(message)


# 단독 테스트
if __name__ == "__main__":
    formatter = SlackFormatter()
    print(f"Webhook URL: {'설정됨' if formatter.webhook_url else '미설정'}")
