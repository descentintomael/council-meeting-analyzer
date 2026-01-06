#!/usr/bin/env python3
"""
Quote Extractor for Van Overbeek Opposition Research

Extracts and categorizes potentially damaging quotes for campaign use.
Categories:
- Dismissive of colleagues
- Conflicts of interest
- Political expediency
- Unresponsive to constituents
- Arrogant/condescending
"""

import sqlite3
import json
import re
from pathlib import Path
from collections import defaultdict

DB_PATH = Path(__file__).parent.parent / "data" / "meetings.db"


def get_key_quotes():
    """Extract all key quotes from analysis that mention Van Overbeek."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT m.clip_id, m.title, m.meeting_date, m.video_url, a.result
        FROM analysis a
        JOIN meetings m ON a.clip_id = m.clip_id
        WHERE a.analysis_type = 'advocacy_intel'
        AND m.status = 'analyzed'
        AND (a.result LIKE '%Van Overbeck%' OR a.result LIKE '%Van Overbeek%'
             OR a.result LIKE '%overbeek%' OR a.result LIKE '%overbeck%')
        ORDER BY m.meeting_date DESC
    """)

    return cursor.fetchall()


def get_transcript_excerpts(clip_id: int, search_terms: list[str]) -> list[dict]:
    """Search transcript for excerpts containing search terms."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT merged_text
        FROM transcription_validation
        WHERE clip_id = ?
    """, (clip_id,))

    result = cursor.fetchone()
    if not result or not result[0]:
        return []

    text = result[0]
    excerpts = []

    for term in search_terms:
        pattern = re.compile(
            rf'.{{0,200}}{re.escape(term)}.{{0,200}}',
            re.IGNORECASE
        )
        matches = pattern.findall(text)
        for match in matches:
            excerpts.append({
                "term": term,
                "excerpt": match.strip()
            })

    return excerpts


# Attack categories and their search patterns
ATTACK_CATEGORIES = {
    "dismissive": {
        "keywords": ["silly", "ridiculous", "waste of time", "grandstanding",
                     "not serious", "pointless", "absurd"],
        "description": "Dismissive of colleagues or constituent concerns"
    },
    "condescending": {
        "keywords": ["you don't understand", "let me explain", "obviously",
                     "clearly you", "that's not how", "you should know"],
        "description": "Condescending or arrogant tone"
    },
    "conflicts": {
        "keywords": ["recuse", "conflict", "financial interest", "bar", "downtown",
                     "business owner", "property"],
        "description": "Conflicts of interest"
    },
    "political": {
        "keywords": ["re-election", "reelection", "campaign", "voters", "political",
                     "election year"],
        "description": "Political expediency over principle"
    },
    "unresponsive": {
        "keywords": ["no response", "didn't respond", "ignored", "failed to",
                     "unresponsive", "never got back"],
        "description": "Unresponsive to constituents"
    },
    "interrupting": {
        "keywords": ["let me finish", "I wasn't done", "don't interrupt",
                     "hold on", "wait a minute"],
        "description": "Interrupting or dismissing others"
    }
}


def categorize_quote(quote: str, position: str) -> list[str]:
    """Determine which attack categories a quote falls into."""
    categories = []
    combined = (quote + " " + position).lower()

    for category, config in ATTACK_CATEGORIES.items():
        for keyword in config["keywords"]:
            if keyword in combined:
                categories.append(category)
                break

    return categories


def extract_all_quotes():
    """Extract and categorize all potentially useful quotes."""
    records = get_key_quotes()

    categorized_quotes = defaultdict(list)
    all_quotes = []

    for clip_id, title, date, video_url, result_json in records:
        if not result_json:
            continue

        try:
            result = json.loads(result_json)
        except json.JSONDecodeError:
            continue

        if not isinstance(result, dict):
            continue

        # Extract key quotes
        key_quotes = result.get("key_quotes", [])
        if isinstance(key_quotes, list):
            for quote in key_quotes:
                if isinstance(quote, str):
                    quote_lower = quote.lower()
                    # Check if Van Overbeek is mentioned or this is likely his quote
                    if "overbeek" in quote_lower or "overbeck" in quote_lower:
                        categories = categorize_quote(quote, "")
                        quote_obj = {
                            "date": date,
                            "title": title,
                            "clip_id": clip_id,
                            "video_url": video_url,
                            "quote": quote,
                            "source": "key_quotes",
                            "categories": categories
                        }
                        all_quotes.append(quote_obj)
                        for cat in categories:
                            categorized_quotes[cat].append(quote_obj)

        # Extract positions
        positions = result.get("council_positions", {})
        if isinstance(positions, dict):
            for member, position in positions.items():
                if isinstance(position, str):
                    member_lower = member.lower()
                    if "overbeek" in member_lower or "overbeck" in member_lower:
                        categories = categorize_quote("", position)
                        quote_obj = {
                            "date": date,
                            "title": title,
                            "clip_id": clip_id,
                            "video_url": video_url,
                            "quote": position,
                            "source": "council_positions",
                            "categories": categories
                        }
                        all_quotes.append(quote_obj)
                        for cat in categories:
                            categorized_quotes[cat].append(quote_obj)

    return all_quotes, categorized_quotes


def search_transcripts_for_patterns():
    """Search raw transcripts for specific damaging patterns."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Search patterns
    patterns = [
        ("silly grandstanding", "dismissive"),
        ("waste of time", "dismissive"),
        ("ridiculous", "dismissive"),
        ("re-election", "political"),
        ("reelection", "political"),
        ("conflict of interest", "conflicts"),
        ("recuse myself", "conflicts"),
        ("let me explain", "condescending"),
    ]

    results = []

    for pattern, category in patterns:
        cursor.execute("""
            SELECT m.clip_id, m.title, m.meeting_date, tv.merged_text
            FROM transcription_validation tv
            JOIN meetings m ON tv.clip_id = m.clip_id
            WHERE tv.merged_text LIKE ?
            AND m.status = 'analyzed'
        """, (f"%{pattern}%",))

        for clip_id, title, date, text in cursor.fetchall():
            # Extract context around pattern
            text_lower = text.lower()
            idx = text_lower.find(pattern.lower())
            if idx != -1:
                start = max(0, idx - 150)
                end = min(len(text), idx + len(pattern) + 150)
                excerpt = text[start:end].strip()

                results.append({
                    "date": date,
                    "title": title,
                    "clip_id": clip_id,
                    "pattern": pattern,
                    "category": category,
                    "excerpt": f"...{excerpt}..."
                })

    return results


def print_report():
    """Generate comprehensive quote report."""
    print("=" * 80)
    print("VAN OVERBEEK QUOTE EXTRACTION REPORT")
    print("=" * 80)

    all_quotes, categorized = extract_all_quotes()

    print(f"\nTotal quotes extracted: {len(all_quotes)}")

    # Print by category
    for category, config in ATTACK_CATEGORIES.items():
        quotes = categorized.get(category, [])
        print(f"\n" + "-" * 60)
        print(f"CATEGORY: {category.upper()} ({len(quotes)} quotes)")
        print(f"Description: {config['description']}")
        print("-" * 60)

        for quote_obj in quotes[:5]:  # Top 5 per category
            print(f"\n[{quote_obj['date']}] {quote_obj['title'][:50]}")
            print(f"  \"{quote_obj['quote'][:200]}...\"" if len(quote_obj['quote']) > 200 else f"  \"{quote_obj['quote']}\"")

        if len(quotes) > 5:
            print(f"\n  ... and {len(quotes) - 5} more")

    # Transcript pattern search
    print("\n" + "=" * 80)
    print("TRANSCRIPT PATTERN SEARCH")
    print("=" * 80)

    transcript_results = search_transcripts_for_patterns()
    print(f"\nPatterns found in transcripts: {len(transcript_results)}")

    for result in transcript_results[:15]:
        print(f"\n[{result['date']}] {result['title'][:40]}")
        print(f"  Pattern: \"{result['pattern']}\" ({result['category']})")
        print(f"  {result['excerpt'][:200]}...")

    # Summary of best attack angles
    print("\n" + "=" * 80)
    print("ATTACK ANGLE SUMMARY")
    print("=" * 80)

    for category, quotes in sorted(categorized.items(), key=lambda x: -len(x[1])):
        print(f"\n{category.upper()}: {len(quotes)} instances")
        print(f"  {ATTACK_CATEGORIES[category]['description']}")


def export_to_json(output_path: str):
    """Export all quotes to JSON for further processing."""
    all_quotes, categorized = extract_all_quotes()
    transcript_results = search_transcripts_for_patterns()

    output = {
        "total_quotes": len(all_quotes),
        "all_quotes": all_quotes,
        "by_category": {k: v for k, v in categorized.items()},
        "transcript_patterns": transcript_results,
        "categories": ATTACK_CATEGORIES
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"Exported {len(all_quotes)} quotes to {output_path}")


def get_campaign_ready_quotes():
    """Return the most campaign-ready quotes."""
    all_quotes, categorized = extract_all_quotes()
    transcript_results = search_transcripts_for_patterns()

    # Priority quotes (multiple categories or high-value patterns)
    priority = []

    # The "silly grandstanding" quote is gold
    for result in transcript_results:
        if "grandstanding" in result["pattern"].lower():
            priority.append({
                "quote": result["excerpt"],
                "date": result["date"],
                "title": result["title"],
                "attack_angle": "Dismissive of colleagues discussing disability accessibility",
                "priority": "HIGH"
            })

    # Recusals for conflicts
    for quote in categorized.get("conflicts", []):
        if "recus" in quote["quote"].lower():
            priority.append({
                "quote": quote["quote"],
                "date": quote["date"],
                "title": quote["title"],
                "attack_angle": "Too many conflicts of interest",
                "priority": "HIGH"
            })

    # Political expediency
    for quote in categorized.get("political", []):
        priority.append({
            "quote": quote["quote"],
            "date": quote["date"],
            "title": quote["title"],
            "attack_angle": "Puts politics over principle",
            "priority": "MEDIUM"
        })

    return priority


if __name__ == "__main__":
    print_report()
    print("\n" + "=" * 80)
    print("CAMPAIGN-READY QUOTES")
    print("=" * 80)

    priority_quotes = get_campaign_ready_quotes()
    for i, q in enumerate(priority_quotes[:10], 1):
        print(f"\n{i}. [{q['priority']}] {q['date']}")
        print(f"   Attack: {q['attack_angle']}")
        print(f"   Quote: \"{q['quote'][:150]}...\"" if len(q['quote']) > 150 else f"   Quote: \"{q['quote']}\"")
