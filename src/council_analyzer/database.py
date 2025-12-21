"""SQLite database operations for meeting tracking and analysis storage."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import config

SCHEMA = """
-- Meeting discovery and metadata
CREATE TABLE IF NOT EXISTS meetings (
    clip_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    meeting_date DATE,
    meeting_type TEXT,
    video_url TEXT,
    duration_seconds INTEGER,
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'discovered'
    -- Status values: discovered, downloading, downloaded, transcribing,
    --                transcribed, validating, validated, analyzing, analyzed, failed, skipped
);

-- Agenda/cue points from Granicus
CREATE TABLE IF NOT EXISTS agenda_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_id INTEGER REFERENCES meetings(clip_id),
    item_number TEXT,
    title TEXT,
    start_seconds INTEGER,
    end_seconds INTEGER,
    granicus_item_id INTEGER
);

-- Transcription results
CREATE TABLE IF NOT EXISTS transcripts (
    clip_id INTEGER PRIMARY KEY REFERENCES meetings(clip_id),
    full_text TEXT,
    word_timestamps JSON,
    transcribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    model_used TEXT,
    processing_time_seconds REAL
);

-- Transcription validation results
CREATE TABLE IF NOT EXISTS transcription_validation (
    clip_id INTEGER PRIMARY KEY REFERENCES meetings(clip_id),
    large_v3_text TEXT,
    medium_text TEXT,
    merged_text TEXT,
    wer_score REAL,
    divergent_segments JSON,
    tier1_scores JSON,
    tier2_scores JSON,
    validation_issues JSON,
    validated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    human_review_needed BOOLEAN DEFAULT FALSE
);

-- Segmented transcripts by agenda item
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_id INTEGER REFERENCES meetings(clip_id),
    agenda_item_id INTEGER REFERENCES agenda_items(id),
    segment_text TEXT,
    start_seconds INTEGER,
    end_seconds INTEGER
);

-- LLM analysis results
CREATE TABLE IF NOT EXISTS analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_id INTEGER REFERENCES meetings(clip_id),
    agenda_item_id INTEGER REFERENCES agenda_items(id),
    analysis_type TEXT,
    result JSON,
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    model_used TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER
);

-- Processing log for debugging and resume
CREATE TABLE IF NOT EXISTS processing_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_id INTEGER,
    stage TEXT,
    status TEXT,
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_meetings_status ON meetings(status);
CREATE INDEX IF NOT EXISTS idx_meetings_date ON meetings(meeting_date);
CREATE INDEX IF NOT EXISTS idx_agenda_clip ON agenda_items(clip_id);
CREATE INDEX IF NOT EXISTS idx_segments_clip ON segments(clip_id);
CREATE INDEX IF NOT EXISTS idx_analysis_clip ON analysis(clip_id);
CREATE INDEX IF NOT EXISTS idx_processing_log_clip ON processing_log(clip_id);
"""


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database():
    """Initialize database with schema."""
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.executescript(SCHEMA)
    print(f"Database initialized at {config.DB_PATH}")


def insert_meeting(
    clip_id: int,
    title: str,
    meeting_date: str | None = None,
    meeting_type: str | None = None,
    video_url: str | None = None,
    duration_seconds: int | None = None,
) -> bool:
    """Insert a new meeting. Returns True if inserted, False if already exists."""
    with get_db() as conn:
        try:
            conn.execute(
                """
                INSERT INTO meetings (clip_id, title, meeting_date, meeting_type, video_url, duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (clip_id, title, meeting_date, meeting_type, video_url, duration_seconds),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def update_meeting_status(clip_id: int, status: str):
    """Update the status of a meeting."""
    with get_db() as conn:
        conn.execute(
            "UPDATE meetings SET status = ? WHERE clip_id = ?",
            (status, clip_id),
        )


def update_meeting_video_url(clip_id: int, video_url: str):
    """Update the video URL for a meeting."""
    with get_db() as conn:
        conn.execute(
            "UPDATE meetings SET video_url = ? WHERE clip_id = ?",
            (video_url, clip_id),
        )


def get_meeting(clip_id: int) -> dict | None:
    """Get a single meeting by clip_id."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM meetings WHERE clip_id = ?", (clip_id,)
        ).fetchone()
        return dict(row) if row else None


def get_meetings_by_status(status: str) -> list[dict]:
    """Get all meetings with a specific status."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM meetings WHERE status = ? ORDER BY meeting_date DESC",
            (status,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_next_pending(stage: str) -> dict | None:
    """Get the next meeting pending for a specific stage."""
    status_map = {
        "download": "discovered",
        "transcribe": "downloaded",
        "validate": "transcribed",
        "analyze": "validated",
    }
    status = status_map.get(stage)
    if not status:
        return None

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM meetings WHERE status = ? ORDER BY meeting_date ASC LIMIT 1",
            (status,),
        ).fetchone()
        return dict(row) if row else None


def insert_agenda_items(clip_id: int, items: list[dict]):
    """Insert agenda items for a meeting."""
    with get_db() as conn:
        conn.execute("DELETE FROM agenda_items WHERE clip_id = ?", (clip_id,))
        for item in items:
            conn.execute(
                """
                INSERT INTO agenda_items (clip_id, item_number, title, start_seconds, end_seconds, granicus_item_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    clip_id,
                    item.get("item_number"),
                    item.get("title"),
                    item.get("start_seconds"),
                    item.get("end_seconds"),
                    item.get("granicus_item_id"),
                ),
            )


def get_agenda_items(clip_id: int) -> list[dict]:
    """Get all agenda items for a meeting."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM agenda_items WHERE clip_id = ? ORDER BY start_seconds",
            (clip_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def insert_transcript(
    clip_id: int,
    full_text: str,
    word_timestamps: list[dict] | None = None,
    model_used: str | None = None,
    processing_time_seconds: float | None = None,
):
    """Insert or update transcript for a meeting."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO transcripts
            (clip_id, full_text, word_timestamps, model_used, processing_time_seconds, transcribed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                clip_id,
                full_text,
                json.dumps(word_timestamps) if word_timestamps else None,
                model_used,
                processing_time_seconds,
                datetime.now().isoformat(),
            ),
        )


def get_transcript(clip_id: int) -> dict | None:
    """Get transcript for a meeting."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM transcripts WHERE clip_id = ?", (clip_id,)
        ).fetchone()
        if row:
            result = dict(row)
            if result.get("word_timestamps"):
                result["word_timestamps"] = json.loads(result["word_timestamps"])
            return result
        return None


def insert_validation(
    clip_id: int,
    large_v3_text: str,
    medium_text: str,
    merged_text: str,
    wer_score: float,
    divergent_segments: list[dict] | None = None,
    tier1_scores: dict | None = None,
    tier2_scores: dict | None = None,
    validation_issues: list[str] | None = None,
    human_review_needed: bool = False,
):
    """Insert validation results for a meeting."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO transcription_validation
            (clip_id, large_v3_text, medium_text, merged_text, wer_score,
             divergent_segments, tier1_scores, tier2_scores, validation_issues,
             validated_at, human_review_needed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clip_id,
                large_v3_text,
                medium_text,
                merged_text,
                wer_score,
                json.dumps(divergent_segments) if divergent_segments else None,
                json.dumps(tier1_scores) if tier1_scores else None,
                json.dumps(tier2_scores) if tier2_scores else None,
                json.dumps(validation_issues) if validation_issues else None,
                datetime.now().isoformat(),
                human_review_needed,
            ),
        )


def insert_analysis(
    clip_id: int,
    analysis_type: str,
    result: dict,
    agenda_item_id: int | None = None,
    model_used: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
):
    """Insert analysis result."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO analysis
            (clip_id, agenda_item_id, analysis_type, result, model_used, prompt_tokens, completion_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clip_id,
                agenda_item_id,
                analysis_type,
                json.dumps(result),
                model_used,
                prompt_tokens,
                completion_tokens,
            ),
        )


def log_processing(clip_id: int, stage: str, status: str, message: str = ""):
    """Log a processing event."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO processing_log (clip_id, stage, status, message)
            VALUES (?, ?, ?, ?)
            """,
            (clip_id, stage, status, message),
        )


def get_processing_stats() -> dict[str, Any]:
    """Get summary statistics for the pipeline."""
    with get_db() as conn:
        # Count by status
        status_counts = {}
        rows = conn.execute(
            "SELECT status, COUNT(*) as count FROM meetings GROUP BY status"
        ).fetchall()
        for row in rows:
            status_counts[row["status"]] = row["count"]

        # Total meetings
        total = conn.execute("SELECT COUNT(*) FROM meetings").fetchone()[0]

        # Recent failures
        failures = conn.execute(
            """
            SELECT clip_id, stage, message, created_at
            FROM processing_log
            WHERE status = 'failed'
            ORDER BY created_at DESC
            LIMIT 10
            """
        ).fetchall()

        return {
            "total_meetings": total,
            "by_status": status_counts,
            "recent_failures": [dict(f) for f in failures],
        }


def get_all_meetings() -> list[dict]:
    """Get all meetings ordered by date."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM meetings ORDER BY meeting_date DESC"
        ).fetchall()
        return [dict(row) for row in rows]
