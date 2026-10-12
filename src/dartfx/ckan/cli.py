import csv
import json
import logging
import os
import sys
from enum import StrEnum
from typing import Annotated

import typer
from dotenv import find_dotenv, load_dotenv
from rich.console import Console
from rich.table import Table

from dartfx.ckan.ckan import (
    SearchParameters,
    ServerInstallation,
    fetch_ckan_installations,
)
from dartfx.ckan.ecosystem.manager import EcosystemManager
from dartfx.ckan.harvester import harvest as _harvest_cmd
from dartfx.ckan.server import CKANServer

load_dotenv(find_dotenv(usecwd=True))


def _normalize_smart_dashes() -> None:
    """Sanitize macOS smart dashes (en-dash, em-dash) in sys.argv to standard hyphens."""
    normalized: list[str] = []
    for arg in sys.argv:
        if any(arg.startswith(prefix) for prefix in ("-–", "—", "–", "−")):
            clean = arg.replace("-–", "--").replace("—", "--").replace("−", "-")
            if clean.startswith("–"):
                clean = "--" + clean[1:] if len(clean) > 2 else "-" + clean[1:]
            normalized.append(clean)
        else:
            normalized.append(arg)
    sys.argv[:] = normalized


_normalize_smart_dashes()

app = typer.Typer(
    name="dartfx-ckan",
    help="CLI for discovering, searching, and interacting with CKAN repositories.",
    add_completion=False,
)
console = Console()


class OutputFormat(StrEnum):
    TABLE = "table"
    JSON = "json"
    CSV = "csv"


def get_server(hostname: str | None = None, api_key: str | None = None) -> CKANServer:
    """Helper to create a CKANServer instance."""
    resolved_host = hostname or os.environ.get("CKAN_SERVER") or "demo.ckan.org"
    installation = ServerInstallation(hostname=resolved_host)
    return CKANServer(server=installation, api_key=api_key)


@app.command()
def installations(
    country: Annotated[
        str | None,
        typer.Option(
            "--country",
            "-c",
            help="Filter installations by 2-letter ISO country code or country name.",
        ),
    ] = None,
    server: Annotated[
        str | None,
        typer.Option(
            "--server",
            "-s",
            help="Filter or search for a specific CKAN server hostname.",
        ),
    ] = None,
    format: Annotated[OutputFormat, typer.Option("--format", "-f", help="Output format")] = OutputFormat.TABLE,
    limit: Annotated[int | None, typer.Option("--limit", "-l", help="Limit number of results")] = None,
) -> None:
    """List worldwide CKAN installations."""
    all_installations = fetch_ckan_installations(target_server=server, country=country)

    if limit:
        all_installations = all_installations[:limit]

    if format == OutputFormat.JSON:
        console.print_json(json.dumps([inst.model_dump(exclude_none=True) for inst in all_installations]))
        return

    if format == OutputFormat.CSV:
        writer = csv.DictWriter(
            sys.stdout,
            fieldnames=["name", "hostname", "country", "country_code", "version", "datasets"],
        )
        writer.writeheader()
        for inst in all_installations:
            writer.writerow(
                {
                    "name": inst.name or "",
                    "hostname": inst.clean_hostname or "",
                    "country": inst.country or "",
                    "country_code": inst.country_code or "",
                    "version": inst.version or "",
                    "datasets": inst.dataset_count if inst.dataset_count is not None else "",
                }
            )
        return

    table = Table(title=f"Worldwide CKAN Installations ({len(all_installations)} found)")
    table.add_column("Name", style="cyan")
    table.add_column("Hostname", style="magenta")
    table.add_column("Country", style="green")
    table.add_column("Code", style="yellow", justify="center")
    table.add_column("Version", style="dim", justify="center")
    table.add_column("Datasets", style="bold white", justify="right")

    for inst in all_installations:
        host = inst.clean_hostname or "N/A"
        clickable_host = f"[link={inst.url}]{host}[/link]" if inst.url else host
        ds_count = f"{inst.dataset_count:,}" if inst.dataset_count is not None else "-"
        table.add_row(
            inst.name or "N/A",
            clickable_host,
            inst.country or "N/A",
            inst.country_code or "-",
            inst.version or "-",
            ds_count,
        )

    console.print(table)


@app.command()
def info(
    hostname: Annotated[
        str | None,
        typer.Argument(
            help="CKAN server hostname",
            envvar="CKAN_SERVER",
        ),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option(
            "--api-key",
            "-k",
            envvar=["DARTFX_CKAN_API_KEY", "CKAN_API_KEY", "CKAN_API_TOKEN"],
            help="API Key / Token",
        ),
    ] = None,
) -> None:
    """Get metadata and capabilities for a specific CKAN server."""
    resolved_host = hostname or os.environ.get("CKAN_SERVER") or "demo.ckan.org"
    server_client = get_server(resolved_host, api_key)

    with console.status(f"[bold green]Fetching info from {resolved_host}..."):
        try:
            version_info = server_client.get_info_version()
            server_info = server_client.get_info_server()
        except Exception as e:
            console.print(f"[bold red]Error:[/] {e}")
            raise typer.Exit(code=1) from e

    title = server_info.get("data", {}).get("title") or resolved_host
    version = version_info.get("data", {}).get("version", "N/A")
    desc = server_info.get("data", {}).get("description", "N/A")
    exts = server_info.get("data", {}).get("extensions", [])

    console.print(f"\n[bold cyan]Server:[/] {title} ([dim]{resolved_host}[/dim])")
    console.print(f"[bold cyan]CKAN Version:[/] {version}")
    if desc and desc != "N/A":
        console.print(f"[bold cyan]Description:[/] {desc}")

    if exts:
        ext_str = ", ".join(exts) if isinstance(exts, list) else str(exts)
        console.print(f"[bold cyan]Extensions:[/] {ext_str}")


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query")] = "*:*",
    hostname: Annotated[
        str,
        typer.Option(
            "--hostname",
            "-H",
            envvar="CKAN_SERVER",
            help="CKAN server hostname",
        ),
    ] = "demo.ckan.org",
    limit: Annotated[int, typer.Option("--per-page", "--limit", "-p", "-l", help="Number of results to return")] = 25,
    sort: Annotated[str | None, typer.Option("--sort", "-s", help="Sort order (e.g. metadata_modified desc)")] = None,
    format: Annotated[OutputFormat, typer.Option("--format", "-f", help="Output format")] = OutputFormat.TABLE,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", "-k", envvar=["DARTFX_CKAN_API_KEY", "CKAN_API_KEY"], help="API Key"),
    ] = None,
) -> None:
    """Search for datasets on a CKAN server."""
    server_client = get_server(hostname, api_key)
    params = SearchParameters(q=query, rows=limit, sort=sort)

    with console.status(f"[bold green]Searching {hostname} for '{query}'..."):
        try:
            results = server_client.search(params)
        except Exception as e:
            console.print(f"[bold red]Error:[/] {e}")
            raise typer.Exit(code=1) from e

    if format == OutputFormat.JSON:
        console.print_json(data=results)
        return

    items = results.get("results", [])
    total = results.get("count", len(items))

    if format == OutputFormat.CSV:
        writer = csv.DictWriter(sys.stdout, fieldnames=["name", "title", "organization", "num_resources", "modified"])
        writer.writeheader()
        for item in items:
            org = item.get("organization")
            org_title = org.get("title") or org.get("name") if isinstance(org, dict) else ""
            writer.writerow(
                {
                    "name": item.get("name", ""),
                    "title": item.get("title") or item.get("name", ""),
                    "organization": org_title,
                    "num_resources": item.get("num_resources", len(item.get("resources", []))),
                    "modified": item.get("metadata_modified", ""),
                }
            )
        return

    table = Table(title=f"Search Results on {hostname} for '{query}' (Total: {total})")
    table.add_column("Name / ID", style="magenta")
    table.add_column("Title", style="cyan")
    table.add_column("Organization", style="green")
    table.add_column("Resources", style="yellow", justify="right")
    table.add_column("Modified", style="dim")

    for item in items:
        name = item.get("name") or item.get("id") or "N/A"
        title = item.get("title") or name
        org = item.get("organization")
        org_title = (org.get("title") or org.get("name")) if isinstance(org, dict) else "N/A"
        res_count = str(item.get("num_resources", len(item.get("resources", []))))
        modified = item.get("metadata_modified", "-")

        url = f"https://{hostname}/dataset/{name}"
        clickable_name = f"[link={url}]{name}[/link]"

        table.add_row(clickable_name, title, org_title or "N/A", res_count, modified)

    console.print(table)


@app.command()
def dataset(
    identifier: Annotated[str, typer.Argument(help="Dataset name or ID")],
    hostname: Annotated[
        str,
        typer.Option(
            "--hostname",
            "-H",
            envvar="CKAN_SERVER",
            help="CKAN server hostname",
        ),
    ] = "demo.ckan.org",
    export: Annotated[
        str | None,
        typer.Option("--export", "-e", help="Export format name (e.g. json, dcat, ttl, jsonld)"),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", "-k", envvar=["DARTFX_CKAN_API_KEY", "CKAN_API_KEY"], help="API Key"),
    ] = None,
) -> None:
    """Get metadata or a specific export format for a dataset."""
    server_client = get_server(hostname, api_key)

    with console.status(f"[bold green]Fetching dataset '{identifier}' from {hostname}..."):
        try:
            if export:
                result = server_client.get_dataset_export(identifier, export)
                if isinstance(result, (dict, list)):
                    console.print_json(data=result)
                else:
                    console.print(result)
            else:
                result = server_client.get_dataset(identifier)
                console.print_json(data=result.model_dump(exclude_none=True))
        except Exception as e:
            console.print(f"[bold red]Error:[/] {e}")
            raise typer.Exit(code=1) from e


@app.command()
def organizations(
    hostname: Annotated[
        str | None,
        typer.Argument(
            help="CKAN server hostname",
            envvar="CKAN_SERVER",
        ),
    ] = None,
    format: Annotated[OutputFormat, typer.Option("--format", "-f", help="Output format")] = OutputFormat.TABLE,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Number of organizations to list")] = 50,
    api_key: Annotated[
        str | None,
        typer.Option(
            "--api-key",
            "-k",
            envvar=["DARTFX_CKAN_API_KEY", "CKAN_API_KEY"],
            help="API Key",
        ),
    ] = None,
) -> None:
    """List organizations for a specific CKAN server."""
    resolved_host = hostname or os.environ.get("CKAN_SERVER") or "demo.ckan.org"
    server_client = get_server(resolved_host, api_key)

    with console.status(f"[bold green]Fetching organizations from {resolved_host}..."):
        try:
            orgs = server_client.list_organizations(limit=limit)
        except Exception as e:
            console.print(f"[bold red]Error:[/] {e}")
            raise typer.Exit(code=1) from e

    if format == OutputFormat.JSON:
        console.print_json(json.dumps([o.model_dump(exclude_none=True) for o in orgs]))
        return

    if format == OutputFormat.CSV:
        writer = csv.DictWriter(sys.stdout, fieldnames=["name", "title", "description"])
        writer.writeheader()
        for org in orgs:
            writer.writerow(
                {
                    "name": org.name,
                    "title": org.title or "",
                    "description": org.description or "",
                }
            )
        return

    table = Table(title=f"Organizations on {resolved_host} ({len(orgs)} found)")
    table.add_column("Name / ID", style="magenta")
    table.add_column("Title", style="cyan")
    table.add_column("Description", style="white")

    for org in orgs:
        table.add_row(org.name, org.title or "N/A", (org.description or "N/A")[:80])

    console.print(table)


# ---------------------------------------------------------------------------
# Harvester & Sync Commands
# ---------------------------------------------------------------------------
app.command(
    name="harvest",
    help="Harvest and incrementally sync CKAN metadata records into local storage.",
)(_harvest_cmd)


@app.command(name="stats")
def stats(
    server: Annotated[
        str,
        typer.Option(
            "--server",
            "-s",
            envvar="CKAN_SERVER",
            help="Target CKAN server hostname (e.g. demo.ckan.org, data.gov) or ALL.",
        ),
    ] = "ALL",
    country: Annotated[
        str | None,
        typer.Option(
            "--country",
            "-c",
            help="Filter servers by 2-letter ISO code or country name.",
        ),
    ] = None,
    query: Annotated[
        str | None,
        typer.Option(
            "--query",
            "-q",
            help="Filter datasets by keyword search query.",
        ),
    ] = None,
    api_token: Annotated[
        str | None,
        typer.Option(
            "--api-token",
            "--key",
            "-k",
            envvar=["DARTFX_CKAN_API_KEY", "CKAN_API_KEY", "CKAN_API_TOKEN"],
            help="CKAN API Token for authenticated endpoints.",
        ),
    ] = None,
    refresh: Annotated[
        bool,
        typer.Option(
            "--refresh",
            "--refresh-catalog",
            "-r",
            help="Force a live statistics refresh from servers, bypassing local 24-hour cache.",
        ),
    ] = False,
    cache_ttl: Annotated[
        int,
        typer.Option(
            "--cache-ttl",
            help="Statistics cache expiration time in hours (default: 24).",
        ),
    ] = 24,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            "-t",
            help="HTTP request timeout in seconds per server query (default: 10).",
        ),
    ] = 10,
) -> None:
    """Display live dataset and organization counts for CKAN servers."""
    from dartfx.ckan.harvester import display_server_stats

    display_server_stats(
        server=server,
        country=country,
        query=query,
        api_token=api_token,
        refresh_cache=refresh,
        cache_ttl_hours=float(cache_ttl),
        timeout=timeout,
    )


@app.command(name="errors")
def errors(
    repo_dir: Annotated[
        str | None,
        typer.Argument(
            help="Path to repository storage root directory (defaults to DARTFX_CKAN_REPOSITORY or ./).",
        ),
    ] = None,
    server: Annotated[
        str,
        typer.Option(
            "--server",
            "-s",
            envvar="CKAN_SERVER",
            help="Filter error report by target server hostname (or ALL).",
        ),
    ] = "ALL",
    format: Annotated[
        OutputFormat,
        typer.Option(
            "--format",
            "-f",
            help="Output format: table (default), json, or csv.",
        ),
    ] = OutputFormat.TABLE,
    by_format: Annotated[
        bool,
        typer.Option(
            "--by-format",
            help="Breakdown error counts in a matrix by metadata format.",
        ),
    ] = False,
    by_server: Annotated[
        bool,
        typer.Option(
            "--by-server",
            help="Breakdown error counts by server repository.",
        ),
    ] = False,
    details: Annotated[
        bool,
        typer.Option(
            "--details",
            "-d",
            help="Show individual failed dataset names and reasons.",
        ),
    ] = False,
) -> None:
    """Analyze and report counts per harvest error type from repository manifests."""
    from dartfx.ckan.harvester import analyze_harvest_errors, render_harvest_errors

    analysis = analyze_harvest_errors(repo_dir=repo_dir, server=server)

    if format == OutputFormat.JSON:
        console.print_json(json.dumps(analysis, indent=2))
        return

    if format == OutputFormat.CSV:
        writer = csv.writer(sys.stdout)
        if details:
            writer.writerow(["server", "pid", "url", "format", "error_type", "failed_at", "reason"])
            for rec in analysis.get("records", []):
                writer.writerow(
                    [
                        rec.get("server", ""),
                        rec.get("pid", ""),
                        rec.get("url", ""),
                        rec.get("format", ""),
                        rec.get("error_type", ""),
                        rec.get("failed_at", ""),
                        rec.get("reason", ""),
                    ]
                )
        elif by_server:
            writer.writerow(["server", "error_count", "percentage"])
            tot = analysis.get("total_errors", 1)
            for srv, cnt in analysis.get("by_server", {}).items():
                writer.writerow([srv, cnt, f"{(cnt / tot) * 100:.1f}%"])
        else:
            writer.writerow(["error_type", "count", "percentage"])
            tot = analysis.get("total_errors", 1)
            for etype, cnt in analysis.get("by_type", {}).items():
                writer.writerow([etype, cnt, f"{(cnt / tot) * 100:.1f}%"])
        return

    render_harvest_errors(
        analysis=analysis,
        by_format=by_format,
        by_server=by_server,
        details=details,
        console_out=console,
    )


# ---------------------------------------------------------------------------
# Ecosystem Sub-commands
# ---------------------------------------------------------------------------
ecosystem_app = typer.Typer(help="Commands for the CKAN Ecosystem")
app.add_typer(ecosystem_app, name="ecosystem")


@ecosystem_app.command("sync")
def ecosystem_sync(
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force a synchronization even if data is up-to-date",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    """Synchronize the CKAN Ecosystem datasets to local Parquet files."""
    if verbose:
        logging.basicConfig(level=logging.INFO)
    else:
        logging.basicConfig(level=logging.WARNING)

    try:
        manager = EcosystemManager()
        manager.sync(force=force)
        console.print("[green]Sync completed successfully.[/green]")
    except Exception as e:
        console.print(f"[bold red]Error during sync:[/] {e}")
        raise typer.Exit(code=1) from None


if __name__ == "__main__":
    app()
