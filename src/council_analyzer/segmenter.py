"""Segment transcripts by agenda items using timestamps."""

from rich.console import Console

from .config import config
from .database import (
    get_agenda_items,
    get_meeting,
    get_meetings_by_status,
    get_transcript,
    log_processing,
    update_meeting_status,
)
from .utils import get_transcript_path

console = Console()


def segment_by_agenda(clip_id: int) -> list[dict]:
    """
    Segment a transcript by agenda items using timestamps.

    Returns:
        List of segment dicts with agenda_item_id, text, start, end
    """
    transcript = get_transcript(clip_id)
    if not transcript:
        console.print(f"[red]No transcript found for {clip_id}[/red]")
        return []

    agenda_items = get_agenda_items(clip_id)
    if not agenda_items:
        console.print(f"[yellow]No agenda items for {clip_id}, treating as single segment[/yellow]")
        return [{
            "agenda_item_id": None,
            "text": transcript.get("full_text", ""),
            "start_seconds": 0,
            "end_seconds": None,
        }]

    word_timestamps = transcript.get("word_timestamps", [])
    if not word_timestamps:
        console.print(f"[yellow]No word timestamps for {clip_id}, using full text per item[/yellow]")
        # Fall back to rough splitting based on word count
        return segment_by_word_count(transcript.get("full_text", ""), agenda_items)

    segments = []

    for i, item in enumerate(agenda_items):
        start_sec = item.get("start_seconds", 0)
        end_sec = item.get("end_seconds")

        # If no end time, use start of next item or end of transcript
        if end_sec is None:
            if i + 1 < len(agenda_items):
                end_sec = agenda_items[i + 1].get("start_seconds", start_sec)
            else:
                # Use last word timestamp as end
                if word_timestamps:
                    end_sec = word_timestamps[-1].get("end", start_sec + 3600)
                else:
                    end_sec = start_sec + 3600  # Default 1 hour

        # Collect words in this time range
        segment_words = []
        for word_info in word_timestamps:
            word_start = word_info.get("start", 0)
            word_end = word_info.get("end", 0)

            # Word is in segment if it overlaps
            if word_start >= start_sec and word_start < end_sec:
                segment_words.append(word_info.get("word", ""))
            elif word_start >= end_sec:
                break

        segment_text = " ".join(segment_words).strip()

        segments.append({
            "agenda_item_id": item.get("id"),
            "item_number": item.get("item_number"),
            "item_title": item.get("title"),
            "text": segment_text,
            "start_seconds": start_sec,
            "end_seconds": end_sec,
            "word_count": len(segment_words),
        })

    return segments


def segment_by_word_count(full_text: str, agenda_items: list[dict]) -> list[dict]:
    """
    Fallback segmentation when word timestamps aren't available.
    Splits text roughly based on agenda item time proportions.
    """
    if not agenda_items:
        return [{
            "agenda_item_id": None,
            "text": full_text,
            "start_seconds": 0,
            "end_seconds": None,
        }]

    words = full_text.split()
    total_words = len(words)

    if total_words == 0:
        return []

    # Calculate total duration
    last_item = agenda_items[-1]
    total_duration = last_item.get("end_seconds") or last_item.get("start_seconds", 0) + 600

    segments = []
    word_index = 0

    for i, item in enumerate(agenda_items):
        start_sec = item.get("start_seconds", 0)
        end_sec = item.get("end_seconds")

        if end_sec is None:
            if i + 1 < len(agenda_items):
                end_sec = agenda_items[i + 1].get("start_seconds", start_sec)
            else:
                end_sec = total_duration

        # Calculate proportion of words for this segment
        duration = end_sec - start_sec
        proportion = duration / total_duration if total_duration > 0 else 1 / len(agenda_items)
        word_count = int(total_words * proportion)

        # Extract words for this segment
        segment_words = words[word_index:word_index + word_count]
        word_index += word_count

        segments.append({
            "agenda_item_id": item.get("id"),
            "item_number": item.get("item_number"),
            "item_title": item.get("title"),
            "text": " ".join(segment_words),
            "start_seconds": start_sec,
            "end_seconds": end_sec,
            "word_count": len(segment_words),
        })

    # Add remaining words to last segment
    if word_index < total_words and segments:
        remaining = " ".join(words[word_index:])
        segments[-1]["text"] += " " + remaining
        segments[-1]["word_count"] += total_words - word_index

    return segments


def segment_meeting(clip_id: int) -> list[dict] | None:
    """
    Segment a meeting's transcript by agenda items.

    Returns:
        List of segments or None on failure
    """
    meeting = get_meeting(clip_id)
    if not meeting:
        console.print(f"[red]Meeting {clip_id} not found[/red]")
        return None

    log_processing(clip_id, "segment", "started", "Segmenting transcript")

    try:
        segments = segment_by_agenda(clip_id)

        if segments:
            console.print(f"[green]Segmented {clip_id} into {len(segments)} segments[/green]")
            log_processing(clip_id, "segment", "completed", f"Created {len(segments)} segments")
        else:
            console.print(f"[yellow]No segments created for {clip_id}[/yellow]")

        return segments

    except Exception as e:
        console.print(f"[red]Segmentation error for {clip_id}: {e}[/red]")
        log_processing(clip_id, "segment", "failed", str(e))
        return None


if __name__ == "__main__":
    # Test segmentation on a specific clip
    import sys
    if len(sys.argv) > 1:
        clip_id = int(sys.argv[1])
        segments = segment_meeting(clip_id)
        if segments:
            for seg in segments:
                print(f"\n--- {seg.get('item_number', 'N/A')}: {seg.get('item_title', 'Unknown')[:50]} ---")
                print(f"Time: {seg['start_seconds']}s - {seg['end_seconds']}s")
                print(f"Words: {seg['word_count']}")
                print(seg['text'][:200] + "..." if len(seg['text']) > 200 else seg['text'])
