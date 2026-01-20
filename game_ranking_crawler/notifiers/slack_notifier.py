"""Slack notifier for game rankings - Compact message with thread details"""
import os
import json
import requests
from typing import List, Optional, Dict, Tuple
from datetime import datetime

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from ..models import RankingSnapshot
from ..config import SLACK_WEBHOOK_URL, COUNTRIES
from ..analyzers.diff_analyzer import DiffAnalyzer, GameDiff, MarketInsight
from ..storage.json_storage import JSONStorage

class SlackNotifier:
    """Sends compact game ranking reports to Slack with thread details"""

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        bot_token: Optional[str] = None,
        channel: Optional[str] = None
    ):
        """
        Initialize Slack notifier

        Args:
            webhook_url: Incoming Webhook URL (for simple messages)
            bot_token: Bot Token (for threads - recommended)
            channel: Channel ID or name (required if using bot_token)
        """
        self.webhook_url = webhook_url or SLACK_WEBHOOK_URL
        self.bot_token = bot_token or os.getenv("SLACK_BOT_TOKEN", "")
        self.channel = channel or os.getenv("SLACK_CHANNEL", "#game-rankings")

        # Use Bot Token if available (supports threads)
        if self.bot_token:
            self.client = WebClient(token=self.bot_token)
            self.use_threads = True
            print("[Slack] Using Bot Token (threads enabled)")
        elif self.webhook_url:
            self.client = None
            self.use_threads = False
            print("[Slack] Using Webhook URL (threads disabled)")
        else:
            raise ValueError(
                "Either SLACK_WEBHOOK_URL or SLACK_BOT_TOKEN must be configured. "
                "Bot Token is recommended for thread support."
            )

        self.storage = JSONStorage()
        self.analyzer = DiffAnalyzer()

    def send_daily_report(
        self,
        snapshots: List[RankingSnapshot],
        with_analysis: bool = True
    ) -> bool:
        """
        Send compact daily ranking report to Slack

        Args:
            snapshots: List of ranking snapshots for all countries
            with_analysis: Include change analysis (requires previous data)

        Returns:
            True if successful, False otherwise
        """
        if not snapshots:
            return False

        try:
            # Analyze changes if requested
            all_diffs = {}
            all_insights = {}

            if with_analysis:
                for snapshot in snapshots:
                    previous = self.storage.get_previous_snapshot(
                        snapshot.country_code,
                        snapshot.date
                    )
                    diffs, insight = self.analyzer.compare_snapshots(snapshot, previous)
                    all_diffs[snapshot.country_code] = diffs
                    all_insights[snapshot.country_code] = insight

            # Find global hits
            global_hits = self.analyzer.find_global_hits(snapshots, top_n=10)

            # Format and send main message
            if self.use_threads:
                # Send with Bot Token (supports threads)
                return self._send_with_threads(
                    snapshots, all_diffs, all_insights, global_hits
                )
            else:
                # Send with Webhook (compact only)
                return self._send_compact_webhook(
                    snapshots, all_diffs, all_insights, global_hits
                )

        except Exception as e:
            print(f"[Slack] Error sending report: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _send_with_threads(
        self,
        snapshots: List[RankingSnapshot],
        all_diffs: Dict,
        all_insights: Dict,
        global_hits: List[str]
    ) -> bool:
        """Send compact message + thread replies using Bot Token"""
        try:
            # Create main message
            blocks = self._format_compact_message(
                snapshots, all_diffs, all_insights, global_hits
            )

            # Send main message
            response = self.client.chat_postMessage(
                channel=self.channel,
                text=f"📊 Game Ranking Report - {snapshots[0].date}",
                blocks=blocks
            )

            thread_ts = response["ts"]
            print(f"[Slack] ✓ Main message sent (ts: {thread_ts})")

            # Send thread replies with full rankings
            for snapshot in snapshots:
                country = COUNTRIES.get(snapshot.country_code)
                if not country:
                    continue

                diffs = all_diffs.get(snapshot.country_code, [])
                thread_text = self._format_thread_detail(snapshot, diffs, country)

                self.client.chat_postMessage(
                    channel=self.channel,
                    thread_ts=thread_ts,
                    text=thread_text
                )
                print(f"[Slack] ✓ Thread reply sent for {snapshot.country_code}")

            return True

        except SlackApiError as e:
            print(f"[Slack] ✗ Slack API error: {e.response['error']}")
            return False

    def _send_compact_webhook(
        self,
        snapshots: List[RankingSnapshot],
        all_diffs: Dict,
        all_insights: Dict,
        global_hits: List[str]
    ) -> bool:
        """Send compact message via Webhook (no threads)"""
        blocks = self._format_compact_message(
            snapshots, all_diffs, all_insights, global_hits
        )

        message = {
            "text": f"📊 Game Ranking Report - {snapshots[0].date}",
            "blocks": blocks
        }

        return self._send_to_webhook(message)

    def _format_compact_message(
        self,
        snapshots: List[RankingSnapshot],
        all_diffs: Dict,
        all_insights: Dict,
        global_hits: List[str]
    ) -> List[dict]:
        """Format ultra-compact main message - TOP 5 only"""
        date = snapshots[0].date if snapshots else datetime.utcnow().strftime("%Y-%m-%d")

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Game Rankings(Android) • {date}",
                    "emoji": False
                }
            },
            {"type": "divider"}
        ]

        # Country TOP 5 - Clean and compact
        for snapshot in snapshots:
            country = COUNTRIES.get(snapshot.country_code)
            if not country:
                continue

            # Format TOP 5
            top5_text = f"*{country.flag_emoji} {country.name}*\n"
            for i, game in enumerate(snapshot.games[:5], 1):
                publisher = f" • {game.publisher}" if game.publisher and game.publisher != "Unknown" else ""
                top5_text += f"`{i}` {game.title}{publisher}\n"

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": top5_text.strip()
                }
            })

        blocks.append({"type": "divider"})

        return blocks

    def _generate_highlights(
        self,
        snapshots: List[RankingSnapshot],
        all_insights: Dict
    ) -> str:
        """Generate highlights text"""
        highlights = []

        # Find biggest mover across all countries
        biggest_mover = None
        max_change = 0

        for country_code, insight in all_insights.items():
            if insight.top_movers:
                for title, change in insight.top_movers:
                    if abs(change) > max_change:
                        max_change = abs(change)
                        country = COUNTRIES.get(country_code)
                        direction = "⬆️" if change > 0 else "⬇️"
                        biggest_mover = f"{country.flag_emoji} *{title}* ({direction}{abs(change)})"

        if biggest_mover:
            highlights.append(f"• Biggest Mover: {biggest_mover}")

        # New entries
        total_new = sum(insight.new_entries for insight in all_insights.values())
        if total_new > 0:
            highlights.append(f"• New Entries: {total_new} games")

        return "\n".join(highlights) if highlights else ""

    def _format_market_insights(self, all_insights: Dict) -> str:
        """Format market insights"""
        lines = []

        for country_code, insight in all_insights.items():
            country = COUNTRIES.get(country_code)
            if not country:
                continue

            volatility_emoji = {
                "high": "🔥",
                "medium": "📊",
                "low": "🟢",
                "unknown": "❓"
            }.get(insight.volatility, "📊")

            stability = "stable" if insight.stability_top5 >= 0.8 else "volatile"
            lines.append(f"{country.flag_emoji} {volatility_emoji} {stability}")

        return " | ".join(lines)

    def _format_thread_detail(
        self,
        snapshot: RankingSnapshot,
        diffs: List[GameDiff],
        country
    ) -> str:
        """Format detailed ranking for thread reply with market insights"""
        lines = [
            f"*{country.flag_emoji} {country.name} - Top 20*",
            ""
        ]

        # Create diff map
        diff_map = {d.game.rank: d for d in diffs} if diffs else {}

        for i, game in enumerate(snapshot.games[:20], 1):
            # Rank indicator
            if i == 1:
                rank_str = "🥇"
            elif i == 2:
                rank_str = "🥈"
            elif i == 3:
                rank_str = "🥉"
            else:
                rank_str = f"`{i:2d}`"

            # Game info
            title = game.title
            publisher = f" • _{game.publisher}_" if game.publisher != "Unknown" else ""

            # Change indicator
            change_str = ""
            if i in diff_map:
                diff = diff_map[i]
                if diff.is_new:
                    change_str = " 🆕"
                elif diff.rank_change:
                    if diff.rank_change > 0:
                        change_str = f" ⬆{diff.rank_change}"
                    elif diff.rank_change < 0:
                        change_str = f" ⬇{abs(diff.rank_change)}"

            lines.append(f"{rank_str} {title}{publisher}{change_str}")

        # Add market insights at the end
        if diffs:
            lines.append("")
            lines.append("*Market Insights*")

            # Calculate insights
            new_count = sum(1 for d in diffs if d.is_new)
            movers = [(d.game.title, d.rank_change) for d in diffs if d.rank_change]
            top_movers = sorted(movers, key=lambda x: abs(x[1]), reverse=True)[:3]

            if new_count > 0:
                lines.append(f"• New Entries: {new_count}")

            if top_movers:
                lines.append("• Top Movers:")
                for title, change in top_movers:
                    direction = "⬆" if change > 0 else "⬇"
                    lines.append(f"  {direction} {title} ({abs(change)} ranks)")

        return "\n".join(lines)

    def _send_to_webhook(self, message: dict) -> bool:
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

        if self.use_threads:
            try:
                self.client.chat_postMessage(
                    channel=self.channel,
                    text="⚠️ Crawler Errors",
                    blocks=message["blocks"]
                )
                return True
            except SlackApiError:
                return False
        else:
            return self._send_to_webhook(message)
