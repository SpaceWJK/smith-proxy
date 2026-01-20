"""Data models for Game Ranking Crawler"""
from dataclasses import dataclass, asdict
from typing import Optional, List
from datetime import datetime

@dataclass
class GameApp:
    """Represents a single game app"""
    rank: int
    title: str
    publisher: str
    package_id: Optional[str] = None
    app_url: Optional[str] = None
    icon_url: Optional[str] = None

    def to_dict(self):
        """Convert to dictionary"""
        return asdict(self)

@dataclass
class RankingSnapshot:
    """Represents a ranking snapshot for a country"""
    country_code: str
    country_name: str
    date: str  # YYYY-MM-DD format
    timestamp: str  # ISO format
    games: List[GameApp]

    def to_dict(self):
        """Convert to dictionary"""
        return {
            "country_code": self.country_code,
            "country_name": self.country_name,
            "date": self.date,
            "timestamp": self.timestamp,
            "games": [game.to_dict() for game in self.games]
        }

    @classmethod
    def from_dict(cls, data: dict):
        """Create from dictionary"""
        games = [GameApp(**game) for game in data.get("games", [])]
        return cls(
            country_code=data["country_code"],
            country_name=data["country_name"],
            date=data["date"],
            timestamp=data["timestamp"],
            games=games
        )

@dataclass
class CrawlResult:
    """Result of a crawling operation"""
    success: bool
    country_code: str
    snapshot: Optional[RankingSnapshot] = None
    error: Optional[str] = None
