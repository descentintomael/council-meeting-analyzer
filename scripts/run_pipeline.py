#!/usr/bin/env python3
"""Run the full council meeting analysis pipeline."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from council_analyzer.pipeline import run_full_pipeline, print_status


def main():
    """Run the complete pipeline."""
    print("=" * 50)
    print("Council Meeting Analysis Pipeline")
    print("=" * 50)
    print()

    # Check for flags
    args = sys.argv[1:]

    skip_discovery = "--skip-discovery" in args
    skip_download = "--skip-download" in args
    skip_transcribe = "--skip-transcribe" in args
    skip_validate = "--skip-validate" in args
    skip_analyze = "--skip-analyze" in args
    skip_reports = "--skip-reports" in args
    status_only = "--status" in args

    if status_only:
        print_status()
        return

    # Run pipeline
    result = run_full_pipeline(
        skip_discovery=skip_discovery,
        skip_download=skip_download,
        skip_transcribe=skip_transcribe,
        skip_validate=skip_validate,
        skip_analyze=skip_analyze,
        skip_reports=skip_reports,
    )

    # Print errors if any
    if result.errors:
        print()
        print("Errors encountered:")
        for error in result.errors:
            print(f"  - {error}")


if __name__ == "__main__":
    main()
