#!/usr/bin/env python3
"""
Fix transcript hallucinations by replacing with medium model text.

Strategy:
1. Detect hallucination clusters (consecutive segments with repetitive text)
2. Get the time range of each cluster
3. Replace with text from medium model for that time range
4. Regenerate the full transcript text
"""

import json
import re
from pathlib import Path
from dataclasses import dataclass

PROJECT_ROOT = Path(__file__).parent.parent
TRANSCRIPT_DIR = PROJECT_ROOT / "data" / "transcripts"


@dataclass
class HallucinationCluster:
    """A cluster of hallucinated segments."""
    start_time: float
    end_time: float
    segment_indices: list[int]
    pattern: str
    large_text: str
    medium_text: str = ""


def detect_hallucination_clusters(segments: list[dict]) -> list[HallucinationCluster]:
    """Find clusters of segments with repetitive hallucinations.

    Strategy: Look for consecutive segments that share the same short pattern.
    Whisper hallucinations often create many tiny segments with the same few words.
    """
    clusters = []
    used_indices = set()

    for i, seg in enumerate(segments):
        if i in used_indices:
            continue

        text = seg.get("text", "").strip()
        words = text.split()

        # Skip empty segments
        if len(words) < 1:
            continue

        # Get first 1-2 words as potential pattern
        pattern = " ".join(words[:min(2, len(words))])
        if len(pattern) < 3:
            continue

        # Look for consecutive segments with similar pattern
        cluster_indices = [i]
        j = i + 1

        while j < len(segments):
            next_text = segments[j].get("text", "").strip()
            # Check if pattern appears in next segment or texts are very similar
            if pattern.lower() in next_text.lower() or (
                len(next_text.split()) <= 3 and
                any(w.lower() in next_text.lower() for w in pattern.split())
            ):
                cluster_indices.append(j)
                j += 1
            else:
                break

        # Only consider clusters with 5+ consecutive segments (likely hallucination)
        if len(cluster_indices) >= 5:
            start_time = segments[cluster_indices[0]].get("start", 0)
            end_time = segments[cluster_indices[-1]].get("end", 0)

            # Check that the cluster spans a reasonable time (not spread over minutes)
            # Real hallucinations are usually dense - many segments in a short time
            duration = end_time - start_time
            segments_per_second = len(cluster_indices) / max(duration, 0.1)

            # Skip if too sparse (less than 0.5 segments per second on average)
            if segments_per_second < 0.5:
                continue

            full_text = " ".join(segments[k].get("text", "") for k in cluster_indices)

            # Verify it's actually repetitive (not just similar but different words)
            word_counts = {}
            for w in full_text.lower().split():
                word_counts[w] = word_counts.get(w, 0) + 1

            # If any word appears more than 5 times, it's likely a hallucination
            max_count = max(word_counts.values()) if word_counts else 0
            if max_count >= 5:
                clusters.append(HallucinationCluster(
                    start_time=start_time,
                    end_time=end_time,
                    segment_indices=cluster_indices,
                    pattern=pattern,
                    large_text=full_text[:200] + "..." if len(full_text) > 200 else full_text
                ))
                used_indices.update(cluster_indices)

    return clusters


def get_medium_text_for_range(medium_segments: list[dict], start: float, end: float) -> str:
    """Get text from medium model for a time range."""
    texts = []
    for seg in medium_segments:
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", 0)
        # Include segments that overlap with our range
        if seg_end > start and seg_start < end:
            texts.append(seg.get("text", "").strip())
    return " ".join(texts)


def fix_transcript(clip_id: int, dry_run: bool = True) -> dict:
    """Fix hallucinations in a transcript."""
    large_path = TRANSCRIPT_DIR / f"{clip_id}_large_v3.json"
    medium_path = TRANSCRIPT_DIR / f"{clip_id}_medium.json"

    if not large_path.exists():
        return {"error": f"Large transcript not found: {large_path}"}

    with open(large_path) as f:
        large_data = json.load(f)

    large_segments = large_data.get("segments", [])
    medium_segments = []

    if medium_path.exists():
        with open(medium_path) as f:
            medium_data = json.load(f)
        medium_segments = medium_data.get("segments", [])

    # Detect hallucination clusters
    clusters = detect_hallucination_clusters(large_segments)

    if not clusters:
        return {
            "clip_id": clip_id,
            "hallucinations": 0,
            "fixed": 0,
            "message": "No hallucination clusters detected"
        }

    # Get medium text for each cluster
    for cluster in clusters:
        cluster.medium_text = get_medium_text_for_range(
            medium_segments, cluster.start_time, cluster.end_time
        )

    # Print findings
    print(f"\nClip {clip_id}: Found {len(clusters)} hallucination clusters")
    for i, cluster in enumerate(clusters):
        print(f"\n  Cluster {i+1} ({cluster.start_time:.1f}s - {cluster.end_time:.1f}s):")
        print(f"    Pattern: '{cluster.pattern}' repeated across {len(cluster.segment_indices)} segments")
        print(f"    Large:  {cluster.large_text[:80]}...")
        if cluster.medium_text:
            print(f"    Medium: {cluster.medium_text[:80]}...")
        else:
            print(f"    Medium: [no text available]")

    if dry_run:
        print(f"\nDry run - no changes made. Run with --fix to apply.")
        return {
            "clip_id": clip_id,
            "hallucinations": len(clusters),
            "fixed": 0,
            "clusters": [
                {
                    "start": c.start_time,
                    "end": c.end_time,
                    "pattern": c.pattern,
                    "segments": len(c.segment_indices),
                    "has_medium": bool(c.medium_text)
                }
                for c in clusters
            ]
        }

    # Apply fixes
    fixed_count = 0
    for cluster in clusters:
        if cluster.medium_text:
            # Replace all segments in cluster with a single segment containing medium text
            first_idx = cluster.segment_indices[0]

            # Update first segment with medium text
            large_segments[first_idx]["text"] = cluster.medium_text
            large_segments[first_idx]["fixed_from_medium"] = True

            # Clear text from remaining segments in cluster
            for idx in cluster.segment_indices[1:]:
                large_segments[idx]["text"] = ""
                large_segments[idx]["removed_hallucination"] = True

            fixed_count += 1
        else:
            # No medium text - mark as inaudible
            for idx in cluster.segment_indices:
                large_segments[idx]["text"] = "[inaudible]" if idx == cluster.segment_indices[0] else ""
                large_segments[idx]["marked_inaudible"] = True

    # Rebuild full text
    full_text = " ".join(seg.get("text", "") for seg in large_segments if seg.get("text", "").strip())
    large_data["text"] = full_text
    large_data["segments"] = large_segments
    large_data["hallucinations_fixed"] = fixed_count

    with open(large_path, "w") as f:
        json.dump(large_data, f, indent=2)

    print(f"\nFixed {fixed_count} clusters, saved to {large_path}")

    return {
        "clip_id": clip_id,
        "hallucinations": len(clusters),
        "fixed": fixed_count
    }


def scan_all(dry_run: bool = True):
    """Scan all transcripts for hallucinations."""
    results = []

    for f in sorted(TRANSCRIPT_DIR.glob("*_large_v3.json")):
        clip_id = int(f.stem.replace("_large_v3", ""))
        result = fix_transcript(clip_id, dry_run=dry_run)
        if result.get("hallucinations", 0) > 0:
            results.append(result)

    print(f"\n{'='*60}")
    print(f"SUMMARY: {len(results)} transcripts have hallucination clusters")
    print("="*60)

    for r in sorted(results, key=lambda x: x.get("hallucinations", 0), reverse=True)[:20]:
        print(f"  Clip {r['clip_id']}: {r['hallucinations']} clusters")


def main():
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python fix_transcript_hallucinations.py <clip_id>       # Analyze one clip")
        print("  python fix_transcript_hallucinations.py <clip_id> --fix # Fix one clip")
        print("  python fix_transcript_hallucinations.py --scan          # Scan all clips")
        print("  python fix_transcript_hallucinations.py --fix-all       # Fix all clips")
        return

    if sys.argv[1] == "--scan":
        scan_all(dry_run=True)
    elif sys.argv[1] == "--fix-all":
        scan_all(dry_run=False)
    else:
        clip_id = int(sys.argv[1])
        do_fix = "--fix" in sys.argv
        fix_transcript(clip_id, dry_run=not do_fix)


if __name__ == "__main__":
    main()
