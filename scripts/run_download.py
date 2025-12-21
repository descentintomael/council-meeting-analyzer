#!/usr/bin/env python3
"""Download pending meeting audio."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from council_analyzer.config import ensure_directories
from council_analyzer.database import init_database, get_processing_stats
from council_analyzer.downloader import download_batch, get_pending_downloads


def main(batch_size: int = 10):
    """Download pending meeting audio."""
    print("=" * 50)
    print("Council Meeting Audio Download")
    print("=" * 50)
    print()

    # Setup
    ensure_directories()
    init_database()

    # Check pending
    pending = get_pending_downloads()
    print(f"Meetings pending download: {len(pending)}")

    if not pending:
        print("Nothing to download!")
        return

    # Download
    print(f"Downloading batch of {min(batch_size, len(pending))}...")
    print()

    stats = download_batch(batch_size=batch_size)

    # Show status
    print()
    print("Current status:")
    db_stats = get_processing_stats()
    for status, count in db_stats.get("by_status", {}).items():
        print(f"  {status}: {count}")


if __name__ == "__main__":
    batch_size = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    main(batch_size)
