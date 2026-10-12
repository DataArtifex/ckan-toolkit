#!/usr/bin/env python3
"""CKAN Metadata Harvester & Sync Engine

A smart, incremental harvester for CKAN metadata records.
Uses Typer for CLI interface and Rich for terminal visualizations.
"""

import hashlib
import json
import os
import re
import time
import urllib.parse
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import requests
import typer
from dotenv import find_dotenv, load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text

from .__about__ import __version__
from .ckan import (
    ServerInstallation,
    fetch_ckan_installations,
)

os.environ["PYTHONWARNINGS"] = "ignore"
warnings.filterwarnings("ignore")

app = typer.Typer(
    name="ckan-harvest",
    help="Harvest and incrementally sync CKAN metadata records into local storage.",
    add_completion=False,
)

load_dotenv(find_dotenv(usecwd=True))
console = Console()


class HarvesterFileLogger:
    """File logger for recording execution requests and verbose activity to a timestamped log file."""

    def __init__(self, log_path: Path | None = None) -> None:
        self.log_path = log_path
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, message: str, level: str = "INFO") -> None:
        try:
            plain_msg = Text.from_markup(message).plain
        except Exception:
            plain_msg = message

        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"{timestamp} [{level}] {plain_msg}"

        if self.log_path:
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(formatted + "\n")
            except Exception:
                pass


file_logger = HarvesterFileLogger()


def sanitize_pid(identifier: str) -> str:
    """Convert dataset ID or name to a safe directory name."""
    return re.sub(r"[^a-zA-Z0-9_\-\.]", "_", identifier)


def format_version(version: str | int | float | None) -> str:
    """Format a CKAN version string into a clean semantic version (e.g. 'v2.10', 'v2.11.3')."""
    if not version:
        return "-"
    ver_str = str(version).strip()
    if not ver_str or ver_str == "-":
        return "-"
    match = re.search(r"v?(\d+(?:\.\d+)+)", ver_str, re.IGNORECASE)
    if match:
        return f"v{match.group(1)}"
    match_single = re.search(r"v?(\d+)", ver_str, re.IGNORECASE)
    if match_single:
        return f"v{match_single.group(1)}"
    return ver_str


def get_dataset_metadata_path(server_dir: Path, pid: str, ext: str = ".ckan.json") -> tuple[Path, str]:
    """Get dataset directory and metadata file path inside a dedicated metadata/ folder.

    Returns (full_file_path, relative_path_str).
    """
    pid_dir_name = sanitize_pid(pid)
    metadata_dir = server_dir / pid_dir_name / "metadata"
    file_name = ext.lstrip(".")
    rel_path = f"{pid_dir_name}/metadata/{file_name}"
    return metadata_dir / file_name, rel_path


FORMAT_EXTENSIONS: dict[str, str] = {
    "json": ".ckan.json",
    "native": ".ckan.json",
    "package": ".ckan.json",
    "dcat": ".dcat.xml",
    "dcat-xml": ".dcat.xml",
    "rdf": ".dcat.xml",
    "xml": ".dcat.xml",
    "jsonld": ".dcat.jsonld",
    "dcat_json": ".dcat.jsonld",
    "ttl": ".dcat.ttl",
    "turtle": ".dcat.ttl",
    "resources": ".resources.json",
}

ALL_SUPPORTED_FORMATS: list[str] = ["json", "dcat", "jsonld", "ttl", "resources"]


def get_format_extension(fmt: str) -> str:
    """Get the standard file extension for a given metadata format."""
    clean_fmt = fmt.strip().lower()
    return FORMAT_EXTENSIONS.get(clean_fmt, f".{clean_fmt}")


def normalize_formats(formats_input: str | list[str] | None) -> list[str]:
    """Parse comma-separated or list of metadata formats into a clean list."""
    if not formats_input:
        return []
    if isinstance(formats_input, str):
        raw_list = [formats_input]
    else:
        raw_list = list(formats_input)

    parsed = []
    for entry in raw_list:
        for fmt in entry.split(","):
            fmt_clean = fmt.strip().lower()
            if not fmt_clean:
                continue
            if fmt_clean == "all":
                return list(ALL_SUPPORTED_FORMATS)
            if fmt_clean in ("native", "package"):
                fmt_clean = "json"
            elif fmt_clean in ("xml", "rdf", "dcat-xml"):
                fmt_clean = "dcat"
            elif fmt_clean == "dcat_json":
                fmt_clean = "jsonld"
            elif fmt_clean == "turtle":
                fmt_clean = "ttl"

            if fmt_clean in ALL_SUPPORTED_FORMATS and fmt_clean not in parsed:
                parsed.append(fmt_clean)
    return parsed


DEFAULT_REQUEST_HEADERS: dict[str, str] = {
    "User-Agent": f"dartfx-ckan/{__version__} (Research Harvester; +https://github.com/DataArtifex/dartfx-ckan)",
    "Accept": "application/json, text/plain, */*",
}


def resolve_server_token(
    host: str | None = None,
    repo_root: Path | None = None,
    explicit_token: str | None = None,
) -> str | None:
    """Resolve API token for a CKAN server by searching in order:

    1. Explicitly supplied CLI token (--api-token / -k)
    2. Server-specific directory token file (<repo_root>/<host>/.api_token)
    3. Central repository root tokens mapping (<repo_root>/.ckan_tokens.json)
    4. Current working directory tokens (.ckan_tokens.json or .tokens.json)
    5. Server-specific environment variable (e.g. CKAN_API_TOKEN_DEMO_CKAN_ORG)
    6. Global environment variable (CKAN_API_KEY, DARTFX_CKAN_API_KEY, CKAN_API_TOKEN)
    """
    if explicit_token and explicit_token.strip():
        return explicit_token.strip()

    if not host:
        return (
            os.environ.get("CKAN_API_KEY") or os.environ.get("DARTFX_CKAN_API_KEY") or os.environ.get("CKAN_API_TOKEN")
        )

    clean_host = host.replace("https://", "").replace("http://", "").strip("/")
    if "/" in clean_host:
        clean_host = clean_host.split("/", 1)[0]

    # 1. Check server-specific directory (.api_token)
    search_dirs = []
    if repo_root:
        search_dirs.append(repo_root)
    env_repo = os.environ.get("DARTFX_CKAN_REPOSITORY")
    if env_repo:
        search_dirs.append(Path(env_repo))
    search_dirs.append(Path.cwd())

    for d in search_dirs:
        if d:
            stf = Path(d) / clean_host / ".api_token"
            if stf.exists():
                try:
                    t = stf.read_text("utf-8").strip()
                    if t:
                        return t
                except Exception:
                    pass

    # 2. Check central .ckan_tokens.json / .tokens.json
    for d in search_dirs:
        if d:
            for token_filename in [".ckan_tokens.json", ".tokens.json"]:
                ctf = Path(d) / token_filename
                if ctf.exists():
                    try:
                        m = json.loads(ctf.read_text("utf-8"))
                        if isinstance(m, dict):
                            for k, v in m.items():
                                k_clean = k.replace("https://", "").replace("http://", "").strip("/")
                                if "/" in k_clean:
                                    k_clean = k_clean.split("/", 1)[0]
                                if k_clean.lower() == clean_host.lower() and v:
                                    return str(v).strip()
                    except Exception:
                        pass

    # 3. Server-specific environment variable
    clean_env_name = re.sub(r"[^A-Za-z0-9]", "_", clean_host).upper()
    env_server_key = f"CKAN_API_TOKEN_{clean_env_name}"
    if os.environ.get(env_server_key):
        return os.environ[env_server_key].strip()

    # 4. Global environment variable
    if os.environ.get("CKAN_API_KEY"):
        return os.environ["CKAN_API_KEY"].strip()
    if os.environ.get("DARTFX_CKAN_API_KEY"):
        return os.environ["DARTFX_CKAN_API_KEY"].strip()
    if os.environ.get("CKAN_API_TOKEN"):
        return os.environ["CKAN_API_TOKEN"].strip()

    return None


def save_server_token(host: str, token: str, repo_root: Path | None = None) -> None:
    """Save an API token for a server to both its server directory (.api_token) and central .ckan_tokens.json."""
    clean_host = host.replace("https://", "").replace("http://", "").strip("/")
    if "/" in clean_host:
        clean_host = clean_host.split("/", 1)[0]
    clean_token = token.strip()
    if not clean_token:
        return

    # 1. Save to central .ckan_tokens.json in repo_root (or current dir)
    central_dir = repo_root if repo_root else Path.cwd()
    central_file = central_dir / ".ckan_tokens.json"
    tokens_map = {}
    if central_file.exists():
        try:
            tokens_map = json.loads(central_file.read_text("utf-8"))
        except Exception:
            tokens_map = {}
    tokens_map[clean_host] = clean_token
    try:
        central_file.write_text(json.dumps(tokens_map, indent=2), "utf-8")
    except Exception:
        pass

    # 2. Save to server directory .api_token
    if repo_root:
        server_dir = repo_root / clean_host
        try:
            server_dir.mkdir(parents=True, exist_ok=True)
            (server_dir / ".api_token").write_text(clean_token, "utf-8")
        except Exception:
            pass


def get_request_headers(
    host: str | None = None,
    api_token: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, str]:
    """Return standard headers with User-Agent and resolved CKAN API key."""
    headers = dict(DEFAULT_REQUEST_HEADERS)
    resolved_token = resolve_server_token(host, repo_root=repo_root, explicit_token=api_token)
    if resolved_token:
        headers["Authorization"] = resolved_token.strip()
        headers["X-CKAN-API-Key"] = resolved_token.strip()
    return headers


def format_dataset_url(pid: str, host: str | None = None) -> str:
    """Format dataset URL for console linking."""
    clean_host = host.replace("https://", "").replace("http://", "").strip("/") if host else ""
    if "/" in clean_host:
        clean_host = clean_host.split("/", 1)[0]
    if clean_host:
        return f"https://{clean_host}/dataset/{pid}"
    return f"https://demo.ckan.org/dataset/{pid}"


def is_non_recoverable_error(reason: str | None) -> bool:
    """Check if an error reason is permanent/non-recoverable (no need to retry)."""
    if not reason:
        return False
    r_low = reason.lower()
    return any(
        k in r_low
        for k in [
            "not supported",
            "unsupported format",
            "http 404",
            "http 400",
            "http 403",
            "http 410",
            "empty metadata response",
            "deaccessioned",
            "deleted",
        ]
    )


def _extract_http_error_reason(r: requests.Response) -> str:
    """Extract informative error reason from HTTP response."""
    try:
        data = r.json()
        if isinstance(data, dict):
            if "error" in data and isinstance(data["error"], dict) and "message" in data["error"]:
                return f"HTTP {r.status_code}: {data['error']['message']}"
            if "message" in data and data["message"]:
                return f"HTTP {r.status_code}: {data['message']}"
            if "error" in data and data["error"]:
                return f"HTTP {r.status_code}: {data['error']}"
    except Exception:
        pass
    if r.status_code == 403:
        return "HTTP 403: Forbidden"
    if r.status_code == 404:
        return "HTTP 404: Not Found"
    return f"HTTP {r.status_code}"


def classify_harvest_error(reason: str | None) -> str:
    """Categorize an error message string into a standardized, descriptive error category."""
    if not reason:
        return "Unknown Error"
    r_low = reason.lower()

    # 1. Format Unsupported
    if any(k in r_low for k in ["not supported", "unsupported format", "exporter not found", "not available"]):
        return "Exporter Not Supported on Server"

    # 2. Authentication Required
    if "401" in r_low or "unauthorized" in r_low or "api key required" in r_low:
        return "HTTP 401: Authentication Required (API Token)"

    # 3. Restricted Dataset / Forbidden
    if any(k in r_low for k in ["restricted", "permission denied", "access denied"]):
        return "HTTP 403: Restricted Dataset (Authentication Required)"

    # 4. Bot Protection / WAF
    if any(k in r_low for k in ["cloudflare", "bot protection", "waf", "captcha", "ddos-guard", "incapsula"]):
        return "HTTP 403: Forbidden / Bot Protection (WAF)"

    if "403" in r_low or "forbidden" in r_low:
        return "HTTP 403: Forbidden"

    # 5. Not Found / Deleted
    if "404" in r_low or "not found" in r_low:
        return "HTTP 404: Dataset / Endpoint Not Found"
    if "410" in r_low or "deaccessioned" in r_low or "gone" in r_low or "deleted" in r_low:
        return "HTTP 410: Dataset Deleted / Gone"

    # 6. Unprocessable
    if "422" in r_low or "unprocessable" in r_low:
        return "HTTP 422: Unprocessable Entity"

    # 7. Server Errors
    if any(k in r_low for k in ["500", "502", "503", "504", "internal server error", "bad gateway"]):
        return "HTTP 5xx: Server Error"

    # 8. Rate Limiting
    if "429" in r_low or "rate limit" in r_low or "too many requests" in r_low:
        return "HTTP 429: Rate Limited"

    # 9. Timeouts & Connection
    if "timeout" in r_low:
        return "Request Timeout"
    if any(k in r_low for k in ["connection refused", "failed to establish", "connection error", "name resolution"]):
        return "Network / Connection Error"

    # 10. Parsing
    if any(k in r_low for k in ["jsondecodeerror", "xml syntax", "parse error", "invalid json"]):
        return "JSON / XML Parsing Error"

    if "empty metadata response" in r_low:
        return "Empty Metadata Response (0 bytes)"

    return "Unknown Error"


def analyze_harvest_errors(
    repo_dir: str | Path | None = None,
    server: str = "ALL",
) -> dict[str, Any]:
    """Inspect repository manifests (.manifest.json) and generate structured error analytics."""
    target_repo = Path(repo_dir) if repo_dir else Path.cwd()
    env_repo = os.environ.get("DARTFX_CKAN_REPOSITORY")
    if not repo_dir and env_repo:
        target_repo = Path(env_repo)

    manifest_files: list[Path] = []
    clean_target = (
        server.replace("https://", "").replace("http://", "").strip("/") if server and server.upper() != "ALL" else None
    )
    if clean_target and "/" in clean_target:
        clean_target = clean_target.split("/", 1)[0]

    if clean_target:
        mfile = target_repo / clean_target / ".manifest.json"
        if mfile.exists():
            manifest_files.append(mfile)
    else:
        manifest_files = list(target_repo.glob("*/.manifest.json"))

    by_type: dict[str, int] = {}
    by_format: dict[str, int] = {}
    by_server: dict[str, int] = {}
    matrix: dict[str, dict[str, int]] = {}
    records: list[dict[str, Any]] = []
    affected_datasets: set[str] = set()

    for mfile in manifest_files:
        srv = mfile.parent.name
        try:
            with open(mfile, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        errors_map = data.get("errors", {})
        if not isinstance(errors_map, dict):
            continue

        for err_key, err_info in errors_map.items():
            if not isinstance(err_info, dict):
                continue

            pid = err_info.get("pid") or err_key.split("::")[0]
            fmt = err_info.get("format") or (err_key.split("::")[1] if "::" in err_key else "json")
            raw_reason = err_info.get("reason", "")
            err_cat = err_info.get("error_type") or classify_harvest_error(raw_reason)

            affected_datasets.add(f"{srv}::{pid}")
            by_type[err_cat] = by_type.get(err_cat, 0) + 1
            by_format[fmt] = by_format.get(fmt, 0) + 1
            by_server[srv] = by_server.get(srv, 0) + 1

            if err_cat not in matrix:
                matrix[err_cat] = {}
            matrix[err_cat][fmt] = matrix[err_cat].get(fmt, 0) + 1

            records.append(
                {
                    "server": srv,
                    "pid": pid,
                    "format": fmt,
                    "error_type": err_cat,
                    "reason": raw_reason,
                    "failed_at": err_info.get("failed_at", ""),
                    "url": err_info.get("url") or format_dataset_url(pid, host=srv),
                }
            )

    sorted_by_type = dict(sorted(by_type.items(), key=lambda x: x[1], reverse=True))
    sorted_by_server = dict(sorted(by_server.items(), key=lambda x: x[1], reverse=True))

    return {
        "total_errors": len(records),
        "total_datasets": len(affected_datasets),
        "servers_with_errors": len(by_server),
        "by_type": sorted_by_type,
        "by_format": by_format,
        "by_server": sorted_by_server,
        "matrix": matrix,
        "records": records,
    }


def render_harvest_errors(
    analysis: dict[str, Any],
    by_format: bool = False,
    by_server: bool = False,
    details: bool = False,
    console_out: Console | None = None,
) -> None:
    """Render structured error analysis to the terminal."""
    out = console_out or console
    total = analysis.get("total_errors", 0)

    if total == 0:
        out.print(Panel("[bold green]✓ No harvest errors recorded in repository manifests.[/bold green]", expand=False))
        return

    out.print(
        Panel(
            f"[bold red]Total Harvest Errors:[/] {total:,}  |  "
            f"[bold yellow]Affected Datasets:[/] {analysis.get('total_datasets', 0):,}  |  "
            f"[bold cyan]Servers Affected:[/] {analysis.get('servers_with_errors', 0):,}",
            title="[bold red]CKAN Harvest Error Analysis[/bold red]",
            expand=False,
        )
    )

    if by_format:
        all_fmts = sorted(analysis.get("by_format", {}).keys())
        matrix_table = Table(
            title="Harvest Errors: Breakdown by Error Type & Format",
            header_style="bold magenta",
            show_header=True,
        )
        matrix_table.add_column("Error Category / Type", style="cyan", no_wrap=False)
        for fmt_name in all_fmts:
            matrix_table.add_column(fmt_name.capitalize(), justify="right", style="yellow")
        matrix_table.add_column("Total", justify="right", style="bold red")

        matrix = analysis.get("matrix", {})
        for err_type, count in analysis.get("by_type", {}).items():
            row_cells = [err_type]
            for fmt_name in all_fmts:
                c = matrix.get(err_type, {}).get(fmt_name, 0)
                row_cells.append(str(c) if c > 0 else "[dim]-[/dim]")
            row_cells.append(str(count))
            matrix_table.add_row(*row_cells)

        out.print(matrix_table)

    elif by_server:
        srv_table = Table(
            title="Harvest Errors: Breakdown by Server",
            header_style="bold cyan",
            show_header=True,
        )
        srv_table.add_column("Server Hostname", style="cyan")
        srv_table.add_column("Error Count", justify="right", style="bold red")
        srv_table.add_column("% of Total", justify="right", style="yellow")

        for srv, count in analysis.get("by_server", {}).items():
            pct = f"{(count / total) * 100:.1f}%" if total > 0 else "0%"
            srv_table.add_row(srv, str(count), pct)

        out.print(srv_table)

    else:
        type_table = Table(
            title="Harvest Errors: Count per Error Type",
            header_style="bold red",
            show_header=True,
        )
        type_table.add_column("Error Category / Type", style="cyan", no_wrap=False)
        type_table.add_column("Count", justify="right", style="bold red")
        type_table.add_column("% of Total", justify="right", style="yellow")

        for err_type, count in analysis.get("by_type", {}).items():
            pct = f"{(count / total) * 100:.1f}%" if total > 0 else "0%"
            type_table.add_row(err_type, str(count), pct)

        out.print(type_table)

    if details:
        records = analysis.get("records", [])
        rec_table = Table(
            title=f"Detailed Error Records ({len(records)} Items)",
            header_style="bold yellow",
            show_header=True,
        )
        rec_table.add_column("Server", style="dim", no_wrap=True)
        rec_table.add_column("Dataset ID / Name", style="cyan", no_wrap=True)
        rec_table.add_column("Format", style="yellow", justify="center", no_wrap=True)
        rec_table.add_column("Error Category", style="magenta")
        rec_table.add_column("Reason / Snippet", style="red", no_wrap=False)

        for rec in records:
            reason = rec.get("reason", "")
            if len(reason) > 90:
                reason = reason[:87] + "..."
            srv = rec.get("server", "-")
            pid = rec.get("pid", "-")
            url = rec.get("url") or format_dataset_url(pid, host=srv)

            clean_srv = srv.replace("https://", "").replace("http://", "").strip("/") if srv else ""
            srv_display = f"[link=https://{clean_srv}]{clean_srv}[/link]" if clean_srv and clean_srv != "-" else srv
            pid_display = f"[link={url}]{pid}[/link]" if url and pid != "-" else pid

            rec_table.add_row(
                srv_display,
                pid_display,
                rec.get("format", "-"),
                rec.get("error_type", "-"),
                reason,
            )

        out.print(rec_table)


def format_response_latency(
    latency: float | int | None,
    is_online: bool = True,
    requires_token: bool = False,
    is_error: bool = False,
) -> str:
    """Format response latency with color-coded performance or status badge."""
    if latency is None:
        return "-"
    lat = float(latency)
    if is_error or not is_online:
        return f"[dim red]❌ {lat:.1f}s[/dim red]"
    if requires_token:
        return f"[yellow]🔒 {lat:.1f}s[/yellow]"

    if lat < 1.5:
        return f"[bold green]⚡ {lat:.1f}s[/bold green]"
    elif lat <= 4.0:
        return f"[green]🟢 {lat:.1f}s[/green]"
    elif lat <= 8.0:
        return f"[yellow]🟡 {lat:.1f}s[/yellow]"
    else:
        return f"[bold red]🔴 {lat:.1f}s[/bold red]"


def fetch_server_stats(
    host: str,
    query: str | None = None,
    api_token: str | None = None,
    timeout: int = 10,
    repo_root: Path | None = None,
    refresh_cache: bool = False,
    cache_ttl_hours: float = 24.0,
) -> dict[str, Any]:
    """Retrieve counts of datasets, organizations, version and latency for a CKAN server with 24h cache."""
    clean_host = host.replace("https://", "").replace("http://", "").strip("/")
    if "/" in clean_host:
        clean_host = clean_host.split("/", 1)[0]
    base_url = f"https://{clean_host}"
    headers = get_request_headers(host=clean_host, api_token=api_token, repo_root=repo_root)

    target_repo = repo_root or Path.cwd() / ".cache"
    cache_file = target_repo / clean_host / ".stats_cache.json"

    if cache_file.exists() and not refresh_cache:
        try:
            with open(cache_file, encoding="utf-8") as f:
                cdata = json.load(f)
                cached_at_str = cdata.get("cached_at")
                if cached_at_str:
                    dt = datetime.fromisoformat(cached_at_str)
                    age_hours = (datetime.now(UTC) - dt).total_seconds() / 3600.0
                    if age_hours < cache_ttl_hours:
                        cdata["cached"] = True
                        return cdata
        except Exception:
            pass

    stats: dict[str, Any] = {
        "server": clean_host,
        "datasets": 0,
        "organizations": 0,
        "groups": 0,
        "is_ckan": False,
        "requires_token": False,
        "error": None,
        "version": None,
        "site_title": None,
        "latency_seconds": None,
    }

    t0 = time.time()
    try:
        # 1. Probe status_show
        status_url = f"{base_url}/api/3/action/status_show"
        try:
            r_status = requests.get(status_url, headers=headers, timeout=timeout)
            if r_status.status_code == 200:
                stats["is_ckan"] = True
                s_json = r_status.json()
                res = s_json.get("result", {})
                stats["version"] = res.get("ckan_version") or res.get("installed_version")
                stats["site_title"] = res.get("site_title")
            elif r_status.status_code == 401:
                stats["is_ckan"] = True
                stats["requires_token"] = True
        except Exception:
            pass

        # 2. Probe package_search for dataset count
        search_q = urllib.parse.quote(query) if query else "*:*"
        search_url = f"{base_url}/api/3/action/package_search?q={search_q}&rows=0"
        r_search = requests.get(search_url, headers=headers, timeout=timeout)
        if r_search.status_code == 200:
            stats["is_ckan"] = True
            try:
                s_data = r_search.json()
                res = s_data.get("result", {})
                stats["datasets"] = res.get("count", 0)
            except Exception:
                pass
        elif r_search.status_code == 401:
            stats["is_ckan"] = True
            stats["requires_token"] = True

        # 3. Probe organization_list
        org_url = f"{base_url}/api/3/action/organization_list"
        try:
            r_org = requests.get(org_url, headers=headers, timeout=timeout)
            if r_org.status_code == 200:
                stats["is_ckan"] = True
                org_data = r_org.json()
                res = org_data.get("result", [])
                if isinstance(res, list):
                    stats["organizations"] = len(res)
        except Exception:
            pass

        stats["latency_seconds"] = round(time.time() - t0, 2)

    except requests.exceptions.Timeout:
        stats["latency_seconds"] = round(time.time() - t0, 2)
        stats["error"] = f"Timeout ({timeout}s)"
    except Exception as e:
        stats["latency_seconds"] = round(time.time() - t0, 2)
        stats["error"] = str(e)

    # Cache results
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        stats_to_save = dict(stats)
        stats_to_save["cached_at"] = datetime.now(UTC).isoformat()
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(stats_to_save, f, indent=2)
    except Exception:
        pass

    return stats


def display_server_stats(
    server: str = "ALL",
    country: str | None = None,
    query: str | None = None,
    api_token: str | None = None,
    refresh_cache: bool = False,
    cache_ttl_hours: float = 24.0,
    timeout: int = 10,
    repo_root: Path | None = None,
) -> None:
    """Display live dataset and organization counts for CKAN servers."""
    installations = fetch_ckan_installations(
        target_server=None if server.upper() == "ALL" else server,
        country=country,
        fallback_unlisted=True,
    )

    if not installations:
        console.print(f"[bold red]No CKAN servers found matching filter '{server}'.[/bold red]")
        return

    table = Table(
        title=f"CKAN Server Statistics ({len(installations)} servers)",
        header_style="bold cyan",
        show_header=True,
    )
    table.add_column("Repository / Server", style="white")
    table.add_column("Country", style="green", justify="center")
    table.add_column("Ver", style="dim", justify="center")
    table.add_column("Datasets", justify="right", style="cyan")
    table.add_column("Organizations", justify="right", style="yellow")
    table.add_column("Latency", justify="center")
    table.add_column("Status", justify="left")

    def _query_stat(inst: ServerInstallation) -> tuple[ServerInstallation, dict[str, Any]]:
        s = fetch_server_stats(
            host=inst.clean_hostname,
            query=query,
            api_token=api_token,
            timeout=timeout,
            repo_root=repo_root,
            refresh_cache=refresh_cache,
            cache_ttl_hours=cache_ttl_hours,
        )
        return inst, s

    with console.status("[bold green]Querying CKAN servers..."):
        with ThreadPoolExecutor(max_workers=min(8, len(installations))) as executor:
            futures = [executor.submit(_query_stat, inst) for inst in installations]
            for future in as_completed(futures):
                inst, stat = future.result()
                name_disp = inst.name or inst.clean_hostname
                clickable_host = f"[link={inst.url}]{name_disp}[/link]" if inst.url else name_disp
                cc = inst.country_code or "-"
                ver_disp = format_version(stat.get("version") or inst.version)
                datasets_disp = f"{stat.get('datasets', 0):,}" if stat.get("is_ckan") else "-"
                orgs_disp = f"{stat.get('organizations', 0):,}" if stat.get("is_ckan") else "-"

                lat = stat.get("latency_seconds")
                is_err = bool(stat.get("error"))
                is_ckan = bool(stat.get("is_ckan"))
                req_tok = bool(stat.get("requires_token"))

                lat_badge = format_response_latency(lat, is_online=is_ckan, requires_token=req_tok, is_error=is_err)

                if stat.get("error"):
                    status_text = f"[red]{stat['error']}[/red]"
                elif req_tok:
                    status_text = "[yellow]Auth Required[/yellow]"
                elif stat.get("cached"):
                    status_text = "[dim cyan]Cached (24h)[/dim cyan]"
                else:
                    status_text = "[green]Online[/green]"

                table.add_row(clickable_host, cc, ver_disp, datasets_disp, orgs_disp, lat_badge, status_text)

    console.print(table)


def fetch_active_datasets(
    host: str,
    query: str | None = None,
    since_date: str | None = None,
    limit: int | None = None,
    target_id: str | None = None,
    server_dir: Path | None = None,
    refresh_catalog: bool = False,
    cache_ttl_hours: float = 24.0,
    verbose: bool = False,
    api_token: str | None = None,
    catalog_progress_callback=None,
) -> dict[str, dict[str, Any]]:
    """Retrieve catalog datasets for a CKAN server with 24h caching."""
    clean_host = host.replace("https://", "").replace("http://", "").strip("/")
    if "/" in clean_host:
        clean_host = clean_host.split("/", 1)[0]
    base_url = f"https://{clean_host}"
    headers = get_request_headers(host=clean_host, api_token=api_token)

    cache_file = (server_dir / ".catalog_cache.json") if server_dir else None

    # Check local cache
    if cache_file and cache_file.exists() and not refresh_catalog and not target_id:
        try:
            with open(cache_file, encoding="utf-8") as f:
                cdata = json.load(f)
                cached_at_str = cdata.get("cached_at")
                if cached_at_str:
                    dt = datetime.fromisoformat(cached_at_str)
                    age_hours = (datetime.now(UTC) - dt).total_seconds() / 3600.0
                    if age_hours < cache_ttl_hours:
                        cached_datasets = cdata.get("datasets", {})
                        if limit:
                            filtered = dict(list(cached_datasets.items())[:limit])
                            return filtered
                        return cached_datasets
        except Exception:
            pass

    active_datasets: dict[str, dict[str, Any]] = {}

    if target_id:
        clean_id = target_id.strip()
        active_datasets[clean_id] = {
            "id": clean_id,
            "name": clean_id,
            "title": clean_id,
            "metadata_modified": None,
        }
        return active_datasets

    # Discover datasets via package_search API with pagination
    start = 0
    rows_per_page = 100
    q_term = query if query else "*:*"

    while True:
        encoded_q = urllib.parse.quote(q_term)
        url = f"{base_url}/api/3/action/package_search?q={encoded_q}&rows={rows_per_page}&start={start}"
        if since_date:
            url += f"&fq=metadata_modified:[{urllib.parse.quote(since_date)}%20TO%20*]"

        if verbose:
            console.print(f"[dim]  [API] GET {url}[/dim]")
        file_logger.log(f"[API] GET {url}")

        try:
            r = requests.get(url, headers=headers, timeout=25)
            if r.status_code != 200:
                break
            data = r.json()
            res = data.get("result", {})
            results = res.get("results", [])
            total = res.get("count", len(results))

            if not results:
                break

            for pkg in results:
                pkg_id = str(pkg.get("name") or pkg.get("id", "")).strip()
                if not pkg_id:
                    continue
                active_datasets[pkg_id] = {
                    "id": str(pkg.get("id", "")),
                    "name": pkg_id,
                    "title": pkg.get("title", pkg_id),
                    "metadata_created": pkg.get("metadata_created"),
                    "metadata_modified": pkg.get("metadata_modified"),
                    "num_resources": pkg.get("num_resources", len(pkg.get("resources", []))),
                    "organization": (pkg.get("organization") or {}).get("name")
                    if isinstance(pkg.get("organization"), dict)
                    else None,
                }
                if limit and len(active_datasets) >= limit:
                    break

            if catalog_progress_callback:
                catalog_progress_callback(len(active_datasets), min(total, limit) if limit else total)

            if limit and len(active_datasets) >= limit:
                break

            if len(results) < rows_per_page or len(active_datasets) >= total:
                break

            start += rows_per_page
        except Exception as e:
            file_logger.log(f"[API] Search query error: {e}", level="ERROR")
            break

    # Fallback to package_list if package_search produced no items
    if not active_datasets and not target_id:
        try:
            list_url = f"{base_url}/api/3/action/package_list"
            r_list = requests.get(list_url, headers=headers, timeout=20)
            if r_list.status_code == 200:
                l_data = r_list.json()
                items = l_data.get("result", [])
                if isinstance(items, list):
                    for item in items:
                        pkg_name = str(item).strip()
                        active_datasets[pkg_name] = {
                            "id": pkg_name,
                            "name": pkg_name,
                            "title": pkg_name,
                            "metadata_modified": None,
                        }
                        if limit and len(active_datasets) >= limit:
                            break
        except Exception:
            pass

    # Save to local cache
    if cache_file and active_datasets:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_data = {
                "server": clean_host,
                "cached_at": datetime.now(UTC).isoformat(),
                "query": query,
                "count": len(active_datasets),
                "datasets": active_datasets,
            }
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)
        except Exception:
            pass

    return active_datasets


def fetch_dataset_record(
    host: str,
    identifier: str,
    metadata_format: str = "json",
    verbose: bool = False,
    api_token: str | None = None,
) -> tuple[bytes | None, str, str | None]:
    """Fetch CKAN dataset metadata in specified format (json, dcat, jsonld, ttl, resources).

    Returns (content_bytes, file_extension, error_reason).
    """
    clean_host = host.replace("https://", "").replace("http://", "").strip("/")
    if "/" in clean_host:
        clean_host = clean_host.split("/", 1)[0]
    base_url = f"https://{clean_host}"
    fmt = metadata_format.strip().lower()
    headers = get_request_headers(host=clean_host, api_token=api_token)
    encoded_id = urllib.parse.quote(identifier)

    if fmt in ("json", "native", "package"):
        url = f"{base_url}/api/3/action/package_show?id={encoded_id}"
        ext = ".ckan.json"
    elif fmt in ("dcat", "dcat-xml", "xml", "rdf"):
        url = f"{base_url}/dataset/{encoded_id}.xml"
        ext = ".dcat.xml"
    elif fmt in ("jsonld", "dcat_json"):
        url = f"{base_url}/dataset/{encoded_id}.jsonld"
        ext = ".dcat.jsonld"
    elif fmt in ("ttl", "turtle"):
        url = f"{base_url}/dataset/{encoded_id}.ttl"
        ext = ".dcat.ttl"
    elif fmt == "resources":
        url = f"{base_url}/api/3/action/package_show?id={encoded_id}"
        ext = ".resources.json"
    else:
        return None, f".{fmt}", f"Unsupported format '{fmt}'"

    if verbose:
        console.print(f"[dim]  [API] GET {url}[/dim]")
    file_logger.log(f"[API] GET {url}")

    try:
        r = requests.get(url, headers=headers, timeout=25)
        if r.status_code == 200:
            if fmt == "resources":
                try:
                    payload = r.json().get("result", {})
                    resources_list = payload.get("resources", [])
                    content = json.dumps(resources_list, indent=2).encode("utf-8")
                    return content, ext, None
                except Exception as e:
                    return None, ext, f"Failed to extract resources: {e}"

            content = r.content
            if content and len(content.strip()) > 0:
                # If json format, pretty format it
                if ext.endswith(".json"):
                    try:
                        parsed = json.loads(content.decode("utf-8"))
                        content = json.dumps(parsed, indent=2).encode("utf-8")
                    except Exception:
                        pass
                return content, ext, None
            return None, ext, "Empty metadata response from server (0 bytes)"

        err_msg = _extract_http_error_reason(r)
        return None, ext, err_msg
    except Exception as e:
        return None, ext, str(e)


class ServerHarvester:
    """Manages harvesting, diff detection, and file persistence for a single CKAN server."""

    def __init__(self, host: str, repo_root: Path) -> None:
        self.host = host.replace("https://", "").replace("http://", "").strip("/")
        if "/" in self.host:
            self.host = self.host.split("/", 1)[0]
        self.server_dir = repo_root / self.host
        self.manifest_file = self.server_dir / ".manifest.json"
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> dict[str, Any]:
        if self.manifest_file.exists():
            try:
                with open(self.manifest_file, encoding="utf-8") as f:
                    data = json.load(f)
                    if "errors" not in data:
                        data["errors"] = {}
                    if "records" not in data:
                        data["records"] = {}
                    return data
            except Exception:
                pass
        return {
            "server": self.host,
            "last_synced_at": None,
            "records": {},
            "errors": {},
        }

    def _save_manifest(self) -> None:
        self.server_dir.mkdir(parents=True, exist_ok=True)
        self.manifest["last_synced_at"] = datetime.now(UTC).isoformat()
        with open(self.manifest_file, "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, indent=2)

    def sync(
        self,
        query: str | None = None,
        since_date: str | None = None,
        dry_run: bool = False,
        limit: int | None = None,
        metadata_formats: str | list[str] = "json",
        verbose: bool = False,
        target_id: str | None = None,
        refresh_catalog: bool = False,
        cache_ttl_hours: float = 24.0,
        retry_errors: bool = False,
        force_verify: bool = False,
        api_token: str | None = None,
        progress_callback=None,
        catalog_progress_callback=None,
    ) -> dict[str, list[Any]]:
        """Perform intelligent incremental sync (Additions, Updates, Deletions)."""
        effective_limit = None if limit == 0 else limit
        stats: dict[str, list[Any]] = {
            "datasets": [],
            "added": [],
            "updated": [],
            "deleted": [],
            "unchanged": [],
            "errors": [],
        }
        target_formats = normalize_formats(metadata_formats)

        if verbose:
            console.print(f"[bold cyan]── Syncing Server: {self.host} ──[/bold cyan]")

        active_datasets = fetch_active_datasets(
            self.host,
            query=query,
            since_date=since_date,
            limit=effective_limit,
            target_id=target_id,
            server_dir=self.server_dir,
            refresh_catalog=refresh_catalog,
            cache_ttl_hours=cache_ttl_hours,
            verbose=verbose,
            api_token=api_token,
            catalog_progress_callback=catalog_progress_callback,
        )
        stats["datasets"] = list(active_datasets.keys())

        if not active_datasets and not target_id:
            server_check = fetch_server_stats(self.host, api_token=api_token)
            if not server_check.get("is_ckan"):
                err_msg = str(server_check.get("error") or "Unreachable or not a valid CKAN server")
                stats["errors"].append(
                    {
                        "key": self.host,
                        "pid": self.host,
                        "format": "-",
                        "reason": err_msg,
                    }
                )
                msg = f"Host '{self.host}' is unreachable or not a valid CKAN server: {err_msg}"
                console.print(f"  [bold red][!] {msg}[/bold red]")
                file_logger.log(msg, level="ERROR")
                return stats

        manifest_records = self.manifest.get("records", {})
        existing_errors = self.manifest.get("errors", {})

        # Track records to download
        to_download: list[tuple[str, str, str]] = []  # (pid, fmt, reason)

        for pid, _meta in active_datasets.items():
            for fmt in target_formats:
                record_key = f"{pid}::{fmt}"
                ext = get_format_extension(fmt)
                file_path, _ = get_dataset_metadata_path(self.server_dir, pid, ext)

                # Skip permanent errors unless retry_errors is set
                if not retry_errors and record_key in existing_errors:
                    err_info = existing_errors[record_key]
                    if is_non_recoverable_error(err_info.get("reason")):
                        continue

                if record_key in manifest_records:
                    if not file_path.exists():
                        to_download.append((pid, fmt, "missing_local_file"))
                    elif force_verify:
                        to_download.append((pid, fmt, "force_verify"))
                    else:
                        stats["unchanged"].append(record_key)
                else:
                    to_download.append((pid, fmt, "new_record"))

        total_tasks = len(to_download)
        completed_tasks = 0

        for pid, fmt, _reason in to_download:
            record_key = f"{pid}::{fmt}"
            if dry_run:
                stats["added"].append(record_key)
                completed_tasks += 1
                if progress_callback:
                    progress_callback(completed_tasks, total_tasks, record_key)
                continue

            content, ext, err_msg = fetch_dataset_record(
                self.host,
                pid,
                metadata_format=fmt,
                verbose=verbose,
                api_token=api_token,
            )

            if err_msg or not content:
                err_cat = classify_harvest_error(err_msg)
                self.manifest.setdefault("errors", {})[record_key] = {
                    "pid": pid,
                    "format": fmt,
                    "error_type": err_cat,
                    "reason": err_msg or "Failed to fetch metadata",
                    "failed_at": datetime.now(UTC).isoformat(),
                    "url": format_dataset_url(pid, host=self.host),
                }
                stats["errors"].append(
                    {
                        "key": record_key,
                        "pid": pid,
                        "format": fmt,
                        "reason": err_msg or "Failed to fetch",
                    }
                )
            else:
                # Write file
                file_path, rel_str = get_dataset_metadata_path(self.server_dir, pid, ext)
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_bytes(content)

                sha256_hash = hashlib.sha256(content).hexdigest()
                is_update = record_key in manifest_records

                self.manifest.setdefault("records", {})[record_key] = {
                    "global_id": pid,
                    "format": fmt,
                    "file_path": rel_str,
                    "sha256": sha256_hash,
                    "updated_at": datetime.now(UTC).isoformat(),
                    "verified_at": datetime.now(UTC).isoformat(),
                }
                # Clear previous error if resolved
                if "errors" in self.manifest and record_key in self.manifest["errors"]:
                    del self.manifest["errors"][record_key]

                if is_update:
                    stats["updated"].append(record_key)
                else:
                    stats["added"].append(record_key)

            completed_tasks += 1
            if progress_callback:
                progress_callback(completed_tasks, total_tasks, record_key)

        # Detect deleted datasets if full catalog sync was run
        if not target_id and not query and not since_date and not limit:
            active_keys = {f"{pid}::{fmt}" for pid in active_datasets for fmt in target_formats}
            for rec_key in list(manifest_records.keys()):
                fmt = rec_key.split("::")[1] if "::" in rec_key else "json"
                if fmt in target_formats and rec_key not in active_keys:
                    stats["deleted"].append(rec_key)
                    if not dry_run:
                        del manifest_records[rec_key]

        if not dry_run:
            self._save_manifest()

        return stats


@app.command(name="harvest")
def harvest(
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
            help="Filter servers by 2-letter ISO country code or country name.",
        ),
    ] = None,
    repo_dir: Annotated[
        str | None,
        typer.Option(
            "--repo-dir",
            "-d",
            envvar="DARTFX_CKAN_REPOSITORY",
            help="Repository storage root directory (defaults to current dir).",
        ),
    ] = None,
    metadata_formats: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Metadata format(s) to harvest (json, dcat, jsonld, ttl, resources, or all).",
        ),
    ] = "json",
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            "-l",
            help="Maximum number of datasets to harvest per server (0 for unlimited).",
        ),
    ] = 10,
    workers: Annotated[  # noqa: ARG001
        int,
        typer.Option(
            "--workers",
            "-w",
            help="Number of concurrent server sync workers.",
        ),
    ] = 4,
    since: Annotated[
        str | None,
        typer.Option(
            "--since",
            help="Only harvest datasets created or modified since ISO date (e.g. 2024-01-01).",
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
    retry_errors: Annotated[
        bool,
        typer.Option(
            "--retry-errors",
            help="Retry previously failed datasets recorded in manifests.",
        ),
    ] = False,
    force_verify: Annotated[
        bool,
        typer.Option(
            "--force-verify",
            help="Re-verify and download all records regardless of manifest cache.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Simulate harvesting run without modifying local storage.",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Enable verbose output.",
        ),
    ] = False,
    refresh_catalog: Annotated[
        bool,
        typer.Option(
            "--refresh-catalog",
            "-r",
            help="Force a live catalog refresh, bypassing 24h cache.",
        ),
    ] = False,
    cache_ttl: Annotated[
        int,
        typer.Option(
            "--cache-ttl",
            help="Catalog cache expiration time in hours.",
        ),
    ] = 24,
    api_token: Annotated[
        str | None,
        typer.Option(
            "--api-token",
            "-k",
            envvar=["DARTFX_CKAN_API_KEY", "CKAN_API_KEY", "CKAN_API_TOKEN"],
            help="CKAN API Token for authenticated endpoints.",
        ),
    ] = None,
    log_file: Annotated[
        str | None,
        typer.Option(
            "--log-file",
            help="Path to write execution activity log.",
        ),
    ] = None,
) -> None:
    """Harvest and incrementally sync CKAN metadata records into local storage."""
    global file_logger
    if log_file:
        file_logger = HarvesterFileLogger(Path(log_file))

    target_repo = Path(repo_dir) if repo_dir else Path.cwd()
    target_repo.mkdir(parents=True, exist_ok=True)

    installations = fetch_ckan_installations(
        target_server=None if server.upper() == "ALL" else server,
        country=country,
        fallback_unlisted=True,
    )

    if not installations:
        console.print(f"[bold red]No CKAN servers found matching filter '{server}'.[/bold red]")
        return

    console.print(
        Panel(
            f"[bold green]Starting CKAN Harvest[/bold green]\n"
            f"Servers: [cyan]{len(installations)}[/cyan]  |  "
            f"Formats: [yellow]{metadata_formats}[/yellow]  |  "
            f"Limit: [magenta]{limit if limit else 'Unlimited'}[/magenta]  |  "
            f"Repo: [dim]{target_repo}[/dim]",
            title="[bold blue]dartfx-ckan harvester[/bold blue]",
            expand=False,
        )
    )

    total_added = 0
    total_updated = 0
    total_unchanged = 0
    total_deleted = 0
    total_errors = 0

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
    )

    with progress:
        overall_task = progress.add_task("[bold cyan]Syncing Servers...", total=len(installations))

        for inst in installations:
            host = inst.clean_hostname
            harvester = ServerHarvester(host, target_repo)

            server_task = progress.add_task(f"[dim]Syncing {host}[/dim]", total=100)

            def _progress_cb(
                completed: int,
                total: int,
                record_name: str,
                task_id: Any = server_task,
                srv_host: str = host,
            ) -> None:
                if total > 0:
                    progress.update(
                        task_id,
                        completed=int((completed / total) * 100),
                        description=f"[dim]{srv_host}: {record_name}[/dim]",
                    )

            stats = harvester.sync(
                query=query,
                since_date=since,
                dry_run=dry_run,
                limit=limit,
                metadata_formats=metadata_formats,
                verbose=verbose,
                refresh_catalog=refresh_catalog,
                cache_ttl_hours=float(cache_ttl),
                retry_errors=retry_errors,
                force_verify=force_verify,
                api_token=api_token,
                progress_callback=_progress_cb,
            )

            total_added += len(stats["added"])
            total_updated += len(stats["updated"])
            total_unchanged += len(stats["unchanged"])
            total_deleted += len(stats["deleted"])
            total_errors += len(stats["errors"])

            progress.remove_task(server_task)
            progress.advance(overall_task)

    # Render summary table
    summary_table = Table(title="CKAN Harvest Summary", header_style="bold green")
    summary_table.add_column("Category", style="cyan")
    summary_table.add_column("Count", justify="right", style="bold white")

    summary_table.add_row("Added Records", f"[green]+{total_added:,}[/green]")
    summary_table.add_row("Updated Records", f"[yellow]~{total_updated:,}[/yellow]")
    summary_table.add_row("Unchanged Records", f"[dim]={total_unchanged:,}[/dim]")
    summary_table.add_row("Deleted Records", f"[red]-{total_deleted:,}[/red]")
    summary_table.add_row("Errors", f"[bold red]!{total_errors:,}[/bold red]")

    console.print(summary_table)


if __name__ == "__main__":
    app()
