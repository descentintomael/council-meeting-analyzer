"""Transcription validation with two-tier LLM coherence checking."""

import json
import re
from dataclasses import dataclass

import ollama
from jiwer import wer
from rich.console import Console

from .config import config
from .database import (
    get_agenda_items,
    get_meeting,
    get_meetings_by_status,
    get_transcript,
    insert_validation,
    log_processing,
    update_meeting_status,
)
from .utils import get_transcript_path

console = Console()


# Validation prompts
FAST_VALIDATION_PROMPT = """Check this transcript segment for errors. Return ONLY valid JSON, no other text.

Agenda: {agenda_title}
Text: {segment_text}

Known council members: Coolidge, Reynolds, Brown, Huber, Morgan, Stone, Tandon, van Overbeek
Known Chico terms: Bidwell, Esplanade, Valley's Edge, CARD, CUSD, Enloe, Butte County

Return this exact JSON format:
{{"score": 85, "issues": ["example issue"], "needs_deep_review": false}}"""

DEEP_VALIDATION_PROMPT = """You are validating a city council meeting transcript. Think through potential errors carefully.

Agenda Item: {agenda_title}
Transcript Segment: {segment_text}

Whisper Model Comparison:
- Large-v3 version: {large_text}
- Medium version: {medium_text}

Known council members: Coolidge, Reynolds, Brown, Huber, Morgan, Stone, Tandon, van Overbeek
Known Chico terms: Bidwell, Esplanade, Valley's Edge, CARD, CUSD, Enloe, Butte County

Analyze:
1. Which transcription is more accurate for proper nouns?
2. Are there nonsense words or repeated phrases?
3. Does the discussion match the agenda topic?
4. Are there obvious transcription errors?

Return ONLY valid JSON:
{{"coherence_score": 85, "preferred_transcription": "large_v3", "issues": ["list issues"], "corrections": {{"wrong": "right"}}, "needs_human_review": false}}"""


@dataclass
class ValidationResult:
    """Result of transcript validation."""

    clip_id: int
    wer_score: float
    divergent_segments: list[dict]
    tier1_scores: dict
    tier2_scores: dict
    validation_issues: list[str]
    merged_text: str
    human_review_needed: bool


def calculate_segment_wer(text1: str, text2: str) -> float:
    """Calculate Word Error Rate between two text segments."""
    if not text1 or not text2:
        return 1.0

    # Normalize texts
    text1 = text1.lower().strip()
    text2 = text2.lower().strip()

    if text1 == text2:
        return 0.0

    try:
        return wer(text1, text2)
    except Exception:
        return 1.0


def load_transcript_file(clip_id: int, model: str) -> dict | None:
    """Load a transcript JSON file."""
    path = get_transcript_path(clip_id, config.TRANSCRIPT_DIR, model)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def compare_transcripts(primary: dict, secondary: dict) -> tuple[float, list[dict]]:
    """
    Compare two transcripts and find divergent segments.

    Returns:
        Tuple of (overall_wer, list of divergent segment dicts)
    """
    primary_text = primary.get("text", "")
    secondary_text = secondary.get("text", "")

    overall_wer = calculate_segment_wer(primary_text, secondary_text)

    # Compare segment by segment
    primary_segments = primary.get("segments", [])
    secondary_segments = secondary.get("segments", [])

    divergent = []

    for i, p_seg in enumerate(primary_segments):
        p_text = p_seg.get("text", "")
        p_start = p_seg.get("start") or 0
        p_end = p_seg.get("end") or 0

        # Find corresponding segment in secondary by time overlap
        s_text = ""
        for s_seg in secondary_segments:
            s_start = s_seg.get("start") or 0
            s_end = s_seg.get("end") or 0

            # Check for time overlap
            if s_start <= p_end and s_end >= p_start:
                s_text += " " + s_seg.get("text", "")

        s_text = s_text.strip()
        seg_wer = calculate_segment_wer(p_text, s_text)

        if seg_wer > config.VALIDATION_WER_THRESHOLD:
            divergent.append({
                "segment_index": i,
                "start": p_start,
                "end": p_end,
                "wer": seg_wer,
                "large_text": p_text,
                "medium_text": s_text,
            })

    return overall_wer, divergent


def call_ollama(prompt: str, model: str) -> str:
    """Call Ollama API with the given prompt."""
    try:
        response = ollama.generate(
            model=model,
            prompt=prompt,
            options={
                "temperature": 0.2,
                "num_predict": 500,
            },
        )
        return response.get("response", "")
    except Exception as e:
        console.print(f"[red]Ollama error: {e}[/red]")
        return ""


def parse_json_response(response: str) -> dict | None:
    """Extract and parse JSON from LLM response."""
    # Try to find JSON in the response
    json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Try the whole response
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return None


def tier1_validate_segment(segment_text: str, agenda_title: str) -> dict:
    """
    Tier 1 fast validation using mistral.

    Returns:
        Dict with score, issues, and needs_deep_review flag
    """
    # Truncate long segments
    if len(segment_text) > 2000:
        segment_text = segment_text[:2000] + "..."

    prompt = FAST_VALIDATION_PROMPT.format(
        agenda_title=agenda_title or "General meeting content",
        segment_text=segment_text,
    )

    response = call_ollama(prompt, config.OLLAMA_MODEL_VALIDATION_FAST)
    result = parse_json_response(response)

    if result:
        return {
            "score": result.get("score") or 50,
            "issues": result.get("issues") or [],
            "needs_deep_review": result.get("needs_deep_review") or False,
        }
    else:
        return {
            "score": 50,
            "issues": ["Failed to parse validation response"],
            "needs_deep_review": True,
        }


def tier2_validate_segment(
    segment_text: str,
    agenda_title: str,
    large_text: str,
    medium_text: str,
) -> dict:
    """
    Tier 2 deep validation using deepseek-r1.

    Returns:
        Dict with detailed validation results
    """
    # Truncate long texts
    max_len = 1500
    segment_text = segment_text[:max_len] if len(segment_text) > max_len else segment_text
    large_text = large_text[:max_len] if len(large_text) > max_len else large_text
    medium_text = medium_text[:max_len] if len(medium_text) > max_len else medium_text

    prompt = DEEP_VALIDATION_PROMPT.format(
        agenda_title=agenda_title or "General meeting content",
        segment_text=segment_text,
        large_text=large_text,
        medium_text=medium_text,
    )

    response = call_ollama(prompt, config.OLLAMA_MODEL_VALIDATION_DEEP)
    result = parse_json_response(response)

    if result:
        return {
            "coherence_score": result.get("coherence_score") or 50,
            "preferred_transcription": result.get("preferred_transcription") or "large_v3",
            "issues": result.get("issues") or [],
            "corrections": result.get("corrections") or {},
            "needs_human_review": result.get("needs_human_review") or False,
        }
    else:
        return {
            "coherence_score": 50,
            "preferred_transcription": "large_v3",
            "issues": ["Failed to parse deep validation response"],
            "corrections": {},
            "needs_human_review": True,
        }


def validate_meeting(clip_id: int) -> ValidationResult | None:
    """
    Validate a transcribed meeting using two-tier LLM validation.

    Returns:
        ValidationResult or None on failure
    """
    meeting = get_meeting(clip_id)
    if not meeting:
        console.print(f"[red]Meeting {clip_id} not found[/red]")
        return None

    # Load both transcripts
    primary = load_transcript_file(clip_id, "large_v3")
    secondary = load_transcript_file(clip_id, "medium")

    if not primary:
        console.print(f"[red]No primary transcript found for {clip_id}[/red]")
        return None

    update_meeting_status(clip_id, "validating")
    log_processing(clip_id, "validate", "started", "Starting validation")

    try:
        # Compare transcripts
        if secondary:
            overall_wer, divergent_segments = compare_transcripts(primary, secondary)
            console.print(f"[cyan]Overall WER: {overall_wer:.2%}[/cyan]")
            console.print(f"[cyan]Divergent segments: {len(divergent_segments)}[/cyan]")
        else:
            overall_wer = 0.0
            divergent_segments = []
            console.print("[yellow]No secondary transcript for comparison[/yellow]")

        # Get agenda items for context
        agenda_items = get_agenda_items(clip_id)

        # Tier 1: Validate all segments
        tier1_scores = {}
        segments_needing_deep = []

        console.print("[cyan]Running Tier 1 validation (mistral)...[/cyan]")

        primary_segments = primary.get("segments", [])
        for i, segment in enumerate(primary_segments[:50]):  # Limit to first 50 segments
            segment_text = segment.get("text", "")
            segment_start = segment.get("start") or 0

            # Find matching agenda item
            agenda_title = None
            for item in agenda_items:
                item_start = item.get("start_seconds") or 0
                item_end = item.get("end_seconds")
                if item_start <= segment_start:
                    if item_end is None or item_end >= segment_start:
                        agenda_title = item.get("title")

            result = tier1_validate_segment(segment_text, agenda_title)
            tier1_scores[i] = result

            # Check if needs deep review
            if result["score"] < config.VALIDATION_COHERENCE_THRESHOLD or result["needs_deep_review"]:
                segments_needing_deep.append({
                    "index": i,
                    "segment": segment,
                    "agenda_title": agenda_title,
                })

        # Add divergent segments to deep review list
        for div_seg in divergent_segments:
            if div_seg["segment_index"] not in [s["index"] for s in segments_needing_deep]:
                segments_needing_deep.append({
                    "index": div_seg["segment_index"],
                    "segment": primary_segments[div_seg["segment_index"]] if div_seg["segment_index"] < len(primary_segments) else {},
                    "agenda_title": None,
                    "divergent": div_seg,
                })

        # Tier 2: Deep validation for flagged segments
        tier2_scores = {}
        if segments_needing_deep:
            console.print(f"[cyan]Running Tier 2 validation on {len(segments_needing_deep)} segments (deepseek-r1)...[/cyan]")

            for item in segments_needing_deep[:20]:  # Limit deep validation
                idx = item["index"]
                segment = item["segment"]
                segment_text = segment.get("text", "")

                # Get comparison texts
                large_text = segment_text
                medium_text = ""
                if "divergent" in item:
                    large_text = item["divergent"].get("large_text", segment_text)
                    medium_text = item["divergent"].get("medium_text", "")
                elif secondary:
                    # Try to find matching secondary segment
                    seg_start = segment.get("start") or 0
                    for s_seg in secondary.get("segments", []):
                        s_seg_start = s_seg.get("start") or 0
                        if abs(s_seg_start - seg_start) < 5:
                            medium_text = s_seg.get("text", "")
                            break

                result = tier2_validate_segment(
                    segment_text,
                    item.get("agenda_title"),
                    large_text,
                    medium_text,
                )
                tier2_scores[idx] = result

        # Collect all issues
        all_issues = []
        human_review_needed = False

        for idx, score in tier1_scores.items():
            all_issues.extend(score.get("issues", []))

        for idx, score in tier2_scores.items():
            all_issues.extend(score.get("issues", []))
            if score.get("needs_human_review"):
                human_review_needed = True

        # Use primary transcript as merged (could be enhanced with corrections)
        merged_text = primary.get("text", "")

        # Save validation results
        insert_validation(
            clip_id=clip_id,
            large_v3_text=primary.get("text", ""),
            medium_text=secondary.get("text", "") if secondary else "",
            merged_text=merged_text,
            wer_score=overall_wer,
            divergent_segments=divergent_segments,
            tier1_scores=tier1_scores,
            tier2_scores=tier2_scores,
            validation_issues=list(set(all_issues)),  # Dedupe
            human_review_needed=human_review_needed,
        )

        update_meeting_status(clip_id, "validated")
        log_processing(clip_id, "validate", "completed", f"WER: {overall_wer:.2%}, Issues: {len(all_issues)}")

        console.print(f"[green]Validation complete for {clip_id}[/green]")
        console.print(f"  WER: {overall_wer:.2%}")
        console.print(f"  Issues found: {len(all_issues)}")
        console.print(f"  Human review needed: {human_review_needed}")

        return ValidationResult(
            clip_id=clip_id,
            wer_score=overall_wer,
            divergent_segments=divergent_segments,
            tier1_scores=tier1_scores,
            tier2_scores=tier2_scores,
            validation_issues=list(set(all_issues)),
            merged_text=merged_text,
            human_review_needed=human_review_needed,
        )

    except Exception as e:
        console.print(f"[red]Validation error for {clip_id}: {e}[/red]")
        update_meeting_status(clip_id, "failed")
        log_processing(clip_id, "validate", "failed", str(e))
        return None


def validate_batch(batch_size: int = 5) -> dict:
    """
    Validate a batch of transcribed meetings.

    Returns:
        Stats dict
    """
    stats = {"validated": 0, "failed": 0, "needs_review": 0}

    pending = get_meetings_by_status("transcribed")[:batch_size]

    if not pending:
        console.print("[yellow]No meetings pending validation[/yellow]")
        return stats

    console.print(f"[bold]Validating {len(pending)} meetings...[/bold]")

    for meeting in pending:
        clip_id = meeting["clip_id"]
        console.print(f"\n[bold cyan]Validating {clip_id}: {meeting['title']}[/bold cyan]")

        result = validate_meeting(clip_id)
        if result:
            stats["validated"] += 1
            if result.human_review_needed:
                stats["needs_review"] += 1
        else:
            stats["failed"] += 1

    console.print(f"\n[bold green]Validation batch complete![/bold green]")
    console.print(f"  Validated: {stats['validated']}")
    console.print(f"  Failed: {stats['failed']}")
    console.print(f"  Needs human review: {stats['needs_review']}")

    return stats


if __name__ == "__main__":
    validate_batch()
