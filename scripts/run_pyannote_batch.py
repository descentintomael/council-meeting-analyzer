#!/usr/bin/env python3
"""Batch speaker diarization using pyannote.ai hosted API.

Processes meetings >= 30 minutes that don't have diarization yet.
Tracks API usage and stops before exceeding the hour limit.
"""

import json
import os
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.text import Text

# Load environment variables
load_dotenv()

API_KEY = os.getenv("PYANNOTE_API_KEY")
BASE_URL = "https://api.pyannote.ai/v1"

PROJECT_ROOT = Path(__file__).parent.parent
AUDIO_DIR = PROJECT_ROOT / "data" / "audio"
TRANSCRIPT_DIR = PROJECT_ROOT / "data" / "transcripts"
DB_PATH = PROJECT_ROOT / "data" / "meetings.db"

# Configuration
MIN_DURATION_MINUTES = 30
MAX_HOURS = 150  # Free trial limit

console = Console()


@dataclass
class SessionStats:
    """Track session statistics."""
    completed: int = 0
    failed: int = 0
    hours_used: float = 0.0
    start_time: float = field(default_factory=time.time)
    current_meeting: dict | None = None
    current_status: str = "Initializing..."
    recent_completions: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def get_headers():
    """Get authorization headers."""
    return {"Authorization": f"Bearer {API_KEY}"}


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_audio_duration(clip_id: int) -> float | None:
    """Get audio duration in minutes."""
    audio_path = AUDIO_DIR / f"{clip_id}.mp3"
    if not audio_path.exists():
        return None

    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', str(audio_path)],
        capture_output=True, text=True
    )
    try:
        return float(result.stdout.strip()) / 60
    except:
        return None


def get_eligible_meetings() -> list[dict]:
    """Get meetings eligible for diarization."""
    conn = get_db()
    rows = conn.execute(
        "SELECT clip_id, title, meeting_date FROM meetings WHERE status = 'analyzed' ORDER BY clip_id"
    ).fetchall()
    conn.close()

    eligible = []
    for row in rows:
        clip_id = row['clip_id']

        # Skip if already diarized
        if (TRANSCRIPT_DIR / f"{clip_id}_diarization.json").exists():
            continue

        # Check duration
        duration = get_audio_duration(clip_id)
        if duration is None or duration < MIN_DURATION_MINUTES:
            continue

        eligible.append({
            'clip_id': clip_id,
            'title': row['title'],
            'date': row['meeting_date'],
            'duration_min': duration,
        })

    return eligible


def load_transcript_segments(clip_id: int) -> list[dict]:
    """Load transcript segments with timestamps."""
    json_patterns = [
        f"{clip_id}_large_v3.json",
        f"{clip_id}_medium.json",
        f"{clip_id}.json",
    ]

    for pattern in json_patterns:
        json_path = TRANSCRIPT_DIR / pattern
        if json_path.exists():
            with open(json_path) as f:
                data = json.load(f)
                if "segments" in data:
                    return data["segments"]

    return []


def merge_diarization_with_transcript(
    diarization_segments: list[dict],
    transcript_segments: list[dict],
) -> list[dict]:
    """Align transcript segments with diarization using midpoint matching."""
    if not transcript_segments:
        return []

    diarization_segments = sorted(diarization_segments, key=lambda x: x["start"])

    merged_segments = []
    for t_seg in transcript_segments:
        t_start = t_seg.get("start", 0)
        t_end = t_seg.get("end", t_start)
        t_mid = (t_start + t_end) / 2 if t_end else t_start
        text = t_seg.get("text", "").strip()

        if not text:
            continue

        # Find diarization segment containing this midpoint
        speaker_id = "UNKNOWN"
        confidence = None
        for d_seg in diarization_segments:
            if d_seg["start"] <= t_mid <= d_seg["end"]:
                speaker_id = d_seg["speaker"]
                confidence = d_seg.get("confidence")
                break

        # Find nearest speaker within 30 seconds if no exact match
        if speaker_id == "UNKNOWN" and diarization_segments:
            min_dist = float("inf")
            for d_seg in diarization_segments:
                d_mid = (d_seg["start"] + d_seg["end"]) / 2
                dist = abs(t_mid - d_mid)
                if dist < min_dist and dist < 30:
                    min_dist = dist
                    speaker_id = d_seg["speaker"]
                    confidence = d_seg.get("confidence")

        merged_segments.append({
            "start": t_start,
            "end": t_end,
            "speaker_id": speaker_id,
            "speaker_name": None,
            "confidence": confidence,
            "method": "pyannote.ai",
            "text": text[:500],
        })

    return merged_segments


def upload_audio(clip_id: int) -> str:
    """Upload audio file and return the media:// URL."""
    audio_path = AUDIO_DIR / f"{clip_id}.mp3"
    media_key = f"meeting-{clip_id}"
    media_url = f"media://{media_key}"

    # Get presigned upload URL
    response = requests.post(
        f"{BASE_URL}/media/input",
        headers=get_headers(),
        json={"url": media_url},
    )
    response.raise_for_status()
    upload_url = response.json()["url"]

    # Upload the file
    with open(audio_path, "rb") as f:
        upload_response = requests.put(
            upload_url,
            data=f,
            headers={"Content-Type": "audio/mpeg"},
        )
    upload_response.raise_for_status()

    return media_url


def submit_diarization(media_url: str) -> str:
    """Submit diarization job and return job ID."""
    response = requests.post(
        f"{BASE_URL}/diarize",
        headers=get_headers(),
        json={
            "url": media_url,
            "model": "precision-2",
            "confidence": True,
        },
    )
    response.raise_for_status()
    return response.json()["jobId"]


def wait_for_job(job_id: str, stats: SessionStats, poll_interval: int = 5) -> dict:
    """Poll until job completes and return results."""
    while True:
        response = requests.get(
            f"{BASE_URL}/jobs/{job_id}",
            headers=get_headers(),
        )
        response.raise_for_status()
        result = response.json()
        status = result["status"]

        if status == "succeeded":
            return result
        elif status == "failed":
            raise RuntimeError(f"Job failed: {result.get('error', 'Unknown error')}")
        elif status == "canceled":
            raise RuntimeError("Job was canceled")

        stats.current_status = f"Diarization: {status}..."
        time.sleep(poll_interval)


def process_meeting(meeting: dict, stats: SessionStats) -> bool:
    """Process a single meeting. Returns True on success."""
    clip_id = meeting['clip_id']

    try:
        # Upload
        stats.current_status = "Uploading audio..."
        media_url = upload_audio(clip_id)

        # Submit
        stats.current_status = "Submitting job..."
        job_id = submit_diarization(media_url)

        # Wait for results
        result = wait_for_job(job_id, stats)

        # Process results
        stats.current_status = "Processing results..."
        output = result.get("output", {})
        diarization = output.get("diarization", [])

        diarization_segments = [
            {"start": s["start"], "end": s["end"], "speaker": s["speaker"], "confidence": s.get("confidence")}
            for s in diarization
        ]

        # Load and merge with transcript
        transcript_segments = load_transcript_segments(clip_id)
        merged_segments = merge_diarization_with_transcript(diarization_segments, transcript_segments)

        # Count speakers
        speakers = set(s["speaker"] for s in diarization_segments)

        # Save
        output_path = TRANSCRIPT_DIR / f"{clip_id}_diarization.json"
        with open(output_path, "w") as f:
            json.dump({
                "clip_id": clip_id,
                "source": "pyannote.ai",
                "model": "precision-2",
                "total_speakers": len(speakers),
                "identified_speakers": 0,
                "speaker_mapping": {},
                "segments": merged_segments,
            }, f, indent=2)

        return True

    except Exception as e:
        stats.errors.append({
            'clip_id': clip_id,
            'error': str(e),
            'time': datetime.now().isoformat(),
        })
        return False


def create_dashboard(stats: SessionStats, eligible: list[dict], hours_limit: float) -> Panel:
    """Create the Rich dashboard display."""
    # Calculate progress
    total_eligible = len(eligible)
    processed = stats.completed + stats.failed
    hours_remaining = hours_limit - stats.hours_used

    # Estimate how many more we can do
    if stats.completed > 0:
        avg_hours = stats.hours_used / stats.completed
        can_still_do = int(hours_remaining / avg_hours) if avg_hours > 0 else 0
    else:
        can_still_do = "?"

    # Build display
    text = Text()
    text.append("pyannote.ai Batch Diarization\n", style="bold cyan")
    text.append(f"Started: {datetime.fromtimestamp(stats.start_time).strftime('%H:%M:%S')}\n\n")

    # Progress section
    text.append("─── Progress ───\n", style="dim")
    text.append(f"Completed: ", style="dim")
    text.append(f"{stats.completed}\n", style="green bold")
    text.append(f"Failed: ", style="dim")
    text.append(f"{stats.failed}\n", style="red" if stats.failed else "dim")
    text.append(f"Remaining: ", style="dim")
    text.append(f"{total_eligible - processed}\n\n", style="yellow")

    # Hours section
    text.append("─── API Usage ───\n", style="dim")
    text.append(f"Hours used: ", style="dim")
    text.append(f"{stats.hours_used:.2f} / {hours_limit:.0f}\n", style="cyan")
    text.append(f"Hours remaining: ", style="dim")
    text.append(f"{hours_remaining:.2f}\n", style="green" if hours_remaining > 10 else "yellow")
    text.append(f"Est. more meetings: ", style="dim")
    text.append(f"{can_still_do}\n\n", style="cyan")

    # Current meeting
    if stats.current_meeting:
        text.append("─── Current ───\n", style="dim")
        m = stats.current_meeting
        text.append(f"{m['clip_id']}: ", style="bold")
        text.append(f"{m['title'][:40]}...\n" if len(m['title']) > 40 else f"{m['title']}\n")
        text.append(f"Duration: {m['duration_min']:.1f} min\n", style="dim")
        text.append(f"Status: {stats.current_status}\n\n", style="yellow")

    # Recent completions
    if stats.recent_completions:
        text.append("─── Recent ───\n", style="dim")
        for item in stats.recent_completions[-5:]:
            text.append(f"✓ {item['clip_id']}: ", style="green")
            text.append(f"{item['duration']:.1f}min, {item['speakers']} speakers\n", style="dim")

    # Errors
    if stats.errors:
        text.append("\n─── Errors ───\n", style="dim")
        for err in stats.errors[-3:]:
            text.append(f"✗ {err['clip_id']}: ", style="red")
            text.append(f"{err['error'][:50]}\n", style="dim")

    return Panel(text, title="[bold]Diarization Pipeline[/bold]", border_style="blue")


def main():
    """Run batch diarization."""
    if not API_KEY:
        console.print("[red]ERROR: PYANNOTE_API_KEY not set in .env file[/red]")
        return

    # Parse arguments
    hours_limit = MAX_HOURS
    if len(sys.argv) > 1:
        try:
            hours_limit = float(sys.argv[1])
        except:
            pass

    console.print(f"[cyan]pyannote.ai Batch Diarization[/cyan]")
    console.print(f"Hour limit: {hours_limit}")
    console.print(f"Min duration: {MIN_DURATION_MINUTES} minutes\n")

    # Test API connection
    console.print("Testing API connection...")
    try:
        response = requests.get(f"{BASE_URL}/test", headers=get_headers())
        response.raise_for_status()
        console.print("[green]API connection successful![/green]\n")
    except Exception as e:
        console.print(f"[red]API connection failed: {e}[/red]")
        return

    # Get eligible meetings
    console.print("Finding eligible meetings...")
    eligible = get_eligible_meetings()

    if not eligible:
        console.print("[yellow]No eligible meetings to process.[/yellow]")
        return

    total_hours = sum(m['duration_min'] / 60 for m in eligible)
    console.print(f"Found {len(eligible)} eligible meetings ({total_hours:.1f} hours)")
    console.print(f"Hour limit: {hours_limit} hours\n")

    # Initialize stats
    stats = SessionStats()

    # Process meetings with live dashboard
    try:
        with Live(create_dashboard(stats, eligible, hours_limit), refresh_per_second=0.5) as live:
            for meeting in eligible:
                clip_id = meeting['clip_id']
                duration_hours = meeting['duration_min'] / 60

                # Check if we have enough hours left
                if stats.hours_used + duration_hours > hours_limit:
                    stats.current_status = f"Stopping: would exceed {hours_limit}h limit"
                    live.update(create_dashboard(stats, eligible, hours_limit))
                    break

                # Process meeting
                stats.current_meeting = meeting
                stats.current_status = "Starting..."
                live.update(create_dashboard(stats, eligible, hours_limit))

                start_time = time.time()
                success = process_meeting(meeting, stats)
                elapsed = time.time() - start_time

                if success:
                    stats.completed += 1
                    stats.hours_used += duration_hours

                    # Load result to get speaker count
                    result_path = TRANSCRIPT_DIR / f"{clip_id}_diarization.json"
                    with open(result_path) as f:
                        result_data = json.load(f)

                    stats.recent_completions.append({
                        'clip_id': clip_id,
                        'duration': meeting['duration_min'],
                        'speakers': result_data['total_speakers'],
                        'elapsed': elapsed,
                    })
                else:
                    stats.failed += 1

                stats.current_meeting = None
                live.update(create_dashboard(stats, eligible, hours_limit))

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")

    # Final summary
    console.print(f"\n[bold]Session Complete[/bold]")
    console.print(f"Completed: {stats.completed}")
    console.print(f"Failed: {stats.failed}")
    console.print(f"Hours used: {stats.hours_used:.2f}")

    if stats.errors:
        console.print(f"\n[red]Errors:[/red]")
        for err in stats.errors:
            console.print(f"  {err['clip_id']}: {err['error']}")


if __name__ == "__main__":
    main()
