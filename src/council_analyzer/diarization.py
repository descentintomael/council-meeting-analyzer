"""Speaker diarization with multiple identification methods."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import ollama
from rich.console import Console

from .config import config
from .database import (
    get_agenda_items,
    get_meeting,
    get_transcript,
    log_processing,
    update_meeting_status,
)
from .utils import get_audio_path, get_transcript_path

console = Console()

# Known speakers in Chico City Council
KNOWN_COUNCIL_MEMBERS = [
    "Coolidge",  # Mayor
    "Reynolds",
    "Brown",
    "Huber",
    "Morgan",
    "Stone",
    "Tandon",
    "van Overbeek",
]

KNOWN_STAFF_ROLES = [
    "City Manager",
    "City Attorney",
    "City Clerk",
    "Public Works Director",
    "Community Development Director",
    "Police Chief",
    "Fire Chief",
    "Finance Director",
]

# Patterns for speaker identification from transcript
SPEAKER_PATTERNS = [
    # Self-identification
    r"(?:this is|I'm|I am)\s+(?:Council(?:member|man|woman)?|Mayor|Vice Mayor)?\s*(\w+(?:\s+\w+)?)",
    # Being addressed
    r"(?:thank you|thanks),?\s+(?:Council(?:member|man|woman)?|Mayor|Vice Mayor)?\s*(\w+)",
    # Motion patterns
    r"(?:I move|I second|motion by)\s+(?:Council(?:member|man|woman)?|Mayor|Vice Mayor)?\s*(\w+)",
    # Staff presentations
    r"(\w+(?:\s+\w+)?),?\s+(?:your|our)\s+(?:City Manager|City Attorney|Director|Chief)",
]


@dataclass
class SpeakerSegment:
    """A segment of audio attributed to a speaker."""

    start: float
    end: float
    speaker_id: str  # SPEAKER_00, SPEAKER_01, etc. (from diarization)
    speaker_name: str | None = None  # Identified name
    confidence: float = 0.0
    text: str = ""
    identification_method: str = ""  # "pyannote", "llm", "agenda", "pattern"


@dataclass
class DiarizationResult:
    """Result of speaker diarization and identification."""

    clip_id: int
    segments: list[SpeakerSegment] = field(default_factory=list)
    speaker_mapping: dict = field(default_factory=dict)  # SPEAKER_XX -> name
    total_speakers: int = 0
    identified_speakers: int = 0


def try_load_pyannote():
    """Try to load pyannote if available (requires optional diarization extras)."""
    try:
        from pyannote.audio import Pipeline
        import torch
        return True
    except ImportError:
        return False


PYANNOTE_AVAILABLE = try_load_pyannote()


def run_pyannote_diarization(audio_path: Path) -> list[tuple[float, float, str]]:
    """
    Run pyannote speaker diarization on audio file if available.

    Returns:
        List of (start, end, speaker_id) tuples
    """
    if not PYANNOTE_AVAILABLE:
        console.print("[yellow]Pyannote not available - using LLM-only speaker identification[/yellow]")
        return []

    try:
        from pyannote.audio import Pipeline
        import torch

        console.print("[cyan]Running pyannote speaker diarization...[/cyan]")

        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=config.HUGGINGFACE_TOKEN if hasattr(config, 'HUGGINGFACE_TOKEN') else None,
        )

        # Use MPS (Apple Silicon) if available
        if torch.backends.mps.is_available():
            pipeline.to(torch.device("mps"))
        elif torch.cuda.is_available():
            pipeline.to(torch.device("cuda"))

        diarization = pipeline(str(audio_path))

        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append((turn.start, turn.end, speaker))

        console.print(f"[green]Found {len(set(s[2] for s in segments))} unique speakers[/green]")
        return segments

    except Exception as e:
        console.print(f"[yellow]Pyannote diarization failed: {e}[/yellow]")
        return []


def identify_speakers_from_patterns(transcript_segments: list[dict]) -> dict[str, list[str]]:
    """
    Identify speakers using regex patterns on transcript text.

    Returns:
        Dict mapping estimated speaker positions to possible names
    """
    identifications = {}

    for i, seg in enumerate(transcript_segments):
        text = seg.get("text", "")

        for pattern in SPEAKER_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                name = match.strip()
                # Check if it's a known council member
                for member in KNOWN_COUNCIL_MEMBERS:
                    if member.lower() in name.lower():
                        segment_key = f"seg_{i}"
                        if segment_key not in identifications:
                            identifications[segment_key] = []
                        identifications[segment_key].append(member)

    return identifications


def identify_speakers_from_agenda(
    transcript_segments: list[dict],
    agenda_items: list[dict],
) -> dict[int, str]:
    """
    Identify speakers by correlating with agenda item presenters.

    Returns:
        Dict mapping segment index to likely speaker
    """
    identifications = {}

    for i, seg in enumerate(transcript_segments):
        seg_start = seg.get("start", 0) or 0

        # Find which agenda item this segment belongs to
        for item in agenda_items:
            item_start = item.get("start_seconds") or 0
            item_end = item.get("end_seconds")

            if item_start <= seg_start and (item_end is None or item_end >= seg_start):
                # Check if agenda item has a presenter
                presenter = item.get("presenter")
                if presenter:
                    identifications[i] = presenter
                break

    return identifications


def identify_speakers_with_llm(
    transcript_segments: list[dict],
    agenda_context: str,
) -> list[dict]:
    """
    Use LLM to identify speakers from transcript context.

    Returns:
        List of dicts with speaker identifications per segment
    """
    # Process in batches to manage context size
    batch_size = 10
    all_identifications = []

    prompt_template = """Analyze this city council meeting transcript and identify who is speaking in each segment.

Known Council Members: Coolidge (Mayor), Reynolds, Brown, Huber, Morgan, Stone, Tandon, van Overbeek
Known Staff: City Manager, City Attorney, City Clerk, various Directors

Agenda Context: {agenda}

Transcript Segments:
{segments}

For each segment, identify the likely speaker based on:
1. Self-identification ("This is Council Member X")
2. Being addressed ("Thank you, Mayor")
3. Speech patterns (motions = council members, presentations = staff)
4. Context from previous/next segments

Return ONLY valid JSON array with one object per segment:
[{{"segment_index": 0, "speaker": "Council Member Brown", "confidence": 0.8, "reason": "Self-identified"}}]"""

    for batch_start in range(0, len(transcript_segments), batch_size):
        batch = transcript_segments[batch_start:batch_start + batch_size]

        # Format segments for prompt
        segments_text = "\n".join([
            f"[{batch_start + i}] (t={seg.get('start', 0):.1f}s): {seg.get('text', '')[:200]}"
            for i, seg in enumerate(batch)
        ])

        prompt = prompt_template.format(
            agenda=agenda_context[:1000],
            segments=segments_text,
        )

        try:
            response = ollama.generate(
                model=config.OLLAMA_MODEL_VALIDATION_FAST,  # Use faster model for this
                prompt=prompt,
                options={"temperature": 0.3, "num_predict": 1000},
            )

            # Parse JSON response
            response_text = response.get("response", "")
            json_match = re.search(r'\[[\s\S]*\]', response_text)
            if json_match:
                identifications = json.loads(json_match.group())
                all_identifications.extend(identifications)

        except Exception as e:
            console.print(f"[yellow]LLM identification batch failed: {e}[/yellow]")

    return all_identifications


def merge_speaker_identifications(
    pyannote_segments: list[tuple[float, float, str]],
    pattern_ids: dict[str, list[str]],
    agenda_ids: dict[int, str],
    llm_ids: list[dict],
    transcript_segments: list[dict],
) -> DiarizationResult:
    """
    Merge all speaker identification methods into a unified result.

    Priority: Pattern matching > Agenda > LLM > Pyannote
    """
    result = DiarizationResult(clip_id=0)
    speaker_votes = {}  # Track votes for each pyannote speaker ID

    # Create mapping from pyannote segments
    pyannote_map = {}  # segment_index -> pyannote_speaker_id
    for start, end, speaker_id in pyannote_segments:
        for i, seg in enumerate(transcript_segments):
            seg_start = seg.get("start", 0) or 0
            seg_end = seg.get("end", 0) or 0
            if seg_start >= start and seg_end <= end:
                pyannote_map[i] = speaker_id
                if speaker_id not in speaker_votes:
                    speaker_votes[speaker_id] = {}

    # Process each transcript segment
    for i, seg in enumerate(transcript_segments):
        speaker_segment = SpeakerSegment(
            start=seg.get("start", 0) or 0,
            end=seg.get("end", 0) or 0,
            speaker_id=pyannote_map.get(i, f"UNKNOWN_{i}"),
            text=seg.get("text", ""),
        )

        pyannote_id = pyannote_map.get(i)

        # Check pattern identifications (highest confidence)
        seg_key = f"seg_{i}"
        if seg_key in pattern_ids and pattern_ids[seg_key]:
            speaker_segment.speaker_name = pattern_ids[seg_key][0]
            speaker_segment.confidence = 0.9
            speaker_segment.identification_method = "pattern"
            if pyannote_id:
                name = pattern_ids[seg_key][0]
                speaker_votes[pyannote_id][name] = speaker_votes[pyannote_id].get(name, 0) + 2

        # Check agenda identifications
        elif i in agenda_ids:
            speaker_segment.speaker_name = agenda_ids[i]
            speaker_segment.confidence = 0.7
            speaker_segment.identification_method = "agenda"
            if pyannote_id:
                speaker_votes[pyannote_id][agenda_ids[i]] = speaker_votes[pyannote_id].get(agenda_ids[i], 0) + 1.5

        # Check LLM identifications
        else:
            for llm_id in llm_ids:
                if llm_id.get("segment_index") == i:
                    speaker_segment.speaker_name = llm_id.get("speaker")
                    speaker_segment.confidence = llm_id.get("confidence", 0.5)
                    speaker_segment.identification_method = "llm"
                    if pyannote_id and speaker_segment.speaker_name:
                        name = speaker_segment.speaker_name
                        speaker_votes[pyannote_id][name] = speaker_votes[pyannote_id].get(name, 0) + 1
                    break

        result.segments.append(speaker_segment)

    # Build speaker mapping from votes
    for speaker_id, votes in speaker_votes.items():
        if votes:
            best_name = max(votes, key=votes.get)
            result.speaker_mapping[speaker_id] = best_name

    # Apply mapping to segments without direct identification
    for seg in result.segments:
        if not seg.speaker_name and seg.speaker_id in result.speaker_mapping:
            seg.speaker_name = result.speaker_mapping[seg.speaker_id]
            seg.confidence = 0.6
            seg.identification_method = "pyannote_mapped"

    result.total_speakers = len(set(s.speaker_id for s in result.segments))
    result.identified_speakers = len(result.speaker_mapping)

    return result


def diarize_meeting(clip_id: int) -> DiarizationResult | None:
    """
    Perform full speaker diarization and identification on a meeting.

    Uses multiple methods:
    1. Pyannote neural speaker diarization
    2. Regex pattern matching on transcript
    3. Agenda item correlation
    4. LLM-based inference

    Returns:
        DiarizationResult or None on failure
    """
    meeting = get_meeting(clip_id)
    if not meeting:
        console.print(f"[red]Meeting {clip_id} not found[/red]")
        return None

    console.print(f"[bold cyan]Diarizing meeting {clip_id}: {meeting['title']}[/bold cyan]")

    # Get audio and transcript paths
    audio_path = get_audio_path(clip_id, config.AUDIO_DIR)
    transcript_path = get_transcript_path(clip_id, config.TRANSCRIPT_DIR, "large_v3")

    if not audio_path.exists():
        console.print(f"[red]Audio file not found: {audio_path}[/red]")
        return None

    if not transcript_path.exists():
        console.print(f"[red]Transcript not found: {transcript_path}[/red]")
        return None

    # Load transcript
    with open(transcript_path) as f:
        transcript = json.load(f)
    transcript_segments = transcript.get("segments", [])

    log_processing(clip_id, "diarize", "started", "Starting speaker diarization")

    try:
        # Method 1: Pyannote diarization
        console.print("[cyan]Step 1: Neural speaker diarization (pyannote)...[/cyan]")
        pyannote_segments = run_pyannote_diarization(audio_path)

        # Method 2: Pattern matching
        console.print("[cyan]Step 2: Pattern-based speaker identification...[/cyan]")
        pattern_ids = identify_speakers_from_patterns(transcript_segments)
        console.print(f"  Found {sum(len(v) for v in pattern_ids.values())} pattern matches")

        # Method 3: Agenda correlation
        console.print("[cyan]Step 3: Agenda-based speaker correlation...[/cyan]")
        agenda_items = get_agenda_items(clip_id)
        agenda_ids = identify_speakers_from_agenda(transcript_segments, agenda_items)
        console.print(f"  Matched {len(agenda_ids)} segments to agenda presenters")

        # Method 4: LLM inference
        console.print("[cyan]Step 4: LLM-based speaker inference...[/cyan]")
        agenda_context = "\n".join([
            f"- {item.get('title', 'Unknown')}"
            for item in agenda_items[:10]
        ])
        llm_ids = identify_speakers_with_llm(transcript_segments[:100], agenda_context)
        console.print(f"  LLM identified {len(llm_ids)} speaker assignments")

        # Merge all identifications
        console.print("[cyan]Step 5: Merging identifications...[/cyan]")
        result = merge_speaker_identifications(
            pyannote_segments,
            pattern_ids,
            agenda_ids,
            llm_ids,
            transcript_segments,
        )
        result.clip_id = clip_id

        # Save diarization results
        output_path = config.TRANSCRIPT_DIR / f"{clip_id}_diarization.json"
        with open(output_path, "w") as f:
            json.dump({
                "clip_id": clip_id,
                "total_speakers": result.total_speakers,
                "identified_speakers": result.identified_speakers,
                "speaker_mapping": result.speaker_mapping,
                "segments": [
                    {
                        "start": s.start,
                        "end": s.end,
                        "speaker_id": s.speaker_id,
                        "speaker_name": s.speaker_name,
                        "confidence": s.confidence,
                        "method": s.identification_method,
                        "text": s.text[:500],
                    }
                    for s in result.segments
                ],
            }, f, indent=2)

        log_processing(clip_id, "diarize", "completed",
                       f"Identified {result.identified_speakers}/{result.total_speakers} speakers")

        console.print(f"[green]Diarization complete:[/green]")
        console.print(f"  Total speakers detected: {result.total_speakers}")
        console.print(f"  Speakers identified: {result.identified_speakers}")
        console.print(f"  Speaker mapping: {result.speaker_mapping}")

        return result

    except Exception as e:
        console.print(f"[red]Diarization error: {e}[/red]")
        log_processing(clip_id, "diarize", "failed", str(e))
        return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        clip_id = int(sys.argv[1])
        diarize_meeting(clip_id)
    else:
        console.print("Usage: python -m council_analyzer.diarization <clip_id>")
