"""Sample Real Data Collector - Uses actual ranking data for testing"""
from typing import List
from datetime import datetime

from ..models import GameApp, RankingSnapshot, CrawlResult
from ..config import COUNTRIES, TOP_N_RANKS

# Real data from 2026-01-20
REAL_DATA = {
    "JP": [
        ("Fate/Grand Order", "Aniplex"),
        ("Monster Strike", "MIXI"),
        ("Puzzle & Dragons", "GungHo"),
        ("Dragon Quest Walk", "Square Enix"),
        ("Uma Musume Pretty Derby", "Cygames"),
        ("Pokémon TCG Pocket", "The Pokémon Company"),
        ("Yu-Gi-Oh! Master Duel", "KONAMI"),
        ("Genshin Impact", "HoYoverse"),
        ("Princess Connect! Re:Dive", "Cygames"),
        ("Blue Archive", "Yostar"),
        ("Granblue Fantasy", "Cygames"),
        ("One Piece Treasure Cruise", "Bandai Namco"),
        ("Summoners War", "Com2uS"),
        ("Lineage M", "NCSOFT"),
        ("Last War: Survival Game", "FUNFLY"),
        ("Whiteout Survival", "Century Games"),
        ("승리의 여신: 니케", "Level Infinite"),
        ("Pokémon GO", "Niantic"),
        ("Fire Emblem Heroes", "Nintendo"),
        ("Call of Duty: Mobile", "Activision"),
    ],
    "US": [
        ("MONOPOLY GO!", "Scopely"),
        ("Royal Match", "Dream Games"),
        ("Candy Crush Saga", "King"),
        ("Coin Master", "Moon Active"),
        ("Roblox", "Roblox Corporation"),
        ("Last War: Survival Game", "FUNFLY"),
        ("Whiteout Survival", "Century Games"),
        ("Genshin Impact", "HoYoverse"),
        ("Lords Mobile", "IGG"),
        ("Pokémon GO", "Niantic"),
        ("Clash of Clans", "Supercell"),
        ("Call of Duty: Mobile", "Activision"),
        ("Township", "Playrix"),
        ("Gardenscapes", "Playrix"),
        ("Homescapes", "Playrix"),
        ("Marvel Contest of Champions", "Kabam"),
        ("PUBG Mobile", "Tencent"),
        ("State of Survival", "FunPlus"),
        ("RAID: Shadow Legends", "Plarium"),
        ("Brawl Stars", "Supercell"),
    ],
    "TW": [
        ("Lineage M", "NCSOFT"),
        ("Lineage W", "NCSOFT"),
        ("Ragnarok X: Next Generation", "Gravity"),
        ("Garena 傳說對決", "Garena"),
        ("Fate/Grand Order", "Aniplex"),
        ("Pokémon TCG Pocket", "The Pokémon Company"),
        ("SD Gundam G Generation ETERNAL", "Bandai Namco"),
        ("World of Tanks Blitz", "Wargaming"),
        ("Summoners War", "Com2uS"),
        ("승리의 여신: 니케", "Level Infinite"),
        ("Genshin Impact", "HoYoverse"),
        ("Last War: Survival Game", "FUNFLY"),
        ("Whiteout Survival", "Century Games"),
        ("MapleStory M", "NEXON"),
        ("MU Origin 3", "Webzen"),
        ("Black Desert Mobile", "Pearl Abyss"),
        ("Call of Duty: Mobile", "Activision"),
        ("Dragon Raja", "Archosaur Games"),
        ("AFK Arena", "Lilith Games"),
        ("Rise of Kingdoms", "Lilith Games"),
    ],
    "KR": [
        ("메이플스토리: 아이들 RPG", "넥슨"),
        ("라스트 워: 서바이벌 게임", "FUNFLY"),
        ("화이트아웃 서바이벌", "Century Games"),
        ("라스트 Z: 서바이벌 슈터", "Florere Game"),
        ("원신", "호요버스"),
        ("로블록스", "Roblox Corporation"),
        ("로얄 매치", "Dream Games"),
        ("킹샷", "Century Games"),
        ("리니지M", "엔씨소프트"),
        ("명조: 워더링 웨이브", "쿠로 게임즈"),
        ("가십 하버: 머지 & 스토리", "Microfun"),
        ("오딘: 발할라 라이징", "카카오게임즈"),
        ("승리의 여신: 니케", "레벨 인피니트"),
        ("마비노기 모바일", "넥슨"),
        ("다크 워 서바이벌", "Florere Game"),
        ("드래곤 트래블러", "GameTree"),
        ("FC 모바일", "넥슨"),
        ("뱀피르", "넷마블"),
        ("탑 히어로즈: 킹덤 사가", "RiverGame"),
        ("아이온2", "엔씨소프트"),
    ]
}

class SampleRealCollector:
    """Collector using real ranking data samples"""

    def collect_country(self, country_code: str) -> CrawlResult:
        """Generate snapshot from real data"""
        if country_code not in COUNTRIES:
            return CrawlResult(
                success=False,
                country_code=country_code,
                error=f"Unknown country code: {country_code}"
            )

        country = COUNTRIES[country_code]
        data = REAL_DATA.get(country_code, [])

        print(f"[{country_code}] Using real sample data for {country.name}...")

        games = []
        for rank, (title, publisher) in enumerate(data[:TOP_N_RANKS], 1):
            package_id = f"com.{publisher.lower().replace(' ', '')}.{title.lower().replace(' ', '')[:10]}"
            game = GameApp(
                rank=rank,
                title=title,
                publisher=publisher,
                package_id=package_id,
                app_url=f"https://play.google.com/store/apps/details?id={package_id}",
                icon_url=None
            )
            games.append(game)

        now = datetime.utcnow()
        snapshot = RankingSnapshot(
            country_code=country_code,
            country_name=country.name,
            date=now.strftime("%Y-%m-%d"),
            timestamp=now.isoformat(),
            games=games
        )

        print(f"[{country_code}] ✓ Generated {len(games)} games from real data")
        return CrawlResult(
            success=True,
            country_code=country_code,
            snapshot=snapshot
        )

    def collect_all_countries(self) -> List[CrawlResult]:
        """Collect all countries using real data"""
        results = []
        for country_code in COUNTRIES.keys():
            result = self.collect_country(country_code)
            results.append(result)
        return results
