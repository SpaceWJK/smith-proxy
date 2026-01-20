"""Test script to verify crawler functionality"""
import sys
import os

# Add game_ranking_crawler to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game_ranking_crawler.collectors.dummy_collector import DummyCollector

def test_single_country():
    """Test crawling a single country"""
    collector = DummyCollector()

    print("Testing Korea (KR) crawler...")
    result = collector.collect_country("KR")

    if result.success and result.snapshot:
        print(f"\n✓ Success! Collected {len(result.snapshot.games)} games")
        print("\nTop 5 games:")
        for game in result.snapshot.games[:5]:
            print(f"  {game.rank}. {game.title} ({game.publisher})")
    else:
        print(f"\n✗ Failed: {result.error}")

if __name__ == "__main__":
    test_single_country()
