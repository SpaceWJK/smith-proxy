"""Google Play Store Collector - Gets top grossing games using google-play-scraper"""
import time
from typing import List, Optional
from datetime import datetime
from google_play_scraper import collection, Sort

from ..models import GameApp, RankingSnapshot, CrawlResult
from ..config import (
    COUNTRIES,
    TOP_N_RANKS,
    MAX_RETRIES,
    RETRY_DELAY
)

class GooglePlayCollector:
    """Collects game ranking data from Google Play Store"""

    def __init__(self):
        pass

    def collect_country(self, country_code: str) -> CrawlResult:
        """
        Collect ranking data for a specific country

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

        for attempt in range(MAX_RETRIES):
            try:
                print(f"[{country_code}] Attempt {attempt + 1}/{MAX_RETRIES}: Fetching top grossing games...")

                # Fetch top grossing games from Google Play Store
                results = collection(
                    collection='topselling_paid',  # Top Grossing
                    category='GAME',  # Games only
                    results=TOP_N_RANKS * 2,  # Fetch extra to ensure we get enough
                    country=country_code.lower(),
                    lang=country.language_code
                )

                if not results:
                    raise ValueError("No games found")

                games = self._parse_results(results, country_code)

                if not games:
                    raise ValueError("Failed to parse games")

                # Limit to TOP_N_RANKS
                games = games[:TOP_N_RANKS]

                now = datetime.utcnow()
                snapshot = RankingSnapshot(
                    country_code=country_code,
                    country_name=country.name,
                    date=now.strftime("%Y-%m-%d"),
                    timestamp=now.isoformat(),
                    games=games
                )

                print(f"[{country_code}] ✓ Successfully collected {len(games)} games")
                return CrawlResult(
                    success=True,
                    country_code=country_code,
                    snapshot=snapshot
                )

            except Exception as e:
                print(f"[{country_code}] ✗ Error (attempt {attempt + 1}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                else:
                    return CrawlResult(
                        success=False,
                        country_code=country_code,
                        error=f"Failed after {MAX_RETRIES} attempts: {e}"
                    )

    def _parse_results(self, results: List[dict], country_code: str) -> List[GameApp]:
        """
        Parse Google Play Store results into GameApp objects

        Args:
            results: List of app dictionaries from google-play-scraper
            country_code: Country code for logging

        Returns:
            List of GameApp objects
        """
        games = []

        for idx, app_data in enumerate(results, 1):
            try:
                game = GameApp(
                    rank=idx,
                    title=app_data.get('title', 'Unknown'),
                    publisher=app_data.get('developer', 'Unknown'),
                    package_id=app_data.get('appId'),
                    app_url=app_data.get('url'),
                    icon_url=app_data.get('icon')
                )
                games.append(game)
            except Exception as e:
                print(f"[{country_code}] Warning: Failed to parse app {idx}: {e}")
                continue

        return games

    def collect_all_countries(self) -> List[CrawlResult]:
        """Collect ranking data for all configured countries"""
        results = []

        for country_code in COUNTRIES.keys():
            result = self.collect_country(country_code)
            results.append(result)

            # Small delay between countries to be polite
            if len(results) < len(COUNTRIES):
                time.sleep(2)

        return results
