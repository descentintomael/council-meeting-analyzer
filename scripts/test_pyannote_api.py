#!/usr/bin/env python3
"""Test pyannote.ai hosted API for speaker diarization.

Tests with 3 short meetings to verify the API integration works correctly
before running on the full dataset.
"""

import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

API_KEY = os.getenv("PYANNOTE_API_KEY")
BASE_URL = "https://api.pyannote.ai/v1"
AUDIO_DIR = Path(__file__).parent.parent / "data" / "audio"
TRANSCRIPT_DIR = Path(__file__).parent.parent / "data" / "transcripts"

# Test meetings (30-35 min each, ~100 min total)
TEST_MEETINGS = [1196, 1167, 1009]


def get_headers():
    """Get authorization headers."""
    return {"Authorization": f"Bearer {API_KEY}"}


def upload_audio(clip_id: int) -> str:
    """Upload audio file and return the media:// URL."""
    audio_path = AUDIO_DIR / f"{clip_id}.mp3"
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    media_key = f"meeting-{clip_id}"
    media_url = f"media://{media_key}"

    # Step 1: Get presigned upload URL
    print(f"  Getting upload URL for {clip_id}...")
    response = requests.post(
        f"{BASE_URL}/media/input",
        headers=get_headers(),
        json={"url": media_url},
    )
    response.raise_for_status()
    upload_url = response.json()["url"]

    # Step 2: Upload the file
    print(f"  Uploading {audio_path.name} ({audio_path.stat().st_size / 1024 / 1024:.1f} MB)...")
    with open(audio_path, "rb") as f:
        upload_response = requests.put(
            upload_url,
            data=f,
            headers={"Content-Type": "audio/mpeg"},
        )
    upload_response.raise_for_status()
    print(f"  Upload complete.")

    return media_url


def submit_diarization(media_url: str, clip_id: int) -> str:
    """Submit diarization job and return job ID."""
    print(f"  Submitting diarization job...")
    response = requests.post(
        f"{BASE_URL}/diarize",
        headers=get_headers(),
        json={
            "url": media_url,
            "model": "precision-2",
            "confidence": True,
        },
    )
    response.raise_for_status()
    result = response.json()
    job_id = result["jobId"]
    print(f"  Job ID: {job_id}")
    return job_id


def wait_for_job(job_id: str, poll_interval: int = 5) -> dict:
    """Poll until job completes and return results."""
    print(f"  Waiting for job to complete...")
    while True:
        response = requests.get(
            f"{BASE_URL}/jobs/{job_id}",
            headers=get_headers(),
        )
        response.raise_for_status()
        result = response.json()
        status = result["status"]

        if status == "succeeded":
            print(f"  Job succeeded!")
            return result
        elif status == "failed":
            raise RuntimeError(f"Job failed: {result}")
        elif status == "canceled":
            raise RuntimeError(f"Job was canceled")
        else:
            print(f"    Status: {status}...")
            time.sleep(poll_interval)


def load_transcript_segments(clip_id: int) -> list[dict]:
    """Load transcript segments with timestamps from JSON file."""
    # Try different transcript file patterns
    json_patterns = [
        f"{clip_id}_large_v3.json",  # Primary Whisper output
        f"{clip_id}_medium.json",     # Secondary Whisper output
        f"{clip_id}.json",            # Generic format
    ]

    for pattern in json_patterns:
        json_path = TRANSCRIPT_DIR / pattern
        if json_path.exists():
            with open(json_path) as f:
                data = json.load(f)
                # Handle different transcript formats
                if "segments" in data:
                    return data["segments"]
                elif "word_timestamps" in data:
                    return data.get("segments", [])

    # Fall back to txt file (no timestamps)
    txt_path = TRANSCRIPT_DIR / f"{clip_id}.txt"
    if txt_path.exists():
        with open(txt_path) as f:
            text = f.read()
            # Return as single segment without timestamps
            return [{"text": text, "start": 0, "end": None}]

    return []


def merge_diarization_with_transcript(
    diarization_segments: list[dict],
    transcript_segments: list[dict],
) -> list[dict]:
    """Align transcript segments with diarization using midpoint matching."""
    if not transcript_segments:
        return []

    # Sort diarization by start time
    diarization_segments = sorted(diarization_segments, key=lambda x: x["start"])

    # For each transcript segment, find the speaker at its midpoint
    merged_segments = []
    for t_seg in transcript_segments:
        t_start = t_seg.get("start", 0)
        t_end = t_seg.get("end", t_start)
        t_mid = (t_start + t_end) / 2 if t_end else t_start
        text = t_seg.get("text", "").strip()

        if not text:
            continue

        # Find diarization segment containing this midpoint
        speaker_id = "UNKNOWN"
        confidence = None
        for d_seg in diarization_segments:
            d_start = d_seg["start"]
            d_end = d_seg["end"]
            if d_start <= t_mid <= d_end:
                speaker_id = d_seg["speaker"]
                confidence = d_seg.get("confidence")
                break

        # If no exact match, find nearest speaker within 30 seconds
        if speaker_id == "UNKNOWN" and diarization_segments:
            min_dist = float("inf")
            for d_seg in diarization_segments:
                d_mid = (d_seg["start"] + d_seg["end"]) / 2
                dist = abs(t_mid - d_mid)
                if dist < min_dist and dist < 30:
                    min_dist = dist
                    speaker_id = d_seg["speaker"]
                    confidence = d_seg.get("confidence")

        merged_segments.append({
            "start": t_start,
            "end": t_end,
            "speaker_id": speaker_id,
            "speaker_name": None,  # Could be filled by LLM identification later
            "confidence": confidence,
            "method": "pyannote.ai",
            "text": text[:500],  # Truncate for storage
        })

    return merged_segments


def save_diarization(clip_id: int, job_result: dict):
    """Save diarization results merged with transcript text."""
    output = job_result.get("output", {})
    diarization = output.get("diarization", [])

    # Convert API format to standard format
    diarization_segments = []
    for segment in diarization:
        diarization_segments.append({
            "start": segment["start"],
            "end": segment["end"],
            "speaker": segment["speaker"],
            "confidence": segment.get("confidence"),
        })

    # Count unique speakers from diarization
    speakers = set(s["speaker"] for s in diarization_segments)
    print(f"  Found {len(speakers)} speakers, {len(diarization_segments)} diarization segments")

    # Load and merge with transcript
    transcript_segments = load_transcript_segments(clip_id)
    if transcript_segments:
        print(f"  Loaded {len(transcript_segments)} transcript segments")
        merged_segments = merge_diarization_with_transcript(
            diarization_segments, transcript_segments
        )
        print(f"  Merged into {len(merged_segments)} segments with text")

        # Recount unique speakers in merged result
        merged_speakers = set(s["speaker_id"] for s in merged_segments)
        unknown_count = sum(1 for s in merged_segments if s["speaker_id"] == "UNKNOWN")
        print(f"  Speakers in transcript: {len(merged_speakers)} ({unknown_count} unknown)")
    else:
        print(f"  Warning: No transcript found for {clip_id}")
        merged_segments = []

    # Save to file in format compatible with export script
    output_path = TRANSCRIPT_DIR / f"{clip_id}_diarization.json"
    with open(output_path, "w") as f:
        json.dump(
            {
                "clip_id": clip_id,
                "source": "pyannote.ai",
                "model": "precision-2",
                "total_speakers": len(speakers),
                "identified_speakers": 0,  # No LLM identification yet
                "speaker_mapping": {},
                "segments": merged_segments,
            },
            f,
            indent=2,
        )
    print(f"  Saved to {output_path}")


def process_meeting(clip_id: int):
    """Process a single meeting through the API."""
    print(f"\n{'='*60}")
    print(f"Processing meeting {clip_id}")
    print(f"{'='*60}")

    start_time = time.time()

    # Upload audio
    media_url = upload_audio(clip_id)

    # Submit diarization
    job_id = submit_diarization(media_url, clip_id)

    # Wait for results
    result = wait_for_job(job_id)

    # Save results
    save_diarization(clip_id, result)

    elapsed = time.time() - start_time
    print(f"  Total time: {elapsed:.1f}s")

    return elapsed


def main():
    """Test the API with sample meetings."""
    if not API_KEY:
        print("ERROR: PYANNOTE_API_KEY not set in .env file")
        return

    print("Testing pyannote.ai API")
    print(f"API Key: {API_KEY[:10]}...{API_KEY[-4:]}")
    print(f"Test meetings: {TEST_MEETINGS}")

    # Test API connection
    print("\nTesting API connection...")
    response = requests.get(f"{BASE_URL}/test", headers=get_headers())
    if response.status_code == 200:
        print("API connection successful!")
    else:
        print(f"API connection failed: {response.status_code}")
        print(response.text)
        return

    # Process test meetings
    total_time = 0
    successful = 0

    for clip_id in TEST_MEETINGS:
        try:
            elapsed = process_meeting(clip_id)
            total_time += elapsed
            successful += 1
        except Exception as e:
            print(f"  ERROR: {e}")

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Successful: {successful}/{len(TEST_MEETINGS)}")
    print(f"Total time: {total_time:.1f}s ({total_time/60:.1f} min)")
    if successful > 0:
        print(f"Avg per meeting: {total_time/successful:.1f}s")


if __name__ == "__main__":
    main()
