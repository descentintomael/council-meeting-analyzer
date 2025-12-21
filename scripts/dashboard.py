#!/usr/bin/env python3
"""Real-time dashboard for monitoring the council meeting analysis pipeline."""

import sys
import time
import argparse
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.columns import Columns
from rich.console import Group
from rich.text import Text
from rich import box

from council_analyzer.database import init_database, get_processing_stats, get_meetings_by_status
from council_analyzer.config import config


console = Console()


def get_disk_usage():
    """Get disk usage for data directories."""
    usage = {}

    if config.AUDIO_DIR.exists():
        audio_size = sum(f.stat().st_size for f in config.AUDIO_DIR.glob("*") if f.is_file())
        usage["audio"] = audio_size / (1024 * 1024 * 1024)  # GB
    else:
        usage["audio"] = 0

    if config.TRANSCRIPT_DIR.exists():
        transcript_size = sum(f.stat().st_size for f in config.TRANSCRIPT_DIR.glob("*") if f.is_file())
        usage["transcripts"] = transcript_size / (1024 * 1024)  # MB
    else:
        usage["transcripts"] = 0

    if config.DB_PATH.exists():
        usage["database"] = config.DB_PATH.stat().st_size / (1024 * 1024)  # MB
    else:
        usage["database"] = 0

    return usage


def get_recent_meetings(status: str, limit: int = 5):
    """Get recent meetings with a given status."""
    meetings = get_meetings_by_status(status)
    return meetings[:limit]


def create_status_table(stats: dict) -> Table:
    """Create the main status table."""
    table = Table(
        title="Pipeline Status",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )

    table.add_column("Stage", style="bold")
    table.add_column("Count", justify="right")
    table.add_column("Progress", justify="center")

    # Define stages in order
    stages = [
        ("discovered", "Discovered", "dim"),
        ("downloading", "Downloading", "yellow"),
        ("downloaded", "Downloaded", "blue"),
        ("transcribing", "Transcribing", "yellow"),
        ("transcribed", "Transcribed", "blue"),
        ("validating", "Validating", "yellow"),
        ("validated", "Validated", "green"),
        ("analyzing", "Analyzing", "yellow"),
        ("analyzed", "Analyzed", "bold green"),
        ("failed", "Failed", "red"),
    ]

    by_status = stats.get("by_status", {})
    total = stats.get("total_meetings", 0)

    for key, label, style in stages:
        count = by_status.get(key, 0)
        if count > 0:
            if total > 0:
                pct = count / total * 100
                bar_width = int(pct / 5)  # 20 chars max
                bar = "█" * bar_width + "░" * (20 - bar_width)
                progress = f"{bar} {pct:.1f}%"
            else:
                progress = ""
            table.add_row(f"[{style}]{label}[/{style}]", str(count), progress)

    return table


def create_activity_table(stats: dict) -> Table:
    """Create table showing recent activity."""
    table = Table(
        title="Recent Activity",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
    )

    table.add_column("Stage", style="bold")
    table.add_column("Meeting", style="cyan")
    table.add_column("Title")

    # Show active items (downloading, transcribing, validating, analyzing)
    active_stages = ["downloading", "transcribing", "validating", "analyzing"]

    for stage in active_stages:
        meetings = get_meetings_by_status(stage)
        for m in meetings[:2]:  # Show up to 2 per stage
            clip_id = m.get("clip_id", "?")
            title = m.get("title", "Unknown")[:40]
            if len(m.get("title", "")) > 40:
                title += "..."
            table.add_row(stage.title(), str(clip_id), title)

    if table.row_count == 0:
        table.add_row("[dim]No active tasks[/dim]", "", "")

    return table


def create_recent_completed_table() -> Table:
    """Create table showing recently completed items."""
    table = Table(
        title="Recently Completed",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold green",
    )

    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Title")
    table.add_column("Status", style="green")

    # Show recently analyzed meetings
    analyzed = get_meetings_by_status("analyzed")
    for m in analyzed[:5]:
        clip_id = m.get("clip_id", "?")
        title = m.get("title", "Unknown")[:45]
        if len(m.get("title", "")) > 45:
            title += "..."
        table.add_row(str(clip_id), title, "Analyzed")

    if table.row_count == 0:
        table.add_row("[dim]-[/dim]", "[dim]No completed analyses yet[/dim]", "")

    return table


def create_disk_usage_table() -> Table:
    """Create disk usage table."""
    usage = get_disk_usage()

    table = Table(
        title="Disk Usage",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold yellow",
    )

    table.add_column("Directory", style="bold")
    table.add_column("Size", justify="right")

    table.add_row("Audio Files", f"{usage['audio']:.2f} GB")
    table.add_row("Transcripts", f"{usage['transcripts']:.1f} MB")
    table.add_row("Database", f"{usage['database']:.1f} MB")

    return table


def create_summary_panel(stats: dict) -> Panel:
    """Create summary panel with key metrics."""
    by_status = stats.get("by_status", {})
    total = stats.get("total_meetings", 0)

    analyzed = by_status.get("analyzed", 0)
    validated = by_status.get("validated", 0)
    transcribed = by_status.get("transcribed", 0)
    downloaded = by_status.get("downloaded", 0)

    # Calculate pipeline progress
    if total > 0:
        overall_pct = analyzed / total * 100
    else:
        overall_pct = 0

    # Active counts
    active = sum([
        by_status.get("downloading", 0),
        by_status.get("transcribing", 0),
        by_status.get("validating", 0),
        by_status.get("analyzing", 0),
    ])

    text = Text()
    text.append("Total Meetings: ", style="bold")
    text.append(f"{total}\n", style="cyan")
    text.append("Fully Analyzed: ", style="bold")
    text.append(f"{analyzed}", style="green")
    text.append(f" ({overall_pct:.1f}%)\n", style="dim")
    text.append("Active Tasks: ", style="bold")
    text.append(f"{active}\n", style="yellow" if active > 0 else "dim")
    text.append("Ready for Analysis: ", style="bold")
    text.append(f"{validated}\n", style="blue")

    return Panel(text, title="Summary", border_style="cyan")


def create_dashboard():
    """Create the full dashboard as a simple printable format."""
    stats = get_processing_stats()

    # Top row: Summary + Disk Usage
    top_row = Columns([create_summary_panel(stats), create_disk_usage_table()], equal=True)

    # Status table
    status = create_status_table(stats)

    # Activity table
    activity = create_activity_table(stats)

    # Recent completed
    recent = create_recent_completed_table()

    # Header
    header = Panel(
        Text.from_markup(
            f"[bold cyan]Council Meeting Analysis Pipeline[/bold cyan]\n"
            f"[dim]Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]"
        ),
        box=box.ROUNDED,
    )

    # Return a group that can be rendered
    return Group(header, top_row, status, activity, recent)


def run_dashboard(refresh_rate: float = 5.0, once: bool = False):
    """Run the dashboard with live updates."""
    init_database(quiet=True)

    if once:
        console.print(create_dashboard())
        return

    console.print("[bold cyan]Starting pipeline dashboard...[/bold cyan]")
    console.print(f"[dim]Refreshing every {refresh_rate} seconds. Press Ctrl+C to exit.[/dim]\n")

    try:
        with Live(create_dashboard(), console=console, refresh_per_second=1) as live:
            while True:
                time.sleep(refresh_rate)
                live.update(create_dashboard())
    except KeyboardInterrupt:
        console.print("\n[dim]Dashboard stopped.[/dim]")


def main():
    parser = argparse.ArgumentParser(description="Monitor the council meeting analysis pipeline")
    parser.add_argument(
        "-r", "--refresh",
        type=float,
        default=5.0,
        help="Refresh rate in seconds (default: 5)"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Show dashboard once and exit (no live updates)"
    )

    args = parser.parse_args()
    run_dashboard(refresh_rate=args.refresh, once=args.once)


if __name__ == "__main__":
    main()
