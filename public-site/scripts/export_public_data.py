#!/usr/bin/env python3
"""Export public meeting data from SQLite database for the static site.

This script exports curated, public-facing data while keeping
sensitive research data (advocacy_intel, opposition research) private.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path


# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # council-meeting-analyzer/
DB_PATH = PROJECT_ROOT / "data" / "meetings.db"
TRANSCRIPTS_DIR = PROJECT_ROOT / "data" / "transcripts"
OUTPUT_PATH = SCRIPT_DIR.parent / "src" / "data" / "meetings.json"


def get_db_connection():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def export_meetings():
    """Export all analyzed meetings with public data only."""
    conn = get_db_connection()

    # Get all analyzed meetings
    meetings_query = """
        SELECT
            clip_id,
            title,
            meeting_date,
            meeting_type,
            video_url,
            duration_seconds,
            status
        FROM meetings
        WHERE status = 'analyzed'
        ORDER BY meeting_date DESC
    """
    meetings = conn.execute(meetings_query).fetchall()

    exported_meetings = []

    for meeting in meetings:
        clip_id = meeting["clip_id"]

        # Get summary analysis
        summary = get_analysis(conn, clip_id, "summary")

        # Get vote records
        votes = get_analysis(conn, clip_id, "vote_record")

        # Get priority alerts (topics mentioned)
        alerts = get_analysis(conn, clip_id, "priority_alerts")

        # Get validated transcript for search indexing
        transcript = get_transcript(conn, clip_id)

        # Get speaker-annotated diarization if available
        diarization = get_diarization(clip_id)

        # Build meeting object
        meeting_data = {
            "id": clip_id,
            "title": meeting["title"],
            "date": meeting["meeting_date"],
            "type": meeting["meeting_type"],
            "videoUrl": meeting["video_url"],
            "duration": meeting["duration_seconds"],
            "summary": extract_summary_bullets(summary),
            "votes": extract_votes(votes),
            "topics": extract_topics(alerts),
            "transcript": transcript,
            "diarizedTranscript": diarization,
        }

        exported_meetings.append(meeting_data)

    conn.close()

    # Build final export object
    export_data = {
        "meetings": exported_meetings,
        "metadata": {
            "totalMeetings": len(exported_meetings),
            "dateRange": get_date_range(exported_meetings),
            "exportedAt": datetime.now().isoformat(),
        }
    }

    # Write to JSON
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(export_data, f, indent=2, default=str)

    # Count meetings with diarization
    diarized_count = sum(1 for m in exported_meetings if m.get("diarizedTranscript"))
    print(f"Exported {len(exported_meetings)} meetings to {OUTPUT_PATH}")
    print(f"  - {diarized_count} meetings have speaker-annotated transcripts")
    return export_data


def get_analysis(conn, clip_id: int, analysis_type: str) -> list[dict]:
    """Get analysis results for a meeting by type."""
    query = """
        SELECT result
        FROM analysis
        WHERE clip_id = ? AND analysis_type = ?
    """
    rows = conn.execute(query, (clip_id, analysis_type)).fetchall()
    results = []
    for row in rows:
        try:
            results.append(json.loads(row["result"]))
        except (json.JSONDecodeError, TypeError):
            pass
    return results


def get_transcript(conn, clip_id: int) -> str | None:
    """Get the validated/merged transcript for a meeting."""
    # Try validation table first (merged text is best quality)
    query = """
        SELECT merged_text
        FROM transcription_validation
        WHERE clip_id = ?
    """
    row = conn.execute(query, (clip_id,)).fetchone()
    if row and row["merged_text"]:
        return row["merged_text"]

    # Fall back to transcripts table
    query = """
        SELECT full_text
        FROM transcripts
        WHERE clip_id = ?
    """
    row = conn.execute(query, (clip_id,)).fetchone()
    if row:
        return row["full_text"]

    return None


def get_diarization(clip_id: int) -> list[dict] | None:
    """Load speaker-annotated segments from diarization JSON file."""
    diarization_path = TRANSCRIPTS_DIR / f"{clip_id}_diarization.json"
    if not diarization_path.exists():
        return None

    try:
        with open(diarization_path) as f:
            data = json.load(f)

        # Return simplified segments for frontend
        segments = []
        for seg in data.get("segments", []):
            text = seg.get("text", "").strip()
            if not text:  # Skip empty segments
                continue
            segments.append({
                "speaker": seg.get("speaker_name") or seg.get("speaker_id", "Unknown"),
                "confidence": seg.get("confidence", 0),
                "text": text,
                "start": seg.get("start"),
            })
        return segments if segments else None
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load diarization for {clip_id}: {e}")
        return None


def extract_summary_bullets(analysis_results: list[dict]) -> list[str]:
    """Extract summary bullets from analysis results."""
    bullets = []
    for result in analysis_results:
        if isinstance(result, dict):
            summary = result.get("summary", [])
            if isinstance(summary, list):
                bullets.extend(summary)
            elif isinstance(summary, str):
                bullets.append(summary)
    return bullets


def extract_votes(analysis_results: list[dict]) -> list[dict]:
    """Extract vote records from analysis results."""
    all_votes = []
    for result in analysis_results:
        if isinstance(result, dict):
            votes = result.get("votes", [])
            if isinstance(votes, list):
                for vote in votes:
                    if isinstance(vote, dict):
                        all_votes.append({
                            "motion": vote.get("motion", ""),
                            "result": vote.get("result", ""),
                            "yesCount": vote.get("vote_count", {}).get("yes", 0),
                            "noCount": vote.get("vote_count", {}).get("no", 0),
                            "votes": vote.get("individual_votes", {}),
                        })
    return all_votes


def extract_topics(analysis_results: list[dict]) -> list[str]:
    """Extract topic keywords from priority alerts."""
    topics = set()
    for result in analysis_results:
        if isinstance(result, dict):
            alerts = result.get("alerts", [])
            if isinstance(alerts, list):
                for alert in alerts:
                    if isinstance(alert, dict):
                        keyword = alert.get("keyword", "")
                        if keyword:
                            topics.add(keyword.lower())
    return sorted(list(topics))


def get_date_range(meetings: list[dict]) -> dict:
    """Get the date range of exported meetings."""
    dates = [m["date"] for m in meetings if m.get("date")]
    if not dates:
        return {"start": None, "end": None}
    return {
        "start": min(dates),
        "end": max(dates),
    }


if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        exit(1)

    export_meetings()
