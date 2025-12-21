#!/usr/bin/env python3
"""Discover meetings from Granicus."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from council_analyzer.config import config, ensure_directories
from council_analyzer.database import init_database, get_processing_stats
from council_analyzer.discovery import run_discovery


def main():
    """Run meeting discovery."""
    print("=" * 50)
    print("Council Meeting Discovery")
    print("=" * 50)
    print()

    # Setup
    ensure_directories()
    init_database()

    # Run discovery
    print(f"Scanning clip IDs {config.CLIP_ID_START} to {config.CLIP_ID_END}...")
    print()

    stats = asyncio.run(run_discovery())

    # Show current state
    print()
    print("Current database status:")
    db_stats = get_processing_stats()
    for status, count in db_stats.get("by_status", {}).items():
        print(f"  {status}: {count}")


if __name__ == "__main__":
    main()
