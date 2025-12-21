"""Pipeline orchestration - run the full meeting analysis pipeline."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from rich.console import Console
from rich.table import Table

from .config import config, ensure_directories
from .database import get_processing_stats, get_meetings_by_status, init_database
from .discovery import run_discovery
from .downloader import download_batch
from .transcriber import transcribe_batch
from .diarization import diarize_meeting
from .validator import validate_batch
from .analyzer import analyze_batch
from .reporter import generate_all_reports

console = Console()


@dataclass
class PipelineResult:
    """Result of a pipeline run."""

    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    discovery: dict = field(default_factory=dict)
    download: dict = field(default_factory=dict)
    transcribe: dict = field(default_factory=dict)
    diarize: dict = field(default_factory=dict)
    validate: dict = field(default_factory=dict)
    analyze: dict = field(default_factory=dict)
    reports: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Generate a summary string."""
        duration = ""
        if self.completed_at:
            delta = self.completed_at - self.started_at
            duration = f" in {delta.total_seconds():.1f}s"

        return (
            f"Pipeline completed{duration}\n"
            f"  Discovery: {self.discovery.get('new', 0)} new meetings\n"
            f"  Downloaded: {self.download.get('downloaded', 0)}\n"
            f"  Transcribed: {self.transcribe.get('transcribed', 0)}\n"
            f"  Diarized: {self.diarize.get('diarized', 0)}\n"
            f"  Validated: {self.validate.get('validated', 0)}\n"
            f"  Analyzed: {self.analyze.get('analyzed', 0)}\n"
            f"  Reports: {self.reports}\n"
            f"  Errors: {len(self.errors)}"
        )


def setup_pipeline():
    """Initialize pipeline requirements."""
    console.print("[bold]Setting up pipeline...[/bold]")
    ensure_directories()
    init_database()
    console.print("[green]Pipeline setup complete[/green]")


def diarize_batch(batch_size: int = 5) -> dict:
    """
    Run speaker diarization on transcribed meetings.

    Returns:
        Stats dict with diarized/failed counts
    """
    stats = {"diarized": 0, "failed": 0}

    # Get transcribed meetings that need diarization
    meetings = get_meetings_by_status("transcribed")
    pending = []
    for meeting in meetings[:batch_size]:
        clip_id = meeting["clip_id"]
        diarization_path = config.TRANSCRIPT_DIR / f"{clip_id}_diarization.json"
        if not diarization_path.exists():
            pending.append(meeting)

    if not pending:
        console.print("[yellow]No meetings pending diarization[/yellow]")
        return stats

    console.print(f"[bold]Diarizing {len(pending)} meetings...[/bold]")

    for meeting in pending:
        clip_id = meeting["clip_id"]
        console.print(f"[cyan]Diarizing {clip_id}: {meeting['title']}[/cyan]")

        result = diarize_meeting(clip_id)
        if result:
            stats["diarized"] += 1
        else:
            stats["failed"] += 1

    return stats


def run_full_pipeline(
    skip_discovery: bool = False,
    skip_download: bool = False,
    skip_transcribe: bool = False,
    skip_diarize: bool = False,
    skip_validate: bool = False,
    skip_analyze: bool = False,
    skip_reports: bool = False,
    download_batch_size: int = 10,
    transcribe_batch_size: int = 3,
    diarize_batch_size: int = 5,
    validate_batch_size: int = 5,
    analyze_batch_size: int = 1,
) -> PipelineResult:
    """
    Run the complete pipeline.

    Args:
        skip_*: Skip specific stages
        *_batch_size: Control batch sizes for each stage

    Returns:
        PipelineResult with stats from each stage
    """
    result = PipelineResult()

    setup_pipeline()

    try:
        # Stage 1: Discovery
        if not skip_discovery:
            console.print("\n[bold cyan]Stage 1: Discovery[/bold cyan]")
            result.discovery = asyncio.run(run_discovery())
        else:
            console.print("\n[dim]Skipping discovery[/dim]")

        # Stage 2: Download
        if not skip_download:
            console.print("\n[bold cyan]Stage 2: Download[/bold cyan]")
            result.download = download_batch(batch_size=download_batch_size)
        else:
            console.print("\n[dim]Skipping download[/dim]")

        # Stage 3: Transcribe
        if not skip_transcribe:
            console.print("\n[bold cyan]Stage 3: Transcription[/bold cyan]")
            result.transcribe = transcribe_batch(batch_size=transcribe_batch_size)
        else:
            console.print("\n[dim]Skipping transcription[/dim]")

        # Stage 3.5: Speaker Diarization
        if not skip_diarize:
            console.print("\n[bold cyan]Stage 3.5: Speaker Diarization[/bold cyan]")
            result.diarize = diarize_batch(batch_size=diarize_batch_size)
        else:
            console.print("\n[dim]Skipping diarization[/dim]")

        # Stage 4: Validate
        if not skip_validate:
            console.print("\n[bold cyan]Stage 4: Validation[/bold cyan]")
            result.validate = validate_batch(batch_size=validate_batch_size)
        else:
            console.print("\n[dim]Skipping validation[/dim]")

        # Stage 5: Analyze
        if not skip_analyze:
            console.print("\n[bold cyan]Stage 5: Analysis[/bold cyan]")
            result.analyze = analyze_batch(batch_size=analyze_batch_size)
        else:
            console.print("\n[dim]Skipping analysis[/dim]")

        # Stage 6: Reports
        if not skip_reports:
            console.print("\n[bold cyan]Stage 6: Report Generation[/bold cyan]")
            result.reports = generate_all_reports()
        else:
            console.print("\n[dim]Skipping reports[/dim]")

    except Exception as e:
        result.errors.append(str(e))
        console.print(f"[red]Pipeline error: {e}[/red]")

    result.completed_at = datetime.now()

    # Print summary
    console.print("\n" + "=" * 50)
    console.print("[bold green]Pipeline Complete![/bold green]")
    console.print(result.summary())

    return result


def run_incremental() -> PipelineResult:
    """
    Run pipeline for pending items only (no discovery).
    Useful for processing items that were previously downloaded/transcribed.
    """
    return run_full_pipeline(skip_discovery=True)


def get_pipeline_status() -> dict:
    """
    Get current pipeline status.

    Returns:
        Status dict with counts and estimates
    """
    stats = get_processing_stats()

    by_status = stats.get("by_status", {})

    # Calculate pending counts
    pending_download = by_status.get("discovered", 0)
    pending_transcribe = by_status.get("downloaded", 0)
    pending_validate = by_status.get("transcribed", 0)
    pending_analyze = by_status.get("validated", 0)

    # Estimate remaining time (rough)
    # Download: ~7 min avg, Transcribe: ~25 min avg, Validate: ~3 min avg, Analyze: ~8 min avg
    est_minutes = (
        pending_download * 7
        + pending_transcribe * 25
        + pending_validate * 3
        + pending_analyze * 8
    )

    return {
        "total_meetings": stats.get("total_meetings", 0),
        "by_status": by_status,
        "pending": {
            "download": pending_download,
            "transcribe": pending_transcribe,
            "validate": pending_validate,
            "analyze": pending_analyze,
        },
        "completed": by_status.get("analyzed", 0),
        "failed": by_status.get("failed", 0),
        "estimated_minutes_remaining": est_minutes,
        "recent_failures": stats.get("recent_failures", []),
    }


def print_status():
    """Print a formatted status report."""
    status = get_pipeline_status()

    console.print("\n[bold]Pipeline Status[/bold]")
    console.print("=" * 50)

    # Summary table
    table = Table(show_header=True, header_style="bold")
    table.add_column("Stage")
    table.add_column("Count", justify="right")

    by_status = status.get("by_status", {})
    for stage, count in by_status.items():
        table.add_row(stage, str(count))

    console.print(table)

    # Pending work
    pending = status.get("pending", {})
    console.print("\n[bold]Pending Work:[/bold]")
    console.print(f"  Download: {pending.get('download', 0)}")
    console.print(f"  Transcribe: {pending.get('transcribe', 0)}")
    console.print(f"  Validate: {pending.get('validate', 0)}")
    console.print(f"  Analyze: {pending.get('analyze', 0)}")

    est = status.get("estimated_minutes_remaining", 0)
    if est > 0:
        hours = est // 60
        minutes = est % 60
        console.print(f"\n[dim]Estimated time remaining: {hours}h {minutes}m[/dim]")

    # Recent failures
    failures = status.get("recent_failures", [])
    if failures:
        console.print("\n[bold red]Recent Failures:[/bold red]")
        for f in failures[:5]:
            console.print(f"  Clip {f['clip_id']}: {f['message'][:50]}")


if __name__ == "__main__":
    print_status()
