"""Dummy Collector - Generates fake game data for testing"""
import time
import random
from typing import List
from datetime import datetime

from ..models import GameApp, RankingSnapshot, CrawlResult
from ..config import COUNTRIES, TOP_N_RANKS

# Popular game titles for dummy data
GAME_TITLES = {
    "KR": [
        "리니지M", "바람의나라: 연", "V4", "검은사막 모바일", "페이트/그랜드 오더",
        "배틀그라운드 모바일", "리그 오브 레전드: 와일드 리프트", "쿠키런: 킹덤",
        "카카오프렌즈 사가", "프로야구 H3", "이터널 리턴", "로스트아크", "던전앤파이터 모바일",
        "메이플스토리M", "세븐나이츠2", "블레이드&소울 레볼루션", "원신", "붕괴: 스타레일",
        "니케", "카운터사이드", "블루 아카이브", "워크래프트 럼블", "FC 모바일", "스타크래프트"
    ],
    "JP": [
        "ウマ娘 プリティーダービー", "モンスターストライク", "プロ野球スピリッツA", "パズル&ドラゴンズ",
        "Fate/Grand Order", "原神", "荒野行動", "ドラゴンクエストウォーク", "ポケモンGO",
        "NIKKE", "ブルーアーカイブ", "プリンセスコネクト！Re:Dive", "グランブルーファンタジー",
        "Identity V", "バンドリ！ガールズバンドパーティ！", "プロジェクトセカイ", "Heaven Burns Red",
        "崩壊：スターレイル", "リバース：1999", "アークナイツ", "放置少女", "三国志", "FFⅦ", "DQM"
    ],
    "US": [
        "Candy Crush Saga", "Roblox", "Coin Master", "Pokemon GO", "Gardenscapes",
        "Homescapes", "Royal Match", "Monopoly GO!", "Clash of Clans", "Clash Royale",
        "PUBG Mobile", "Call of Duty Mobile", "Genshin Impact", "Honkai Star Rail",
        "Marvel Snap", "Raid: Shadow Legends", "Lords Mobile", "AFK Arena", "Rise of Kingdoms",
        "State of Survival", "Evony", "Diablo Immortal", "Game of Thrones", "FC Mobile"
    ],
    "TW": [
        "天堂M", "天堂2M", "劍靈：革命", "黑色沙漠 MOBILE", "原神",
        "崩壞：星穹鐵道", "勝利女神：NIKKE", "碧藍檔案", "明日方舟", "反向：1999",
        "絕區零", "第五人格", "傳說對決", "決勝時刻M", "PUBG MOBILE",
        "英雄聯盟：激鬥峽谷", "寶可夢大集結", "部落衝突", "皇室戰爭", "糖果傳奇",
        "三國志·戰略版", "放置少女", "魔靈召喚", "FC MOBILE"
    ]
}

PUBLISHERS = {
    "KR": ["NCSOFT", "Netmarble", "Nexon", "Krafton", "Pearl Abyss", "Com2uS", "GameVil", "Kakao Games"],
    "JP": ["Cygames", "miHoYo", "Square Enix", "Bandai Namco", "NetEase", "GungHo", "Aniplex", "SEGA"],
    "US": ["King", "Roblox Corp", "Niantic", "Supercell", "Activision", "Epic Games", "EA", "Zynga"],
    "TW": ["NCSOFT", "miHoYo", "Garena", "Activision", "Supercell", "NetEase", "Tencent", "Lilith"]
}

class DummyCollector:
    """Generates dummy game ranking data for testing"""

    def __init__(self, add_variance: bool = True):
        """
        Args:
            add_variance: If True, adds random variance to rankings
        """
        self.add_variance = add_variance
        random.seed()  # Use current time for randomness

    def collect_country(self, country_code: str) -> CrawlResult:
        """
        Generate dummy ranking data for a specific country

        Args:
            country_code: Country code (KR, JP, US, TW)

        Returns:
            CrawlResult with dummy snapshot data
        """
        if country_code not in COUNTRIES:
            return CrawlResult(
                success=False,
                country_code=country_code,
                error=f"Unknown country code: {country_code}"
            )

        country = COUNTRIES[country_code]

        print(f"[{country_code}] Generating dummy data for {country.name}...")

        # Get game titles for this country
        titles = GAME_TITLES.get(country_code, GAME_TITLES["US"])
        publishers = PUBLISHERS.get(country_code, PUBLISHERS["US"])

        # Shuffle if variance is enabled
        if self.add_variance:
            titles = titles.copy()
            random.shuffle(titles)

        # Generate games
        games = []
        for rank in range(1, TOP_N_RANKS + 1):
            if rank <= len(titles):
                title = titles[rank - 1]
                publisher = random.choice(publishers)
                package_id = f"com.{publisher.lower().replace(' ', '')}.game{rank}"

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

        print(f"[{country_code}] ✓ Generated {len(games)} dummy games")
        return CrawlResult(
            success=True,
            country_code=country_code,
            snapshot=snapshot
        )

    def collect_all_countries(self) -> List[CrawlResult]:
        """Generate dummy ranking data for all configured countries"""
        results = []

        for country_code in COUNTRIES.keys():
            result = self.collect_country(country_code)
            results.append(result)

            # Small delay to simulate real crawling
            time.sleep(0.5)

        return results
