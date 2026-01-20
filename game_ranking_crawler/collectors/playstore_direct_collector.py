"""Direct Google Play Store Collector - Parses HTML/JSON from Play Store"""
import time
import requests
import json
import re
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

class PlayStoreDirectCollector:
    """Collects game ranking data directly from Google Play Store"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
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

        # Try multiple URL formats
        urls = [
            # Format 1: Top charts with category
            f"https://play.google.com/store/apps/top?category=GAME&chart=topselling&hl={country.language_code}&gl={country_code}",
            # Format 2: Collection URL
            f"https://play.google.com/store/apps/collection/topselling_paid?category=GAME&hl={country.language_code}&gl={country_code}",
            # Format 3: Top grossing
            f"https://play.google.com/store/apps/collection/topgrossing?category=GAME&hl={country.language_code}&gl={country_code}",
        ]

        for url in urls:
            for attempt in range(MAX_RETRIES):
                try:
                    print(f"[{country_code}] Attempt {attempt + 1}/{MAX_RETRIES}: Trying {url[:80]}...")

                    response = self.session.get(url, timeout=REQUEST_TIMEOUT)
                    response.raise_for_status()

                    games = self._parse_playstore_html(response.text, country_code)

                    if games and len(games) >= 10:  # Consider success if we got at least 10 games
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
                    else:
                        print(f"[{country_code}] ⚠ Found only {len(games) if games else 0} games, trying next URL...")

                except requests.RequestException as e:
                    print(f"[{country_code}] ✗ Request error: {e}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_DELAY)
                except Exception as e:
                    print(f"[{country_code}] ✗ Parse error: {e}")

                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)

        return CrawlResult(
            success=False,
            country_code=country_code,
            error="Failed to collect games from all URL formats"
        )

    def _parse_playstore_html(self, html: str, country_code: str) -> List[GameApp]:
        """
        Parse Google Play Store HTML to extract app data

        Google Play Store embeds app data in JavaScript as JSON
        """
        games = []

        # Try to extract JSON data from script tags
        soup = BeautifulSoup(html, "lxml")

        # Method 1: Extract from AF_initDataCallback (common pattern)
        scripts = soup.find_all("script", string=re.compile(r"AF_initDataCallback"))

        for script in scripts:
            try:
                # Extract JSON data from AF_initDataCallback
                match = re.search(r'AF_initDataCallback\({[^}]*key:\s*\'([^\']+)\'[^}]*data:([^}]+)\}\);', script.string)
                if match:
                    json_str = match.group(2)
                    # Try to parse as JSON
                    try:
                        data = json.loads(json_str)
                        apps_from_json = self._extract_apps_from_json(data, country_code)
                        if apps_from_json:
                            games.extend(apps_from_json)
                    except json.JSONDecodeError:
                        continue
            except Exception as e:
                continue

        # Method 2: Extract from visible HTML elements (fallback)
        if not games:
            games = self._parse_html_elements(soup, country_code)

        # Assign ranks
        for idx, game in enumerate(games, 1):
            game.rank = idx

        return games

    def _extract_apps_from_json(self, data, country_code: str) -> List[GameApp]:
        """Extract app information from JSON data structure"""
        apps = []

        def extract_apps_recursive(obj, depth=0):
            if depth > 10:  # Prevent infinite recursion
                return

            if isinstance(obj, dict):
                # Check if this looks like an app object
                if 'title' in obj and ('packageName' in obj or 'appId' in obj):
                    try:
                        app = GameApp(
                            rank=0,  # Will be set later
                            title=obj.get('title', 'Unknown'),
                            publisher=obj.get('developer', obj.get('author', 'Unknown')),
                            package_id=obj.get('packageName', obj.get('appId')),
                            app_url=obj.get('url'),
                            icon_url=obj.get('icon')
                        )
                        apps.append(app)
                    except:
                        pass

                # Recurse into dict values
                for value in obj.values():
                    extract_apps_recursive(value, depth + 1)

            elif isinstance(obj, list):
                # Recurse into list items
                for item in obj:
                    extract_apps_recursive(item, depth + 1)

        extract_apps_recursive(data)
        return apps

    def _parse_html_elements(self, soup: BeautifulSoup, country_code: str) -> List[GameApp]:
        """Parse visible HTML elements as fallback"""
        apps = []

        # Try to find app cards/links
        app_links = soup.find_all('a', href=re.compile(r'/store/apps/details\?id='))

        seen_packages = set()

        for link in app_links[:TOP_N_RANKS]:
            try:
                # Extract package ID from URL
                href = link.get('href', '')
                match = re.search(r'id=([^&]+)', href)
                if not match:
                    continue

                package_id = match.group(1)

                if package_id in seen_packages:
                    continue
                seen_packages.add(package_id)

                # Extract title (usually in nested div or span)
                title_elem = link.find('span') or link.find('div')
                title = title_elem.get_text(strip=True) if title_elem else package_id

                app = GameApp(
                    rank=0,  # Will be set later
                    title=title,
                    publisher="Unknown",  # Hard to extract from HTML
                    package_id=package_id,
                    app_url=f"https://play.google.com{href}",
                    icon_url=None
                )
                apps.append(app)

            except Exception as e:
                continue

        return apps

    def collect_all_countries(self) -> List[CrawlResult]:
        """Collect ranking data for all configured countries"""
        results = []

        for country_code in COUNTRIES.keys():
            result = self.collect_country(country_code)
            results.append(result)

            # Delay between countries
            if len(results) < len(COUNTRIES):
                time.sleep(2)

        return results
