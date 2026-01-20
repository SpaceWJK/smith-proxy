"""Main pipeline for Game Ranking Crawler"""
import sys
import os
from datetime import datetime
from typing import List

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game_ranking_crawler.collectors.dummy_collector import DummyCollector
from game_ranking_crawler.collectors.claude_api_collector import ClaudeAPICollector
from game_ranking_crawler.storage.json_storage import JSONStorage
from game_ranking_crawler.notifiers.slack_notifier import SlackNotifier
from game_ranking_crawler.models import RankingSnapshot, CrawlResult
from game_ranking_crawler.config import COUNTRIES, SLACK_WEBHOOK_URL, ANTHROPIC_API_KEY

def run_daily_crawl():
    """
    Main pipeline: Crawl -> Store -> Notify

    Steps:
    1. Crawl all countries (KR, JP, US, TW)
    2. Save snapshots to JSON files
    3. Send Slack notification with results
    """
    print("=" * 60)
    print(f"🚀 Game Ranking Crawler Started - {datetime.utcnow().isoformat()}")
    print("=" * 60)

    # Initialize components
    # Choose collector based on environment
    use_claude_api = os.getenv("USE_CLAUDE_API", "").lower() == "true" or bool(ANTHROPIC_API_KEY)

    if use_claude_api and ANTHROPIC_API_KEY:
        print("🤖 Using Claude API collector (real data via LLM)")
        collector = ClaudeAPICollector()
    else:
        print("🎲 Using dummy collector (test data)")
        if not ANTHROPIC_API_KEY:
            print("💡 Tip: Set ANTHROPIC_API_KEY to use real data collection")
        collector = DummyCollector()

    storage = JSONStorage()

    # Step 1: Crawl all countries
    print("\n📡 Step 1: Crawling game rankings...")
    print("-" * 60)

    results: List[CrawlResult] = collector.collect_all_countries()

    # Check results
    successful_snapshots: List[RankingSnapshot] = []
    errors: List[str] = []

    for result in results:
        if result.success and result.snapshot:
            successful_snapshots.append(result.snapshot)
            print(f"✓ {result.country_code}: {len(result.snapshot.games)} games collected")
        else:
            error_msg = f"✗ {result.country_code}: {result.error}"
            errors.append(error_msg)
            print(error_msg)

    # Step 2: Save snapshots
    print("\n💾 Step 2: Saving snapshots...")
    print("-" * 60)

    for snapshot in successful_snapshots:
        try:
            file_path = storage.save_snapshot(snapshot)
            print(f"✓ {snapshot.country_code}: Saved to {file_path}")
        except Exception as e:
            error_msg = f"Failed to save {snapshot.country_code}: {e}"
            errors.append(error_msg)
            print(f"✗ {error_msg}")

    # Step 3: Send Slack notification
    print("\n📨 Step 3: Sending Slack notification...")
    print("-" * 60)

    if not SLACK_WEBHOOK_URL:
        print("⚠️  Slack webhook URL not configured. Skipping notification.")
        print("   Set SLACK_WEBHOOK_URL environment variable to enable Slack notifications.")
    else:
        try:
            notifier = SlackNotifier()

            if successful_snapshots:
                success = notifier.send_daily_report(successful_snapshots)
                if success:
                    print("✓ Slack notification sent successfully")
                else:
                    print("✗ Failed to send Slack notification")

            # Send error notification if there were any errors
            if errors:
                notifier.send_error_notification(errors)

        except Exception as e:
            print(f"✗ Slack notification error: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("📊 Summary")
    print("=" * 60)
    print(f"✓ Successful: {len(successful_snapshots)}/{len(COUNTRIES)} countries")
    if errors:
        print(f"✗ Errors: {len(errors)}")
        for error in errors:
            print(f"  - {error}")
    print("=" * 60)

    # Exit with error code if any country failed
    if len(successful_snapshots) < len(COUNTRIES):
        sys.exit(1)

    print("\n✅ Pipeline completed successfully!\n")

def main():
    """Entry point"""
    try:
        run_daily_crawl()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
