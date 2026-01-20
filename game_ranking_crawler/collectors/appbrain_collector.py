"""AppBrain Collector - Scrapes top grossing games from AppBrain"""
import time
import requests
from bs4 import BeautifulSoup
from typing import List, Optional
from datetime import datetime

from ..models import GameApp, RankingSnapshot, CrawlResult
from ..config import (
    COUNTRIES,
    TOP_N_RANKS,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
    RETRY_DELAY,
    USER_AGENT
)

class AppBrainCollector:
    """Collects game ranking data from AppBrain"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        })

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
                print(f"[{country_code}] Attempt {attempt + 1}/{MAX_RETRIES}: Fetching {country.appbrain_url}")

                response = self.session.get(
                    country.appbrain_url,
                    timeout=REQUEST_TIMEOUT
                )
                response.raise_for_status()

                games = self._parse_html(response.text, country_code)

                if not games:
                    raise ValueError("No games found in page")

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

            except requests.RequestException as e:
                print(f"[{country_code}] ✗ Request error (attempt {attempt + 1}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                else:
                    return CrawlResult(
                        success=False,
                        country_code=country_code,
                        error=f"Request failed after {MAX_RETRIES} attempts: {e}"
                    )
            except Exception as e:
                print(f"[{country_code}] ✗ Parse error: {e}")
                return CrawlResult(
                    success=False,
                    country_code=country_code,
                    error=f"Parse error: {e}"
                )

    def _parse_html(self, html: str, country_code: str) -> List[GameApp]:
        """
        Parse HTML to extract game ranking data

        AppBrain structure (as of 2024):
        - Table with class "table-apps" or similar
        - Each row contains: rank, icon, title, publisher, etc.
        """
        soup = BeautifulSoup(html, "lxml")
        games = []

        # Try multiple possible selectors
        # AppBrain typically uses a table or list structure

        # Method 1: Look for app table rows
        app_rows = soup.select("table.table-apps tbody tr")

        if not app_rows:
            # Method 2: Look for divs with app data
            app_rows = soup.select("div.app-row, div.approw, div[data-app-id]")

        if not app_rows:
            # Method 3: Look for any table with apps
            tables = soup.find_all("table")
            for table in tables:
                rows = table.select("tbody tr")
                if rows and len(rows) >= 10:  # Likely the ranking table
                    app_rows = rows
                    break

        print(f"[{country_code}] Found {len(app_rows)} app rows in HTML")

        for idx, row in enumerate(app_rows, 1):
            try:
                game = self._parse_app_row(row, idx)
                if game:
                    games.append(game)
            except Exception as e:
                print(f"[{country_code}] Warning: Failed to parse row {idx}: {e}")
                continue

        return games

    def _parse_app_row(self, row, rank: int) -> Optional[GameApp]:
        """Parse a single app row"""

        # Extract title - usually in <a> tag with class like "app-title" or similar
        title_elem = (
            row.select_one("a.app-title") or
            row.select_one("td.app-title a") or
            row.select_one("a[href*='/app/']") or
            row.find("a", href=lambda x: x and "/app/" in x)
        )

        if not title_elem:
            return None

        title = title_elem.get_text(strip=True)
        app_url = title_elem.get("href", "")

        # Extract package ID from URL
        # URL format: /app/com.example.game or similar
        package_id = None
        if app_url and "/app/" in app_url:
            package_id = app_url.split("/app/")[-1].split("/")[0]

        # Extract publisher - usually near the title
        publisher_elem = (
            row.select_one("td.publisher") or
            row.select_one("span.publisher") or
            row.select_one("a[href*='/dev/']") or
            row.find("a", href=lambda x: x and "/dev/" in x)
        )

        publisher = publisher_elem.get_text(strip=True) if publisher_elem else "Unknown"

        # Extract icon URL
        icon_elem = row.select_one("img.app-icon") or row.find("img")
        icon_url = icon_elem.get("src") if icon_elem else None

        return GameApp(
            rank=rank,
            title=title,
            publisher=publisher,
            package_id=package_id,
            app_url=f"https://www.appbrain.com{app_url}" if app_url and not app_url.startswith("http") else app_url,
            icon_url=icon_url
        )

    def collect_all_countries(self) -> List[CrawlResult]:
        """Collect ranking data for all configured countries"""
        results = []

        for country_code in COUNTRIES.keys():
            result = self.collect_country(country_code)
            results.append(result)

            # Small delay between countries to be polite
            if len(results) < len(COUNTRIES):
                time.sleep(1)

        return results
