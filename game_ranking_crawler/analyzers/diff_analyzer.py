"""Analyzer for comparing ranking changes"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from ..models import RankingSnapshot, GameApp

@dataclass
class GameDiff:
    """Represents a game's ranking change"""
    game: GameApp
    previous_rank: Optional[int] = None
    rank_change: Optional[int] = None  # Positive = moved up, Negative = moved down
    is_new: bool = False
    is_dropped: bool = False

@dataclass
class MarketInsight:
    """Market insights for a country"""
    country_code: str
    volatility: str  # "high", "medium", "low"
    new_entries: int
    dropped_games: int
    top_movers: List[Tuple[str, int]]  # [(game_title, rank_change), ...]
    stability_top5: float  # 0-1, how stable are top 5 positions

class DiffAnalyzer:
    """Analyzes differences between ranking snapshots"""

    @staticmethod
    def compare_snapshots(
        current: RankingSnapshot,
        previous: Optional[RankingSnapshot]
    ) -> Tuple[List[GameDiff], MarketInsight]:
        """
        Compare current snapshot with previous to find changes

        Args:
            current: Today's snapshot
            previous: Yesterday's snapshot (None if first run)

        Returns:
            Tuple of (game_diffs, market_insight)
        """
        if not previous:
            # First run - no comparison
            diffs = [
                GameDiff(game=game, is_new=True)
                for game in current.games
            ]
            insight = MarketInsight(
                country_code=current.country_code,
                volatility="unknown",
                new_entries=0,
                dropped_games=0,
                top_movers=[],
                stability_top5=1.0
            )
            return diffs, insight

        # Build lookup maps
        current_map = {
            game.package_id or game.title: (game, game.rank)
            for game in current.games
        }
        previous_map = {
            game.package_id or game.title: (game, game.rank)
            for game in previous.games
        }

        diffs = []
        new_entries = 0
        dropped_games = 0
        rank_movements = []

        # Analyze current games
        for game in current.games:
            key = game.package_id or game.title

            if key in previous_map:
                _, prev_rank = previous_map[key]
                rank_change = prev_rank - game.rank  # Positive = moved up
                diffs.append(GameDiff(
                    game=game,
                    previous_rank=prev_rank,
                    rank_change=rank_change
                ))
                rank_movements.append(abs(rank_change))
            else:
                # New entry
                diffs.append(GameDiff(game=game, is_new=True))
                new_entries += 1

        # Find dropped games (in previous but not in current)
        for key, (prev_game, _) in previous_map.items():
            if key not in current_map:
                dropped_games += 1

        # Calculate metrics
        top_movers = sorted(
            [(d.game.title, d.rank_change) for d in diffs if d.rank_change],
            key=lambda x: abs(x[1]),
            reverse=True
        )[:3]

        # Volatility based on total movement
        total_movement = sum(rank_movements)
        if total_movement > 50:
            volatility = "high"
        elif total_movement > 20:
            volatility = "medium"
        else:
            volatility = "low"

        # Top 5 stability
        top5_current = set([g.package_id or g.title for g in current.games[:5]])
        top5_previous = set([g.package_id or g.title for g in previous.games[:5]])
        stability_top5 = len(top5_current & top5_previous) / 5.0

        insight = MarketInsight(
            country_code=current.country_code,
            volatility=volatility,
            new_entries=new_entries,
            dropped_games=dropped_games,
            top_movers=top_movers,
            stability_top5=stability_top5
        )

        return diffs, insight

    @staticmethod
    def find_global_hits(snapshots: List[RankingSnapshot], top_n: int = 10) -> List[str]:
        """
        Find games that appear in top N of all countries

        Args:
            snapshots: List of snapshots for all countries
            top_n: Top N positions to consider

        Returns:
            List of game titles that appear in all countries
        """
        if not snapshots:
            return []

        # Get top N from each country
        top_games_per_country = []
        for snapshot in snapshots:
            top_titles = set([
                game.package_id or game.title
                for game in snapshot.games[:top_n]
            ])
            top_games_per_country.append(top_titles)

        # Find intersection
        if not top_games_per_country:
            return []

        common_games = top_games_per_country[0]
        for games in top_games_per_country[1:]:
            common_games = common_games & games

        # Get actual titles
        result = []
        for snapshot in snapshots:
            for game in snapshot.games[:top_n]:
                key = game.package_id or game.title
                if key in common_games and game.title not in result:
                    result.append(game.title)

        return result
