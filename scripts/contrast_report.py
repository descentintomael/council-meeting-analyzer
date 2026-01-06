#!/usr/bin/env python3
"""
Van Overbeek vs Winslow Contrast Report

Generates side-by-side comparison for campaign messaging.
"""

import sqlite3
import json
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "data" / "meetings.db"


def get_all_positions():
    """Get all council positions."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT m.clip_id, m.title, m.meeting_date, a.result
        FROM analysis a
        JOIN meetings m ON a.clip_id = m.clip_id
        WHERE a.analysis_type = 'advocacy_intel'
        AND m.status = 'analyzed'
        ORDER BY m.meeting_date
    """)

    return cursor.fetchall()


def normalize_member_name(name: str) -> str | None:
    """Normalize council member names."""
    name_lower = name.lower().strip()

    # Remove prefixes
    for prefix in ["councilmember ", "council member ", "councilman ", "councilwoman ",
                   "vice mayor ", "mayor ", "cm ", "member "]:
        if name_lower.startswith(prefix):
            name_lower = name_lower[len(prefix):]

    if "overbeek" in name_lower or "overbeck" in name_lower:
        return "Van Overbeek"
    elif "winslow" in name_lower:
        return "Winslow"

    return None


def extract_member_data(records):
    """Extract data for Van Overbeek and Winslow."""
    overbeek_data = {
        "positions": [],
        "recusals": [],
        "key_quotes": [],
        "topics": defaultdict(int)
    }
    winslow_data = {
        "positions": [],
        "recusals": [],
        "key_quotes": [],
        "topics": defaultdict(int)
    }

    for clip_id, title, date, result_json in records:
        if not result_json:
            continue

        try:
            result = json.loads(result_json)
        except json.JSONDecodeError:
            continue

        if not isinstance(result, dict):
            continue

        positions = result.get("council_positions", {})
        key_quotes = result.get("key_quotes", [])

        for member, position in positions.items():
            normalized = normalize_member_name(member)
            if not normalized or not isinstance(position, str):
                continue

            data = overbeek_data if normalized == "Van Overbeek" else winslow_data if normalized == "Winslow" else None
            if not data:
                continue

            data["positions"].append({
                "date": date,
                "title": title,
                "position": position,
                "clip_id": clip_id
            })

            # Track recusals
            if "recus" in position.lower():
                data["recusals"].append({
                    "date": date,
                    "title": title,
                    "reason": position
                })

            # Track topics
            title_lower = title.lower()
            topics = {
                "housing": ["housing", "apartment", "residential"],
                "downtown": ["downtown", "parklet", "main street"],
                "parks": ["park", "bidwell", "trail"],
                "homelessness": ["homeless", "shelter", "encampment"],
                "budget": ["budget", "tax", "fee"],
                "public_safety": ["police", "fire", "safety"]
            }
            for topic, keywords in topics.items():
                if any(kw in title_lower for kw in keywords):
                    data["topics"][topic] += 1

        # Track key quotes mentioning either member
        if isinstance(key_quotes, list):
            for quote in key_quotes:
                if isinstance(quote, str):
                    quote_lower = quote.lower()
                    if "overbeek" in quote_lower or "overbeck" in quote_lower:
                        overbeek_data["key_quotes"].append({
                            "date": date,
                            "quote": quote
                        })
                    if "winslow" in quote_lower:
                        winslow_data["key_quotes"].append({
                            "date": date,
                            "quote": quote
                        })

    return overbeek_data, winslow_data


def find_direct_disagreements(records):
    """Find meetings where Van Overbeek and Winslow took opposite positions."""
    disagreements = []

    for clip_id, title, date, result_json in records:
        if not result_json:
            continue

        try:
            result = json.loads(result_json)
        except json.JSONDecodeError:
            continue

        if not isinstance(result, dict):
            continue

        positions = result.get("council_positions", {})

        overbeek_pos = None
        winslow_pos = None

        for member, position in positions.items():
            normalized = normalize_member_name(member)
            if normalized == "Van Overbeek":
                overbeek_pos = position
            elif normalized == "Winslow":
                winslow_pos = position

        if overbeek_pos and winslow_pos:
            # Check for clear disagreement
            o_lower = overbeek_pos.lower()
            w_lower = winslow_pos.lower()

            # Skip if either recused
            if "recus" in o_lower or "recus" in w_lower:
                continue

            # Check for yes/no disagreement
            o_yes = any(x in o_lower for x in ["yes", "aye", "favor", "support"])
            o_no = any(x in o_lower for x in [" no ", "nay", "against", "oppose", "voted no"])
            w_yes = any(x in w_lower for x in ["yes", "aye", "favor", "support"])
            w_no = any(x in w_lower for x in [" no ", "nay", "against", "oppose", "voted no"])

            if (o_yes and w_no) or (o_no and w_yes):
                disagreements.append({
                    "date": date,
                    "title": title,
                    "clip_id": clip_id,
                    "overbeek": overbeek_pos,
                    "winslow": winslow_pos
                })

    return disagreements


def generate_report():
    """Generate the full contrast report."""
    records = get_all_positions()
    overbeek, winslow = extract_member_data(records)
    disagreements = find_direct_disagreements(records)

    print("=" * 80)
    print("VAN OVERBEEK vs WINSLOW - CONTRAST REPORT")
    print("=" * 80)

    # Overall stats
    print("\n## OVERVIEW")
    print("-" * 40)
    print(f"{'Metric':<30} {'Van Overbeek':<15} {'Winslow':<15}")
    print("-" * 60)
    print(f"{'Total positions documented':<30} {len(overbeek['positions']):<15} {len(winslow['positions']):<15}")
    print(f"{'Recusals':<30} {len(overbeek['recusals']):<15} {len(winslow['recusals']):<15}")
    print(f"{'Key quotes':<30} {len(overbeek['key_quotes']):<15} {len(winslow['key_quotes']):<15}")

    # Recusal comparison - KEY DIFFERENTIATOR
    print("\n## RECUSAL COMPARISON")
    print("-" * 40)
    print(f"\nVan Overbeek recusals: {len(overbeek['recusals'])}")
    for rec in overbeek['recusals']:
        print(f"  [{rec['date']}] {rec['title'][:40]}")
        print(f"    Reason: {rec['reason'][:80]}...")

    print(f"\nWinslow recusals: {len(winslow['recusals'])}")
    for rec in winslow['recusals']:
        print(f"  [{rec['date']}] {rec['title'][:40]}")
        print(f"    Reason: {rec['reason'][:80]}...")

    # Direct disagreements
    print("\n## DIRECT DISAGREEMENTS")
    print("-" * 40)
    print(f"\nTotal direct disagreements found: {len(disagreements)}")

    for d in disagreements:
        print(f"\n[{d['date']}] {d['title'][:50]}")
        print(f"  Van Overbeek: {d['overbeek'][:100]}...")
        print(f"  Winslow: {d['winslow'][:100]}...")

    # Topic engagement comparison
    print("\n## TOPIC ENGAGEMENT")
    print("-" * 40)
    print(f"\n{'Topic':<20} {'Van Overbeek':<15} {'Winslow':<15}")
    print("-" * 50)
    all_topics = set(overbeek['topics'].keys()) | set(winslow['topics'].keys())
    for topic in sorted(all_topics):
        o_count = overbeek['topics'].get(topic, 0)
        w_count = winslow['topics'].get(topic, 0)
        print(f"{topic:<20} {o_count:<15} {w_count:<15}")

    # Campaign messaging opportunities
    print("\n" + "=" * 80)
    print("CAMPAIGN MESSAGING OPPORTUNITIES")
    print("=" * 80)

    print("""
## KEY CONTRASTS FOR CAMPAIGN USE

### 1. CONFLICTS OF INTEREST
Van Overbeek: {0} documented recusals (bar ownership, property interests)
Winslow: {1} documented recusals

**Message:** "Van Overbeek is too conflicted to serve your interests."

### 2. DISMISSIVE OF COLLEAGUES
Van Overbeek: Called disability accessibility motion "silly grandstanding"
Winslow: (search for supportive statements)

**Message:** "Winslow listens. Van Overbeek dismisses."

### 3. POLITICAL CALCULATION
Van Overbeek: Admitted making decisions based on "re-election considerations"
Winslow: (contrast needed)

**Message:** "Van Overbeek votes for himself. Winslow votes for you."

### 4. CONSTITUENT RESPONSIVENESS
Van Overbeek: Documented failure to respond to motor oil complaint
Winslow: (search for positive constituent interactions)

**Message:** "When you call, Winslow answers."

## LIMITATIONS

NOTE: Van Overbeek and Winslow agree on 88.7% of votes.
The contrast is more about STYLE and CONFLICTS than POLICY.
Focus messaging on character and responsiveness, not voting record.
""".format(len(overbeek['recusals']), len(winslow['recusals'])))


def export_report(output_path: str):
    """Export report data to JSON."""
    records = get_all_positions()
    overbeek, winslow = extract_member_data(records)
    disagreements = find_direct_disagreements(records)

    output = {
        "van_overbeek": {
            "positions_count": len(overbeek['positions']),
            "recusals_count": len(overbeek['recusals']),
            "recusals": overbeek['recusals'],
            "topics": dict(overbeek['topics']),
            "key_quotes": overbeek['key_quotes'][:20]
        },
        "winslow": {
            "positions_count": len(winslow['positions']),
            "recusals_count": len(winslow['recusals']),
            "recusals": winslow['recusals'],
            "topics": dict(winslow['topics']),
            "key_quotes": winslow['key_quotes'][:20]
        },
        "disagreements": disagreements,
        "agreement_rate": "88.7%",
        "campaign_angles": [
            "Conflicts of interest (6 recusals)",
            "Dismissive of colleagues",
            "Political calculation over principle",
            "Unresponsive to constituents"
        ]
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"Exported to {output_path}")


if __name__ == "__main__":
    generate_report()
