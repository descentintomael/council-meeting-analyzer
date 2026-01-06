#!/usr/bin/env python3
"""
Voting Alignment Analysis for Van Overbeek Opposition Research

Analyzes voting patterns to determine:
- Who Van Overbeek votes with most/least often
- Issues where he diverges from majority
- Patterns in his voting behavior
"""

import sqlite3
import json
import re
from collections import defaultdict
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "meetings.db"

# Council member name normalization
MEMBER_ALIASES = {
    "van overbeek": "Van Overbeek",
    "van overbeck": "Van Overbeek",
    "overbeck": "Van Overbeek",
    "overbeek": "Van Overbeek",
    "winslow": "Winslow",
    "reynolds": "Reynolds",
    "brown": "Brown",
    "morgan": "Morgan",
    "coolidge": "Coolidge",
    "huber": "Huber",
    "stone": "Stone",
    "tandon": "Tandon",
    "bennett": "Bennett",
    "hawley": "Hawley",
    "goldstein": "Goldstein",
    "o'brien": "O'Brien",
    "obrien": "O'Brien",
    "holley": "Holley",
}


def normalize_member_name(name: str) -> str | None:
    """Normalize council member names."""
    name_lower = name.lower().strip()

    # Remove common prefixes
    for prefix in ["councilmember ", "council member ", "councilman ", "councilwoman ",
                   "vice mayor ", "mayor ", "cm ", "member "]:
        if name_lower.startswith(prefix):
            name_lower = name_lower[len(prefix):]

    # Check aliases
    for alias, normalized in MEMBER_ALIASES.items():
        if alias in name_lower:
            return normalized

    return None


def normalize_vote(position: str) -> str | None:
    """Normalize vote positions to yes/no/abstain/recused."""
    if not position:
        return None

    pos_lower = position.lower()

    # Recused
    if "recus" in pos_lower:
        return "recused"

    # Abstain
    if "abstain" in pos_lower or "absent" in pos_lower:
        return "abstain"

    # Yes votes
    yes_patterns = ["yes", "aye", "favor", "support", "voted for", "in favor",
                    "approved", "seconded"]
    for pattern in yes_patterns:
        if pattern in pos_lower:
            return "yes"

    # No votes
    no_patterns = ["no", "nay", "against", "oppose", "voted against", "dissent"]
    for pattern in no_patterns:
        if pattern in pos_lower:
            return "no"

    return None


def get_all_positions():
    """Extract all council positions from analysis."""
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


def extract_votes():
    """Extract and normalize all votes."""
    records = get_all_positions()

    all_votes = []  # [(date, title, clip_id, {member: vote})]

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
        if not positions or not isinstance(positions, dict):
            continue

        # Normalize positions
        vote_record = {}
        for member, position in positions.items():
            normalized_name = normalize_member_name(member)
            if not normalized_name:
                continue

            if isinstance(position, str):
                normalized_vote = normalize_vote(position)
                if normalized_vote:
                    vote_record[normalized_name] = normalized_vote

        if vote_record:
            all_votes.append((date, title, clip_id, vote_record))

    return all_votes


def calculate_alignment(votes: list, target_member: str = "Van Overbeek"):
    """Calculate voting alignment between target member and all others."""
    alignment = defaultdict(lambda: {"agree": 0, "disagree": 0, "total": 0})

    for date, title, clip_id, vote_record in votes:
        if target_member not in vote_record:
            continue

        target_vote = vote_record[target_member]
        if target_vote in ["recused", "abstain"]:
            continue

        for member, vote in vote_record.items():
            if member == target_member:
                continue
            if vote in ["recused", "abstain"]:
                continue

            alignment[member]["total"] += 1
            if vote == target_vote:
                alignment[member]["agree"] += 1
            else:
                alignment[member]["disagree"] += 1

    return alignment


def find_divergent_votes(votes: list, target_member: str = "Van Overbeek"):
    """Find votes where target member disagreed with majority."""
    divergent = []

    for date, title, clip_id, vote_record in votes:
        if target_member not in vote_record:
            continue

        target_vote = vote_record[target_member]
        if target_vote in ["recused", "abstain"]:
            continue

        # Count yes/no votes
        yes_count = sum(1 for v in vote_record.values() if v == "yes")
        no_count = sum(1 for v in vote_record.values() if v == "no")

        # Determine majority
        if yes_count > no_count:
            majority = "yes"
        elif no_count > yes_count:
            majority = "no"
        else:
            continue  # Tie

        # Check if target diverged
        if target_vote != majority:
            divergent.append({
                "date": date,
                "title": title,
                "clip_id": clip_id,
                "target_vote": target_vote,
                "majority": majority,
                "yes_count": yes_count,
                "no_count": no_count,
                "all_votes": vote_record
            })

    return divergent


def analyze_vote_patterns(votes: list, target_member: str = "Van Overbeek"):
    """Analyze voting patterns by topic keywords."""
    patterns = defaultdict(lambda: {"yes": 0, "no": 0, "recused": 0})

    topic_keywords = {
        "housing": ["housing", "apartment", "residential", "zoning", "development"],
        "downtown": ["downtown", "main street", "parklet", "sidewalk cafe"],
        "homelessness": ["homeless", "shelter", "encampment", "unhoused"],
        "police": ["police", "public safety", "law enforcement", "crime"],
        "parks": ["park", "bidwell", "recreation", "trail"],
        "budget": ["budget", "tax", "fee", "revenue", "spending"],
        "business": ["business", "commercial", "retail", "restaurant", "bar"],
    }

    for date, title, clip_id, vote_record in votes:
        if target_member not in vote_record:
            continue

        target_vote = vote_record[target_member]
        title_lower = title.lower()

        for topic, keywords in topic_keywords.items():
            if any(kw in title_lower for kw in keywords):
                if target_vote in ["yes", "no", "recused"]:
                    patterns[topic][target_vote] += 1

    return patterns


def print_report(target_member: str = "Van Overbeek"):
    """Generate and print the full voting alignment report."""
    print("=" * 80)
    print(f"VOTING ALIGNMENT ANALYSIS: {target_member}")
    print("=" * 80)

    votes = extract_votes()
    print(f"\nTotal vote records analyzed: {len(votes)}")

    # Alignment matrix
    print("\n" + "-" * 40)
    print("ALIGNMENT WITH OTHER COUNCIL MEMBERS")
    print("-" * 40)

    alignment = calculate_alignment(votes, target_member)

    # Sort by agreement percentage
    alignment_list = []
    for member, stats in alignment.items():
        if stats["total"] > 0:
            pct = (stats["agree"] / stats["total"]) * 100
            alignment_list.append((member, pct, stats["agree"], stats["disagree"], stats["total"]))

    alignment_list.sort(key=lambda x: x[1], reverse=True)

    print(f"\n{'Member':<15} {'Agreement':<12} {'Agree':<8} {'Disagree':<10} {'Total':<8}")
    print("-" * 55)
    for member, pct, agree, disagree, total in alignment_list:
        print(f"{member:<15} {pct:>6.1f}%      {agree:<8} {disagree:<10} {total:<8}")

    # Divergent votes
    print("\n" + "-" * 40)
    print(f"VOTES WHERE {target_member.upper()} DIVERGED FROM MAJORITY")
    print("-" * 40)

    divergent = find_divergent_votes(votes, target_member)
    print(f"\nTotal divergent votes: {len(divergent)}")

    for vote in divergent[:15]:
        print(f"\n[{vote['date']}] {vote['title'][:60]}")
        print(f"  {target_member}: {vote['target_vote'].upper()} (Majority: {vote['majority'].upper()})")
        print(f"  Vote count: {vote['yes_count']} yes, {vote['no_count']} no")

    if len(divergent) > 15:
        print(f"\n... and {len(divergent) - 15} more divergent votes")

    # Voting patterns by topic
    print("\n" + "-" * 40)
    print(f"VOTING PATTERNS BY TOPIC")
    print("-" * 40)

    patterns = analyze_vote_patterns(votes, target_member)

    print(f"\n{'Topic':<15} {'Yes':<8} {'No':<8} {'Recused':<10}")
    print("-" * 45)
    for topic, stats in sorted(patterns.items()):
        total = stats["yes"] + stats["no"] + stats["recused"]
        if total > 0:
            print(f"{topic:<15} {stats['yes']:<8} {stats['no']:<8} {stats['recused']:<10}")

    # Recusal analysis
    print("\n" + "-" * 40)
    print(f"RECUSAL ANALYSIS")
    print("-" * 40)

    recusals = []
    for date, title, clip_id, vote_record in votes:
        if target_member in vote_record and vote_record[target_member] == "recused":
            recusals.append((date, title))

    print(f"\nTotal recusals: {len(recusals)}")
    for date, title in recusals:
        print(f"  [{date}] {title[:60]}")

    # Compare with Winslow
    print("\n" + "-" * 40)
    print("COMPARISON: Van Overbeek vs Winslow")
    print("-" * 40)

    overbeek_vs_winslow = {"agree": 0, "disagree": 0}
    disagreement_list = []

    for date, title, clip_id, vote_record in votes:
        if "Van Overbeek" in vote_record and "Winslow" in vote_record:
            vo_vote = vote_record["Van Overbeek"]
            w_vote = vote_record["Winslow"]

            if vo_vote in ["recused", "abstain"] or w_vote in ["recused", "abstain"]:
                continue

            if vo_vote == w_vote:
                overbeek_vs_winslow["agree"] += 1
            else:
                overbeek_vs_winslow["disagree"] += 1
                disagreement_list.append((date, title, vo_vote, w_vote))

    total = overbeek_vs_winslow["agree"] + overbeek_vs_winslow["disagree"]
    if total > 0:
        agree_pct = (overbeek_vs_winslow["agree"] / total) * 100
        print(f"\nAgreement rate: {agree_pct:.1f}%")
        print(f"Agreed: {overbeek_vs_winslow['agree']}, Disagreed: {overbeek_vs_winslow['disagree']}")

        print("\n### DISAGREEMENTS ###")
        for date, title, vo, w in disagreement_list[:10]:
            print(f"\n[{date}] {title[:50]}")
            print(f"  Van Overbeek: {vo.upper()}, Winslow: {w.upper()}")


def export_to_json(output_path: str = None):
    """Export analysis to JSON for further processing."""
    votes = extract_votes()
    alignment = calculate_alignment(votes)
    divergent = find_divergent_votes(votes)
    patterns = analyze_vote_patterns(votes)

    output = {
        "target_member": "Van Overbeek",
        "total_votes_analyzed": len(votes),
        "alignment": {
            member: {
                "agreement_pct": (stats["agree"] / stats["total"] * 100) if stats["total"] > 0 else 0,
                **stats
            }
            for member, stats in alignment.items()
        },
        "divergent_votes": divergent,
        "patterns_by_topic": dict(patterns),
    }

    if output_path:
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"Exported to {output_path}")

    return output


if __name__ == "__main__":
    print_report()

    # Optionally export to JSON
    # export_to_json("/tmp/voting_alignment.json")
