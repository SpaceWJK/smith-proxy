"""Configuration for Game Ranking Crawler"""
import os
from dataclasses import dataclass
from typing import Dict

@dataclass
class CountryConfig:
    """Country-specific configuration"""
    code: str
    name: str
    appbrain_url: str
    flag_emoji: str
    language_code: str = "en"  # For Google Play API

# Target countries configuration
COUNTRIES: Dict[str, CountryConfig] = {
    "KR": CountryConfig(
        code="KR",
        name="South Korea",
        appbrain_url="https://www.appbrain.com/stats/google-play-top-grossing/games/kr",
        flag_emoji="🇰🇷",
        language_code="ko"
    ),
    "JP": CountryConfig(
        code="JP",
        name="Japan",
        appbrain_url="https://www.appbrain.com/stats/google-play-top-grossing/games/jp",
        flag_emoji="🇯🇵",
        language_code="ja"
    ),
    "US": CountryConfig(
        code="US",
        name="United States",
        appbrain_url="https://www.appbrain.com/stats/google-play-top-grossing/games/us",
        flag_emoji="🇺🇸",
        language_code="en"
    ),
    "TW": CountryConfig(
        code="TW",
        name="Taiwan",
        appbrain_url="https://www.appbrain.com/stats/google-play-top-grossing/games/tw",
        flag_emoji="🇹🇼",
        language_code="zh-TW"
    ),
}

# Crawler settings
TOP_N_RANKS = 20
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

# Storage settings
SNAPSHOTS_DIR = "snapshots"
HISTORY_FILE = "history.json"

# Slack settings (from environment variables)
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "#game-rankings")

# User agent for web scraping
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
