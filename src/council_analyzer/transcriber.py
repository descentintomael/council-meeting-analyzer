"""Audio transcription using mlx-whisper with dual-model comparison."""

import json
import time
from pathlib import Path

import mlx_whisper
from rich.console import Console
from rich.progress import Progress

from .config import config
from .database import (
    get_meeting,
    get_meetings_by_status,
    insert_transcript,
    log_processing,
    update_meeting_status,
)
from .utils import get_audio_path, get_transcript_path

console = Console()


def transcribe_audio(
    audio_path: Path,
    model: str = config.WHISPER_MODEL_PRIMARY,
    language: str = "en",
) -> dict:
    """
    Transcribe audio file using mlx-whisper.

    Args:
        audio_path: Path to audio file
        model: Whisper model to use
        language: Language code

    Returns:
        Dict with transcription result including segments and word timestamps
    """
    start_time = time.time()

    result = mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo=model,
        word_timestamps=True,
        language=language,
        task="transcribe",
        verbose=False,
    )

    processing_time = time.time() - start_time

    return {
        "text": result.get("text", ""),
        "segments": result.get("segments", []),
        "language": result.get("language", language),
        "processing_time_seconds": processing_time,
        "model": model,
    }


def transcribe_with_both_models(audio_path: Path) -> dict:
    """
    Transcribe audio with both primary and secondary models.

    Returns:
        Dict with both transcription results
    """
    console.print(f"[cyan]Transcribing with primary model (large-v3)...[/cyan]")
    primary_result = transcribe_audio(audio_path, config.WHISPER_MODEL_PRIMARY)
    console.print(
        f"[green]Primary transcription complete in "
        f"{primary_result['processing_time_seconds']:.1f}s[/green]"
    )

    console.print(f"[cyan]Transcribing with secondary model (medium)...[/cyan]")
    secondary_result = transcribe_audio(audio_path, config.WHISPER_MODEL_SECONDARY)
    console.print(
        f"[green]Secondary transcription complete in "
        f"{secondary_result['processing_time_seconds']:.1f}s[/green]"
    )

    return {
        "primary": primary_result,
        "secondary": secondary_result,
    }


def save_transcript_to_file(
    clip_id: int,
    result: dict,
    output_dir: Path,
    model_name: str,
) -> Path:
    """Save transcription result to JSON file."""
    output_path = get_transcript_path(clip_id, output_dir, model_name)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    return output_path


def transcribe_meeting(clip_id: int, dual_model: bool = True) -> dict | None:
    """
    Transcribe a single meeting.

    Args:
        clip_id: Meeting clip ID
        dual_model: Whether to use both models for validation

    Returns:
        Transcription result dict or None on failure
    """
    meeting = get_meeting(clip_id)
    if not meeting:
        console.print(f"[red]Meeting {clip_id} not found[/red]")
        return None

    audio_path = get_audio_path(clip_id, config.AUDIO_DIR)
    if not audio_path.exists():
        console.print(f"[red]Audio file not found for meeting {clip_id}[/red]")
        update_meeting_status(clip_id, "failed")
        log_processing(clip_id, "transcribe", "failed", "Audio file not found")
        return None

    update_meeting_status(clip_id, "transcribing")
    log_processing(clip_id, "transcribe", "started", f"Starting transcription: {meeting['title']}")

    try:
        if dual_model:
            result = transcribe_with_both_models(audio_path)

            # Save both transcripts
            save_transcript_to_file(
                clip_id, result["primary"], config.TRANSCRIPT_DIR, "large_v3"
            )
            save_transcript_to_file(
                clip_id, result["secondary"], config.TRANSCRIPT_DIR, "medium"
            )

            # Store primary transcript in database
            insert_transcript(
                clip_id=clip_id,
                full_text=result["primary"]["text"],
                word_timestamps=extract_word_timestamps(result["primary"]["segments"]),
                model_used="dual:large-v3+medium",
                processing_time_seconds=(
                    result["primary"]["processing_time_seconds"]
                    + result["secondary"]["processing_time_seconds"]
                ),
            )

            total_time = (
                result["primary"]["processing_time_seconds"]
                + result["secondary"]["processing_time_seconds"]
            )
            console.print(
                f"[green]Transcription complete for {clip_id} in {total_time:.1f}s total[/green]"
            )

        else:
            result = transcribe_audio(audio_path, config.WHISPER_MODEL_PRIMARY)
            save_transcript_to_file(clip_id, result, config.TRANSCRIPT_DIR, "large_v3")

            insert_transcript(
                clip_id=clip_id,
                full_text=result["text"],
                word_timestamps=extract_word_timestamps(result["segments"]),
                model_used="large-v3",
                processing_time_seconds=result["processing_time_seconds"],
            )

            console.print(
                f"[green]Transcription complete for {clip_id} in "
                f"{result['processing_time_seconds']:.1f}s[/green]"
            )

        update_meeting_status(clip_id, "transcribed")
        log_processing(clip_id, "transcribe", "completed", "Transcription successful")
        return result

    except Exception as e:
        console.print(f"[red]Transcription error for {clip_id}: {e}[/red]")
        update_meeting_status(clip_id, "failed")
        log_processing(clip_id, "transcribe", "failed", str(e))
        return None


def extract_word_timestamps(segments: list[dict]) -> list[dict]:
    """Extract word-level timestamps from segments."""
    words = []
    for segment in segments:
        if "words" in segment:
            for word_info in segment["words"]:
                words.append({
                    "word": word_info.get("word", ""),
                    "start": word_info.get("start", 0),
                    "end": word_info.get("end", 0),
                })
    return words


def transcribe_batch(batch_size: int = 3, dual_model: bool = True) -> dict:
    """
    Transcribe a batch of pending meetings.

    Returns:
        Stats dict: {"transcribed": count, "failed": count}
    """
    stats = {"transcribed": 0, "failed": 0}

    pending = get_meetings_by_status("downloaded")[:batch_size]

    if not pending:
        console.print("[yellow]No meetings pending transcription[/yellow]")
        return stats

    console.print(f"[bold]Transcribing {len(pending)} meetings...[/bold]")

    for meeting in pending:
        clip_id = meeting["clip_id"]
        console.print(f"\n[bold cyan]Processing {clip_id}: {meeting['title']}[/bold cyan]")

        result = transcribe_meeting(clip_id, dual_model=dual_model)
        if result:
            stats["transcribed"] += 1
        else:
            stats["failed"] += 1

    console.print(f"\n[bold green]Transcription batch complete![/bold green]")
    console.print(f"  Transcribed: {stats['transcribed']}")
    console.print(f"  Failed: {stats['failed']}")

    return stats


def get_pending_transcriptions() -> list[dict]:
    """Get list of meetings pending transcription."""
    return get_meetings_by_status("downloaded")


if __name__ == "__main__":
    transcribe_batch()
