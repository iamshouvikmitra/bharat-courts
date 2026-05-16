"""CLI entry point for bharat-courts.

Command surface (top-level groups match SDK module names exactly):

    bharat-courts version
    bharat-courts courts [--type all|hc|sc]
    bharat-courts install-skills

    bharat-courts hcservices ...        # hcservices.ecourts.gov.in
    bharat-courts districtcourts ...    # services.ecourts.gov.in
    bharat-courts calcuttahc ...        # calcuttahighcourt.gov.in
    bharat-courts judgments ...         # judgments.ecourts.gov.in
    bharat-courts sci ...               # www.sci.gov.in

Global flags (work on every subcommand): --json, --captcha-attempts N, -v/--verbose.

TODO: the README still documents the old flat command layout
(``bharat-courts search``, ``bharat-courts orders``, etc.). Those have
moved under ``hcservices`` (search/orders/cause-list), ``judgments search``,
and ``sci recent``. README needs updating.
"""

from __future__ import annotations

import asyncio
import json as jsonlib
import logging
import re
import sys
import uuid
from pathlib import Path
from typing import Any

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def _ctx_obj(ctx: click.Context) -> dict:
    """Return the shared dict stashed on the click context."""
    return ctx.ensure_object(dict)


def _is_json(ctx: click.Context) -> bool:
    return bool(_ctx_obj(ctx).get("json"))


def _captcha_attempts(ctx: click.Context) -> int:
    return int(_ctx_obj(ctx).get("captcha_attempts", 5))


def _emit_json(value: Any) -> None:
    """Print a single JSON value (no trailing banner)."""
    click.echo(jsonlib.dumps(value, indent=2, default=str))


def _serialize(items: Any, *, exclude_none: bool = True) -> Any:
    """Recursively convert dataclasses with to_dict into JSON-safe structures."""
    if items is None:
        return None
    if hasattr(items, "to_dict"):
        return items.to_dict(exclude_none=exclude_none)
    if isinstance(items, list):
        return [_serialize(i, exclude_none=exclude_none) for i in items]
    if isinstance(items, dict):
        return {k: _serialize(v, exclude_none=exclude_none) for k, v in items.items()}
    return items


_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(stem: str) -> str:
    """Sanitise a string for use as a filename stem."""
    cleaned = _FILENAME_SAFE_RE.sub("_", stem.strip())
    cleaned = cleaned.strip("_")
    if not cleaned:
        cleaned = f"unnamed_{uuid.uuid4().hex[:8]}"
    return cleaned


def _ensure_dir(path: str) -> Path:
    p = Path(path).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _save_pdf(directory: Path, stem: str, suffix: str, content: bytes) -> Path:
    """Write PDF bytes to ``<directory>/<safe_stem>_<suffix>.pdf``."""
    safe_stem = _safe_filename(stem) if stem else f"unnamed_{uuid.uuid4().hex[:8]}"
    safe_suffix = _safe_filename(suffix) if suffix else ""
    name = f"{safe_stem}_{safe_suffix}".strip("_") + ".pdf"
    out = directory / name
    out.write_bytes(content)
    return out


def _warn(msg: str) -> None:
    click.echo(f"WARN: {msg}", err=True)


def _resolve_court_or_die(court_code: str) -> Any:
    court = get_court(court_code)
    if not court:
        click.echo(
            f"Unknown court: {court_code}. Run `bharat-courts courts` to list available codes.",
            err=True,
        )
        sys.exit(1)
    return court


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(__version__, prog_name="bharat-courts")
@click.option("--json", "json_out", is_flag=True, help="Emit JSON output instead of text.")
@click.option(
    "--captcha-attempts",
    type=int,
    default=5,
    show_default=True,
    help="Max CAPTCHA solve attempts per call (judgments/calcuttahc only; "
    "hcservices/districtcourts use a fixed internal budget).",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable INFO-level SDK logging.")
@click.pass_context
def main(ctx: click.Context, json_out: bool, captcha_attempts: int, verbose: bool):
    """bharat-courts — Access Indian court data from the command line."""
    obj = ctx.ensure_object(dict)
    obj["json"] = json_out
    obj["captcha_attempts"] = captcha_attempts
    if verbose:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        )
        logging.getLogger("bharat_courts").setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Top-level utility commands
# ---------------------------------------------------------------------------


@main.command()
def version():
    """Print the version."""
    click.echo(__version__)


@main.command()
@click.option("--type", "court_type", type=click.Choice(["all", "hc", "sc"]), default="all")
@click.pass_context
def courts(ctx: click.Context, court_type: str):
    """List available courts."""
    all_courts = list_all_courts()
    if court_type == "hc":
        all_courts = [c for c in all_courts if c.court_type.value == "high_court"]
    elif court_type == "sc":
        all_courts = [c for c in all_courts if c.court_type.value == "supreme_court"]

    if _is_json(ctx):
        _emit_json([c.to_dict(exclude_none=True) for c in all_courts])
        return

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


@main.command(name="install-skills")
def install_skills():
    """Install AI agent skill files for Claude Code, Copilot, and others."""
    import shutil

    skill_source = Path(__file__).parent / "skill"
    if not skill_source.exists():
        click.echo("Skill source directory not found.", err=True)
        sys.exit(1)

    skill_dest = Path.cwd() / ".claude" / "skills" / "bharat-courts"
    skill_dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skill_source, skill_dest, dirs_exist_ok=True)
    click.echo(f"Skills installed to `{skill_dest.relative_to(Path.cwd())}`.")


# ---------------------------------------------------------------------------
# hcservices group
# ---------------------------------------------------------------------------


@main.group()
def hcservices():
    """High Court Services portal (hcservices.ecourts.gov.in)."""


@hcservices.command("benches")
@click.argument("court_code")
@click.pass_context
def hcservices_benches(ctx: click.Context, court_code: str):
    """List benches for a High Court."""
    court = _resolve_court_or_die(court_code)

    async def _go():
        from bharat_courts.hcservices.client import HCServicesClient

        async with HCServicesClient() as client:
            return await client.list_benches(court)

    benches = _run(_go())
    if _is_json(ctx):
        _emit_json(benches)
        return
    if not benches:
        click.echo("No benches found.")
        return
    click.echo(f"Benches for {court.name}:")
    for code, name in benches.items():
        click.echo(f"  {code:<6}  {name}")


@hcservices.command("case-types")
@click.argument("court_code")
@click.option("--bench", "bench_code", default="1", help="Bench code from `benches`.")
@click.pass_context
def hcservices_case_types(ctx: click.Context, court_code: str, bench_code: str):
    """List available case types for a court bench."""
    court = _resolve_court_or_die(court_code)

    async def _go():
        from bharat_courts.hcservices.client import HCServicesClient

        async with HCServicesClient() as client:
            return await client.list_case_types(court, bench_code=bench_code)

    case_types = _run(_go())
    if _is_json(ctx):
        _emit_json(case_types)
        return
    if not case_types:
        click.echo("No case types found.")
        return
    click.echo(f"Case types for {court.name} (bench={bench_code}):")
    for code, name in case_types.items():
        click.echo(f"  {code:<6}  {name}")


@hcservices.command("search")
@click.argument("court_code")
@click.option("--case-type", required=True, help="Numeric case type code.")
@click.option("--case-number", required=True, help="Case number.")
@click.option("--year", required=True, help="Registration year.")
@click.option("--bench", "bench_code", default="1", help="Bench code (default `1`).")
@click.pass_context
def hcservices_search(
    ctx: click.Context,
    court_code: str,
    case_type: str,
    case_number: str,
    year: str,
    bench_code: str,
):
    """Search case status on HC Services."""
    court = _resolve_court_or_die(court_code)

    async def _go():
        from bharat_courts.hcservices.client import HCServicesClient

        async with HCServicesClient() as client:
            return await client.case_status(
                court,
                case_type=case_type,
                case_number=case_number,
                year=year,
                bench_code=bench_code,
            )

    results = _run(_go())
    if _is_json(ctx):
        _emit_json([c.to_dict(exclude_none=True) for c in results])
        return
    if not results:
        click.echo("No results found.")
        return
    for case in results:
        click.echo(f"\n{case.case_number}")
        if case.petitioner or case.respondent:
            click.echo(f"  {case.petitioner} vs {case.respondent}")
        if case.status:
            click.echo(f"  Status: {case.status}")
        if case.cnr_number:
            click.echo(f"  CNR: {case.cnr_number}")
        if case.registration_date:
            click.echo(f"  Registered: {case.registration_date}")


@hcservices.command("search-by-party")
@click.argument("court_code")
@click.option("--party", "party_name", required=True, help="Petitioner/respondent name.")
@click.option("--year", required=True, help="Registration year (mandatory).")
@click.option(
    "--status",
    type=click.Choice(["pending", "disposed", "both"]),
    default="both",
    help="Filter by case status.",
)
@click.option("--bench", "bench_code", default="1")
@click.pass_context
def hcservices_search_by_party(
    ctx: click.Context,
    court_code: str,
    party_name: str,
    year: str,
    status: str,
    bench_code: str,
):
    """Search HC Services by party name."""
    court = _resolve_court_or_die(court_code)
    status_filter = {"pending": "Pending", "disposed": "Disposed", "both": "Both"}[status]

    async def _go():
        from bharat_courts.hcservices.client import HCServicesClient

        async with HCServicesClient() as client:
            return await client.case_status_by_party(
                court,
                party_name=party_name,
                year=year,
                bench_code=bench_code,
                status_filter=status_filter,
            )

    results = _run(_go())
    if _is_json(ctx):
        _emit_json([c.to_dict(exclude_none=True) for c in results])
        return
    if not results:
        click.echo("No results found.")
        return
    for case in results:
        click.echo(f"\n{case.case_number}")
        if case.petitioner or case.respondent:
            click.echo(f"  {case.petitioner} vs {case.respondent}")
        if case.status:
            click.echo(f"  Status: {case.status}")


@hcservices.command("orders")
@click.argument("court_code")
@click.option("--case-type", required=True)
@click.option("--case-number", required=True)
@click.option("--year", required=True)
@click.option("--bench", "bench_code", default="1")
@click.option("--download", "download_dir", default=None, help="Save PDFs to this directory.")
@click.pass_context
def hcservices_orders(
    ctx: click.Context,
    court_code: str,
    case_type: str,
    case_number: str,
    year: str,
    bench_code: str,
    download_dir: str | None,
):
    """Get court orders for a case from HC Services."""
    court = _resolve_court_or_die(court_code)

    async def _go():
        from bharat_courts.hcservices.client import HCServicesClient

        async with HCServicesClient() as client:
            orders = await client.court_orders(
                court,
                case_type=case_type,
                case_number=case_number,
                year=year,
                bench_code=bench_code,
            )
            local_paths: dict[int, str] = {}
            if download_dir and orders:
                out_dir = _ensure_dir(download_dir)
                for idx, order in enumerate(orders):
                    if not order.pdf_url:
                        continue
                    try:
                        content = await client.download_order_pdf(order.pdf_url)
                    except RuntimeError as e:
                        _warn(f"download failed for {order.pdf_url}: {e}")
                        continue
                    stem = case_number or "case"
                    suffix = (
                        order.order_date.isoformat() if order.order_date else f"order_{idx + 1}"
                    )
                    out_path = _save_pdf(out_dir, stem, suffix, content)
                    local_paths[idx] = str(out_path)
                    if not _is_json(ctx):
                        click.echo(f"Saved: {out_path} ({len(content)} bytes)")
            return orders, local_paths

    orders, local_paths = _run(_go())

    if _is_json(ctx):
        out = []
        for idx, order in enumerate(orders):
            d = order.to_dict(exclude_none=True)
            if idx in local_paths:
                d["pdf_local_path"] = local_paths[idx]
            out.append(d)
        _emit_json(out)
        return

    if not orders:
        click.echo("No orders found.")
        return
    for order in orders:
        click.echo(f"\n{order.order_date} — {order.order_type}")
        if order.judge:
            click.echo(f"  Judge: {order.judge}")
        if order.pdf_url:
            click.echo(f"  PDF: {order.pdf_url}")


@hcservices.command("cause-list")
@click.argument("court_code")
@click.option("--date", "causelist_date", default="", help="Date (DD-MM-YYYY, defaults to today).")
@click.option("--criminal", is_flag=True, help="Criminal cause list (default: civil).")
@click.option("--bench", "bench_code", default="1")
@click.option("--download", "download_dir", default=None, help="Save PDFs to this directory.")
@click.pass_context
def hcservices_cause_list(
    ctx: click.Context,
    court_code: str,
    causelist_date: str,
    criminal: bool,
    bench_code: str,
    download_dir: str | None,
):
    """Get cause list PDFs from HC Services."""
    court = _resolve_court_or_die(court_code)

    async def _go():
        from bharat_courts.hcservices.client import HCServicesClient

        async with HCServicesClient() as client:
            pdfs = await client.cause_list(
                court,
                civil=not criminal,
                bench_code=bench_code,
                causelist_date=causelist_date,
            )
            local_paths: dict[int, str] = {}
            if download_dir and pdfs:
                out_dir = _ensure_dir(download_dir)
                for idx, pdf in enumerate(pdfs):
                    if not pdf.pdf_url:
                        continue
                    try:
                        content = await client.download_order_pdf(pdf.pdf_url)
                    except RuntimeError as e:
                        _warn(f"download failed for {pdf.pdf_url}: {e}")
                        continue
                    stem = f"causelist_{pdf.serial_number or idx + 1}_{pdf.bench or 'bench'}"
                    suffix = causelist_date or "today"
                    out_path = _save_pdf(out_dir, stem, suffix, content)
                    local_paths[idx] = str(out_path)
                    if not _is_json(ctx):
                        click.echo(f"Saved: {out_path} ({len(content)} bytes)")
            return pdfs, local_paths

    pdfs, local_paths = _run(_go())

    if _is_json(ctx):
        out = []
        for idx, pdf in enumerate(pdfs):
            d = pdf.to_dict(exclude_none=True)
            if idx in local_paths:
                d["pdf_local_path"] = local_paths[idx]
            out.append(d)
        _emit_json(out)
        return

    if not pdfs:
        click.echo("No cause list PDFs found.")
        return
    for pdf in pdfs:
        click.echo(f"\n#{pdf.serial_number} {pdf.bench}")
        click.echo(f"  Type: {pdf.cause_list_type}")
        if pdf.pdf_url:
            click.echo(f"  PDF: {pdf.pdf_url}")


# ---------------------------------------------------------------------------
# districtcourts group
# ---------------------------------------------------------------------------


@main.group()
def districtcourts():
    """District Courts portal (services.ecourts.gov.in)."""


def _dc_human_dict(label: str, data: dict[str, str]) -> None:
    if not data:
        click.echo(f"No {label} found.")
        return
    click.echo(f"{label.capitalize()}:")
    for code, name in data.items():
        click.echo(f"  {code:<10}  {name}")


@districtcourts.command("states")
@click.pass_context
def dc_states(ctx: click.Context):
    """List states for the district courts portal."""

    async def _go():
        from bharat_courts.districtcourts.client import DistrictCourtClient

        async with DistrictCourtClient() as client:
            return await client.list_states()

    states = _run(_go())
    if _is_json(ctx):
        _emit_json(states)
        return
    _dc_human_dict("states", states)


@districtcourts.command("districts")
@click.option("--state", "state_code", required=True)
@click.pass_context
def dc_districts(ctx: click.Context, state_code: str):
    """List districts for a state."""

    async def _go():
        from bharat_courts.districtcourts.client import DistrictCourtClient

        async with DistrictCourtClient() as client:
            return await client.list_districts(state_code)

    districts = _run(_go())
    if _is_json(ctx):
        _emit_json(districts)
        return
    _dc_human_dict("districts", districts)


@districtcourts.command("complexes")
@click.option("--state", "state_code", required=True)
@click.option("--dist", "dist_code", required=True)
@click.pass_context
def dc_complexes(ctx: click.Context, state_code: str, dist_code: str):
    """List court complexes for a district."""

    async def _go():
        from bharat_courts.districtcourts.client import DistrictCourtClient

        async with DistrictCourtClient() as client:
            return await client.list_complexes(state_code, dist_code)

    complexes = _run(_go())
    if _is_json(ctx):
        _emit_json(complexes)
        return
    _dc_human_dict("complexes", complexes)


@districtcourts.command("establishments")
@click.option("--state", "state_code", required=True)
@click.option("--dist", "dist_code", required=True)
@click.option("--complex", "complex_code", required=True)
@click.pass_context
def dc_establishments(ctx: click.Context, state_code: str, dist_code: str, complex_code: str):
    """List establishments for a court complex."""

    async def _go():
        from bharat_courts.districtcourts.client import DistrictCourtClient

        async with DistrictCourtClient() as client:
            return await client.list_establishments(state_code, dist_code, complex_code)

    ests = _run(_go())
    if _is_json(ctx):
        _emit_json(ests)
        return
    _dc_human_dict("establishments", ests)


@districtcourts.command("case-types")
@click.option("--state", "state_code", required=True)
@click.option("--dist", "dist_code", required=True)
@click.option("--complex", "complex_code", required=True)
@click.option("--est", "est_code", default="")
@click.pass_context
def dc_case_types(
    ctx: click.Context,
    state_code: str,
    dist_code: str,
    complex_code: str,
    est_code: str,
):
    """List case types for a court."""

    async def _go():
        from bharat_courts.districtcourts.client import DistrictCourtClient

        async with DistrictCourtClient() as client:
            return await client.list_case_types(state_code, dist_code, complex_code, est_code)

    cts = _run(_go())
    if _is_json(ctx):
        _emit_json(cts)
        return
    _dc_human_dict("case types", cts)


@districtcourts.command("courts")
@click.option("--state", "state_code", required=True)
@click.option("--dist", "dist_code", required=True)
@click.option("--complex", "complex_code", required=True)
@click.option("--est", "est_code", default="")
@click.pass_context
def dc_courts(
    ctx: click.Context,
    state_code: str,
    dist_code: str,
    complex_code: str,
    est_code: str,
):
    """List courts available for cause-list lookup."""

    async def _go():
        from bharat_courts.districtcourts.client import DistrictCourtClient

        async with DistrictCourtClient() as client:
            return await client.list_cause_list_courts(
                state_code, dist_code, complex_code, est_code
            )

    courts_map = _run(_go())
    if _is_json(ctx):
        _emit_json(courts_map)
        return
    _dc_human_dict("courts", courts_map)


@districtcourts.command("search")
@click.option("--state", "state_code", required=True)
@click.option("--dist", "dist_code", required=True)
@click.option("--complex", "complex_code", required=True)
@click.option("--est", "est_code", default="")
@click.option("--case-type", required=True)
@click.option("--case-number", required=True)
@click.option("--year", required=True)
@click.pass_context
def dc_search(
    ctx: click.Context,
    state_code: str,
    dist_code: str,
    complex_code: str,
    est_code: str,
    case_type: str,
    case_number: str,
    year: str,
):
    """Search case status on the district courts portal."""

    async def _go():
        from bharat_courts.districtcourts.client import DistrictCourtClient

        async with DistrictCourtClient() as client:
            return await client.case_status(
                state_code=state_code,
                dist_code=dist_code,
                court_complex_code=complex_code,
                est_code=est_code,
                case_type=case_type,
                case_number=case_number,
                year=year,
            )

    results = _run(_go())
    if _is_json(ctx):
        _emit_json([c.to_dict(exclude_none=True) for c in results])
        return
    if not results:
        click.echo("No results found.")
        return
    for case in results:
        click.echo(f"\n{case.case_number}")
        if case.petitioner or case.respondent:
            click.echo(f"  {case.petitioner} vs {case.respondent}")
        if case.status:
            click.echo(f"  Status: {case.status}")
        if case.cnr_number:
            click.echo(f"  CNR: {case.cnr_number}")


@districtcourts.command("search-by-party")
@click.option("--state", "state_code", required=True)
@click.option("--dist", "dist_code", required=True)
@click.option("--complex", "complex_code", required=True)
@click.option("--est", "est_code", default="")
@click.option("--party", "party_name", required=True)
@click.option("--year", required=True)
@click.option(
    "--status",
    type=click.Choice(["pending", "disposed", "both"]),
    default="both",
)
@click.pass_context
def dc_search_by_party(
    ctx: click.Context,
    state_code: str,
    dist_code: str,
    complex_code: str,
    est_code: str,
    party_name: str,
    year: str,
    status: str,
):
    """Search district courts by party name."""
    status_filter = {"pending": "Pending", "disposed": "Disposed", "both": "Both"}[status]

    async def _go():
        from bharat_courts.districtcourts.client import DistrictCourtClient

        async with DistrictCourtClient() as client:
            return await client.case_status_by_party(
                state_code=state_code,
                dist_code=dist_code,
                court_complex_code=complex_code,
                est_code=est_code,
                party_name=party_name,
                year=year,
                status_filter=status_filter,
            )

    results = _run(_go())
    if _is_json(ctx):
        _emit_json([c.to_dict(exclude_none=True) for c in results])
        return
    if not results:
        click.echo("No results found.")
        return
    for case in results:
        click.echo(f"\n{case.case_number}")
        if case.petitioner or case.respondent:
            click.echo(f"  {case.petitioner} vs {case.respondent}")
        if case.status:
            click.echo(f"  Status: {case.status}")


@districtcourts.command("orders")
@click.option("--state", "state_code", required=True)
@click.option("--dist", "dist_code", required=True)
@click.option("--complex", "complex_code", required=True)
@click.option("--est", "est_code", default="")
@click.option("--case-type", required=True)
@click.option("--case-number", required=True)
@click.option("--year", required=True)
@click.option("--download", "download_dir", default=None, help="Save PDFs to this directory.")
@click.pass_context
def dc_orders(
    ctx: click.Context,
    state_code: str,
    dist_code: str,
    complex_code: str,
    est_code: str,
    case_type: str,
    case_number: str,
    year: str,
    download_dir: str | None,
):
    """Get court orders for a case from district courts."""

    async def _go():
        from bharat_courts.districtcourts.client import DistrictCourtClient
        from bharat_courts.http import RateLimitedClient

        async with DistrictCourtClient() as client:
            orders = await client.court_orders(
                state_code=state_code,
                dist_code=dist_code,
                court_complex_code=complex_code,
                est_code=est_code,
                case_type=case_type,
                case_number=case_number,
                year=year,
            )
            local_paths: dict[int, str] = {}
            if download_dir and orders:
                # The DC client doesn't expose a download_order_pdf method —
                # the order PDFs are served directly from the portal.
                out_dir = _ensure_dir(download_dir)
                http: RateLimitedClient = client._http  # reuse session
                for idx, order in enumerate(orders):
                    if not order.pdf_url:
                        continue
                    try:
                        content = await http.get_bytes(
                            order.pdf_url,
                            headers={"Referer": "https://services.ecourts.gov.in/"},
                        )
                        if content[:4] != b"%PDF":
                            raise RuntimeError(f"not a PDF (head={content[:32]!r})")
                    except Exception as e:
                        _warn(f"download failed for {order.pdf_url}: {e}")
                        continue
                    stem = case_number or "case"
                    suffix = (
                        order.order_date.isoformat() if order.order_date else f"order_{idx + 1}"
                    )
                    out_path = _save_pdf(out_dir, stem, suffix, content)
                    local_paths[idx] = str(out_path)
                    if not _is_json(ctx):
                        click.echo(f"Saved: {out_path} ({len(content)} bytes)")
            return orders, local_paths

    orders, local_paths = _run(_go())

    if _is_json(ctx):
        out = []
        for idx, order in enumerate(orders):
            d = order.to_dict(exclude_none=True)
            if idx in local_paths:
                d["pdf_local_path"] = local_paths[idx]
            out.append(d)
        _emit_json(out)
        return

    if not orders:
        click.echo("No orders found.")
        return
    for order in orders:
        click.echo(f"\n{order.order_date} — {order.order_type}")
        if order.judge:
            click.echo(f"  Judge: {order.judge}")
        if order.pdf_url:
            click.echo(f"  PDF: {order.pdf_url}")


@districtcourts.command("cause-list")
@click.option("--state", "state_code", required=True)
@click.option("--dist", "dist_code", required=True)
@click.option("--complex", "complex_code", required=True)
@click.option("--est", "est_code", default="")
@click.option("--court-no", required=True, help="Court code from `courts` subcommand.")
@click.option("--court-name", default="", help="Court display name (auto-resolved if blank).")
@click.option("--date", "causelist_date", default="", help="Date (DD-MM-YYYY).")
@click.option("--criminal", is_flag=True)
@click.pass_context
def dc_cause_list(
    ctx: click.Context,
    state_code: str,
    dist_code: str,
    complex_code: str,
    est_code: str,
    court_no: str,
    court_name: str,
    causelist_date: str,
    criminal: bool,
):
    """Get cause list entries for a district court."""

    async def _go():
        from bharat_courts.districtcourts.client import DistrictCourtClient

        async with DistrictCourtClient() as client:
            return await client.cause_list(
                state_code=state_code,
                dist_code=dist_code,
                court_complex_code=complex_code,
                est_code=est_code,
                court_no=court_no,
                court_name=court_name,
                causelist_date=causelist_date,
                civil=not criminal,
            )

    entries = _run(_go())

    if _is_json(ctx):
        _emit_json([e.to_dict(exclude_none=True) for e in entries])
        return

    if not entries:
        click.echo("No cause list entries found.")
        return
    for entry in entries:
        click.echo(f"\n#{entry.serial_number} {entry.case_number}")
        if entry.petitioner or entry.respondent:
            click.echo(f"  {entry.petitioner} vs {entry.respondent}")
        if entry.judge:
            click.echo(f"  Judge: {entry.judge}")


# ---------------------------------------------------------------------------
# calcuttahc group
# ---------------------------------------------------------------------------


@main.group()
def calcuttahc():
    """Calcutta High Court dedicated portal (calcuttahighcourt.gov.in)."""


@calcuttahc.command("search")
@click.option("--case-type", required=True, help="Numeric case type code (e.g. 12 for WPA).")
@click.option("--case-number", required=True)
@click.option("--year", required=True)
@click.option(
    "--establishment",
    type=click.Choice(["appellate", "original", "jalpaiguri", "portblair"]),
    default="appellate",
)
@click.option("--download", "download_dir", default=None, help="Save PDFs to this directory.")
@click.pass_context
def calcuttahc_search(
    ctx: click.Context,
    case_type: str,
    case_number: str,
    year: str,
    establishment: str,
    download_dir: str | None,
):
    """Search Calcutta HC orders/judgments."""
    attempts = _captcha_attempts(ctx)

    async def _go():
        from bharat_courts.calcuttahc.client import CalcuttaHCClient

        async with CalcuttaHCClient() as client:
            case_info, orders = await client.search_orders(
                case_type=case_type,
                case_number=case_number,
                year=year,
                establishment=establishment,
                max_captcha_attempts=attempts,
            )
            local_paths: dict[int, str] = {}
            if download_dir and orders:
                out_dir = _ensure_dir(download_dir)
                stem = (
                    case_info.case_number
                    if case_info and case_info.case_number
                    else f"{case_type}_{case_number}_{year}"
                )
                for idx, order in enumerate(orders):
                    if not order.pdf_url:
                        continue
                    try:
                        content = await client.download_order_pdf(order.pdf_url)
                    except RuntimeError as e:
                        _warn(f"download failed for {order.pdf_url}: {e}")
                        continue
                    suffix = (
                        order.order_date.isoformat() if order.order_date else f"order_{idx + 1}"
                    )
                    out_path = _save_pdf(out_dir, stem, suffix, content)
                    local_paths[idx] = str(out_path)
                    if not _is_json(ctx):
                        click.echo(f"Saved: {out_path} ({len(content)} bytes)")
            return case_info, orders, local_paths

    case_info, orders, local_paths = _run(_go())

    if _is_json(ctx):
        order_dicts = []
        for idx, order in enumerate(orders):
            d = order.to_dict(exclude_none=True)
            if idx in local_paths:
                d["pdf_local_path"] = local_paths[idx]
            order_dicts.append(d)
        _emit_json(
            {
                "case_info": case_info.to_dict(exclude_none=True) if case_info else None,
                "orders": order_dicts,
            }
        )
        return

    if case_info is None and not orders:
        click.echo("No matching case found.")
        return
    if case_info:
        click.echo(f"{case_info.case_number}  ({case_info.case_type})")
        click.echo(f"  CNR: {case_info.cnr_number}")
        if case_info.petitioner or case_info.respondent:
            click.echo(f"  {case_info.petitioner} vs {case_info.respondent}")
        if case_info.court_name:
            click.echo(f"  {case_info.court_name}")
    if not orders:
        click.echo("\nNo orders.")
        return
    click.echo(f"\n{len(orders)} order(s):")
    for order in orders:
        click.echo(f"\n  {order.order_date} — {order.order_type}")
        if order.judge:
            click.echo(f"    Judge: {order.judge}")
        if order.neutral_citation:
            click.echo(f"    Citation: {order.neutral_citation}")
        if order.pdf_url:
            click.echo(f"    PDF: {order.pdf_url}")


# ---------------------------------------------------------------------------
# judgments group
# ---------------------------------------------------------------------------


@main.group()
def judgments():
    """Judgment Search portal (judgments.ecourts.gov.in)."""


def _print_judgment_human(j: Any) -> None:
    click.echo(f"\n{j.title}")
    if j.case_number:
        click.echo(f"  {j.case_number} — {j.court_name}")
    elif j.court_name:
        click.echo(f"  {j.court_name}")
    if j.judgment_date:
        click.echo(f"  Date: {j.judgment_date}")
    if j.judges:
        click.echo(f"  Judges: {', '.join(j.judges)}")
    if j.pdf_url:
        click.echo(f"  PDF path: {j.pdf_url}")


async def _download_judgment_pdfs(client, items, out_dir: Path, court_type: str) -> dict[int, str]:
    local_paths: dict[int, str] = {}
    for idx, j in enumerate(items):
        if not j.pdf_url:
            continue
        try:
            await client.download_pdf(j, court_type=court_type)
        except Exception as e:  # SDK raises RuntimeError; be defensive
            _warn(f"download failed for {j.case_number or j.title!r}: {e}")
            continue
        if not j.pdf_bytes:
            _warn(f"download returned empty bytes for {j.case_number or j.title!r}")
            continue
        stem = j.case_number or j.title or "judgment"
        suffix = j.judgment_date.isoformat() if j.judgment_date else f"item_{idx + 1}"
        out_path = _save_pdf(out_dir, stem, suffix, j.pdf_bytes)
        local_paths[idx] = str(out_path)
        click.echo(f"Saved: {out_path} ({len(j.pdf_bytes)} bytes)")
    return local_paths


@judgments.command("search")
@click.option("--text", "search_text", required=True, help="Search keywords or phrase.")
@click.option("--page", default=1, type=int)
@click.option("--page-size", default=10, type=int)
@click.option("--search-opt", type=click.Choice(["PHRASE", "ANY", "ALL"]), default="PHRASE")
@click.option("--court-type", default="2", help='"2" for High Courts, "3" for SCR.')
@click.option("--download", "download_dir", default=None, help="Save PDFs to this directory.")
@click.pass_context
def judgments_search(
    ctx: click.Context,
    search_text: str,
    page: int,
    page_size: int,
    search_opt: str,
    court_type: str,
    download_dir: str | None,
):
    """Search judgments on the judgment portal."""
    attempts = _captcha_attempts(ctx)
    is_json_out = _is_json(ctx)

    async def _go():
        from bharat_courts.judgments.client import JudgmentSearchClient

        async with JudgmentSearchClient() as client:
            sr = await client.search(
                search_text,
                page=page,
                page_size=page_size,
                search_opt=search_opt,
                court_type=court_type,
                max_captcha_attempts=attempts,
            )
            local_paths: dict[int, str] = {}
            if download_dir and sr.items:
                out_dir = _ensure_dir(download_dir)
                # Suppress per-file echo in JSON mode
                if is_json_out:
                    for idx, j in enumerate(sr.items):
                        if not j.pdf_url:
                            continue
                        try:
                            await client.download_pdf(j, court_type=court_type)
                        except Exception as e:
                            _warn(f"download failed for {j.case_number or j.title!r}: {e}")
                            continue
                        if not j.pdf_bytes:
                            continue
                        stem = j.case_number or j.title or "judgment"
                        suffix = (
                            j.judgment_date.isoformat() if j.judgment_date else f"item_{idx + 1}"
                        )
                        out_path = _save_pdf(out_dir, stem, suffix, j.pdf_bytes)
                        local_paths[idx] = str(out_path)
                else:
                    local_paths = await _download_judgment_pdfs(
                        client, sr.items, out_dir, court_type
                    )
            return sr, local_paths

    sr, local_paths = _run(_go())

    if is_json_out:
        items_out = []
        for idx, j in enumerate(sr.items):
            d = j.to_dict(exclude_none=True)
            if idx in local_paths:
                d["pdf_local_path"] = local_paths[idx]
            items_out.append(d)
        _emit_json(
            {
                "total_count": sr.total_count,
                "page": sr.page,
                "page_size": sr.page_size,
                "has_next": sr.has_next,
                "total_pages": sr.total_pages,
                "items": items_out,
            }
        )
        return

    if not sr.items:
        click.echo("No judgments found.")
        return
    click.echo(f"Found {sr.total_count} judgments (page {sr.page} of {sr.total_pages})")
    for j in sr.items:
        _print_judgment_human(j)


@judgments.command("search-all")
@click.option("--text", "search_text", required=True)
@click.option("--page-size", default=25, type=int)
@click.option("--max-pages", default=0, type=int, help="Stop after N pages (0 = all).")
@click.option("--search-opt", type=click.Choice(["PHRASE", "ANY", "ALL"]), default="PHRASE")
@click.option("--court-type", default="2")
@click.option("--download", "download_dir", default=None)
@click.pass_context
def judgments_search_all(
    ctx: click.Context,
    search_text: str,
    page_size: int,
    max_pages: int,
    search_opt: str,
    court_type: str,
    download_dir: str | None,
):
    """Walk every page of judgment results."""
    attempts = _captcha_attempts(ctx)
    is_json_out = _is_json(ctx)

    async def _go():
        from bharat_courts.judgments.client import JudgmentSearchClient

        all_items: list = []
        item_paths: list[str | None] = []
        out_dir = _ensure_dir(download_dir) if download_dir else None

        async with JudgmentSearchClient() as client:
            page_num = 0
            async for sr in client.search_all(
                search_text,
                page_size=page_size,
                search_opt=search_opt,
                court_type=court_type,
                max_captcha_attempts=attempts,
            ):
                page_num += 1
                for j in sr.items:
                    all_items.append(j)
                    item_paths.append(None)
                if out_dir:
                    base = len(all_items) - len(sr.items)
                    for offset, j in enumerate(sr.items):
                        if not j.pdf_url:
                            continue
                        try:
                            await client.download_pdf(j, court_type=court_type)
                        except Exception as e:
                            _warn(f"download failed for {j.case_number or j.title!r}: {e}")
                            continue
                        if not j.pdf_bytes:
                            continue
                        stem = j.case_number or j.title or "judgment"
                        suffix = (
                            j.judgment_date.isoformat()
                            if j.judgment_date
                            else f"item_{base + offset + 1}"
                        )
                        out_path = _save_pdf(out_dir, stem, suffix, j.pdf_bytes)
                        item_paths[base + offset] = str(out_path)
                        if not is_json_out:
                            click.echo(f"Saved: {out_path} ({len(j.pdf_bytes)} bytes)")
                if max_pages and page_num >= max_pages:
                    break
        return all_items, item_paths

    all_items, item_paths = _run(_go())

    if is_json_out:
        out = []
        for idx, j in enumerate(all_items):
            d = j.to_dict(exclude_none=True)
            if item_paths[idx]:
                d["pdf_local_path"] = item_paths[idx]
            out.append(d)
        _emit_json({"total_items": len(all_items), "items": out})
        return

    if not all_items:
        click.echo("No judgments found.")
        return
    click.echo(f"Walked {len(all_items)} judgments")
    for j in all_items:
        _print_judgment_human(j)


# ---------------------------------------------------------------------------
# sci group
# ---------------------------------------------------------------------------


@main.group()
def sci():
    """Supreme Court of India (www.sci.gov.in)."""


@sci.command("recent")
@click.option("--limit", default=50, type=int, help="Max items to print (homepage caps at 50).")
@click.option("--download", "download_dir", default=None, help="Save PDFs to this directory.")
@click.pass_context
def sci_recent(ctx: click.Context, limit: int, download_dir: str | None):
    """List the most recent Supreme Court judgments (homepage feed)."""
    is_json_out = _is_json(ctx)

    async def _go():
        from bharat_courts.sci.client import SCIClient

        async with SCIClient() as client:
            items = await client.list_recent_judgments(limit=limit)
            local_paths: dict[int, str] = {}
            if download_dir and items:
                out_dir = _ensure_dir(download_dir)
                for idx, j in enumerate(items):
                    if not j.pdf_url:
                        continue
                    try:
                        await client.download_pdf(j)
                    except Exception as e:
                        _warn(f"download failed for {j.case_number or j.title!r}: {e}")
                        continue
                    if not j.pdf_bytes:
                        continue
                    stem = j.case_number or j.source_id or j.title or "judgment"
                    suffix = j.judgment_date.isoformat() if j.judgment_date else f"item_{idx + 1}"
                    out_path = _save_pdf(out_dir, stem, suffix, j.pdf_bytes)
                    local_paths[idx] = str(out_path)
                    if not is_json_out:
                        click.echo(f"Saved: {out_path} ({len(j.pdf_bytes)} bytes)")
            return items, local_paths

    items, local_paths = _run(_go())

    if is_json_out:
        out = []
        for idx, j in enumerate(items):
            d = j.to_dict(exclude_none=True)
            if idx in local_paths:
                d["pdf_local_path"] = local_paths[idx]
            out.append(d)
        _emit_json(out)
        return

    if not items:
        click.echo("No SC judgments found.")
        return
    click.echo(f"Found {len(items)} recent SC judgments")
    for j in items:
        click.echo(f"\n{j.title}")
        if j.case_number:
            click.echo(f"  {j.case_number}")
        if j.judgment_date:
            click.echo(f"  Date: {j.judgment_date}")
        if j.source_id:
            click.echo(f"  Diary: {j.source_id}")
        if j.pdf_url:
            click.echo(f"  PDF: {j.pdf_url}")


# ---------------------------------------------------------------------------
# archive group  (AWS Open Data — historical judgment metadata)
# ---------------------------------------------------------------------------


@main.group()
def archive():
    """Historical judgment archive (AWS Open Data S3 buckets)."""


def _parse_year_arg(year: str | None) -> int | tuple[int, int] | None:
    """Accept ``"2020"`` or ``"2018-2024"``."""
    if not year:
        return None
    if "-" in year:
        lo, hi = year.split("-", 1)
        return (int(lo), int(hi))
    return int(year)


def _print_judgment_archive_human(j: Any) -> None:
    click.echo(f"\n{j.title or '(no title)'}")
    parts: list[str] = []
    if j.cnr:
        parts.append(f"CNR {j.cnr}")
    if j.case_id:
        parts.append(j.case_id)
    if j.citation:
        parts.append(j.citation)
    if parts:
        click.echo("  " + " · ".join(parts))
    if j.court:
        click.echo(f"  Court: {j.court.name}")
    elif j.court_name_raw:
        click.echo(f"  Court: {j.court_name_raw}")
    if j.decision_date:
        click.echo(f"  Decided: {j.decision_date}")
    if j.judges:
        click.echo(f"  Bench: {', '.join(j.judges)}")
    if j.disposal_nature:
        click.echo(f"  Outcome: {j.disposal_nature}")


@archive.command("query")
@click.option(
    "--court",
    "court_code",
    default=None,
    help="Court code (e.g. 'sci', 'delhi'). Omit to query all sources.",
)
@click.option("--year", default=None, help="Single year (2020) or range (2018-2024).")
@click.option("--judge", default=None, help="Case-insensitive judge substring.")
@click.option("--party", default=None, help="Case-insensitive party/title substring.")
@click.option("--citation", default=None, help="SCI citation substring.")
@click.option("--cnr", default=None, help="Exact CNR match.")
@click.option("--limit", default=20, type=int, show_default=True)
@click.pass_context
def archive_query(
    ctx: click.Context,
    court_code: str | None,
    year: str | None,
    judge: str | None,
    party: str | None,
    citation: str | None,
    cnr: str | None,
    limit: int,
):
    """Query historical judgment metadata from the AWS archive."""
    try:
        from bharat_courts.archive.client import ArchiveClient
    except ImportError as e:
        click.echo(
            "Archive support requires the 'archive' extra: pip install 'bharat-courts[archive]'",
            err=True,
        )
        raise SystemExit(1) from e

    year_arg = _parse_year_arg(year)

    async def _go():
        async with ArchiveClient() as client:
            return await client.search(
                court=court_code,
                year=year_arg,
                judge=judge,
                party=party,
                citation=citation,
                cnr=cnr,
                limit=limit,
            )

    results = _run(_go())

    if _is_json(ctx):
        _emit_json([j.to_dict(exclude_none=True) for j in results])
        return

    if not results:
        click.echo("No judgments found.")
        return
    click.echo(f"Found {len(results)} judgment(s):")
    for j in results:
        _print_judgment_archive_human(j)


@archive.command("get")
@click.option("--cnr", required=True, help="CNR to look up and fetch.")
@click.option("--pdf", "as_pdf", is_flag=True, help="Save the PDF (otherwise print metadata).")
@click.option(
    "--out",
    "out_path",
    default=None,
    help="Output file (PDF mode) or directory. Defaults to <cnr>.pdf in cwd.",
)
@click.option(
    "--language",
    default="english",
    show_default=True,
    help="SCI only: 'english' or a regional language code/name.",
)
@click.pass_context
def archive_get(
    ctx: click.Context,
    cnr: str,
    as_pdf: bool,
    out_path: str | None,
    language: str,
):
    """Look up a CNR in the archive; optionally save the PDF."""
    try:
        from bharat_courts.archive.client import ArchiveClient, ArchivePdfError
    except ImportError as e:
        click.echo(
            "Archive support requires the 'archive' extra: pip install 'bharat-courts[archive]'",
            err=True,
        )
        raise SystemExit(1) from e

    async def _go():
        async with ArchiveClient() as client:
            results = await client.search(cnr=cnr, limit=1)
            if not results:
                return None, None
            j = results[0]
            if not as_pdf:
                return j, None
            try:
                data = await client.fetch_pdf(j, language=language)
            except ArchivePdfError as err:
                return j, ("error", str(err))
            return j, ("ok", data)

    judgment, pdf_result = _run(_go())

    if judgment is None:
        click.echo(f"No archive record for CNR {cnr}", err=True)
        raise SystemExit(2)

    if not as_pdf:
        if _is_json(ctx):
            _emit_json(judgment.to_dict(exclude_none=True))
            return
        _print_judgment_archive_human(judgment)
        return

    assert pdf_result is not None
    status, payload = pdf_result
    if status == "error":
        click.echo(f"PDF fetch failed: {payload}", err=True)
        raise SystemExit(3)

    data: bytes = payload  # type: ignore[assignment]
    if out_path:
        out = Path(out_path).expanduser()
        if out.is_dir() or out_path.endswith("/"):
            out = out / f"{cnr}.pdf"
    else:
        out = Path.cwd() / f"{cnr}.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)

    if _is_json(ctx):
        _emit_json({"cnr": cnr, "bytes": len(data), "path": str(out)})
    else:
        click.echo(f"Saved {len(data):,} bytes → {out}")


@archive.command("download")
@click.option(
    "--court",
    "court_code",
    default="sci",
    show_default=True,
    help="Court code. SCI pre-warms the year tar; HC is a no-op for now.",
)
@click.option("--year", required=True, type=int)
@click.option("--language", default="english", show_default=True, help="SCI only.")
@click.pass_context
def archive_download(
    ctx: click.Context,
    court_code: str,
    year: int,
    language: str,
):
    """Pre-warm the local cache (currently SCI tar bundles only)."""
    try:
        from bharat_courts.archive.client import ArchiveClient
    except ImportError as e:
        click.echo(
            "Archive support requires the 'archive' extra: pip install 'bharat-courts[archive]'",
            err=True,
        )
        raise SystemExit(1) from e

    court = _resolve_court_or_die(court_code)
    if court.court_type.value != "supreme_court":
        click.echo(
            f"download only supports SCI year tars today — {court.name} ships "
            "individual PDFs that are fetched on demand by `archive get`.",
            err=True,
        )
        raise SystemExit(1)

    async def _go():
        async with ArchiveClient() as client:
            return await client.prefetch_sci_year(year, language=language)

    path = _run(_go())

    if _is_json(ctx):
        _emit_json({"path": path})
    else:
        click.echo(f"Cached: {path}")


@archive.command("cache")
@click.option("--clear", is_flag=True, help="Delete the entire archive cache directory.")
@click.pass_context
def archive_cache(ctx: click.Context, clear: bool):
    """Show cache stats or clear the cache."""
    try:
        from bharat_courts.archive.client import ArchiveClient
    except ImportError as e:
        click.echo(
            "Archive support requires the 'archive' extra: pip install 'bharat-courts[archive]'",
            err=True,
        )
        raise SystemExit(1) from e

    async def _info():
        async with ArchiveClient() as client:
            return client.cache_info()

    info = _run(_info())

    if clear:
        import shutil

        cache_dir = Path(info["cache_dir"])
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
            click.echo(f"Cleared {info['files']} files ({info['bytes']:,} bytes) from {cache_dir}")
        else:
            click.echo(f"Cache directory does not exist: {cache_dir}")
        return

    if _is_json(ctx):
        _emit_json(info)
        return
    click.echo(f"Cache directory: {info['cache_dir']}")
    click.echo(f"  Files: {info['files']:,}")
    click.echo(f"  Size:  {info['bytes']:,} bytes ({info['bytes'] / (1024**2):.1f} MiB)")
    click.echo(f"  Cap:   {info['max_bytes']:,} bytes ({info['max_bytes'] / (1024**3):.1f} GiB)")


@archive.command("count")
@click.option(
    "--court",
    "court_code",
    default=None,
    help="Court code (e.g. 'sci', 'delhi'). Omit to count both buckets.",
)
@click.option("--year", default=None, type=int, help="Restrict to a single year.")
@click.pass_context
def archive_count(ctx: click.Context, court_code: str | None, year: int | None):
    """Show row counts in the archive for a court and/or year."""
    try:
        from bharat_courts.archive.client import ArchiveClient
    except ImportError as e:
        click.echo(
            "Archive support requires the 'archive' extra: pip install 'bharat-courts[archive]'",
            err=True,
        )
        raise SystemExit(1) from e

    async def _go():
        async with ArchiveClient() as client:
            return await client.count(court=court_code, year=year)

    counts = _run(_go())

    if _is_json(ctx):
        _emit_json(counts)
        return
    for source, n in counts.items():
        click.echo(f"  {source}: {n:,}")


if __name__ == "__main__":
    main()
