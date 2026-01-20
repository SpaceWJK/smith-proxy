"""Gemini API Collector - Uses Google Gemini to get game rankings"""
import os
import json
import time
from typing import List, Optional
from datetime import datetime

import google.generativeai as genai

from ..models import GameApp, RankingSnapshot, CrawlResult
from ..config import COUNTRIES, TOP_N_RANKS

class GeminiAPICollector:
    """
    Collects game ranking data using Google Gemini API

    This avoids bot detection by using Gemini's web browsing capabilities
    instead of direct HTTP requests.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Gemini API collector

        Args:
            api_key: Google Gemini API key (defaults to GEMINI_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")

        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY not found. "
                "Set it as environment variable or pass to constructor."
            )

        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')

    def collect_country(self, country_code: str) -> CrawlResult:
        """
        Collect ranking data for a specific country using Gemini API

        Args:
            country_code: Country code (KR, JP, US, TW)

        Returns:
            CrawlResult with snapshot data or error
        """
        if country_code not in COUNTRIES:
            return CrawlResult(
                success=False,
                country_code=country_code,
                error=f"Unknown country code: {country_code}"
            )

        country = COUNTRIES[country_code]
        url = country.appbrain_url

        print(f"[{country_code}] Using Gemini API to fetch from {url}...")

        try:
            # Construct prompt for Gemini
            prompt = f"""Please fetch and extract the top {TOP_N_RANKS} grossing games from this AppBrain page: {url}

Extract the following information for each game:
- Rank (1-{TOP_N_RANKS})
- Game title
- Publisher/Developer name
- Package ID (if available, usually in format com.company.game)
- App URL (if available)

Return ONLY a valid JSON array with this structure:
[
  {{
    "rank": 1,
    "title": "Game Name",
    "publisher": "Publisher Name",
    "package_id": "com.example.game",
    "app_url": "https://..."
  }},
  ...
]

Important:
- Return ONLY the JSON array, no explanations or markdown
- Ensure valid JSON format
- If package_id or app_url is not available, use null
- Game titles should be in their original language
- Include all {TOP_N_RANKS} games"""

            # Call Gemini API with prompt
            response = self.model.generate_content(prompt)

            if not response or not response.text:
                raise ValueError("Empty response from Gemini API")

            response_text = response.text
            print(f"[{country_code}] Received response from Gemini API")

            # Parse JSON from response
            games = self._parse_gemini_response(response_text, country_code)

            if not games:
                raise ValueError("No games found in Gemini's response")

            # Limit to TOP_N_RANKS
            games = games[:TOP_N_RANKS]

            # Create snapshot
            now = datetime.utcnow()
            snapshot = RankingSnapshot(
                country_code=country_code,
                country_name=country.name,
                date=now.strftime("%Y-%m-%d"),
                timestamp=now.isoformat(),
                games=games
            )

            print(f"[{country_code}] ✓ Successfully collected {len(games)} games via Gemini API")
            return CrawlResult(
                success=True,
                country_code=country_code,
                snapshot=snapshot
            )

        except Exception as e:
            error_msg = f"Gemini API error: {e}"
            print(f"[{country_code}] ✗ {error_msg}")
            return CrawlResult(
                success=False,
                country_code=country_code,
                error=error_msg
            )

    def _parse_gemini_response(self, response_text: str, country_code: str) -> List[GameApp]:
        """
        Parse Gemini's response to extract game data

        Args:
            response_text: Response text from Gemini
            country_code: Country code for logging

        Returns:
            List of GameApp objects
        """
        try:
            # Try to find JSON array in response
            # Gemini might wrap it in markdown code blocks
            response_text = response_text.strip()

            # Remove markdown code blocks if present
            if response_text.startswith("```"):
                # Remove ```json or ``` at start
                lines = response_text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].strip() == "```":
                    lines = lines[:-1]
                response_text = "\n".join(lines)

            # Parse JSON
            data = json.loads(response_text)

            if not isinstance(data, list):
                print(f"[{country_code}] Warning: Expected array, got {type(data)}")
                # Try to extract games array from dict
                if isinstance(data, dict) and "games" in data:
                    data = data["games"]
                else:
                    raise ValueError("Response is not a JSON array")

            # Convert to GameApp objects
            games = []
            for item in data:
                try:
                    game = GameApp(
                        rank=item.get("rank", len(games) + 1),
                        title=item.get("title", "Unknown"),
                        publisher=item.get("publisher", "Unknown"),
                        package_id=item.get("package_id"),
                        app_url=item.get("app_url"),
                        icon_url=item.get("icon_url")
                    )
                    games.append(game)
                except Exception as e:
                    print(f"[{country_code}] Warning: Failed to parse game item: {e}")
                    continue

            return games

        except json.JSONDecodeError as e:
            print(f"[{country_code}] JSON parse error: {e}")
            print(f"[{country_code}] Response preview: {response_text[:500]}...")
            return []
        except Exception as e:
            print(f"[{country_code}] Parse error: {e}")
            return []

    def collect_all_countries(self) -> List[CrawlResult]:
        """Collect ranking data for all configured countries"""
        results = []

        for country_code in COUNTRIES.keys():
            result = self.collect_country(country_code)
            results.append(result)

            # Delay between API calls to avoid rate limits
            if len(results) < len(COUNTRIES):
                print(f"Waiting 3 seconds before next country...")
                time.sleep(3)

        return results
