"""Granicus meeting discovery - scrape clip pages to find meetings."""

import asyncio
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup
from rich.console import Console
from rich.progress import Progress, TaskID

from .config import config
from .database import get_meeting, insert_agenda_items, insert_meeting, log_processing, update_meeting_video_url
from .utils import parse_meeting_date, parse_meeting_type

console = Console()


@dataclass
class MeetingMetadata:
    """Metadata extracted from a Granicus clip page."""

    clip_id: int
    title: str
    meeting_date: str | None
    meeting_type: str | None
    video_url: str | None
    duration_seconds: int | None
    agenda_items: list[dict]


async def fetch_clip_page(client: httpx.AsyncClient, clip_id: int) -> str | None:
    """Fetch a Granicus clip page. Returns HTML or None if not found."""
    url = config.CLIP_URL_TEMPLATE.format(clip_id=clip_id)
    try:
        response = await client.get(url, timeout=config.HTTP_TIMEOUT_SEC)
        if response.status_code == 200:
            return response.text
        elif response.status_code == 404:
            return None
        else:
            console.print(f"[yellow]Clip {clip_id}: HTTP {response.status_code}[/yellow]")
            return None
    except httpx.TimeoutException:
        console.print(f"[yellow]Clip {clip_id}: Timeout[/yellow]")
        return None
    except httpx.RequestError as e:
        console.print(f"[red]Clip {clip_id}: Request error: {e}[/red]")
        return None


def parse_clip_page(html: str, clip_id: int) -> MeetingMetadata | None:
    """Parse a Granicus clip page to extract meeting metadata."""
    soup = BeautifulSoup(html, "lxml")

    # Extract title from <title> tag
    title_tag = soup.find("title")
    if not title_tag:
        return None
    title = title_tag.get_text(strip=True)

    # Skip non-meeting pages
    if not title or "granicus" in title.lower() and "city" not in title.lower():
        return None

    # Parse date and type from title
    meeting_date = parse_meeting_date(title)
    meeting_type = parse_meeting_type(title)

    # Extract video URL from source tag or script
    video_url = None

    # Try source tag first
    source_tag = soup.find("source", {"type": "application/x-mpegurl"})
    if source_tag and source_tag.get("src"):
        video_url = source_tag["src"]

    # Fall back to JavaScript variable
    if not video_url:
        scripts = soup.find_all("script")
        for script in scripts:
            if script.string and "video_url" in script.string:
                match = re.search(r'video_url\s*=\s*["\']([^"\']+)["\']', script.string)
                if match:
                    video_url = match.group(1)
                    break

    # Extract duration from page if available
    duration_seconds = None
    # Look for duration in data attributes or scripts
    for script in soup.find_all("script"):
        if script.string and "duration" in script.string.lower():
            # Try to find duration value
            match = re.search(r'duration["\s:]+(\d+)', script.string, re.IGNORECASE)
            if match:
                duration_seconds = int(match.group(1))
                break

    # Extract agenda items from .index-point divs
    agenda_items = []
    index_points = soup.find_all("div", class_="index-point")
    for i, point in enumerate(index_points):
        time_attr = point.get("time")
        data_id = point.get("data-id")
        text = point.get_text(strip=True)

        if time_attr:
            start_seconds = int(time_attr)
            # Calculate end time from next item
            end_seconds = None
            if i + 1 < len(index_points):
                next_time = index_points[i + 1].get("time")
                if next_time:
                    end_seconds = int(next_time)

            # Try to extract item number
            item_number = None
            num_match = re.match(r"^(\d+\.?\d*\.?)\s*", text)
            if num_match:
                item_number = num_match.group(1).rstrip(".")

            agenda_items.append({
                "item_number": item_number,
                "title": text[:500],  # Truncate long titles
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "granicus_item_id": int(data_id) if data_id else None,
            })

    return MeetingMetadata(
        clip_id=clip_id,
        title=title,
        meeting_date=meeting_date,
        meeting_type=meeting_type,
        video_url=video_url,
        duration_seconds=duration_seconds,
        agenda_items=agenda_items,
    )


async def discover_single_clip(client: httpx.AsyncClient, clip_id: int) -> MeetingMetadata | None:
    """Discover a single meeting from its clip ID."""
    html = await fetch_clip_page(client, clip_id)
    if not html:
        return None

    return parse_clip_page(html, clip_id)


async def discover_meetings_in_range(
    start_id: int = config.CLIP_ID_START,
    end_id: int = config.CLIP_ID_END,
    filter_types: list[str] | None = None,
    concurrency: int = 5,
) -> list[MeetingMetadata]:
    """
    Discover all meetings in a clip ID range.

    Args:
        start_id: Starting clip ID
        end_id: Ending clip ID (inclusive)
        filter_types: Only include these meeting types (None = all)
        concurrency: Max concurrent requests

    Returns:
        List of discovered meetings
    """
    if filter_types is None:
        filter_types = config.MEETING_TYPES

    discovered = []
    semaphore = asyncio.Semaphore(concurrency)

    async def discover_with_semaphore(client: httpx.AsyncClient, clip_id: int) -> MeetingMetadata | None:
        async with semaphore:
            return await discover_single_clip(client, clip_id)

    async with httpx.AsyncClient() as client:
        with Progress() as progress:
            task = progress.add_task(
                f"[cyan]Discovering clips {start_id}-{end_id}...",
                total=end_id - start_id + 1,
            )

            tasks = []
            for clip_id in range(start_id, end_id + 1):
                tasks.append(discover_with_semaphore(client, clip_id))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(results):
                progress.update(task, advance=1)

                if isinstance(result, Exception):
                    console.print(f"[red]Error discovering clip {start_id + i}: {result}[/red]")
                    continue

                if result is None:
                    continue

                # Filter by meeting type
                if filter_types and result.meeting_type not in filter_types:
                    continue

                discovered.append(result)

    console.print(f"[green]Discovered {len(discovered)} meetings[/green]")
    return discovered


def save_discovered_meetings(meetings: list[MeetingMetadata]) -> dict:
    """
    Save discovered meetings to the database.

    Returns:
        Stats: {"new": count, "existing": count, "updated": count}
    """
    stats = {"new": 0, "existing": 0, "updated": 0}

    for meeting in meetings:
        existing = get_meeting(meeting.clip_id)

        if existing:
            stats["existing"] += 1
            # Update video URL if we now have it
            if meeting.video_url and not existing.get("video_url"):
                update_meeting_video_url(meeting.clip_id, meeting.video_url)
                stats["updated"] += 1
        else:
            # Insert new meeting
            inserted = insert_meeting(
                clip_id=meeting.clip_id,
                title=meeting.title,
                meeting_date=meeting.meeting_date,
                meeting_type=meeting.meeting_type,
                video_url=meeting.video_url,
                duration_seconds=meeting.duration_seconds,
            )
            if inserted:
                stats["new"] += 1

                # Insert agenda items
                if meeting.agenda_items:
                    insert_agenda_items(meeting.clip_id, meeting.agenda_items)

                log_processing(meeting.clip_id, "discovery", "completed", f"Discovered: {meeting.title}")

    return stats


async def run_discovery(
    start_id: int | None = None,
    end_id: int | None = None,
) -> dict:
    """
    Main discovery function - discovers and saves meetings.

    Returns:
        Stats dict with discovery results
    """
    start = start_id or config.CLIP_ID_START
    end = end_id or config.CLIP_ID_END

    console.print(f"[bold]Starting discovery for clips {start} to {end}[/bold]")

    meetings = await discover_meetings_in_range(start, end)
    stats = save_discovered_meetings(meetings)

    console.print(f"[bold green]Discovery complete![/bold green]")
    console.print(f"  New meetings: {stats['new']}")
    console.print(f"  Already known: {stats['existing']}")
    console.print(f"  Updated: {stats['updated']}")

    return stats


# Synchronous wrapper for script usage
def discover_all() -> dict:
    """Synchronous wrapper for run_discovery."""
    return asyncio.run(run_discovery())


if __name__ == "__main__":
    discover_all()
