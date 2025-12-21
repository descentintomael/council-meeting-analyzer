#!/usr/bin/env python3
"""Transcribe pending audio files with dual-model validation."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from council_analyzer.config import ensure_directories
from council_analyzer.database import init_database, get_processing_stats
from council_analyzer.transcriber import transcribe_batch, get_pending_transcriptions


def main(batch_size: int = 3):
    """Transcribe pending audio files."""
    print("=" * 50)
    print("Council Meeting Transcription")
    print("=" * 50)
    print()

    # Setup
    ensure_directories()
    init_database()

    # Check pending
    pending = get_pending_transcriptions()
    print(f"Meetings pending transcription: {len(pending)}")

    if not pending:
        print("Nothing to transcribe!")
        return

    # Transcribe
    print(f"Transcribing batch of {min(batch_size, len(pending))}...")
    print("Using dual-model transcription (large-v3 + medium)")
    print()

    stats = transcribe_batch(batch_size=batch_size, dual_model=True)

    # Show status
    print()
    print("Current status:")
    db_stats = get_processing_stats()
    for status, count in db_stats.get("by_status", {}).items():
        print(f"  {status}: {count}")


if __name__ == "__main__":
    batch_size = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    main(batch_size)
