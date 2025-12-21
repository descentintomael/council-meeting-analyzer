#!/usr/bin/env python3
"""Compare analysis results with and without speaker diarization."""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.table import Table
from council_analyzer.config import config

console = Console()


def load_original_analysis(clip_id: int) -> dict | None:
    """Load the original analysis results from database."""
    import sqlite3

    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row

    cursor = conn.execute(
        'SELECT analysis_type, result FROM analysis WHERE clip_id = ?',
        (clip_id,)
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return None

    # Combine all analysis results
    analysis = {"clip_id": clip_id, "segments": []}
    for row in rows:
        try:
            result = json.loads(row['result']) if row['result'] else {}
            analysis["segments"].append({
                "type": row['analysis_type'],
                "result": result
            })
        except json.JSONDecodeError:
            pass

    return analysis


def load_diarization(clip_id: int) -> dict | None:
    """Load diarization results."""
    path = config.TRANSCRIPT_DIR / f"{clip_id}_diarization.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def count_speakers_in_analysis(analysis: dict) -> dict:
    """Count speaker mentions in analysis text."""
    speaker_mentions = {}
    text = json.dumps(analysis).lower()

    # Known council members
    known = ["coolidge", "reynolds", "brown", "huber", "morgan", "stone", "tandon", "overbeek"]

    for name in known:
        count = text.count(name.lower())
        if count > 0:
            speaker_mentions[name.title()] = count

    return speaker_mentions


def main():
    console.print("=" * 60)
    console.print("[bold cyan]Diarization Comparison Analysis[/bold cyan]")
    console.print("=" * 60)
    console.print()

    clip_id = 1244

    # Load data
    original = load_original_analysis(clip_id)
    diarization = load_diarization(clip_id)

    if not original:
        console.print(f"[red]No original analysis found for {clip_id}[/red]")
        return

    if not diarization:
        console.print(f"[red]No diarization found for {clip_id}[/red]")
        return

    # Analyze diarization results
    console.print("[bold]1. Speaker Identification Summary[/bold]")
    console.print()

    speaker_segments = {}
    for seg in diarization['segments']:
        name = seg.get('speaker_name', 'Unknown')
        if name:
            speaker_segments[name] = speaker_segments.get(name, 0) + 1

    # Sort by segment count
    sorted_speakers = sorted(speaker_segments.items(), key=lambda x: -x[1])[:10]

    table = Table(title="Top 10 Identified Speakers")
    table.add_column("Speaker", style="cyan")
    table.add_column("Segments", style="green")
    table.add_column("Confidence", style="yellow")

    for name, count in sorted_speakers:
        # Find average confidence for this speaker
        confidences = [s['confidence'] for s in diarization['segments']
                      if s.get('speaker_name') == name]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0
        table.add_row(name, str(count), f"{avg_conf:.1%}")

    console.print(table)
    console.print()

    # Check for known council members
    console.print("[bold]2. Known Council Member Coverage[/bold]")
    console.print()
    known_members = ["Coolidge", "Reynolds", "Brown", "Huber", "Morgan", "Stone", "Tandon", "van Overbeek"]

    for member in known_members:
        found = any(member.lower() in (s.get('speaker_name') or '').lower()
                   for s in diarization['segments'])
        status = "[green]✓ Found[/green]" if found else "[red]✗ Not found[/red]"
        console.print(f"  {member}: {status}")

    console.print()

    # Analysis enhancement potential
    console.print("[bold]3. Analysis Enhancement Potential[/bold]")
    console.print()
    console.print("  Without diarization:")
    console.print("    - Transcript shows continuous text without speaker labels")
    console.print("    - Analysis must infer speakers from context")
    console.print()
    console.print("  With diarization:")
    console.print("    - Each segment tagged with speaker name and confidence")
    console.print("    - Analysis can attribute statements to specific speakers")
    console.print("    - Vote records can be more accurate (who said what)")
    console.print()

    # Compare speaker mentions in original analysis
    console.print("[bold]4. Speaker Mentions in Original Analysis[/bold]")
    console.print()

    mentions = count_speakers_in_analysis(original)
    if mentions:
        for name, count in sorted(mentions.items(), key=lambda x: -x[1]):
            console.print(f"  {name}: {count} mentions")
    else:
        console.print("  No council member names found in analysis")

    console.print()
    console.print("[bold green]Summary:[/bold green]")
    console.print(f"  Total segments analyzed: {len(diarization['segments'])}")
    console.print(f"  Segments with speaker ID: {sum(1 for s in diarization['segments'] if s.get('speaker_name'))}")
    console.print(f"  Unique speakers identified: {len(set(s.get('speaker_name') for s in diarization['segments'] if s.get('speaker_name')))}")
    console.print()
    console.print("[yellow]Recommendation:[/yellow]")
    console.print("  The diarization provides speaker context that can improve analysis accuracy.")
    console.print("  Consider enhancing the analysis prompts to use speaker attribution for:")
    console.print("    - More accurate vote records")
    console.print("    - Better advocacy intelligence (who supports what)")
    console.print("    - Clearer speaker positions on priority issues")


if __name__ == "__main__":
    main()
