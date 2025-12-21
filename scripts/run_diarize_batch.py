#!/usr/bin/env python3
"""Run speaker diarization on all transcribed meetings."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from council_analyzer.diarization import diarize_meeting
from council_analyzer.database import init_database, get_meetings_by_status
from council_analyzer.config import config

console = Console()


def main():
    """Run diarization on all transcribed/validated/analyzed meetings."""
    console.print("=" * 50)
    console.print("[bold cyan]Batch Speaker Diarization[/bold cyan]")
    console.print("=" * 50)
    console.print()

    init_database()

    # Get all meetings that have been transcribed (or further along)
    statuses = ["transcribed", "validated", "analyzed"]
    meetings = []
    for status in statuses:
        meetings.extend(get_meetings_by_status(status))

    # Filter out already diarized meetings
    pending = []
    for meeting in meetings:
        clip_id = meeting["clip_id"]
        diarization_path = config.TRANSCRIPT_DIR / f"{clip_id}_diarization.json"
        if not diarization_path.exists():
            pending.append(meeting)

    if not pending:
        console.print("[yellow]No meetings pending diarization[/yellow]")
        return

    console.print(f"[bold]Found {len(pending)} meetings to diarize[/bold]")
    console.print()

    stats = {"success": 0, "failed": 0}

    for meeting in pending:
        clip_id = meeting["clip_id"]
        console.print(f"\n[cyan]Diarizing {clip_id}: {meeting['title']}[/cyan]")

        result = diarize_meeting(clip_id)
        if result:
            stats["success"] += 1
            console.print(f"[green]✓ Diarized {clip_id}[/green]")
        else:
            stats["failed"] += 1
            console.print(f"[red]✗ Failed to diarize {clip_id}[/red]")

    console.print()
    console.print("[bold green]Batch diarization complete![/bold green]")
    console.print(f"  Success: {stats['success']}")
    console.print(f"  Failed: {stats['failed']}")


if __name__ == "__main__":
    main()
