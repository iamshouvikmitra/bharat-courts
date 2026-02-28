"""CLI entry point for bharat-courts."""

from __future__ import annotations

import asyncio
import sys

try:
    import click
except ImportError:
    print("CLI requires the 'cli' extra: pip install bharat-courts[cli]", file=sys.stderr)
    sys.exit(1)

from bharat_courts._version import __version__
from bharat_courts.courts import get_court, list_all_courts

try:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


@click.group()
@click.version_option(__version__)
def main():
    """bharat-courts — Access Indian court data from the command line."""


@main.command()
@click.option("--type", "court_type", type=click.Choice(["all", "hc", "sc"]), default="all")
def courts(court_type: str):
    """List available courts."""
    all_courts = list_all_courts()

    if court_type == "hc":
        all_courts = [c for c in all_courts if c.court_type.value == "high_court"]
    elif court_type == "sc":
        all_courts = [c for c in all_courts if c.court_type.value == "supreme_court"]

    if HAS_RICH:
        table = Table(title="Indian Courts")
        table.add_column("Code", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("State Code")
        table.add_column("Type")
        for c in all_courts:
            table.add_row(c.code, c.name, c.state_code, c.court_type.value)
        console.print(table)
    else:
        click.echo(f"{'Code':<25} {'Name':<45} {'State':<6} {'Type'}")
        click.echo("-" * 90)
        for c in all_courts:
            click.echo(f"{c.code:<25} {c.name:<45} {c.state_code:<6} {c.court_type.value}")


@main.command()
@click.argument("court_code")
@click.option("--case-type", required=True, help="Case type, e.g. WP(C)")
@click.option("--case-number", required=True, help="Case number")
@click.option("--year", required=True, help="Year")
def search(court_code: str, case_type: str, case_number: str, year: str):
    """Search case status on HC Services."""
    court = get_court(court_code)
    if not court:
        click.echo(f"Unknown court: {court_code}. Run 'courts' to list.", err=True)
        sys.exit(1)

    async def _search():
        from bharat_courts.hcservices.client import HCServicesClient

        async with HCServicesClient() as client:
            return await client.case_status(
                court, case_type=case_type, case_number=case_number, year=year
            )

    results = _run(_search())

    if not results:
        click.echo("No results found.")
        return

    for case in results:
        click.echo(f"\n{case.case_number}")
        click.echo(f"  {case.petitioner} vs {case.respondent}")
        click.echo(f"  Status: {case.status}")
        if case.registration_date:
            click.echo(f"  Registered: {case.registration_date}")


@main.command()
@click.argument("court_code")
@click.option("--case-type", required=True, help="Case type code (e.g. 134)")
@click.option("--case-number", required=True, help="Case number")
@click.option("--year", required=True, help="Year")
def orders(court_code: str, case_type: str, case_number: str, year: str):
    """Get court orders for a case from HC Services."""
    court = get_court(court_code)
    if not court:
        click.echo(f"Unknown court: {court_code}", err=True)
        sys.exit(1)

    async def _orders():
        from bharat_courts.hcservices.client import HCServicesClient

        async with HCServicesClient() as client:
            return await client.court_orders(
                court, case_type=case_type, case_number=case_number, year=year
            )

    results = _run(_orders())

    if not results:
        click.echo("No orders found.")
        return

    for order in results:
        click.echo(f"\n{order.order_date} — {order.order_type}")
        if order.judge:
            click.echo(f"  Judge: {order.judge}")
        if order.pdf_url:
            click.echo(f"  PDF: {order.pdf_url}")


@main.command(name="cause-list")
@click.argument("court_code")
@click.option("--date", "causelist_date", default="", help="Date (DD-MM-YYYY, default today)")
@click.option("--criminal", is_flag=True, help="Criminal cause list (default: civil)")
def cause_list(court_code: str, causelist_date: str, criminal: bool):
    """Get cause list PDFs from HC Services."""
    court = get_court(court_code)
    if not court:
        click.echo(f"Unknown court: {court_code}", err=True)
        sys.exit(1)

    async def _cause_list():
        from bharat_courts.hcservices.client import HCServicesClient

        async with HCServicesClient() as client:
            return await client.cause_list(court, civil=not criminal, causelist_date=causelist_date)

    pdfs = _run(_cause_list())

    if not pdfs:
        click.echo("No cause list PDFs found.")
        return

    for pdf in pdfs:
        click.echo(f"\n#{pdf.serial_number} {pdf.bench}")
        click.echo(f"  Type: {pdf.cause_list_type}")
        if pdf.pdf_url:
            click.echo(f"  PDF: {pdf.pdf_url}")


@main.command()
@click.argument("court_code")
@click.option("--from-date", default="", help="From date (DD-MM-YYYY)")
@click.option("--to-date", default="", help="To date (DD-MM-YYYY)")
@click.option("--judge", default="", help="Judge name")
@click.option("--party", default="", help="Party name")
@click.option("--text", "free_text", default="", help="Free text search")
@click.option("--page", default=1, help="Page number")
def judgments(
    court_code: str,
    from_date: str,
    to_date: str,
    judge: str,
    party: str,
    free_text: str,
    page: int,
):
    """Search judgments on the judgment portal."""
    court = get_court(court_code)
    if not court:
        click.echo(f"Unknown court: {court_code}", err=True)
        sys.exit(1)

    async def _judgments():
        from bharat_courts.judgments.client import JudgmentSearchClient

        async with JudgmentSearchClient() as client:
            return await client.search(
                court,
                from_date=from_date,
                to_date=to_date,
                judge_name=judge,
                party_name=party,
                free_text=free_text,
                page=page,
            )

    result = _run(_judgments())

    if not result.items:
        click.echo("No judgments found.")
        return

    click.echo(f"Found {result.total_count} judgments (page {result.page})")
    for j in result.items:
        click.echo(f"\n{j.title}")
        click.echo(f"  {j.case_number} — {j.court_name}")
        click.echo(f"  Date: {j.judgment_date}")
        if j.judges:
            click.echo(f"  Judges: {', '.join(j.judges)}")
        if j.pdf_url:
            click.echo(f"  PDF: {j.pdf_url}")


@main.command()
@click.option("--year", required=True, type=int, help="Year")
@click.option("--month", default=None, type=int, help="Month (1-12)")
def sci(year: int, month: int | None):
    """Search Supreme Court judgments."""

    async def _sci():
        from bharat_courts.sci.client import SCIClient

        async with SCIClient() as client:
            return await client.search_by_year(year, month)

    results = _run(_sci())

    if not results:
        click.echo("No SC judgments found.")
        return

    click.echo(f"Found {len(results)} SC judgments")
    for j in results:
        click.echo(f"\n{j.title}")
        if j.case_number:
            click.echo(f"  {j.case_number}")
        click.echo(f"  Date: {j.judgment_date}")
        if j.pdf_url:
            click.echo(f"  PDF: {j.pdf_url}")


@main.command(name="install-skills")
def install_skills():
    """Install AI agent skill files for Claude Code, Copilot, and others."""
    import shutil
    from pathlib import Path

    skill_source = Path(__file__).parent / "skill"
    if not skill_source.exists():
        click.echo("Skill source directory not found.", err=True)
        sys.exit(1)

    skill_dest = Path.cwd() / ".claude" / "skills" / "bharat-courts"
    skill_dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skill_source, skill_dest, dirs_exist_ok=True)
    click.echo(f"Skills installed to `{skill_dest.relative_to(Path.cwd())}`.")


if __name__ == "__main__":
    main()
