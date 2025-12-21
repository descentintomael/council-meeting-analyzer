#!/usr/bin/env python3
"""Run speaker diarization on transcribed meetings."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from council_analyzer.diarization import diarize_meeting
from council_analyzer.database import init_database

console = Console()


def main():
    """Run diarization on specified meeting or all transcribed meetings."""
    console.print("=" * 50)
    console.print("[bold cyan]Council Meeting Speaker Diarization[/bold cyan]")
    console.print("=" * 50)
    console.print()

    init_database()

    if len(sys.argv) > 1:
        clip_id = int(sys.argv[1])
        console.print(f"Diarizing meeting {clip_id}...")
        result = diarize_meeting(clip_id)
        if result:
            console.print(f"\n[green]Successfully diarized meeting {clip_id}[/green]")
        else:
            console.print(f"\n[red]Failed to diarize meeting {clip_id}[/red]")
            sys.exit(1)
    else:
        console.print("Usage: python scripts/run_diarize.py <clip_id>")
        console.print("Example: python scripts/run_diarize.py 1244")


if __name__ == "__main__":
    main()
