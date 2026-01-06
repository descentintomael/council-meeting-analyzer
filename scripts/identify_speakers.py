#!/usr/bin/env python3
"""Speaker identification for diarized council meeting transcripts.

Identifies speakers by analyzing transcript patterns:
1. Role detection (Chair/Mayor, Clerk)
2. Council member identification (from motions, seconds, roll call)
3. Guest speaker identification (from self-introductions)
4. LLM-based inference for remaining speakers

Usage:
    python scripts/identify_speakers.py              # Process all diarized meetings
    python scripts/identify_speakers.py 1196         # Process single meeting
    python scripts/identify_speakers.py --dry-run    # Analyze without saving
"""

import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.table import Table

PROJECT_ROOT = Path(__file__).parent.parent
TRANSCRIPT_DIR = PROJECT_ROOT / "data" / "transcripts"

console = Console()

# Known council members (current and recent)
KNOWN_COUNCIL_MEMBERS = [
    "Coolidge", "Reynolds", "Brown", "Huber", "Morgan",
    "Stone", "Tandon", "Winslow", "Bennett", "Van Overbeck",
    "Schwab", "Ory", "Ori", "Orry",  # Various spellings
]

KNOWN_STAFF_TITLES = [
    "City Manager", "City Attorney", "City Clerk", "Deputy Clerk",
    "Public Works Director", "Community Development Director",
    "Police Chief", "Fire Chief", "Finance Director",
]


@dataclass
class SpeakerProfile:
    """Accumulated evidence for a speaker's identity."""
    speaker_id: str
    segment_count: int = 0
    total_duration: float = 0.0

    # Role indicators
    chair_score: int = 0
    clerk_score: int = 0
    council_score: int = 0
    staff_score: int = 0
    public_score: int = 0

    # Identified names
    self_intro_names: list = field(default_factory=list)
    attributed_names: list = field(default_factory=list)
    motion_names: list = field(default_factory=list)

    # Final identification
    identified_name: str | None = None
    identified_role: str | None = None
    confidence: float = 0.0


class SpeakerIdentifier:
    """Identifies speakers in diarized meeting transcripts."""

    # Patterns for role detection
    CHAIR_PATTERNS = [
        re.compile(r"call.*(?:meeting|session).*to order", re.I),
        re.compile(r"all (?:those )?in favor", re.I),
        re.compile(r"motion (?:carries|passes|fails|is adopted)", re.I),
        re.compile(r"(?:take|call) the roll", re.I),
        re.compile(r"entertain a motion", re.I),
        re.compile(r"public (?:comment|hearing) (?:is )?(?:now )?(?:open|closed)", re.I),
        re.compile(r"meeting (?:is )?adjourned", re.I),
        re.compile(r"we(?:'ll| will) (?:move|proceed) (?:on )?to", re.I),
    ]

    CLERK_PATTERNS = [
        re.compile(r"(?:council\s*member|mayor|vice\s*mayor)\s+[a-z]+\s*\?", re.I),
        re.compile(r"(?:aye|yes|no|nay)\s*[.,]\s*(?:council\s*member|mayor)", re.I),
        re.compile(r"motion (?:by|from)\s+(?:council\s*member|vice\s*mayor)", re.I),
        re.compile(r"second(?:ed)?\s+(?:by|from)\s+(?:council\s*member|vice\s*mayor)", re.I),
        re.compile(r"(?:item|agenda item)\s+\d+", re.I),
    ]

    # Patterns for speaker identification
    SELF_INTRO_PATTERNS = [
        re.compile(r"(?:^|[.!?]\s+)my name is\s+(?:to\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", re.I),  # handles "to Neil" ASR error
        re.compile(r"(?:^|good\s+(?:morning|evening|afternoon)[,.]?\s*)I'm\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", re.I),
        re.compile(r"(?:^|[.!?]\s+)this is\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:speaking|here)", re.I),
        re.compile(r"(?:^|[.!?]\s+)I am\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:and|,|from|with)", re.I),
    ]

    # Pattern to detect public speaker queue announced by clerk
    SPEAKER_QUEUE_PATTERNS = [
        re.compile(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+followed by\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", re.I),
        re.compile(r"(?:next|first|our)\s+speaker\s+(?:is\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", re.I),
        re.compile(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*[.,]?\s*(?:welcome|please|go ahead|come)", re.I),
    ]

    MOTION_ATTRIBUTION_PATTERNS = [
        re.compile(r"motion (?:by|from)\s+(?:council\s*member\s+)?([A-Z][a-z]+)", re.I),
        re.compile(r"(?:council\s*member|vice\s*mayor)\s+([A-Z][a-z]+)\s+moves?", re.I),
        re.compile(r"([A-Z][a-z]+)\s+moves?\s+(?:to|that)", re.I),
    ]

    SECOND_ATTRIBUTION_PATTERNS = [
        re.compile(r"second(?:ed)?\s+(?:by|from)\s+(?:council\s*member\s+)?([A-Z][a-z]+)", re.I),
        re.compile(r"(?:council\s*member|vice\s*mayor)\s+([A-Z][a-z]+)\s+seconds?", re.I),
    ]

    DIRECT_ADDRESS_PATTERNS = [
        re.compile(r"thank(?:s|\s+you),?\s+(?:council\s*member\s+)?([A-Z][a-z]+)", re.I),
        re.compile(r"(?:mr|ms|mrs)\.\s+([A-Z][a-z]+)", re.I),
        re.compile(r"mayor\s+([A-Z][a-z]+)", re.I),
        re.compile(r"vice\s*mayor\s+([A-Z][a-z]+)", re.I),
    ]

    def __init__(self, clip_id: int):
        self.clip_id = clip_id
        self.segments: list[dict] = []
        self.profiles: dict[str, SpeakerProfile] = {}
        self.speaker_mapping: dict[str, str] = {}

    def load_diarization(self) -> bool:
        """Load diarization file."""
        diar_path = TRANSCRIPT_DIR / f"{self.clip_id}_diarization.json"
        if not diar_path.exists():
            console.print(f"[red]Diarization file not found: {diar_path}[/red]")
            return False

        with open(diar_path) as f:
            data = json.load(f)

        self.segments = data.get("segments", [])
        self.original_data = data

        # Initialize profiles for each speaker
        for seg in self.segments:
            speaker_id = seg.get("speaker_id", "UNKNOWN")
            if speaker_id not in self.profiles:
                self.profiles[speaker_id] = SpeakerProfile(speaker_id=speaker_id)

            profile = self.profiles[speaker_id]
            profile.segment_count += 1
            start = seg.get("start", 0)
            end = seg.get("end", start)
            profile.total_duration += (end - start)

        return True

    def detect_roles(self):
        """Detect Chair and Clerk by their characteristic phrases."""
        for seg in self.segments:
            text = seg.get("text", "")
            speaker_id = seg.get("speaker_id", "UNKNOWN")
            profile = self.profiles.get(speaker_id)
            if not profile:
                continue

            # Check for chair patterns
            for pattern in self.CHAIR_PATTERNS:
                if pattern.search(text):
                    profile.chair_score += 1
                    break

            # Check for clerk patterns
            for pattern in self.CLERK_PATTERNS:
                if pattern.search(text):
                    profile.clerk_score += 1
                    break

        # Assign roles based on scores
        chair_candidates = [(sp, p.chair_score) for sp, p in self.profiles.items() if p.chair_score > 0]
        if chair_candidates:
            chair_id = max(chair_candidates, key=lambda x: x[1])[0]
            self.profiles[chair_id].identified_role = "Chair"
            self.profiles[chair_id].identified_name = "Mayor"  # Will be refined later

        clerk_candidates = [(sp, p.clerk_score) for sp, p in self.profiles.items()
                          if p.clerk_score > 0 and self.profiles[sp].identified_role != "Chair"]
        if clerk_candidates:
            clerk_id = max(clerk_candidates, key=lambda x: x[1])[0]
            self.profiles[clerk_id].identified_role = "Clerk"
            self.profiles[clerk_id].identified_name = "City Clerk"

    # Words that are NOT names (false positives from "I'm just...", "I'm not...", etc.)
    FALSE_POSITIVE_NAMES = {
        "i", "we", "you", "just", "not", "sure", "sorry", "here", "going",
        "trying", "looking", "hoping", "thinking", "wondering", "asking",
        "saying", "making", "doing", "getting", "having", "taking", "coming",
        "speaking", "talking", "reading", "writing", "working", "running",
        "very", "really", "actually", "also", "still", "even", "only",
        "glad", "happy", "pleased", "honored", "grateful", "excited",
        "concerned", "worried", "confused", "curious", "afraid", "opposed",
        "in", "on", "at", "to", "for", "with", "from", "a", "the", "an",
        "assuming", "guessing", "betting", "certain", "confident",
        # Common false positives from speaker announcements
        "wel", "welcome", "thank", "thanks", "please", "next", "first", "last",
        "our", "the", "this", "that", "item", "agenda", "motion", "second",
        "council", "member", "mayor", "vice", "city", "public", "speaker",
    }

    def detect_self_introductions(self):
        """Find speakers who introduce themselves."""
        for seg in self.segments:
            text = seg.get("text", "")
            speaker_id = seg.get("speaker_id", "UNKNOWN")
            profile = self.profiles.get(speaker_id)
            if not profile:
                continue

            for pattern in self.SELF_INTRO_PATTERNS:
                match = pattern.search(text)
                if match:
                    name = match.group(1).strip()
                    # Filter out false positives
                    first_word = name.split()[0].lower()
                    if first_word not in self.FALSE_POSITIVE_NAMES and len(name) > 2:
                        # Additional check: name should start with capital letter
                        if name[0].isupper():
                            profile.self_intro_names.append(name)
                            profile.public_score += 1

    def detect_speaker_queue(self):
        """Detect public speakers announced by the clerk."""
        announced_speakers = []

        for i, seg in enumerate(self.segments):
            text = seg.get("text", "")
            speaker_id = seg.get("speaker_id", "UNKNOWN")
            start = seg.get("start", 0)

            # Check if this is likely the clerk/chair making an announcement
            profile = self.profiles.get(speaker_id)
            if not profile or (profile.identified_role not in ["Chair", "Clerk"] and profile.clerk_score == 0):
                continue

            # Look for speaker queue patterns
            for pattern in self.SPEAKER_QUEUE_PATTERNS:
                matches = pattern.findall(text)
                for match in matches:
                    if isinstance(match, tuple):
                        for name in match:
                            if name and name[0].isupper():
                                announced_speakers.append((name, start))
                    elif match and match[0].isupper():
                        announced_speakers.append((match, start))

        # Now try to match announced speakers to the next speaker after announcement
        for announced_name, announce_time in announced_speakers:
            # Find the next segment from a different speaker
            for seg in self.segments:
                seg_start = seg.get("start", 0)
                seg_speaker = seg.get("speaker_id")

                # Look for segments shortly after the announcement (within 60 seconds)
                if seg_start > announce_time and seg_start < announce_time + 60:
                    profile = self.profiles.get(seg_speaker)
                    if profile and profile.identified_role not in ["Chair", "Clerk"]:
                        # Check if this speaker hasn't been identified yet
                        if not profile.identified_name:
                            first_word = announced_name.split()[0].lower()
                            if first_word not in self.FALSE_POSITIVE_NAMES:
                                profile.self_intro_names.append(announced_name)
                                profile.public_score += 1
                        break

    def detect_attributions(self):
        """Detect when speakers are attributed by the chair/clerk."""
        for i, seg in enumerate(self.segments):
            text = seg.get("text", "")
            speaker_id = seg.get("speaker_id", "UNKNOWN")

            # Check for motion attributions
            for pattern in self.MOTION_ATTRIBUTION_PATTERNS:
                match = pattern.search(text)
                if match:
                    name = match.group(1).strip()
                    if self._is_council_name(name):
                        # Find who made the motion (usually previous speaker or speaker right before this)
                        self._attribute_action_to_speaker(i, name, "motion")

            # Check for second attributions
            for pattern in self.SECOND_ATTRIBUTION_PATTERNS:
                match = pattern.search(text)
                if match:
                    name = match.group(1).strip()
                    if self._is_council_name(name):
                        self._attribute_action_to_speaker(i, name, "second")

            # Check for direct address
            for pattern in self.DIRECT_ADDRESS_PATTERNS:
                for match in pattern.finditer(text):
                    name = match.group(1).strip()
                    if self._is_council_name(name):
                        # The previous speaker might be this council member
                        if i > 0:
                            prev_speaker = self.segments[i-1].get("speaker_id")
                            if prev_speaker and prev_speaker != speaker_id:
                                profile = self.profiles.get(prev_speaker)
                                if profile:
                                    profile.attributed_names.append(name)

    def _is_council_name(self, name: str) -> bool:
        """Check if name matches a known council member."""
        name_lower = name.lower()
        for member in KNOWN_COUNCIL_MEMBERS:
            if member.lower() == name_lower or member.lower().startswith(name_lower):
                return True
        return False

    def _attribute_action_to_speaker(self, seg_index: int, name: str, action_type: str):
        """Try to find which speaker performed the action."""
        # Look backwards for a speaker who might have made the motion/second
        current_speaker = self.segments[seg_index].get("speaker_id")

        for j in range(seg_index - 1, max(0, seg_index - 5), -1):
            prev_seg = self.segments[j]
            prev_speaker = prev_seg.get("speaker_id")
            prev_text = prev_seg.get("text", "").lower()

            if prev_speaker != current_speaker:
                # Check if this speaker's text contains motion/second language
                if action_type == "motion" and ("move" in prev_text or "motion" in prev_text):
                    profile = self.profiles.get(prev_speaker)
                    if profile:
                        profile.motion_names.append(name)
                        profile.council_score += 2
                    break
                elif action_type == "second" and "second" in prev_text:
                    profile = self.profiles.get(prev_speaker)
                    if profile:
                        profile.motion_names.append(name)
                        profile.council_score += 2
                    break

    def finalize_identifications(self):
        """Finalize speaker identifications based on accumulated evidence."""
        for speaker_id, profile in self.profiles.items():
            # Skip if already identified as Chair or Clerk
            if profile.identified_role in ["Chair", "Clerk"]:
                profile.confidence = 0.8
                continue

            # Check self-introductions (highest confidence for guests)
            if profile.self_intro_names:
                # Most common self-introduction
                name_counts = Counter(profile.self_intro_names)
                most_common_name = name_counts.most_common(1)[0][0]

                # Check if it's a council member or guest
                if self._is_council_name(most_common_name):
                    profile.identified_name = f"Council Member {most_common_name}"
                    profile.identified_role = "Council"
                    profile.confidence = 0.9
                else:
                    profile.identified_name = most_common_name
                    profile.identified_role = "Public"
                    profile.confidence = 0.85
                continue

            # Check motion attributions
            if profile.motion_names:
                name_counts = Counter(profile.motion_names)
                most_common_name = name_counts.most_common(1)[0][0]
                profile.identified_name = f"Council Member {most_common_name}"
                profile.identified_role = "Council"
                profile.confidence = 0.8
                continue

            # Check attributed names
            if profile.attributed_names:
                name_counts = Counter(profile.attributed_names)
                most_common_name = name_counts.most_common(1)[0][0]
                if self._is_council_name(most_common_name):
                    profile.identified_name = f"Council Member {most_common_name}"
                    profile.identified_role = "Council"
                    profile.confidence = 0.7
                continue

            # Mark remaining speakers based on segment count
            if profile.segment_count >= 10:
                profile.identified_role = "Unknown (frequent)"
            elif profile.segment_count >= 3:
                profile.identified_role = "Unknown (occasional)"
            else:
                profile.identified_role = "Unknown (brief)"

    def build_speaker_mapping(self) -> dict[str, str]:
        """Build the final speaker_id -> name mapping."""
        self.speaker_mapping = {}

        for speaker_id, profile in self.profiles.items():
            if profile.identified_name:
                self.speaker_mapping[speaker_id] = profile.identified_name
            elif profile.identified_role:
                self.speaker_mapping[speaker_id] = profile.identified_role

        return self.speaker_mapping

    def run(self) -> dict[str, str]:
        """Run full identification pipeline."""
        if not self.load_diarization():
            return {}

        # Phase 1: Detect roles (Chair, Clerk)
        self.detect_roles()

        # Phase 2: Detect self-introductions
        self.detect_self_introductions()

        # Phase 3: Detect speaker queue announcements
        self.detect_speaker_queue()

        # Phase 4: Detect attributions (motions, seconds, direct address)
        self.detect_attributions()

        # Phase 5: Finalize identifications
        self.finalize_identifications()

        return self.build_speaker_mapping()

    def save(self):
        """Save updated diarization file with speaker mapping."""
        diar_path = TRANSCRIPT_DIR / f"{self.clip_id}_diarization.json"

        # Update original data
        self.original_data["speaker_mapping"] = self.speaker_mapping
        self.original_data["identified_speakers"] = sum(
            1 for p in self.profiles.values()
            if p.identified_name and not p.identified_name.startswith("Unknown")
        )

        # Update segments with speaker names
        for seg in self.original_data.get("segments", []):
            speaker_id = seg.get("speaker_id", "UNKNOWN")
            if speaker_id in self.speaker_mapping:
                seg["speaker_name"] = self.speaker_mapping[speaker_id]

        with open(diar_path, "w") as f:
            json.dump(self.original_data, f, indent=2)

    def print_summary(self):
        """Print identification summary."""
        table = Table(title=f"Speaker Identification - Meeting {self.clip_id}")
        table.add_column("Speaker ID", style="cyan")
        table.add_column("Identified As", style="green")
        table.add_column("Role", style="yellow")
        table.add_column("Segments", justify="right")
        table.add_column("Duration", justify="right")
        table.add_column("Confidence", justify="right")

        for speaker_id, profile in sorted(
            self.profiles.items(),
            key=lambda x: x[1].segment_count,
            reverse=True
        ):
            name = profile.identified_name or "-"
            role = profile.identified_role or "-"
            duration = f"{profile.total_duration:.0f}s"
            conf = f"{profile.confidence:.0%}" if profile.confidence > 0 else "-"

            table.add_row(
                speaker_id,
                name,
                role,
                str(profile.segment_count),
                duration,
                conf
            )

        console.print(table)

        # Summary stats
        identified = sum(1 for p in self.profiles.values()
                        if p.identified_name and not p.identified_name.startswith("Unknown"))
        total = len(self.profiles)
        console.print(f"\nIdentified: {identified}/{total} speakers ({identified/total:.0%})")


def process_meeting(clip_id: int, dry_run: bool = False) -> dict:
    """Process a single meeting."""
    console.print(f"\n[bold]Processing meeting {clip_id}[/bold]")

    identifier = SpeakerIdentifier(clip_id)
    mapping = identifier.run()

    if mapping:
        identifier.print_summary()

        if not dry_run:
            identifier.save()
            console.print(f"[green]Saved updated diarization file[/green]")

    return mapping


def process_all_meetings(dry_run: bool = False):
    """Process all diarized meetings."""
    diar_files = sorted(TRANSCRIPT_DIR.glob("*_diarization.json"))

    console.print(f"[bold]Found {len(diar_files)} diarized meetings[/bold]")

    total_identified = 0
    total_speakers = 0

    for diar_file in diar_files:
        clip_id = int(diar_file.stem.split("_")[0])

        identifier = SpeakerIdentifier(clip_id)
        mapping = identifier.run()

        if mapping:
            identified = sum(1 for p in identifier.profiles.values()
                           if p.identified_name and not p.identified_name.startswith("Unknown"))
            total = len(identifier.profiles)

            console.print(f"  {clip_id}: {identified}/{total} speakers identified")

            total_identified += identified
            total_speakers += total

            if not dry_run:
                identifier.save()

    console.print(f"\n[bold]Summary[/bold]")
    console.print(f"Total speakers: {total_speakers}")
    console.print(f"Total identified: {total_identified} ({total_identified/total_speakers:.0%})")


def main():
    """Main entry point."""
    dry_run = "--dry-run" in sys.argv

    # Check for specific clip ID
    clip_ids = [arg for arg in sys.argv[1:] if arg.isdigit()]

    if clip_ids:
        for clip_id in clip_ids:
            process_meeting(int(clip_id), dry_run)
    else:
        process_all_meetings(dry_run)


if __name__ == "__main__":
    main()
