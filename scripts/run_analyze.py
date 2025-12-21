#!/usr/bin/env python3
"""Analyze validated transcripts with LLM."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from council_analyzer.config import ensure_directories
from council_analyzer.database import init_database, get_processing_stats, get_meetings_by_status
from council_analyzer.analyzer import analyze_batch


def main(batch_size: int = 1):
    """Analyze validated transcripts."""
    print("=" * 50)
    print("Council Meeting Analysis")
    print("=" * 50)
    print()

    # Setup
    ensure_directories()
    init_database()

    # Check pending
    pending = get_meetings_by_status("validated")
    print(f"Meetings pending analysis: {len(pending)}")

    if not pending:
        print("Nothing to analyze!")
        return

    # Analyze
    print(f"Analyzing batch of {min(batch_size, len(pending))}...")
    print("Using qwen2.5vl:72b for analysis")
    print()

    stats = analyze_batch(batch_size=batch_size)

    # Show status
    print()
    print("Current status:")
    db_stats = get_processing_stats()
    for status, count in db_stats.get("by_status", {}).items():
        print(f"  {status}: {count}")


if __name__ == "__main__":
    batch_size = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    main(batch_size)
