"""Generate reports and export analysis results."""

import json
from datetime import datetime
from pathlib import Path

from rich.console import Console

from .config import config
from .database import get_all_meetings, get_meeting, get_processing_stats, get_db

console = Console()


def get_meeting_analysis(clip_id: int) -> list[dict]:
    """Get all analysis results for a meeting."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT analysis_type, result, analyzed_at
            FROM analysis
            WHERE clip_id = ?
            ORDER BY analyzed_at
            """,
            (clip_id,),
        ).fetchall()

        results = []
        for row in rows:
            result = dict(row)
            if result.get("result"):
                result["result"] = json.loads(result["result"])
            results.append(result)
        return results


def generate_meeting_report(clip_id: int) -> dict:
    """
    Generate a comprehensive report for a single meeting.

    Returns:
        Report dict with all meeting data and analysis
    """
    meeting = get_meeting(clip_id)
    if not meeting:
        return {}

    analysis = get_meeting_analysis(clip_id)

    # Compile report
    report = {
        "meeting": {
            "clip_id": clip_id,
            "title": meeting.get("title"),
            "date": meeting.get("meeting_date"),
            "type": meeting.get("meeting_type"),
            "status": meeting.get("status"),
            "granicus_url": f"https://chico-ca.granicus.com/player/clip/{clip_id}",
        },
        "analysis": {},
        "generated_at": datetime.now().isoformat(),
    }

    # Organize analysis by type
    for item in analysis:
        analysis_type = item.get("analysis_type")
        if analysis_type:
            if analysis_type not in report["analysis"]:
                report["analysis"][analysis_type] = []
            report["analysis"][analysis_type].append(item.get("result"))

    return report


def generate_status_report() -> dict:
    """Generate a pipeline status report."""
    stats = get_processing_stats()
    meetings = get_all_meetings()

    # Group meetings by status
    by_status = {}
    for meeting in meetings:
        status = meeting.get("status", "unknown")
        if status not in by_status:
            by_status[status] = []
        by_status[status].append({
            "clip_id": meeting["clip_id"],
            "title": meeting["title"],
            "date": meeting.get("meeting_date"),
        })

    return {
        "summary": stats,
        "meetings_by_status": by_status,
        "generated_at": datetime.now().isoformat(),
    }


def export_to_json(report: dict, output_path: Path) -> None:
    """Export report to JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    console.print(f"[green]Exported to {output_path}[/green]")


def export_to_markdown(report: dict, output_path: Path) -> None:
    """Export meeting report to Markdown format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    meeting = report.get("meeting", {})
    analysis = report.get("analysis", {})

    md_lines = [
        f"# {meeting.get('title', 'Meeting Report')}",
        "",
        f"**Date:** {meeting.get('date', 'Unknown')}",
        f"**Type:** {meeting.get('type', 'Unknown')}",
        f"**Clip ID:** {meeting.get('clip_id')}",
        f"**Granicus URL:** {meeting.get('granicus_url')}",
        "",
        "---",
        "",
    ]

    # Add summary if available
    if "summary" in analysis:
        md_lines.append("## Summary")
        md_lines.append("")
        for summary_item in analysis["summary"]:
            if isinstance(summary_item, dict) and "summary" in summary_item:
                for bullet in summary_item["summary"]:
                    md_lines.append(f"- {bullet}")
            elif isinstance(summary_item, list):
                for bullet in summary_item:
                    md_lines.append(f"- {bullet}")
        md_lines.append("")

    # Add priority alerts
    if "priority_alerts" in analysis:
        md_lines.append("## Priority Alerts")
        md_lines.append("")
        for alert_set in analysis["priority_alerts"]:
            if isinstance(alert_set, dict) and "alerts" in alert_set:
                for alert in alert_set["alerts"]:
                    md_lines.append(f"### {alert.get('keyword', 'Unknown')}")
                    md_lines.append(f"- **Speaker:** {alert.get('speaker', 'Unknown')}")
                    md_lines.append(f"- **Sentiment:** {alert.get('sentiment', 'Unknown')}")
                    md_lines.append(f"- **Context:** {alert.get('context', '')}")
                    md_lines.append("")

    # Add vote records
    if "vote_record" in analysis:
        md_lines.append("## Votes")
        md_lines.append("")
        for vote_set in analysis["vote_record"]:
            if isinstance(vote_set, dict) and "votes" in vote_set:
                for vote in vote_set["votes"]:
                    md_lines.append(f"### {vote.get('motion', 'Unknown motion')}")
                    md_lines.append(f"- **Result:** {vote.get('result', 'Unknown')}")
                    md_lines.append(f"- **Mover:** {vote.get('mover', 'Unknown')}")
                    md_lines.append(f"- **Seconder:** {vote.get('seconder', 'Unknown')}")
                    if vote.get("vote_count"):
                        vc = vote["vote_count"]
                        md_lines.append(f"- **Count:** Yes: {vc.get('yes', 0)}, No: {vc.get('no', 0)}, Abstain: {vc.get('abstain', 0)}")
                    md_lines.append("")

    # Add advocacy intelligence
    if "advocacy_intel" in analysis:
        md_lines.append("## Advocacy Intelligence")
        md_lines.append("")
        for intel in analysis["advocacy_intel"]:
            if isinstance(intel, dict):
                if intel.get("housing_mentions"):
                    md_lines.append("### Housing")
                    for item in intel["housing_mentions"]:
                        md_lines.append(f"- {item}")
                    md_lines.append("")

                if intel.get("council_positions"):
                    md_lines.append("### Council Positions")
                    for member, position in intel["council_positions"].items():
                        md_lines.append(f"- **{member}:** {position}")
                    md_lines.append("")

    md_lines.append("---")
    md_lines.append(f"*Generated: {report.get('generated_at', datetime.now().isoformat())}*")

    with open(output_path, "w") as f:
        f.write("\n".join(md_lines))

    console.print(f"[green]Exported to {output_path}[/green]")


def generate_all_reports(output_dir: Path | None = None) -> int:
    """
    Generate reports for all analyzed meetings.

    Returns:
        Number of reports generated
    """
    if output_dir is None:
        output_dir = config.ANALYSIS_DIR / "reports"

    meetings = get_all_meetings()
    analyzed = [m for m in meetings if m.get("status") == "analyzed"]

    if not analyzed:
        console.print("[yellow]No analyzed meetings to report on[/yellow]")
        return 0

    console.print(f"[bold]Generating reports for {len(analyzed)} meetings...[/bold]")

    count = 0
    for meeting in analyzed:
        clip_id = meeting["clip_id"]
        report = generate_meeting_report(clip_id)

        if report:
            # Export as both JSON and Markdown
            date_str = meeting.get("meeting_date", "unknown")
            filename_base = f"{date_str}_{clip_id}"

            export_to_json(report, output_dir / f"{filename_base}.json")
            export_to_markdown(report, output_dir / f"{filename_base}.md")
            count += 1

    console.print(f"[green]Generated {count} reports[/green]")
    return count


if __name__ == "__main__":
    generate_all_reports()
