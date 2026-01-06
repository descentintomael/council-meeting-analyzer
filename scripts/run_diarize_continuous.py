#!/usr/bin/env python3
"""Continuous speaker diarization pipeline with real-time monitoring dashboard.

Processes all analyzed meetings that don't have diarization files yet.
Uses pyannote.audio for neural speaker diarization (community-1 model).

IMPORTANT: Processing time is ~2 hours per meeting on CPU (M2 Ultra).
For 218 meetings, expect ~18 days of continuous processing.

Includes retry logic, progress tracking, and a Rich TUI dashboard.

Usage:
    python scripts/run_diarize_continuous.py           # Run pipeline with dashboard
    python scripts/run_diarize_continuous.py --once    # Show status and exit
    python scripts/run_diarize_continuous.py --max-retries 5  # Custom retry limit
"""

import argparse
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table
from rich.text import Text
from rich import box

from council_analyzer.config import config
from council_analyzer.database import (
    get_diarization_retry_count,
    get_meetings_by_status,
    init_database,
    log_processing,
)
from council_analyzer.diarization import diarize_meeting

console = Console()


@dataclass
class CompletionRecord:
    """Record of a completed diarization."""
    clip_id: int
    title: str
    elapsed_seconds: float
    speaker_count: int
    success: bool
    error_message: str = ""


@dataclass
class SessionStats:
    """Track session statistics for the dashboard."""
    completed: int = 0
    failed: int = 0
    permanently_failed: int = 0
    current_meeting: dict | None = None
    current_status: str = "Initializing..."
    current_start_time: float | None = None
    recent_completions: list[CompletionRecord] = field(default_factory=list)
    pending_retries: list[dict] = field(default_factory=list)
    session_start_time: float = field(default_factory=time.time)
    completion_times: list[float] = field(default_factory=list)

    def add_completion(self, meeting: dict, elapsed: float, result, success: bool, error: str = ""):
        """Record a completion (success or failure)."""
        speaker_count = 0
        if result and hasattr(result, 'total_speakers'):
            speaker_count = result.total_speakers

        record = CompletionRecord(
            clip_id=meeting["clip_id"],
            title=meeting.get("title", "Unknown")[:50],
            elapsed_seconds=elapsed,
            speaker_count=speaker_count,
            success=success,
            error_message=error,
        )
        self.recent_completions.insert(0, record)
        self.recent_completions = self.recent_completions[:10]  # Keep last 10

        if success:
            self.completion_times.append(elapsed)
            self.completion_times = self.completion_times[-20:]  # Rolling window of 20

    @property
    def speed_per_hour(self) -> float:
        """Calculate processing speed (meetings per hour)."""
        if not self.completion_times:
            return 0.0
        avg_seconds = sum(self.completion_times) / len(self.completion_times)
        return 3600 / avg_seconds if avg_seconds > 0 else 0.0

    @property
    def current_elapsed(self) -> float:
        """Get elapsed time for current meeting."""
        if self.current_start_time:
            return time.time() - self.current_start_time
        return 0.0

    @property
    def session_duration(self) -> float:
        """Get total session duration in seconds."""
        return time.time() - self.session_start_time


def get_pending_diarization() -> list[dict]:
    """Get analyzed meetings without diarization files."""
    meetings = get_meetings_by_status("analyzed")
    pending = []
    for m in meetings:
        diarization_path = config.TRANSCRIPT_DIR / f"{m['clip_id']}_diarization.json"
        if not diarization_path.exists():
            pending.append(m)
    # Sort by clip_id to process oldest first
    return sorted(pending, key=lambda m: m["clip_id"])


def get_diarization_progress() -> dict:
    """Get overall diarization progress stats."""
    total_analyzed = len(get_meetings_by_status("analyzed"))
    diarized_files = list(config.TRANSCRIPT_DIR.glob("*_diarization.json"))
    diarized_count = len(diarized_files)
    return {
        "total": total_analyzed,
        "diarized": diarized_count,
        "pending": total_analyzed - diarized_count,
        "percent": (diarized_count / total_analyzed * 100) if total_analyzed > 0 else 0,
    }


def format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    return f"{hours}h {mins:02d}m"


def create_progress_panel(progress: dict) -> Panel:
    """Create the progress panel with overall stats."""
    pct = progress["percent"]
    bar_width = 20
    filled = int(pct / 100 * bar_width)
    bar = "[green]" + "█" * filled + "[/green][dim]" + "░" * (bar_width - filled) + "[/dim]"

    text = Text()
    text.append("Total:     ", style="bold")
    text.append(f"{progress['total']}\n", style="cyan")
    text.append("Diarized:  ", style="bold")
    text.append(f"{progress['diarized']}", style="green")
    text.append(f"  ({pct:.1f}%)\n", style="dim")
    text.append("Pending:   ", style="bold")
    text.append(f"{progress['pending']}\n", style="yellow")
    text.append(f"{bar}", style="")

    return Panel(text, title="Progress", border_style="cyan", box=box.ROUNDED)


def create_session_panel(stats: SessionStats, progress: dict) -> Panel:
    """Create the session statistics panel."""
    text = Text()
    text.append("Completed: ", style="bold")
    text.append(f"{stats.completed}\n", style="green")
    text.append("Failed:    ", style="bold")
    text.append(f"{stats.failed}\n", style="red" if stats.failed > 0 else "dim")
    text.append("Speed:     ", style="bold")
    if stats.speed_per_hour > 0:
        text.append(f"{stats.speed_per_hour:.1f}/hr\n", style="cyan")
    else:
        text.append("--\n", style="dim")
    text.append("ETA:       ", style="bold")
    if stats.speed_per_hour > 0:
        eta_hours = progress["pending"] / stats.speed_per_hour
        if eta_hours >= 24:
            eta_days = eta_hours / 24
            text.append(f"{eta_days:.1f} days\n", style="yellow")
        else:
            text.append(f"{eta_hours:.1f} hours\n", style="yellow")
    else:
        # Estimate based on ~2 hours per meeting
        est_hours = progress["pending"] * 2
        est_days = est_hours / 24
        text.append(f"~{est_days:.0f} days\n", style="dim")
    text.append("Session:   ", style="bold")
    text.append(f"{format_duration(stats.session_duration)}", style="dim")

    return Panel(text, title="Session Stats", border_style="magenta", box=box.ROUNDED)


def create_current_panel(stats: SessionStats) -> Panel:
    """Create the currently processing panel."""
    if stats.current_meeting:
        clip_id = stats.current_meeting["clip_id"]
        title = stats.current_meeting.get("title", "Unknown")[:55]
        date = stats.current_meeting.get("meeting_date", "")

        text = Text()
        text.append(f"Clip {clip_id}: ", style="bold cyan")
        text.append(f"{title}\n", style="")
        if date:
            text.append(f"Date: {date}\n", style="dim")
        text.append(f"Step: ", style="bold")
        text.append(f"{stats.current_status}\n", style="yellow")
        text.append(f"Elapsed: ", style="bold")
        text.append(f"{format_duration(stats.current_elapsed)}", style="cyan")
    else:
        text = Text()
        text.append(stats.current_status, style="dim italic")

    return Panel(text, title="Currently Processing", border_style="yellow", box=box.ROUNDED)


def create_activity_table(stats: SessionStats) -> Table:
    """Create the recent activity table."""
    table = Table(
        title="Recent Activity",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold green",
        expand=True,
    )

    table.add_column("", width=2)
    table.add_column("ID", style="cyan", justify="right", width=6)
    table.add_column("Time", justify="right", width=8)
    table.add_column("Spkrs", justify="right", width=5)
    table.add_column("Title", no_wrap=True)

    for record in stats.recent_completions[:6]:
        if record.success:
            status = "[green]✓[/green]"
            time_str = format_duration(record.elapsed_seconds)
            speakers = str(record.speaker_count)
        else:
            status = "[red]✗[/red]"
            time_str = "[red]FAIL[/red]"
            speakers = "-"

        table.add_row(
            status,
            str(record.clip_id),
            time_str,
            speakers,
            record.title[:40] + ("..." if len(record.title) > 40 else ""),
        )

    if not stats.recent_completions:
        table.add_row("[dim]-[/dim]", "[dim]-[/dim]", "[dim]-[/dim]", "[dim]-[/dim]", "[dim]No completions yet[/dim]")

    return table


def create_errors_panel(stats: SessionStats) -> Panel | None:
    """Create the errors panel if there are pending retries."""
    failed_records = [r for r in stats.recent_completions if not r.success][:3]

    if not failed_records:
        return None

    text = Text()
    for record in failed_records:
        text.append(f"{record.clip_id}: ", style="bold red")
        error_msg = record.error_message[:60] if record.error_message else "Unknown error"
        text.append(f"{error_msg}\n", style="")

    return Panel(text, title="Recent Errors", border_style="red", box=box.ROUNDED)


def create_dashboard(stats: SessionStats) -> Group:
    """Create the full dashboard layout."""
    progress = get_diarization_progress()

    # Header
    status_text = "Running" if stats.current_meeting else "Idle"
    status_color = "green" if stats.current_meeting else "yellow"
    header = Panel(
        Text.from_markup(
            f"[bold cyan]Diarization Pipeline[/bold cyan] - [{status_color}]{status_text}[/{status_color}]\n"
            f"[dim]Last update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]"
        ),
        box=box.ROUNDED,
    )

    # Top row: Progress + Session stats
    progress_panel = create_progress_panel(progress)
    session_panel = create_session_panel(stats, progress)

    # Currently processing
    current_panel = create_current_panel(stats)

    # Activity table
    activity_table = create_activity_table(stats)

    # Errors panel (optional)
    errors_panel = create_errors_panel(stats)

    components = [header, progress_panel, session_panel, current_panel, activity_table]
    if errors_panel:
        components.append(errors_panel)

    return Group(*components)


def run_once():
    """Show current diarization status and exit."""
    init_database(quiet=True)

    progress = get_diarization_progress()
    pending = get_pending_diarization()

    console.print()
    console.print("[bold cyan]Diarization Status[/bold cyan]")
    console.print("=" * 40)
    console.print(f"Total analyzed meetings: {progress['total']}")
    console.print(f"Already diarized:        {progress['diarized']} ({progress['percent']:.1f}%)")
    console.print(f"Pending diarization:     {progress['pending']}")
    console.print()

    if pending:
        console.print("[bold]Next 5 meetings to process:[/bold]")
        for m in pending[:5]:
            clip_id = m["clip_id"]
            title = m.get("title", "Unknown")[:50]
            retries = get_diarization_retry_count(clip_id)
            retry_str = f" [yellow](retry {retries})[/yellow]" if retries > 0 else ""
            console.print(f"  {clip_id}: {title}{retry_str}")
    else:
        console.print("[green]All meetings have been diarized![/green]")

    console.print()


def run_continuous(max_retries: int = 3, retry_delay: int = 60):
    """Run the continuous diarization pipeline with dashboard."""
    init_database(quiet=True)

    stats = SessionStats()
    permanently_failed: set[int] = set()
    shutdown_requested = False

    def signal_handler(signum, frame):
        nonlocal shutdown_requested
        shutdown_requested = True
        stats.current_status = "Shutdown requested..."

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    console.print("[bold cyan]Starting continuous diarization pipeline...[/bold cyan]")
    console.print(f"[dim]Max retries: {max_retries}, Retry delay: {retry_delay}s[/dim]")
    console.print("[dim]Press Ctrl+C for graceful shutdown[/dim]")
    console.print()

    try:
        with Live(create_dashboard(stats), console=console, refresh_per_second=0.5) as live:
            while not shutdown_requested:
                # Get pending meetings
                pending = get_pending_diarization()

                # Filter out permanently failed and max-retried meetings
                pending = [
                    m for m in pending
                    if m["clip_id"] not in permanently_failed
                    and get_diarization_retry_count(m["clip_id"]) < max_retries
                ]

                if not pending:
                    stats.current_meeting = None
                    stats.current_status = "All caught up! Waiting for new meetings..."
                    live.update(create_dashboard(stats))

                    # Poll every 5 minutes
                    for _ in range(300):
                        if shutdown_requested:
                            break
                        time.sleep(1)
                        live.update(create_dashboard(stats))
                    continue

                # Process next meeting
                meeting = pending[0]
                clip_id = meeting["clip_id"]
                stats.current_meeting = meeting
                stats.current_status = "Running pyannote diarization..."
                stats.current_start_time = time.time()
                live.update(create_dashboard(stats))

                # Run diarization
                start_time = time.time()
                result = None
                error_message = ""

                try:
                    result = diarize_meeting(clip_id)
                except Exception as e:
                    error_message = str(e)

                elapsed = time.time() - start_time

                if result:
                    # Success
                    stats.completed += 1
                    stats.add_completion(meeting, elapsed, result, success=True)
                else:
                    # Failure
                    retries = get_diarization_retry_count(clip_id)
                    if not error_message:
                        error_message = "Diarization returned None"

                    if retries >= max_retries - 1:
                        # Max retries reached
                        permanently_failed.add(clip_id)
                        stats.permanently_failed += 1
                        stats.add_completion(meeting, elapsed, None, success=False,
                                           error=f"Max retries reached: {error_message}")
                    else:
                        # Will retry
                        stats.failed += 1
                        stats.add_completion(meeting, elapsed, None, success=False,
                                           error=f"Attempt {retries + 1}/{max_retries}: {error_message}")

                        # Wait before retry
                        stats.current_meeting = None
                        stats.current_status = f"Waiting {retry_delay}s before retry..."
                        live.update(create_dashboard(stats))

                        for _ in range(retry_delay):
                            if shutdown_requested:
                                break
                            time.sleep(1)
                            live.update(create_dashboard(stats))
                        continue

                # Brief pause between meetings
                stats.current_meeting = None
                stats.current_status = "Preparing next meeting..."
                live.update(create_dashboard(stats))
                time.sleep(2)

    except KeyboardInterrupt:
        pass

    # Print session summary
    console.print()
    console.print("[bold cyan]Session Summary[/bold cyan]")
    console.print("=" * 40)
    console.print(f"Duration:           {format_duration(stats.session_duration)}")
    console.print(f"Completed:          {stats.completed}")
    console.print(f"Failed (will retry):{stats.failed}")
    console.print(f"Permanently failed: {stats.permanently_failed}")
    if stats.speed_per_hour > 0:
        console.print(f"Average speed:      {stats.speed_per_hour:.1f} meetings/hour")

    progress = get_diarization_progress()
    console.print(f"Overall progress:   {progress['diarized']}/{progress['total']} ({progress['percent']:.1f}%)")
    console.print()


def main():
    parser = argparse.ArgumentParser(
        description="Continuous speaker diarization pipeline with monitoring dashboard"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Show current status and exit (no processing)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum retry attempts per meeting (default: 3)",
    )
    parser.add_argument(
        "--retry-delay",
        type=int,
        default=60,
        help="Seconds to wait between retries (default: 60)",
    )

    args = parser.parse_args()

    if args.once:
        run_once()
    else:
        run_continuous(max_retries=args.max_retries, retry_delay=args.retry_delay)


if __name__ == "__main__":
    main()
