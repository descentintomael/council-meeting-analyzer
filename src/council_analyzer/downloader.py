"""Video downloader - download HLS streams and extract audio using ffmpeg."""

import subprocess
from pathlib import Path

from rich.console import Console
from rich.progress import Progress

from .config import config
from .database import (
    get_meetings_by_status,
    get_meeting,
    log_processing,
    update_meeting_status,
)
from .utils import get_audio_path

console = Console()


def download_audio(clip_id: int, video_url: str, output_path: Path) -> bool:
    """
    Download HLS stream and extract audio using ffmpeg.

    Args:
        clip_id: The meeting clip ID
        video_url: HLS playlist URL (m3u8)
        output_path: Where to save the MP3 file

    Returns:
        True if successful, False otherwise
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ffmpeg command to download HLS stream and extract audio as MP3
    cmd = [
        "ffmpeg",
        "-y",  # Overwrite output
        "-i", video_url,  # Input HLS stream
        "-vn",  # No video
        "-acodec", "libmp3lame",  # MP3 codec
        "-q:a", "2",  # Quality (2 = ~190 kbps VBR)
        "-map", "0:a:0",  # First audio stream
        str(output_path),
    ]

    try:
        log_processing(clip_id, "download", "started", f"Starting download: {video_url}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config.DOWNLOAD_TIMEOUT_SEC,
        )

        if result.returncode == 0:
            # Verify file exists and has content
            if output_path.exists() and output_path.stat().st_size > 0:
                log_processing(clip_id, "download", "completed", f"Downloaded to {output_path}")
                return True
            else:
                log_processing(clip_id, "download", "failed", "Output file empty or missing")
                return False
        else:
            log_processing(clip_id, "download", "failed", f"ffmpeg error: {result.stderr[:500]}")
            return False

    except subprocess.TimeoutExpired:
        log_processing(clip_id, "download", "failed", "Download timeout")
        return False
    except Exception as e:
        log_processing(clip_id, "download", "failed", str(e))
        return False


def verify_audio(audio_path: Path) -> dict | None:
    """
    Verify audio file using ffprobe.

    Returns:
        Dict with duration_seconds and format info, or None if invalid
    """
    if not audio_path.exists():
        return None

    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(audio_path),
    ]

    try:
        import json
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if "format" in data:
                duration = float(data["format"].get("duration", 0))
                return {
                    "duration_seconds": int(duration),
                    "format": data["format"].get("format_name"),
                    "size_bytes": int(data["format"].get("size", 0)),
                }
    except Exception:
        pass

    return None


def download_meeting(clip_id: int) -> bool:
    """
    Download a single meeting's audio.

    Returns:
        True if successful, False otherwise
    """
    meeting = get_meeting(clip_id)
    if not meeting:
        console.print(f"[red]Meeting {clip_id} not found[/red]")
        return False

    if not meeting.get("video_url"):
        console.print(f"[yellow]Meeting {clip_id} has no video URL[/yellow]")
        update_meeting_status(clip_id, "failed")
        log_processing(clip_id, "download", "failed", "No video URL available")
        return False

    output_path = get_audio_path(clip_id, config.AUDIO_DIR)

    # Check if already downloaded
    if output_path.exists():
        info = verify_audio(output_path)
        if info and info["duration_seconds"] > 0:
            console.print(f"[yellow]Meeting {clip_id} already downloaded[/yellow]")
            update_meeting_status(clip_id, "downloaded")
            return True

    update_meeting_status(clip_id, "downloading")
    console.print(f"[cyan]Downloading meeting {clip_id}: {meeting['title']}[/cyan]")

    success = download_audio(clip_id, meeting["video_url"], output_path)

    if success:
        update_meeting_status(clip_id, "downloaded")
        info = verify_audio(output_path)
        if info:
            console.print(
                f"[green]Downloaded {clip_id}: "
                f"{info['duration_seconds'] // 60}m {info['duration_seconds'] % 60}s, "
                f"{info['size_bytes'] // (1024*1024)}MB[/green]"
            )
    else:
        update_meeting_status(clip_id, "failed")
        console.print(f"[red]Failed to download meeting {clip_id}[/red]")

    return success


def download_batch(batch_size: int = 10) -> dict:
    """
    Download a batch of pending meetings.

    Returns:
        Stats dict: {"downloaded": count, "failed": count, "skipped": count}
    """
    stats = {"downloaded": 0, "failed": 0, "skipped": 0}

    pending = get_meetings_by_status("discovered")[:batch_size]

    if not pending:
        console.print("[yellow]No meetings pending download[/yellow]")
        return stats

    console.print(f"[bold]Downloading {len(pending)} meetings...[/bold]")

    with Progress() as progress:
        task = progress.add_task("[cyan]Downloading...", total=len(pending))

        for meeting in pending:
            clip_id = meeting["clip_id"]

            if not meeting.get("video_url"):
                stats["skipped"] += 1
                update_meeting_status(clip_id, "failed")
                log_processing(clip_id, "download", "failed", "No video URL")
            else:
                success = download_meeting(clip_id)
                if success:
                    stats["downloaded"] += 1
                else:
                    stats["failed"] += 1

            progress.update(task, advance=1)

    console.print(f"[bold green]Download batch complete![/bold green]")
    console.print(f"  Downloaded: {stats['downloaded']}")
    console.print(f"  Failed: {stats['failed']}")
    console.print(f"  Skipped (no URL): {stats['skipped']}")

    return stats


def get_pending_downloads() -> list[dict]:
    """Get list of meetings pending download."""
    return get_meetings_by_status("discovered")


if __name__ == "__main__":
    download_batch()
