"""JSON-based storage for game ranking snapshots"""
import json
import os
from pathlib import Path
from typing import Optional
from datetime import datetime

from ..models import RankingSnapshot

class JSONStorage:
    """Simple JSON file storage for ranking snapshots"""

    def __init__(self, base_dir: str = "snapshots"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)

    def save_snapshot(self, snapshot: RankingSnapshot) -> str:
        """
        Save a ranking snapshot to JSON file

        File structure: snapshots/{YYYY-MM-DD}/{country_code}.json

        Returns:
            Path to saved file
        """
        date_dir = self.base_dir / snapshot.date
        date_dir.mkdir(exist_ok=True)

        file_path = date_dir / f"{snapshot.country_code}.json"

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(snapshot.to_dict(), f, indent=2, ensure_ascii=False)

        print(f"[Storage] Saved snapshot: {file_path}")
        return str(file_path)

    def load_snapshot(self, country_code: str, date: Optional[str] = None) -> Optional[RankingSnapshot]:
        """
        Load a ranking snapshot from JSON file

        Args:
            country_code: Country code (KR, JP, US, TW)
            date: Date in YYYY-MM-DD format (defaults to today)

        Returns:
            RankingSnapshot if found, None otherwise
        """
        if date is None:
            date = datetime.utcnow().strftime("%Y-%m-%d")

        file_path = self.base_dir / date / f"{country_code}.json"

        if not file_path.exists():
            return None

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return RankingSnapshot.from_dict(data)

    def get_latest_snapshot(self, country_code: str) -> Optional[RankingSnapshot]:
        """Get the most recent snapshot for a country"""
        if not self.base_dir.exists():
            return None

        # Find all date directories
        date_dirs = sorted([d for d in self.base_dir.iterdir() if d.is_dir()], reverse=True)

        for date_dir in date_dirs:
            file_path = date_dir / f"{country_code}.json"
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return RankingSnapshot.from_dict(data)

        return None

    def get_previous_snapshot(self, country_code: str, current_date: str) -> Optional[RankingSnapshot]:
        """Get the snapshot from the day before current_date"""
        if not self.base_dir.exists():
            return None

        # Find all date directories before current_date
        date_dirs = sorted([
            d for d in self.base_dir.iterdir()
            if d.is_dir() and d.name < current_date
        ], reverse=True)

        for date_dir in date_dirs:
            file_path = date_dir / f"{country_code}.json"
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return RankingSnapshot.from_dict(data)

        return None
