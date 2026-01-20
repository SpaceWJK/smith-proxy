"""Slack notifier for game rankings"""
import json
import requests
from typing import List
from datetime import datetime

from ..models import RankingSnapshot
from ..config import SLACK_WEBHOOK_URL, COUNTRIES

class SlackNotifier:
    """Sends game ranking reports to Slack"""

    def __init__(self, webhook_url: str = None):
        self.webhook_url = webhook_url or SLACK_WEBHOOK_URL

        if not self.webhook_url:
            raise ValueError("Slack webhook URL not configured")

    def send_daily_report(self, snapshots: List[RankingSnapshot]) -> bool:
        """
        Send daily ranking report to Slack

        Args:
            snapshots: List of ranking snapshots for all countries

        Returns:
            True if successful, False otherwise
        """
        if not snapshots:
            return False

        try:
            message = self._format_report(snapshots)
            return self._send_to_slack(message)
        except Exception as e:
            print(f"[Slack] Error sending report: {e}")
            return False

    def _format_report(self, snapshots: List[RankingSnapshot]) -> dict:
        """Format ranking data as Slack message"""

        # Report header
        date = snapshots[0].date if snapshots else datetime.utcnow().strftime("%Y-%m-%d")
        header_text = f"📊 *Game Ranking Report - {date}*"

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"📊 Game Ranking Report - {date}",
                    "emoji": True
                }
            },
            {
                "type": "divider"
            }
        ]

        # Add each country's ranking
        for snapshot in snapshots:
            country = COUNTRIES.get(snapshot.country_code)
            if not country:
                continue

            # Country header
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{country.flag_emoji} {country.name} ({snapshot.country_code})*"
                }
            })

            # Format top 20 games
            games_text = self._format_games_list(snapshot.games)

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": games_text
                }
            })

            blocks.append({"type": "divider"})

        # Footer
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"🤖 _Collected at {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}_"
                }
            ]
        })

        return {
            "text": header_text,  # Fallback text
            "blocks": blocks
        }

    def _format_games_list(self, games: List) -> str:
        """Format list of games as markdown text"""
        lines = []

        for game in games[:20]:  # Top 20
            # Medal emojis for top 3
            if game.rank == 1:
                prefix = "🥇"
            elif game.rank == 2:
                prefix = "🥈"
            elif game.rank == 3:
                prefix = "🥉"
            else:
                prefix = f"`{game.rank:2d}`"

            # Format: [rank] Title (Publisher)
            line = f"{prefix} *{game.title}*"
            if game.publisher and game.publisher != "Unknown":
                line += f" _{game.publisher}_"

            lines.append(line)

        return "\n".join(lines)

    def _send_to_slack(self, message: dict) -> bool:
        """Send message to Slack webhook"""
        try:
            response = requests.post(
                self.webhook_url,
                json=message,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            response.raise_for_status()

            print(f"[Slack] ✓ Message sent successfully")
            return True

        except requests.RequestException as e:
            print(f"[Slack] ✗ Failed to send message: {e}")
            return False

    def send_error_notification(self, errors: List[str]) -> bool:
        """Send error notification to Slack"""
        message = {
            "text": "⚠️ Game Ranking Crawler Errors",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "⚠️ Crawler Errors",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "\n".join([f"• {error}" for error in errors])
                    }
                }
            ]
        }

        return self._send_to_slack(message)
