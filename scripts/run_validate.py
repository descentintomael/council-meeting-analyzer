#!/usr/bin/env python3
"""Validate transcriptions using two-tier LLM validation."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from council_analyzer.config import ensure_directories
from council_analyzer.database import init_database, get_processing_stats, get_meetings_by_status
from council_analyzer.validator import validate_batch


def main(batch_size: int = 5):
    """Validate pending transcriptions."""
    print("=" * 50)
    print("Council Meeting Transcription Validation")
    print("=" * 50)
    print()

    # Setup
    ensure_directories()
    init_database()

    # Check pending
    pending = get_meetings_by_status("transcribed")
    print(f"Meetings pending validation: {len(pending)}")

    if not pending:
        print("Nothing to validate!")
        return

    # Validate
    print(f"Validating batch of {min(batch_size, len(pending))}...")
    print("Using two-tier validation (mistral + deepseek-r1)")
    print()

    stats = validate_batch(batch_size=batch_size)

    # Show status
    print()
    print("Current status:")
    db_stats = get_processing_stats()
    for status, count in db_stats.get("by_status", {}).items():
        print(f"  {status}: {count}")


if __name__ == "__main__":
    batch_size = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    main(batch_size)
