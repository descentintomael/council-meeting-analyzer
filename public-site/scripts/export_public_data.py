#!/usr/bin/env python3
"""Export public meeting data from SQLite database for the static site.

This script exports curated, public-facing data while keeping
sensitive research data (advocacy_intel, opposition research) private.

Enhanced to export:
- WER quality scores for transcripts
- Council member voting records and alignment
- Topic aggregations
- Statistics for dashboard
- CSV exports for researchers
- Downloadable transcript text files
"""

import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # council-meeting-analyzer/
DB_PATH = PROJECT_ROOT / "data" / "meetings.db"
TRANSCRIPTS_DIR = PROJECT_ROOT / "data" / "transcripts"
OUTPUT_DIR = SCRIPT_DIR.parent / "src" / "data"
OUTPUT_PATH = OUTPUT_DIR / "meetings.json"
PUBLIC_DIR = SCRIPT_DIR.parent / "public"
PUBLIC_DATA_DIR = PUBLIC_DIR / "data"
PUBLIC_TRANSCRIPTS_DIR = PUBLIC_DIR / "transcripts"


def get_db_connection():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_wer_scores(conn) -> dict[int, float]:
    """Get WER scores for all meetings."""
    query = """
        SELECT clip_id, wer_score
        FROM transcription_validation
        WHERE wer_score IS NOT NULL
    """
    rows = conn.execute(query).fetchall()
    return {row["clip_id"]: row["wer_score"] for row in rows}


def export_meetings():
    """Export all analyzed meetings with public data only."""
    conn = get_db_connection()

    # Get WER scores for quality indicators
    wer_scores = get_wer_scores(conn)

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
    all_votes = []  # Collect all votes for member/alignment analysis

    for meeting in meetings:
        clip_id = meeting["clip_id"]

        # Get summary analysis
        summary = get_analysis(conn, clip_id, "summary")

        # Get vote records
        votes_raw = get_analysis(conn, clip_id, "vote_record")

        # Get priority alerts (topics mentioned)
        alerts = get_analysis(conn, clip_id, "priority_alerts")

        # Get validated transcript for search indexing
        transcript = get_transcript(conn, clip_id)

        # Get speaker-annotated diarization if available
        diarization = get_diarization(clip_id)

        # Extract votes with meeting context
        votes = extract_votes(votes_raw)
        for vote in votes:
            vote["meetingId"] = clip_id
            vote["meetingDate"] = meeting["meeting_date"]
            vote["meetingTitle"] = meeting["title"]
            all_votes.append(vote)

        # Build meeting object
        meeting_data = {
            "id": clip_id,
            "title": meeting["title"],
            "date": meeting["meeting_date"],
            "type": meeting["meeting_type"],
            "videoUrl": meeting["video_url"],
            "duration": meeting["duration_seconds"],
            "summary": extract_summary_bullets(summary),
            "votes": votes,
            "topics": extract_topics(alerts),
            "transcript": transcript,
            "diarizedTranscript": diarization,
            "werScore": wer_scores.get(clip_id),
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
    print(f"  - {len(wer_scores)} meetings have WER quality scores")

    return export_data, all_votes


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


# Known council members and their name variations
KNOWN_COUNCIL_MEMBERS = {
    # Current and recent council members
    "Coolidge": ["Coolidge", "coolidge", "Mayor Coolidge"],
    "Reynolds": ["Reynolds", "reynolds", "Vice Mayor Reynolds"],
    "Brown": ["Brown", "brown", "Council Member Brown", "Councilmember Brown"],
    "Morgan": ["Morgan", "morgan", "Council Member Morgan"],
    "Tandon": ["Tandon", "tandon", "Council Member Tandon"],
    "Stone": ["Stone", "stone", "Council Member Stone"],
    "Huber": ["Huber", "huber", "Council Member Huber"],
    "Bennett": ["Bennett", "bennett", "Vice Mayor Bennett", "Vice mayor Bennett"],
    "O'Brien": ["O'Brien", "O'bryan", "O'brien", "Obrien", "Council Member O'Brien", "Council member O'Brien"],
    "van Overbeek": ["van Overbeek", "Van Overbeek", "Van Overbeck", "van Overbeck", "vanoverbeek"],
    "Schwab": ["Schwab", "schwab", "Council Member Schwab"],
    "Ory": ["Ory", "ory", "Council Member Ory"],
    "Denlay": ["Denlay", "denlay", "Council Member Denlay"],
    "Holley": ["Holley", "Holly", "Holli", "holley", "Council Member Holley", "Council member Holly"],
    "Goldstein": ["Goldstein", "goldstein", "Council Member Goldstein", "Council member Goldstein"],
    "Winslow": ["Winslow", "Winso", "winslow", "Council Member Winslow", "Council member Winslow"],
    "Rounds": ["Rounds", "rounds", "Vice Mayor Rounds"],
    "Tyler": ["Tyler", "tyler", "Council Member Tyler"],
    "Hawley": ["Hawley", "hawley", "Council Member Hawley"],
}

# Build reverse lookup
MEMBER_NAME_LOOKUP = {}
for canonical, variations in KNOWN_COUNCIL_MEMBERS.items():
    for var in variations:
        MEMBER_NAME_LOOKUP[var.lower()] = canonical


def normalize_member_name(name: str) -> str:
    """Normalize council member names to a consistent format."""
    if not name:
        return ""

    # Remove common prefixes to get base name
    prefixes = ["Council Member ", "Councilmember ", "Council member ",
                "Vice Mayor ", "Vice mayor ", "Mayor ", "CM "]
    normalized = name.strip()
    for prefix in prefixes:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break

    normalized = normalized.strip()

    # Try to match to known council member
    lookup_key = normalized.lower()
    if lookup_key in MEMBER_NAME_LOOKUP:
        return MEMBER_NAME_LOOKUP[lookup_key]

    # Also try the full original name
    full_lookup = name.strip().lower()
    if full_lookup in MEMBER_NAME_LOOKUP:
        return MEMBER_NAME_LOOKUP[full_lookup]

    # Return empty string for unknown members (will be filtered out)
    return ""


def normalize_vote(vote: str) -> str:
    """Normalize vote values to yes/no/abstain."""
    if not vote:
        return "unknown"
    vote_lower = vote.lower().strip()
    if vote_lower in ("yes", "aye", "yea", "y"):
        return "yes"
    elif vote_lower in ("no", "nay", "n"):
        return "no"
    elif vote_lower in ("abstain", "abstained", "recused", "absent"):
        return "abstain"
    return "unknown"


def export_members(all_votes: list[dict]) -> dict:
    """Export council member voting records and statistics."""
    # Collect votes by member
    member_votes = defaultdict(list)

    for vote in all_votes:
        individual_votes = vote.get("votes", {})
        if not individual_votes:
            continue

        result = vote.get("result", "").lower()

        for member_name, member_vote in individual_votes.items():
            normalized_name = normalize_member_name(member_name)
            if not normalized_name:
                continue

            normalized_vote = normalize_vote(member_vote)
            # Determine if member voted with the majority
            if "passed" in result or "approved" in result:
                with_majority = normalized_vote == "yes"
            elif "failed" in result or "denied" in result:
                with_majority = normalized_vote == "no"
            else:
                with_majority = None

            member_votes[normalized_name].append({
                "motion": vote.get("motion", ""),
                "vote": normalized_vote,
                "result": vote.get("result", ""),
                "meetingId": vote.get("meetingId"),
                "meetingDate": vote.get("meetingDate"),
                "meetingTitle": vote.get("meetingTitle"),
                "withMajority": with_majority,
            })

    # Calculate statistics for each member
    members_data = {}
    for member, votes in member_votes.items():
        yes_count = sum(1 for v in votes if v["vote"] == "yes")
        no_count = sum(1 for v in votes if v["vote"] == "no")
        abstain_count = sum(1 for v in votes if v["vote"] == "abstain")
        total = len(votes)
        with_majority = sum(1 for v in votes if v["withMajority"] is True)
        majority_votes = sum(1 for v in votes if v["withMajority"] is not None)

        members_data[member] = {
            "name": member,
            "totalVotes": total,
            "yesVotes": yes_count,
            "noVotes": no_count,
            "abstainVotes": abstain_count,
            "yesPercent": round(yes_count / total * 100, 1) if total > 0 else 0,
            "withMajorityPercent": round(with_majority / majority_votes * 100, 1) if majority_votes > 0 else 0,
            "votes": votes,
        }

    # Write members.json
    members_path = OUTPUT_DIR / "members.json"
    with open(members_path, "w") as f:
        json.dump(members_data, f, indent=2)
    print(f"Exported {len(members_data)} council members to {members_path}")

    return members_data


def export_alignment(all_votes: list[dict]) -> dict:
    """Calculate and export voting alignment between council members.

    Enhanced to track:
    - Member tenure (first and last vote dates)
    - Number of shared votes between each pair
    - Only show alignment for members with overlapping service
    """
    # Build a map of (vote_id) -> {member: vote, date: meeting_date}
    vote_records = defaultdict(dict)
    vote_dates = {}  # vote_id -> date

    # Track each member's vote dates for tenure calculation
    member_vote_dates = defaultdict(list)

    for vote in all_votes:
        individual_votes = vote.get("votes", {})
        if not individual_votes:
            continue

        # Create unique vote identifier
        vote_id = f"{vote.get('meetingId')}_{vote.get('motion', '')[:50]}"
        meeting_date = vote.get("meetingDate")
        vote_dates[vote_id] = meeting_date

        for member_name, member_vote in individual_votes.items():
            normalized_name = normalize_member_name(member_name)
            if normalized_name:
                vote_records[vote_id][normalized_name] = normalize_vote(member_vote)
                if meeting_date:
                    member_vote_dates[normalized_name].append(meeting_date)

    # Calculate member tenures
    member_tenures = {}
    for member, dates in member_vote_dates.items():
        if dates:
            sorted_dates = sorted(dates)
            member_tenures[member] = {
                "firstVote": sorted_dates[0],
                "lastVote": sorted_dates[-1],
                "voteCount": len(dates),
            }

    # Calculate pairwise alignment with shared vote counts
    all_members = set()
    for votes in vote_records.values():
        all_members.update(votes.keys())

    alignment_matrix = {}
    shared_votes_matrix = {}  # Track number of shared votes for each pair

    for member1 in sorted(all_members):
        alignment_matrix[member1] = {}
        shared_votes_matrix[member1] = {}

        for member2 in sorted(all_members):
            if member1 == member2:
                alignment_matrix[member1][member2] = 100.0
                shared_votes_matrix[member1][member2] = member_tenures.get(member1, {}).get("voteCount", 0)
                continue

            # Count votes where both members voted
            same_vote = 0
            total_shared = 0
            for vote_id, votes in vote_records.items():
                if member1 in votes and member2 in votes:
                    v1 = votes[member1]
                    v2 = votes[member2]
                    # Only count yes/no votes for alignment
                    if v1 in ("yes", "no") and v2 in ("yes", "no"):
                        total_shared += 1
                        if v1 == v2:
                            same_vote += 1

            shared_votes_matrix[member1][member2] = total_shared

            if total_shared >= 5:  # Minimum 5 shared votes for meaningful alignment
                alignment_matrix[member1][member2] = round(same_vote / total_shared * 100, 1)
            else:
                alignment_matrix[member1][member2] = None

    # Identify the current council (members active in the most recent year)
    all_dates = [d for dates in member_vote_dates.values() for d in dates if d]
    if all_dates:
        most_recent = max(all_dates)
        # Consider "current" as anyone who voted in the last year
        from datetime import datetime, timedelta
        try:
            recent_cutoff = datetime.fromisoformat(most_recent) - timedelta(days=365)
            recent_cutoff_str = recent_cutoff.strftime("%Y-%m-%d")
        except:
            recent_cutoff_str = most_recent[:4] + "-01-01"  # Fallback to start of year

        current_members = [
            m for m, tenure in member_tenures.items()
            if tenure.get("lastVote", "") >= recent_cutoff_str
        ]
    else:
        current_members = list(all_members)

    # Write alignment.json
    alignment_path = OUTPUT_DIR / "alignment.json"
    alignment_data = {
        "matrix": alignment_matrix,
        "sharedVotes": shared_votes_matrix,
        "members": sorted(all_members),
        "currentMembers": sorted(current_members),
        "tenures": member_tenures,
        "minSharedVotes": 5,
    }
    with open(alignment_path, "w") as f:
        json.dump(alignment_data, f, indent=2)
    print(f"Exported voting alignment for {len(all_members)} members to {alignment_path}")
    print(f"  - {len(current_members)} members active in past year")

    return alignment_data


def export_topics(meetings: list[dict]) -> dict:
    """Export topic aggregations across all meetings."""
    topic_meetings = defaultdict(list)

    for meeting in meetings:
        for topic in meeting.get("topics", []):
            topic_meetings[topic].append({
                "id": meeting["id"],
                "title": meeting["title"],
                "date": meeting["date"],
                "type": meeting["type"],
            })

    # Sort topics by frequency
    topics_data = {
        topic: {
            "topic": topic,
            "meetingCount": len(meetings_list),
            "meetings": sorted(meetings_list, key=lambda x: x["date"] or "", reverse=True),
        }
        for topic, meetings_list in topic_meetings.items()
    }

    # Sort by meeting count for the list
    sorted_topics = sorted(topics_data.values(), key=lambda x: x["meetingCount"], reverse=True)

    # Write topics.json
    topics_path = OUTPUT_DIR / "topics.json"
    with open(topics_path, "w") as f:
        json.dump({
            "topics": {t["topic"]: t for t in sorted_topics},
            "topicList": [t["topic"] for t in sorted_topics],
        }, f, indent=2)
    print(f"Exported {len(topics_data)} topics to {topics_path}")

    return topics_data


def export_statistics(meetings: list[dict], all_votes: list[dict]) -> dict:
    """Export pre-calculated statistics for dashboard."""
    # Meetings by month
    meetings_by_month = Counter()
    meetings_by_type = Counter()
    topics_by_month = defaultdict(Counter)

    for meeting in meetings:
        date = meeting.get("date", "")
        if date:
            month = date[:7]  # YYYY-MM
            meetings_by_month[month] += 1
            meetings_by_type[meeting.get("type", "Unknown")] += 1
            for topic in meeting.get("topics", []):
                topics_by_month[month][topic] += 1

    # Vote statistics
    vote_results = Counter()
    votes_by_month = Counter()
    for vote in all_votes:
        result = vote.get("result", "").lower()
        if "passed" in result or "approved" in result:
            vote_results["passed"] += 1
        elif "failed" in result or "denied" in result:
            vote_results["failed"] += 1
        else:
            vote_results["other"] += 1

        date = vote.get("meetingDate", "")
        if date:
            month = date[:7]
            votes_by_month[month] += 1

    # Quality statistics
    # Filter out invalid WER scores (> 1.0 indicates data issues)
    # WER is model agreement between large_v3 and medium Whisper models
    valid_wer_scores = [
        m.get("werScore") for m in meetings
        if m.get("werScore") is not None and m.get("werScore") <= 1.0
    ]
    # Use median for robustness against outliers
    if valid_wer_scores:
        sorted_wer = sorted(valid_wer_scores)
        n = len(sorted_wer)
        median_wer = sorted_wer[n // 2] if n % 2 else (sorted_wer[n // 2 - 1] + sorted_wer[n // 2]) / 2
    else:
        median_wer = None
    diarized_count = sum(1 for m in meetings if m.get("diarizedTranscript"))

    stats_data = {
        "overview": {
            "totalMeetings": len(meetings),
            "totalVotes": len(all_votes),
            "totalTopics": len(set(t for m in meetings for t in m.get("topics", []))),
            "diarizedMeetings": diarized_count,
            "medianWer": round(median_wer, 3) if median_wer else None,
            "validWerCount": len(valid_wer_scores),
        },
        "meetingsByMonth": dict(sorted(meetings_by_month.items())),
        "meetingsByType": dict(meetings_by_type.most_common()),
        "voteResults": dict(vote_results),
        "votesByMonth": dict(sorted(votes_by_month.items())),
        "topTopics": [
            {"topic": topic, "count": count}
            for topic, count in Counter(
                t for m in meetings for t in m.get("topics", [])
            ).most_common(20)
        ],
    }

    # Write statistics.json
    stats_path = OUTPUT_DIR / "statistics.json"
    with open(stats_path, "w") as f:
        json.dump(stats_data, f, indent=2)
    print(f"Exported statistics to {stats_path}")

    return stats_data


def export_csv_files(meetings: list[dict], all_votes: list[dict]):
    """Export CSV files for researchers."""
    PUBLIC_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Meetings CSV
    meetings_csv_path = PUBLIC_DATA_DIR / "meetings.csv"
    with open(meetings_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "title", "date", "type", "duration_seconds", "video_url", "summary_count", "vote_count", "topics", "wer_score"])
        for m in meetings:
            writer.writerow([
                m["id"],
                m["title"],
                m["date"],
                m["type"],
                m["duration"],
                m["videoUrl"],
                len(m.get("summary", [])),
                len(m.get("votes", [])),
                "|".join(m.get("topics", [])),
                m.get("werScore", ""),
            ])
    print(f"Exported meetings CSV to {meetings_csv_path}")

    # Votes CSV
    votes_csv_path = PUBLIC_DATA_DIR / "votes.csv"
    with open(votes_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["meeting_id", "meeting_date", "meeting_title", "motion", "result", "yes_count", "no_count"])
        for v in all_votes:
            writer.writerow([
                v.get("meetingId"),
                v.get("meetingDate"),
                v.get("meetingTitle"),
                v.get("motion", ""),
                v.get("result", ""),
                v.get("yesCount", 0),
                v.get("noCount", 0),
            ])
    print(f"Exported votes CSV to {votes_csv_path}")


def export_transcript_files(meetings: list[dict]):
    """Export individual transcript text files for download."""
    PUBLIC_TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    count = 0
    for meeting in meetings:
        transcript = meeting.get("transcript")
        if not transcript:
            continue

        # Create a nicely formatted text file
        txt_path = PUBLIC_TRANSCRIPTS_DIR / f"{meeting['id']}.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"{'='*60}\n")
            f.write(f"{meeting['title']}\n")
            f.write(f"Date: {meeting['date']}\n")
            f.write(f"Type: {meeting['type']}\n")
            if meeting.get("werScore"):
                wer_pct = round((1 - meeting["werScore"]) * 100, 1)
                f.write(f"Transcript Accuracy: ~{wer_pct}%\n")
            f.write(f"{'='*60}\n\n")
            f.write("DISCLAIMER: This transcript was generated using AI speech recognition\n")
            f.write("and may contain errors. Please verify against the original video.\n\n")
            f.write(f"{'='*60}\n\n")
            f.write(transcript)
            f.write("\n")
        count += 1

    print(f"Exported {count} transcript text files to {PUBLIC_TRANSCRIPTS_DIR}")


if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        exit(1)

    # Export main meetings data
    export_data, all_votes = export_meetings()
    meetings = export_data["meetings"]

    # Export additional data files
    export_members(all_votes)
    export_alignment(all_votes)
    export_topics(meetings)
    export_statistics(meetings, all_votes)
    export_csv_files(meetings, all_votes)
    export_transcript_files(meetings)

    print("\nAll exports complete!")
