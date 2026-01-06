#!/usr/bin/env python3
"""
Compare large_v3 and medium model transcripts to identify and fix hallucinations.

Uses segment timestamps to align the two transcriptions and identify where
they diverge significantly (potential hallucinations).
"""

import json
import re
from pathlib import Path
from dataclasses import dataclass

PROJECT_ROOT = Path(__file__).parent.parent
TRANSCRIPT_DIR = PROJECT_ROOT / "data" / "transcripts"


@dataclass
class Segment:
    """A transcript segment with timing."""
    start: float
    end: float
    text: str
    no_speech_prob: float = 0.0


def load_segments(clip_id: int, model: str = "large_v3") -> list[Segment]:
    """Load segments from a transcript file."""
    path = TRANSCRIPT_DIR / f"{clip_id}_{model}.json"
    if not path.exists():
        return []

    with open(path) as f:
        data = json.load(f)

    segments = []
    for seg in data.get("segments", []):
        segments.append(Segment(
            start=seg.get("start", 0),
            end=seg.get("end", 0),
            text=seg.get("text", ""),
            no_speech_prob=seg.get("no_speech_prob", 0)
        ))

    return segments


def detect_repetition(text: str) -> tuple[bool, str]:
    """Check if text contains severe repetition."""
    # Pattern: word(s) repeated 5+ times
    pattern = r'\b((?:\w+\s+){0,2}\w+)(\s+\1){4,}'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return True, match.group(1)
    return False, ""


def find_segments_at_time(segments: list[Segment], start: float, end: float) -> list[Segment]:
    """Find all segments that overlap with the given time range."""
    return [s for s in segments if s.start < end and s.end > start]


def compare_transcripts(clip_id: int):
    """Compare large_v3 and medium transcripts for a clip."""
    large_segs = load_segments(clip_id, "large_v3")
    medium_segs = load_segments(clip_id, "medium")

    if not large_segs or not medium_segs:
        print(f"Missing transcripts for clip {clip_id}")
        return

    print(f"Clip {clip_id}: {len(large_segs)} large segments, {len(medium_segs)} medium segments")

    # Find hallucinations in large_v3
    hallucinations = []
    for i, seg in enumerate(large_segs):
        has_rep, pattern = detect_repetition(seg.text)
        if has_rep:
            hallucinations.append((i, seg, pattern))

    if not hallucinations:
        print("  No hallucinations detected in large_v3")
        return

    print(f"  Found {len(hallucinations)} potential hallucinations")

    # For each hallucination, compare with medium
    fixes = []
    for idx, seg, pattern in hallucinations[:10]:  # First 10
        print(f"\n  Segment {idx} ({seg.start:.1f}s - {seg.end:.1f}s):")
        print(f"    Large: {seg.text[:80]}...")
        print(f"    Pattern: '{pattern}' repeated")

        # Find corresponding medium segments
        medium_match = find_segments_at_time(medium_segs, seg.start, seg.end)
        if medium_match:
            medium_text = " ".join(s.text for s in medium_match).strip()
            has_same_rep, _ = detect_repetition(medium_text)

            if not has_same_rep:
                print(f"    Medium: {medium_text[:80]}...")
                print(f"    → FIXABLE: Medium doesn't have this hallucination")
                fixes.append({
                    "segment_idx": idx,
                    "start": seg.start,
                    "end": seg.end,
                    "large_text": seg.text,
                    "medium_text": medium_text
                })
            else:
                print(f"    Medium: {medium_text[:80]}...")
                print(f"    → UNFIXABLE: Medium has same issue")
        else:
            print(f"    → No matching medium segments")

    return fixes


def fix_with_medium(clip_id: int, fixes: list[dict], dry_run: bool = True):
    """Apply fixes by replacing hallucinated segments with medium text."""
    large_path = TRANSCRIPT_DIR / f"{clip_id}_large_v3.json"

    with open(large_path) as f:
        data = json.load(f)

    segments = data.get("segments", [])
    fixed_count = 0

    for fix in fixes:
        idx = fix["segment_idx"]
        if idx < len(segments):
            old_text = segments[idx]["text"]
            new_text = fix["medium_text"]

            if not dry_run:
                segments[idx]["text"] = new_text
                segments[idx]["fixed_from_medium"] = True

            fixed_count += 1
            print(f"  Segment {idx}: '{old_text[:40]}...' → '{new_text[:40]}...'")

    if not dry_run:
        # Rebuild full text
        data["text"] = " ".join(seg["text"] for seg in segments)
        data["segments"] = segments
        data["hallucinations_fixed"] = fixed_count

        with open(large_path, "w") as f:
            json.dump(data, f, indent=2)

        print(f"\nSaved {fixed_count} fixes to {large_path}")

    return fixed_count


def main():
    import sys

    if len(sys.argv) < 2:
        print("Usage: python compare_models.py <clip_id> [--fix]")
        print("Example: python compare_models.py 1196 --fix")
        return

    clip_id = int(sys.argv[1])
    do_fix = "--fix" in sys.argv

    fixes = compare_transcripts(clip_id)

    if fixes and do_fix:
        print(f"\n{'='*60}")
        print("APPLYING FIXES")
        print("="*60)
        fix_with_medium(clip_id, fixes, dry_run=False)
    elif fixes:
        print(f"\n{len(fixes)} segments can be fixed. Run with --fix to apply.")


if __name__ == "__main__":
    main()
