#!/usr/bin/env python3
"""
Parse meeting minutes PDFs from Granicus to extract speaker names.
Uses the MinutesViewer.php endpoint to download minutes PDFs.

This helps improve speaker identification by extracting official names from:
- Roll call attendance
- Public comment speakers
- Motion/second attributions
- Other speaker mentions
"""

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from urllib.request import urlretrieve
import time

# Patterns for extracting speaker information from minutes

# Public comment speakers - multiple patterns
PUBLIC_COMMENT_PATTERNS = [
    # "Addressing the Council [via X] were/was X, Y, and Z"
    re.compile(r"[Aa]ddressing the [Cc]ouncil(?:\s+via\s+\w+(?:\s+\w+)*)?\s+(?:regarding[^.]+)?\s*(?:were|was)\s+(.+?)(?:\.|$)", re.MULTILINE),
    # "Members of the public addressing the Council included X, Y, Z"
    re.compile(r"[Mm]embers of the public (?:addressing|who addressed).*?(?:were|included|:)\s+(.+?)(?:\.|$)", re.MULTILINE),
    # "Public comments were made by X, Y, Z"
    re.compile(r"[Pp]ublic comments? (?:were|was) (?:made|provided|given) by\s+(.+?)(?:\.|$)", re.MULTILINE),
    # "Speakers included X, Y, Z"
    re.compile(r"[Ss]peakers? (?:included|were|:)\s+(.+?)(?:\.|$)", re.MULTILINE),
]

# Motion patterns - capture multi-word names like "van Overbeek"
# Use word boundary or punctuation to stop capture
MOTION_PATTERNS = [
    # "A motion was made by Councilmember X and seconded by..."
    re.compile(r"[Mm]otion (?:was )?made by (?:Council\s*member|Councilmember|Vice Mayor|Mayor)\s+([A-Za-z]+(?:\s+[A-Z][a-z]+)?)(?:\s+(?:to|and|$|[,.])|$)", re.I),
    re.compile(r"[Ss]econded by (?:Council\s*member|Councilmember|Vice Mayor|Mayor)\s+([A-Za-z]+(?:\s+[A-Z][a-z]+)?)(?:\s+(?:to|and|$|[,.])|$)", re.I),
    # "Moved by Vice Mayor X, seconded by..."
    re.compile(r"[Mm]oved by (?:Council\s*member|Councilmember|Vice Mayor|Mayor)\s+([A-Za-z]+(?:\s+[A-Z][a-z]+)?)(?:[,.]|$)", re.I),
]

# Roll call patterns
ROLL_CALL_PATTERNS = [
    # Present: list of names (OCR sometimes has "Present:" with capital P)
    re.compile(r"Present:\s*([A-Za-z,\s]+?)(?:\n\s*Absent:|$)", re.MULTILINE),
    re.compile(r"PRESENT:\s*\n?\s*([A-Za-z,\s]+?)(?:\nABSENT:|$)", re.I | re.MULTILINE),
    re.compile(r"AYES:\s*\n?\s*([A-Za-z,\s]+?)(?:\n\s*NOES:|$)", re.I | re.MULTILINE),
]

# Named speaker patterns
NAMED_SPEAKER_PATTERNS = [
    # "Councilmember X stated..."
    re.compile(r"(?:Council\s*member|Councilmember|Vice Mayor|Mayor)\s+([A-Za-z]+)\s+(?:stated|asked|commented|noted|moved|seconded|requested)", re.I),
    # "City Manager X reported..."
    re.compile(r"(?:City Manager|Fire Chief|Police Chief|City Attorney|City Clerk|Deputy City Manager)\s+([A-Za-z]+\s+[A-Za-z]+)(?:\s+(?:stated|reported|noted|presented))?", re.I),
]


def download_minutes_pdf(clip_id: int, output_path: str) -> bool:
    """Download minutes PDF from Granicus MinutesViewer."""
    url = f"https://chico-ca.granicus.com/MinutesViewer.php?clip_id={clip_id}&embedded=1"
    try:
        urlretrieve(url, output_path)
        # Check if it's actually a PDF
        with open(output_path, 'rb') as f:
            header = f.read(5)
            if header != b'%PDF-':
                return False
        return True
    except Exception as e:
        print(f"  Error downloading minutes for clip {clip_id}: {e}")
        return False


def pdf_to_text(pdf_path: str) -> Optional[str]:
    """Convert PDF to text using pdftotext, falling back to OCR for scanned PDFs."""
    # First try pdftotext (fast, works for text-based PDFs)
    try:
        result = subprocess.run(
            ['pdftotext', '-layout', pdf_path, '-'],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except Exception as e:
        print(f"  pdftotext failed: {e}")

    # Fall back to OCR for scanned PDFs
    print(f"  No text in PDF, using OCR...")
    return pdf_to_text_ocr(pdf_path)


def pdf_to_text_ocr(pdf_path: str) -> Optional[str]:
    """Convert scanned PDF to text using OCR (tesseract)."""
    try:
        # Get number of pages
        result = subprocess.run(
            ['pdfinfo', pdf_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        pages = 1
        for line in result.stdout.split('\n'):
            if line.startswith('Pages:'):
                pages = int(line.split(':')[1].strip())
                break

        all_text = []
        with tempfile.TemporaryDirectory() as tmpdir:
            # Convert PDF pages to images
            subprocess.run(
                ['pdftoppm', '-png', pdf_path, f'{tmpdir}/page'],
                capture_output=True,
                timeout=120
            )

            # OCR each page
            for i in range(1, pages + 1):
                # pdftoppm names files as page-1.png, page-2.png, etc.
                img_path = f'{tmpdir}/page-{i}.png'
                if not os.path.exists(img_path):
                    continue

                result = subprocess.run(
                    ['tesseract', img_path, 'stdout', '-l', 'eng'],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=tmpdir  # Run from tmpdir to avoid path issues
                )
                if result.returncode == 0:
                    all_text.append(result.stdout)

        return '\n'.join(all_text) if all_text else None

    except Exception as e:
        print(f"  OCR failed: {e}")
        return None


def parse_name_list(text: str) -> list[str]:
    """Parse a comma/and separated list of names."""
    # Clean up the text
    text = text.strip()
    text = re.sub(r'\s+', ' ', text)  # Normalize whitespace

    # Split by various connectors
    # Handle "followed by", "and", comma
    text = re.sub(r'\s+followed by\s+', ', ', text, flags=re.I)
    text = re.sub(r'\s+and\s+', ', ', text, flags=re.I)

    # Split by comma
    names = [n.strip() for n in text.split(',')]

    # Clean and validate names
    cleaned = []
    for name in names:
        name = name.strip()
        # Remove titles
        name = re.sub(r'^(Mr\.|Mrs\.|Ms\.|Dr\.)\s*', '', name)
        # Skip empty or too short
        if len(name) < 2:
            continue
        # Skip if it starts with lowercase (likely not a name)
        if name and not name[0].isupper():
            continue
        # Skip common non-name words
        skip_words = {'None', 'Item', 'Items', 'All', 'The', 'Members', 'Present', 'Absent'}
        if name in skip_words:
            continue
        cleaned.append(name)

    return cleaned


def parse_roll_call(text: str) -> list[str]:
    """Parse roll call list, handling multi-word names like 'van Overbeek'."""
    # Clean up the text
    text = text.strip()
    text = re.sub(r'\s+', ' ', text)  # Normalize whitespace

    # Known multi-word council member names
    multi_word_names = ['van Overbeek']

    # Temporarily replace multi-word names
    placeholders = {}
    for i, name in enumerate(multi_word_names):
        placeholder = f"__MULTIWORD_{i}__"
        text = text.replace(name, placeholder)
        placeholders[placeholder] = name

    # Split by comma
    names = [n.strip() for n in text.split(',')]

    # Restore multi-word names and clean
    cleaned = []
    for name in names:
        name = name.strip()
        # Restore any placeholders
        for placeholder, real_name in placeholders.items():
            name = name.replace(placeholder, real_name)
        # Skip empty or too short
        if len(name) < 2:
            continue
        # Skip non-name words
        skip_words = {'None', 'Item', 'Items', 'All', 'The', 'Members', 'Present', 'Absent'}
        if name in skip_words:
            continue
        cleaned.append(name)

    return cleaned


def extract_speakers_from_minutes(text: str) -> dict:
    """Extract all speaker information from minutes text."""
    result = {
        'public_speakers': [],
        'council_members': set(),
        'staff': [],
        'all_names': set()
    }

    # Extract public comment speakers
    for pattern in PUBLIC_COMMENT_PATTERNS:
        for match in pattern.finditer(text):
            names = parse_name_list(match.group(1))
            result['public_speakers'].extend(names)
            result['all_names'].update(names)

    # Extract council members from motions and roll call
    for pattern in MOTION_PATTERNS:
        for match in pattern.finditer(text):
            name = match.group(1).strip()
            if name:
                result['council_members'].add(name)
                result['all_names'].add(name)

    for pattern in ROLL_CALL_PATTERNS:
        for match in pattern.finditer(text):
            names = parse_roll_call(match.group(1))
            result['council_members'].update(names)
            result['all_names'].update(names)

    # Extract named speakers
    for pattern in NAMED_SPEAKER_PATTERNS:
        for match in pattern.finditer(text):
            name = match.group(1).strip()
            if name:
                result['all_names'].add(name)
                # Check if it's staff (multi-word name)
                if ' ' in name:
                    result['staff'].append(name)

    # Clean up council member names
    # Remove partial names that are part of multi-word names
    cleaned_council = set()
    for name in result['council_members']:
        # Skip "van" if "van Overbeek" is present
        if name == 'van' and any('van Overbeek' in n for n in result['council_members']):
            continue
        # Split "Winslow Reynolds" into separate names (OCR sometimes misses commas)
        if name == 'Winslow Reynolds':
            cleaned_council.add('Winslow')
            cleaned_council.add('Reynolds')
            continue
        cleaned_council.add(name)

    result['council_members'] = cleaned_council

    # Convert sets to sorted lists
    result['council_members'] = sorted(result['council_members'])
    result['all_names'] = sorted(result['all_names'])

    return result


def get_diarized_clip_ids(transcripts_dir: str) -> list[int]:
    """Get list of clip IDs that have diarization files."""
    clip_ids = []
    for f in os.listdir(transcripts_dir):
        if f.endswith('_diarization.json'):
            clip_id = int(f.replace('_diarization.json', ''))
            clip_ids.append(clip_id)
    return sorted(clip_ids)


def main():
    """Main entry point."""
    project_root = Path(__file__).parent.parent
    transcripts_dir = project_root / "data" / "transcripts"
    minutes_dir = project_root / "data" / "minutes"

    # Create minutes directory
    minutes_dir.mkdir(exist_ok=True)

    # Get diarized meetings
    clip_ids = get_diarized_clip_ids(transcripts_dir)
    print(f"Found {len(clip_ids)} diarized meetings")

    results = {}

    for i, clip_id in enumerate(clip_ids):
        print(f"\n[{i+1}/{len(clip_ids)}] Processing clip {clip_id}...")

        # Download PDF
        pdf_path = minutes_dir / f"{clip_id}_minutes.pdf"
        txt_path = minutes_dir / f"{clip_id}_minutes.txt"
        json_path = minutes_dir / f"{clip_id}_minutes.json"

        # Check if already processed
        if json_path.exists():
            print(f"  Already processed, loading cached result")
            with open(json_path) as f:
                results[clip_id] = json.load(f)
            continue

        # Download if needed
        if not pdf_path.exists():
            print(f"  Downloading minutes PDF...")
            if not download_minutes_pdf(clip_id, str(pdf_path)):
                print(f"  No minutes PDF available")
                results[clip_id] = None
                continue

        # Convert to text
        print(f"  Converting PDF to text...")
        text = pdf_to_text(str(pdf_path))
        if not text:
            print(f"  Failed to convert PDF")
            results[clip_id] = None
            continue

        # Save text for debugging
        with open(txt_path, 'w') as f:
            f.write(text)

        # Extract speakers
        print(f"  Extracting speakers...")
        speakers = extract_speakers_from_minutes(text)

        print(f"  Found: {len(speakers['public_speakers'])} public speakers, "
              f"{len(speakers['council_members'])} council members")

        # Save results
        with open(json_path, 'w') as f:
            json.dump(speakers, f, indent=2)

        results[clip_id] = speakers

        # Be nice to the server
        time.sleep(0.5)

    # Print summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    total_public = 0
    total_council = 0
    all_public = set()
    all_council = set()

    for clip_id, data in results.items():
        if data:
            total_public += len(data['public_speakers'])
            total_council += len(data['council_members'])
            all_public.update(data['public_speakers'])
            all_council.update(data['council_members'])

    print(f"\nMeetings processed: {len([r for r in results.values() if r])}")
    print(f"Total public speakers found: {total_public} ({len(all_public)} unique)")
    print(f"Total council members found: {total_council} ({len(all_council)} unique)")

    print(f"\nUnique council members: {sorted(all_council)}")
    print(f"\nSample public speakers (first 20): {sorted(all_public)[:20]}")


if __name__ == "__main__":
    main()
