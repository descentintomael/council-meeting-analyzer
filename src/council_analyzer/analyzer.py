"""LLM analysis of meeting transcripts using qwen2.5vl."""

import json
import re

import ollama
from rich.console import Console

from .config import config
from .database import (
    get_meeting,
    get_meetings_by_status,
    get_transcript,
    insert_analysis,
    log_processing,
    update_meeting_status,
)
from .segmenter import segment_meeting
from .utils import chunk_text

console = Console()


def load_diarization(clip_id: int) -> dict | None:
    """Load diarization results for a meeting if available."""
    diarization_path = config.TRANSCRIPT_DIR / f"{clip_id}_diarization.json"
    if not diarization_path.exists():
        return None

    try:
        with open(diarization_path) as f:
            return json.load(f)
    except Exception as e:
        console.print(f"[yellow]Could not load diarization: {e}[/yellow]")
        return None


def enhance_text_with_speakers(text: str, diarization: dict) -> str:
    """
    Enhance transcript text with speaker attributions from diarization.

    Returns text with speaker labels prepended where identified.
    """
    if not diarization:
        return text

    segments = diarization.get("segments", [])
    speaker_mapping = diarization.get("speaker_mapping", {})

    # Build a list of (text_snippet, speaker_name) pairs
    speaker_labels = []
    for seg in segments:
        speaker_name = seg.get("speaker_name")
        if speaker_name and seg.get("text"):
            speaker_labels.append({
                "text": seg["text"][:50],  # First 50 chars for matching
                "speaker": speaker_name,
                "confidence": seg.get("confidence", 0)
            })

    if not speaker_labels:
        return text

    # Add speaker context header
    identified_speakers = [s for s in speaker_mapping.values() if s]
    if identified_speakers:
        header = f"[Identified speakers: {', '.join(set(identified_speakers))}]\n\n"
        return header + text

    return text


def get_speaker_summary(diarization: dict) -> str:
    """Generate a summary of identified speakers for prompts."""
    if not diarization:
        return ""

    speaker_mapping = diarization.get("speaker_mapping", {})
    identified = {k: v for k, v in speaker_mapping.items() if v}

    if not identified:
        return ""

    lines = ["Identified speakers in this meeting:"]
    for speaker_id, name in identified.items():
        lines.append(f"  - {name}")

    return "\n".join(lines)


# Analysis prompts for Smart Growth Advocates
ANALYSIS_PROMPTS = {
    "summary": """Summarize this city council meeting segment in 3-5 bullet points.
Focus on:
- Key decisions made
- Major debates or disagreements
- Action items or next steps
- Public comment themes

Segment:
{text}

Return JSON: {{"summary": ["bullet1", "bullet2", ...]}}""",

    "advocacy_intel": """Analyze this city council meeting segment for Smart Growth advocacy intelligence.

Extract:
1. Housing and development discussions
2. Zoning changes or proposals
3. Infrastructure and transit topics
4. Environmental and sustainability mentions
5. Council member positions on growth issues

Segment:
{text}

Agenda Item: {agenda_title}

Return JSON:
{{
  "housing_mentions": ["list of housing-related discussions"],
  "zoning_topics": ["any zoning changes discussed"],
  "infrastructure": ["infrastructure topics"],
  "sustainability": ["environmental mentions"],
  "council_positions": {{"member_name": "their stated position"}},
  "key_quotes": ["notable quotes"],
  "action_items": ["decisions or next steps"]
}}""",

    "vote_record": """Extract all votes from this meeting segment.

For each vote, identify:
- What was voted on
- Who made the motion
- Who seconded
- Vote result
- Individual votes if mentioned

Segment:
{text}

Return JSON:
{{
  "votes": [
    {{
      "motion": "description of what was voted on",
      "mover": "who made motion",
      "seconder": "who seconded",
      "result": "passed/failed",
      "vote_count": {{"yes": 0, "no": 0, "abstain": 0}},
      "individual_votes": {{"member": "yes/no/abstain"}}
    }}
  ]
}}""",

    "priority_alerts": """Check this segment for these priority topics for Smart Growth Advocates:
- Valley's Edge development
- Parking minimums or parking reform
- Missing middle housing
- Infill development
- Groundwater or water supply
- Infrastructure deficit
- Form-based codes
- ADU (accessory dwelling units)

For each mention, note the context and who said it.

Segment:
{text}

Return JSON:
{{
  "alerts": [
    {{
      "keyword": "the priority topic found",
      "context": "what was said about it",
      "speaker": "who mentioned it",
      "sentiment": "supportive/opposed/neutral"
    }}
  ]
}}""",

    "opposition_tracking": """Find statements by these council members in this segment:
- Tom van Overbeek
- Kasey Reynolds

For each statement, note:
- The topic being discussed
- Their stated position
- How they voted (if applicable)

Segment:
{text}

Return JSON:
{{
  "van_overbeek": [
    {{"topic": "topic", "position": "their stance", "quote": "relevant quote"}}
  ],
  "reynolds": [
    {{"topic": "topic", "position": "their stance", "quote": "relevant quote"}}
  ]
}}""",

    "public_comment": """Summarize public comments in this segment:
- How many speakers (estimate)
- Main topics raised
- General sentiment
- Any notable organizations represented

Segment:
{text}

Return JSON:
{{
  "speaker_count": 0,
  "topics": ["main topics"],
  "sentiment_summary": "overall tone",
  "organizations": ["groups represented"],
  "key_points": ["main points raised"]
}}""",
}


def call_ollama_analysis(prompt: str) -> dict | None:
    """Call Ollama for analysis and parse JSON response."""
    try:
        response = ollama.generate(
            model=config.OLLAMA_MODEL_ANALYSIS,
            prompt=prompt,
            options={
                "temperature": 0.3,
                "num_predict": 2000,
            },
        )

        response_text = response.get("response", "")

        # Try to extract JSON
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # Try parsing whole response
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            console.print(f"[yellow]Could not parse JSON response[/yellow]")
            return {"raw_response": response_text}

    except Exception as e:
        console.print(f"[red]Ollama analysis error: {e}[/red]")
        return None


def analyze_segment(
    text: str,
    analysis_type: str,
    agenda_title: str | None = None,
) -> dict | None:
    """
    Analyze a single segment with a specific analysis type.

    Returns:
        Analysis result dict or None on failure
    """
    if analysis_type not in ANALYSIS_PROMPTS:
        console.print(f"[red]Unknown analysis type: {analysis_type}[/red]")
        return None

    prompt_template = ANALYSIS_PROMPTS[analysis_type]

    # Handle long text by chunking
    if len(text) > 6000:
        text = text[:6000] + "... [truncated]"

    prompt = prompt_template.format(
        text=text,
        agenda_title=agenda_title or "General meeting content",
    )

    return call_ollama_analysis(prompt)


def analyze_meeting(
    clip_id: int,
    analysis_types: list[str] | None = None,
) -> dict:
    """
    Analyze a meeting with specified analysis types.

    Args:
        clip_id: Meeting clip ID
        analysis_types: List of analysis types to run (None = all)

    Returns:
        Dict with all analysis results
    """
    if analysis_types is None:
        analysis_types = ["summary", "advocacy_intel", "vote_record", "priority_alerts"]

    meeting = get_meeting(clip_id)
    if not meeting:
        console.print(f"[red]Meeting {clip_id} not found[/red]")
        return {}

    transcript = get_transcript(clip_id)
    if not transcript:
        console.print(f"[red]No transcript for {clip_id}[/red]")
        return {}

    # Load diarization data if available
    diarization = load_diarization(clip_id)
    if diarization:
        identified = diarization.get("identified_speakers", 0)
        total = diarization.get("total_speakers", 0)
        console.print(f"[green]Using diarization: {identified}/{total} speakers identified[/green]")
    else:
        console.print("[yellow]No diarization data available[/yellow]")

    update_meeting_status(clip_id, "analyzing")
    log_processing(clip_id, "analyze", "started", f"Analysis types: {analysis_types}")

    results = {}
    results["diarization_used"] = diarization is not None

    try:
        # Get segments
        segments = segment_meeting(clip_id)

        if not segments:
            # Fall back to full transcript
            segments = [{
                "agenda_item_id": None,
                "item_title": None,
                "text": transcript.get("full_text", ""),
            }]

        # Get speaker context for prompts
        speaker_context = get_speaker_summary(diarization) if diarization else ""

        # Analyze each segment
        for i, segment in enumerate(segments):
            segment_text = segment.get("text", "")
            if not segment_text or len(segment_text) < 50:
                continue

            # Enhance segment text with speaker identifications
            enhanced_text = enhance_text_with_speakers(segment_text, diarization)

            agenda_title = segment.get("item_title")
            segment_key = f"segment_{i}"
            results[segment_key] = {
                "agenda_item": agenda_title,
                "analyses": {},
                "speaker_enhanced": diarization is not None,
            }

            for analysis_type in analysis_types:
                console.print(
                    f"[cyan]Analyzing segment {i+1}/{len(segments)}: {analysis_type}[/cyan]"
                )

                # Use enhanced text with speaker context
                result = analyze_segment(enhanced_text, analysis_type, agenda_title)
                if result:
                    results[segment_key]["analyses"][analysis_type] = result

                    # Save to database
                    insert_analysis(
                        clip_id=clip_id,
                        analysis_type=analysis_type,
                        result=result,
                        agenda_item_id=segment.get("agenda_item_id"),
                        model_used=config.OLLAMA_MODEL_ANALYSIS,
                    )

        # Generate meeting-level summary
        full_text = transcript.get("full_text", "")
        if len(full_text) > 8000:
            # Summarize in chunks then combine
            chunks = chunk_text(full_text, 4000)
            chunk_summaries = []
            for chunk in chunks[:3]:  # Limit to first 3 chunks
                result = analyze_segment(chunk, "summary")
                if result and "summary" in result:
                    chunk_summaries.extend(result["summary"])

            results["meeting_summary"] = {"summary": chunk_summaries[:10]}
        else:
            results["meeting_summary"] = analyze_segment(full_text, "summary")

        update_meeting_status(clip_id, "analyzed")
        log_processing(clip_id, "analyze", "completed", f"Completed {len(analysis_types)} analysis types")

        console.print(f"[green]Analysis complete for {clip_id}[/green]")
        return results

    except Exception as e:
        console.print(f"[red]Analysis error for {clip_id}: {e}[/red]")
        update_meeting_status(clip_id, "failed")
        log_processing(clip_id, "analyze", "failed", str(e))
        return {}


def analyze_batch(batch_size: int = 1) -> dict:
    """
    Analyze a batch of validated meetings.

    Returns:
        Stats dict
    """
    stats = {"analyzed": 0, "failed": 0}

    # Get meetings ready for analysis (validated status)
    pending = get_meetings_by_status("validated")[:batch_size]

    if not pending:
        console.print("[yellow]No meetings pending analysis[/yellow]")
        return stats

    console.print(f"[bold]Analyzing {len(pending)} meetings...[/bold]")

    for meeting in pending:
        clip_id = meeting["clip_id"]
        console.print(f"\n[bold cyan]Analyzing {clip_id}: {meeting['title']}[/bold cyan]")

        results = analyze_meeting(clip_id)
        if results:
            stats["analyzed"] += 1
        else:
            stats["failed"] += 1

    console.print(f"\n[bold green]Analysis batch complete![/bold green]")
    console.print(f"  Analyzed: {stats['analyzed']}")
    console.print(f"  Failed: {stats['failed']}")

    return stats


if __name__ == "__main__":
    analyze_batch()
