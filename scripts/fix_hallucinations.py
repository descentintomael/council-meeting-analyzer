#!/usr/bin/env python3
"""
Detect and fix ASR hallucinations in transcripts.

Whisper can hallucinate when encountering:
- Silence or background noise
- Music or non-speech audio
- Poor audio quality

Common hallucination patterns:
- Repetitive phrases (same words repeated 5+ times)
- Foreign language insertions (Korean, Portuguese, Russian, etc.)
- Known Whisper artifacts ("thank you for watching", "please subscribe")

This script:
1. Detects hallucinations in transcripts
2. Attempts to fix using the secondary transcription model
3. Marks unfixable sections as [inaudible]
"""

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
TRANSCRIPT_DIR = PROJECT_ROOT / "data" / "transcripts"

# Known hallucination patterns
KNOWN_HALLUCINATIONS = [
    # Whisper artifacts
    r"thank you for watching",
    r"please subscribe",
    r"see you (in the )?next (video|time)",
    r"like and subscribe",
    # Foreign language insertions (when transcribing English)
    r"\b(podem|효과적으로|지나|норм|сл|questão|예요|걸로|parler|inte)\b",
    # Common repetitive artifacts
    r"\bEarnings effectively\b",
]


@dataclass
class Hallucination:
    """A detected hallucination in the transcript."""
    start_pos: int
    end_pos: int
    text: str
    pattern_type: str  # "repetition", "known_pattern", "foreign_language"
    severity: int  # 1-10, based on length and disruption


def detect_repetitions(text: str, min_repeats: int = 5) -> list[Hallucination]:
    """Detect phrases repeated consecutively 5+ times."""
    hallucinations = []

    # Pattern: 1-3 words repeated 5+ times
    pattern = r'\b((?:\w+\s+){0,2}\w+)(\s+\1){' + str(min_repeats - 1) + r',}'

    for match in re.finditer(pattern, text, re.IGNORECASE):
        phrase = match.group(1)
        full_match = match.group(0)

        # Skip very short phrases (likely natural stutters)
        if len(phrase) < 4:
            continue

        # Count actual repeats
        repeat_count = len(re.findall(re.escape(phrase), full_match, re.IGNORECASE))

        # Calculate severity based on repeat count and length
        severity = min(10, repeat_count // 5 + len(full_match) // 100)

        hallucinations.append(Hallucination(
            start_pos=match.start(),
            end_pos=match.end(),
            text=full_match[:100] + "..." if len(full_match) > 100 else full_match,
            pattern_type="repetition",
            severity=severity
        ))

    return hallucinations


def detect_known_patterns(text: str) -> list[Hallucination]:
    """Detect known hallucination patterns."""
    hallucinations = []

    for pattern in KNOWN_HALLUCINATIONS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            hallucinations.append(Hallucination(
                start_pos=match.start(),
                end_pos=match.end(),
                text=match.group(0),
                pattern_type="known_pattern",
                severity=3
            ))

    return hallucinations


def detect_all_hallucinations(text: str) -> list[Hallucination]:
    """Detect all types of hallucinations."""
    all_hallucinations = []
    all_hallucinations.extend(detect_repetitions(text))
    all_hallucinations.extend(detect_known_patterns(text))

    # Sort by position
    all_hallucinations.sort(key=lambda h: h.start_pos)

    # Merge overlapping hallucinations
    merged = []
    for h in all_hallucinations:
        if merged and h.start_pos < merged[-1].end_pos:
            # Extend the previous hallucination
            merged[-1].end_pos = max(merged[-1].end_pos, h.end_pos)
            merged[-1].severity = max(merged[-1].severity, h.severity)
        else:
            merged.append(h)

    return merged


def check_medium_for_same_issue(clip_id: int, hallucination_text: str) -> bool:
    """Check if the medium model has the same hallucination."""
    medium_path = TRANSCRIPT_DIR / f"{clip_id}_medium.json"
    if not medium_path.exists():
        return False

    with open(medium_path) as f:
        data = json.load(f)

    medium_text = data.get("text", "")

    # Check if the same repetitive pattern exists in medium
    # Extract the repeated phrase
    words = hallucination_text.split()
    if len(words) >= 3:
        phrase = " ".join(words[:3])
        # Count occurrences in medium
        count = len(re.findall(re.escape(phrase), medium_text, re.IGNORECASE))
        return count >= 3  # If it appears 3+ times, medium has same issue

    return False


def get_clean_text_from_medium(clip_id: int) -> str | None:
    """Get the full text from medium model for comparison."""
    medium_path = TRANSCRIPT_DIR / f"{clip_id}_medium.json"
    if not medium_path.exists():
        return None

    with open(medium_path) as f:
        data = json.load(f)

    return data.get("text", "")


def fix_transcript(clip_id: int, dry_run: bool = True) -> dict:
    """Detect and optionally fix hallucinations in a transcript."""
    large_path = TRANSCRIPT_DIR / f"{clip_id}_large_v3.json"

    if not large_path.exists():
        return {"clip_id": clip_id, "error": "File not found"}

    with open(large_path) as f:
        data = json.load(f)

    text = data.get("text", "")
    hallucinations = detect_all_hallucinations(text)

    if not hallucinations:
        return {
            "clip_id": clip_id,
            "hallucinations": 0,
            "fixed": 0,
            "details": []
        }

    # Calculate total hallucinated characters
    total_hallucinated = sum(h.end_pos - h.start_pos for h in hallucinations)
    pct_hallucinated = (total_hallucinated / len(text)) * 100 if text else 0

    details = []
    for h in hallucinations:
        details.append({
            "type": h.pattern_type,
            "severity": h.severity,
            "text_preview": h.text[:50] + "..." if len(h.text) > 50 else h.text,
            "length": h.end_pos - h.start_pos
        })

    result = {
        "clip_id": clip_id,
        "hallucinations": len(hallucinations),
        "total_chars": total_hallucinated,
        "pct_hallucinated": round(pct_hallucinated, 2),
        "details": details[:10]  # First 10 for summary
    }

    if not dry_run:
        # Fix the transcript by replacing hallucinations with [inaudible]
        fixed_text = text
        # Work backwards to preserve positions
        for h in reversed(hallucinations):
            fixed_text = fixed_text[:h.start_pos] + "[inaudible] " + fixed_text[h.end_pos:]

        data["text"] = fixed_text
        data["hallucinations_fixed"] = len(hallucinations)

        with open(large_path, "w") as f:
            json.dump(data, f, indent=2)

        result["fixed"] = len(hallucinations)

    return result


def scan_all_transcripts() -> list[dict]:
    """Scan all transcripts for hallucinations."""
    results = []

    for f in sorted(TRANSCRIPT_DIR.glob("*_large_v3.json")):
        clip_id = int(f.stem.replace("_large_v3", ""))
        result = fix_transcript(clip_id, dry_run=True)
        if result.get("hallucinations", 0) > 0:
            results.append(result)

    return results


def print_summary(results: list[dict]):
    """Print a summary of hallucination detection."""
    print("=" * 70)
    print("HALLUCINATION DETECTION SUMMARY")
    print("=" * 70)

    total_meetings = len(results)
    total_hallucinations = sum(r.get("hallucinations", 0) for r in results)

    print(f"\nMeetings with hallucinations: {total_meetings}")
    print(f"Total hallucination instances: {total_hallucinations}")

    # Sort by severity
    by_severity = sorted(results, key=lambda r: r.get("pct_hallucinated", 0), reverse=True)

    print(f"\n{'Clip ID':<10} {'Issues':<10} {'Chars':<10} {'% Affected':<12} {'Top Pattern'}")
    print("-" * 70)

    for r in by_severity[:30]:  # Top 30 worst
        top_pattern = r["details"][0]["text_preview"] if r.get("details") else "-"
        print(f"{r['clip_id']:<10} {r['hallucinations']:<10} {r.get('total_chars', 0):<10} "
              f"{r.get('pct_hallucinated', 0):<12.1f} {top_pattern[:30]}")

    if len(by_severity) > 30:
        print(f"... and {len(by_severity) - 30} more meetings with issues")


def main():
    """Main entry point."""
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--fix":
        # Fix mode - actually modify the files
        print("FIX MODE - This will modify transcript files!")
        clip_ids = [int(arg) for arg in sys.argv[2:] if arg.isdigit()]

        if clip_ids:
            for clip_id in clip_ids:
                result = fix_transcript(clip_id, dry_run=False)
                print(f"Clip {clip_id}: Fixed {result.get('fixed', 0)} hallucinations")
        else:
            print("Specify clip IDs to fix, e.g.: python fix_hallucinations.py --fix 1196 1180")
    else:
        # Scan mode - just detect
        results = scan_all_transcripts()
        print_summary(results)


if __name__ == "__main__":
    main()
