"""Shared utilities for the council meeting analyzer."""

import re
from datetime import datetime
from pathlib import Path


def parse_meeting_date(title: str) -> str | None:
    """
    Parse date from meeting title like '12/4/24 City Council'.
    Returns ISO format date string or None.
    """
    # Pattern: M/D/YY or MM/DD/YY at start of title
    match = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2})", title)
    if match:
        month, day, year = match.groups()
        # Convert 2-digit year to 4-digit
        year_int = int(year)
        if year_int < 50:
            year_full = 2000 + year_int
        else:
            year_full = 1900 + year_int
        try:
            dt = datetime(year_full, int(month), int(day))
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def parse_meeting_type(title: str) -> str | None:
    """Extract meeting type from title."""
    title_lower = title.lower()

    if "special meeting" in title_lower or "special" in title_lower:
        return "Special Meeting"
    if "planning commission" in title_lower:
        return "Planning Commission"
    if "city council" in title_lower:
        return "City Council"
    if "budget" in title_lower:
        return "Budget Meeting"

    return "City Council"  # Default


def format_duration(seconds: int) -> str:
    """Format duration in seconds to human-readable string."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


def sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    # Replace problematic characters
    sanitized = re.sub(r'[<>:"/\\|?*]', "_", name)
    # Remove leading/trailing whitespace and dots
    sanitized = sanitized.strip(". ")
    # Limit length
    return sanitized[:200]


def get_audio_path(clip_id: int, base_dir: Path) -> Path:
    """Get the audio file path for a clip."""
    return base_dir / f"{clip_id}.mp3"


def get_transcript_path(clip_id: int, base_dir: Path, model: str = "large-v3") -> Path:
    """Get the transcript file path for a clip."""
    model_suffix = model.replace("/", "_").replace("-", "_")
    return base_dir / f"{clip_id}_{model_suffix}.json"


def seconds_to_timestamp(seconds: int) -> str:
    """Convert seconds to HH:MM:SS format."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def timestamp_to_seconds(timestamp: str) -> int:
    """Convert HH:MM:SS or MM:SS format to seconds."""
    parts = timestamp.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    else:
        return int(parts[0])


def chunk_text(text: str, max_chars: int = 4000) -> list[str]:
    """
    Split text into chunks for LLM processing.
    Tries to split on sentence boundaries.
    """
    if len(text) <= max_chars:
        return [text]

    chunks = []
    current_chunk = ""

    # Split into sentences (rough approximation)
    sentences = re.split(r'(?<=[.!?])\s+', text)

    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 <= max_chars:
            current_chunk += (" " if current_chunk else "") + sentence
        else:
            if current_chunk:
                chunks.append(current_chunk)
            # If single sentence is too long, split by words
            if len(sentence) > max_chars:
                words = sentence.split()
                current_chunk = ""
                for word in words:
                    if len(current_chunk) + len(word) + 1 <= max_chars:
                        current_chunk += (" " if current_chunk else "") + word
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                        current_chunk = word
            else:
                current_chunk = sentence

    if current_chunk:
        chunks.append(current_chunk)

    return chunks
