#!/usr/bin/env python3
"""Check pipeline status."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from council_analyzer.config import ensure_directories
from council_analyzer.database import init_database
from council_analyzer.pipeline import print_status


def main():
    """Print pipeline status."""
    ensure_directories()
    init_database()
    print_status()


if __name__ == "__main__":
    main()
