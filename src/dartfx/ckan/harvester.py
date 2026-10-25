#!/usr/bin/env python3
"""CKAN Metadata Harvester & Sync Engine

A smart, incremental harvester for CKAN metadata records.
Uses Typer for CLI interface and Rich for terminal visualizations.
"""

import csv
import hashlib
import io
import json
import os
import re
import socket
import ssl
import sys
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
    "metadata": ".ckan.json",
    "dcat": ".dcat.xml",
    "dcat-xml": ".dcat.xml",
    "rdf": ".dcat.xml",
    "xml": ".dcat.xml",
    "jsonld": ".dcat.jsonld",
    "dcat_json": ".dcat.jsonld",
    "ttl": ".dcat.ttl",
    "turtle": ".dcat.ttl",
    "resources": ".resources.json",
    "schemaorg": ".schemaorg.jsonld",
    "schema": ".schemaorg.jsonld",
    "schema.org": ".schemaorg.jsonld",
    "croissant": ".croissant.jsonld",
    "mlcroissant": ".croissant.jsonld",
    "ddi": ".ddi.xml",
    "ddi-xml": ".ddi.xml",
}

ALL_SUPPORTED_FORMATS: list[str] = [
    "json",
    "dcat",
    "jsonld",
    "ttl",
    "resources",
    "schemaorg",
    "croissant",
    "ddi",
]

FORMAT_EXTENSION_REQUIREMENTS: dict[str, str | None] = {
    "json": None,
    "native": None,
    "package": None,
    "metadata": None,
    "resources": None,
    "dcat": "ckanext-dcat",
    "dcat-xml": "ckanext-dcat",
    "rdf": "ckanext-dcat",
    "xml": "ckanext-dcat",
    "jsonld": "ckanext-dcat",
    "dcat_json": "ckanext-dcat",
    "ttl": "ckanext-dcat",
    "turtle": "ckanext-dcat",
    "schemaorg": "ckanext-dcat",
    "schema": "ckanext-dcat",
    "schema.org": "ckanext-dcat",
    "croissant": "ckanext-dcat (croissant)",
    "mlcroissant": "ckanext-dcat (croissant)",
    "ddi": "ckanext-ddi",
    "ddi-xml": "ckanext-ddi",
}


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
            if fmt_clean in ("all", "metadata"):
                return list(ALL_SUPPORTED_FORMATS)
            if fmt_clean in ("native", "package"):
                fmt_clean = "json"
            elif fmt_clean in ("xml", "rdf", "dcat-xml"):
                fmt_clean = "dcat"
            elif fmt_clean == "dcat_json":
                fmt_clean = "jsonld"
            elif fmt_clean == "turtle":
                fmt_clean = "ttl"
            elif fmt_clean in ("schema", "schema.org", "schema_org", "schema-org"):
                fmt_clean = "schemaorg"
            elif fmt_clean in ("mlcroissant",):
                fmt_clean = "croissant"
            elif fmt_clean in ("ddi-xml", "ddi_xml", "codebook"):
                fmt_clean = "ddi"

            if fmt_clean in ALL_SUPPORTED_FORMATS and fmt_clean not in parsed:
                parsed.append(fmt_clean)
    return parsed


DEFAULT_REQUEST_HEADERS: dict[str, str] = {
    "User-Agent": f"Mozilla/5.0 (compatible; dartfx-ckan/{__version__}; +https://github.com/DataArtifex/dartfx-ckan)",
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
    env_repo = (
        os.environ.get("DARTFX_CKAN_REPOSITORY_ROOT")
        or os.environ.get("DARTFX_CKAN_REPOSITORY")
        or os.environ.get("CKAN_REPOSITORY_ROOT")
        or os.environ.get("CKAN_REPOSITORY")
    )
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
    custom_ua = os.environ.get("CKAN_USER_AGENT") or os.environ.get("DARTFX_CKAN_USER_AGENT")
    if custom_ua:
        headers["User-Agent"] = custom_ua.strip()
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
    if any(
        k in r_low
        for k in [
            "500",
            "502",
            "503",
            "504",
            "internal server error",
            "bad gateway",
            "service unavailable",
        ]
    ):
        return "HTTP 5xx: Server Error"

    # 8. Rate Limiting
    if "429" in r_low or "rate limit" in r_low or "too many requests" in r_low:
        return "HTTP 429: Rate Limited"

    # 9. SSL / TLS Diagnostics (checked before generic network errors)
    if "ssl" in r_low or "certificate" in r_low:
        if (
            "unable to get local issuer certificate" in r_low
            or "unable to verify the first certificate" in r_low
            or "missing intermediate" in r_low
            or "incomplete chain" in r_low
        ):
            return "Network: SSL Incomplete Chain (Missing Intermediate CA)"
        if "expired" in r_low:
            return "Network: SSL Certificate Expired"
        if "hostname" in r_low and ("mismatch" in r_low or "doesn't match" in r_low or "not valid" in r_low):
            return "Network: SSL Hostname Mismatch"
        if "self-signed" in r_low or "self signed" in r_low:
            return "Network: SSL Self-Signed Certificate"
        if "unexpected_eof" in r_low or "unexpected eof" in r_low or "eof occurred" in r_low:
            return "Network: SSL Handshake Failed (Unexpected EOF)"
        return "Network: SSL / TLS Certificate Error"

    # 10. Timeouts & Connection
    if any(k in r_low for k in ["timeout", "timed out", "connecttimeout", "readtimeout"]):
        return "Request Timeout"
    if any(
        k in r_low
        for k in [
            "connection refused",
            "connection error",
            "max retries exceeded",
            "failed to establish a new connection",
            "nameresolutionerror",
            "getaddrinfo failed",
            "nodename nor servname",
            "name or service not known",
            "remotedisconnected",
        ]
    ):
        return "Network: Connection Failure"

    # 11. Parsing
    if any(
        k in r_low
        for k in [
            "parseerror",
            "jsondecodeerror",
            "syntaxerror",
            "xml.etree",
            "xml syntax",
            "invalid xml",
            "invalid json",
        ]
    ):
        return "JSON / XML Parsing Error"

    if "empty metadata response" in r_low:
        return "Empty Metadata Response (0 bytes)"

    return "Unknown Error"


def abbreviate_error(reason: str | None) -> str:
    """Format a verbose error or exception string into a concise label for CLI table display."""
    if not reason:
        return "Unknown Error"
    r_low = reason.lower()

    # 0. Domain Parked / Expired / For Sale or Not CKAN
    if any(k in r_low for k in ["hugedomains", "for sale", "domain expired", "domain parked", "parked domain"]):
        return "Domain For Sale"
    if "not a ckan server" in r_low or "not ckan server" in r_low or "not ckan" in r_low:
        return "Not CKAN Server"

    # 1. SSL / TLS Diagnostics
    if (
        "ssl" in r_low
        or "certificate" in r_low
        or "cert" in r_low
        or "unexpected_eof" in r_low
        or "eof occurred" in r_low
    ):
        if "hostname" in r_low and ("mismatch" in r_low or "doesn't match" in r_low or "not valid" in r_low):
            return "SSL Hostname Mismatch"
        if "expired" in r_low:
            return "SSL Certificate Expired"
        if "self-signed" in r_low or "self signed" in r_low:
            return "SSL Self-Signed Cert"
        if (
            "unable to get local issuer certificate" in r_low
            or "unable to verify the first certificate" in r_low
            or "missing intermediate" in r_low
            or "incomplete chain" in r_low
        ):
            return "SSL Incomplete Chain"
        if "unexpected_eof" in r_low or "unexpected eof" in r_low or "eof occurred" in r_low:
            return "SSL Handshake Failed"
        return "SSL Certificate Error"

    # 2. Timeout (preserve concise format like "Timeout (10s)" if already present)
    m = re.search(r"timeout\s*\(\d+s\)", reason, re.IGNORECASE)
    if m:
        return m.group(0).capitalize()
    if any(k in r_low for k in ["timeout", "timed out", "connecttimeout", "readtimeout"]):
        return "Request Timeout"

    # 3. DNS / Name Resolution
    if any(
        k in r_low
        for k in ["nameresolutionerror", "getaddrinfo failed", "nodename nor servname", "name or service not known"]
    ):
        return "DNS Resolution Failure"

    # 4. Connection Failures
    if "connection refused" in r_low:
        return "Connection Refused"
    if "connection reset" in r_low:
        return "Connection Reset"
    if any(
        k in r_low
        for k in [
            "connection error",
            "max retries exceeded",
            "failed to establish a new connection",
            "remotedisconnected",
        ]
    ):
        return "Connection Failure"

    # 5. Authentication / Forbidden
    if "401" in r_low or "unauthorized" in r_low:
        return "Auth Required (401)"
    if any(k in r_low for k in ["cloudflare", "bot protection", "waf", "captcha", "ddos-guard", "incapsula"]):
        return "Bot Protection (WAF)"
    if "403" in r_low or "forbidden" in r_low:
        return "Forbidden (403)"

    # 6. HTTP Status Codes
    if "404" in r_low or "not found" in r_low:
        return "Not Found (404)"
    if "500" in r_low or "internal server error" in r_low:
        return "Server Error (500)"
    if "502" in r_low or "bad gateway" in r_low:
        return "Bad Gateway (502)"
    if "503" in r_low or "service unavailable" in r_low:
        return "Service Unavailable (503)"
    if "504" in r_low or "gateway timeout" in r_low:
        return "Gateway Timeout (504)"
    if any(k in r_low for k in ["5xx", "server error"]):
        return "Server Error (5xx)"

    # 7. Parse Errors
    if any(k in r_low for k in ["parseerror", "jsondecodeerror", "syntaxerror", "malformed"]):
        return "Malformed Response"

    # 8. Short clean string or fallback
    clean = reason.strip()
    if len(clean) <= 28 and not any(
        x in r_low for x in ["httpconnection", "httpsconnection", "traceback", "caused by", "socket"]
    ):
        return clean

    classified = classify_harvest_error(reason)
    if classified.startswith("Network: "):
        return classified[len("Network: ") :]
    if classified.startswith("HTTP "):
        return classified
    if classified != "Unknown Error":
        return classified

    return "Connection Failure"


def analyze_harvest_errors(
    repo_dir: str | Path | None = None,
    server: str = "ALL",
) -> dict[str, Any]:
    """Inspect repository manifests (.manifest.json) and generate structured error analytics."""
    target_repo = Path(repo_dir) if repo_dir else Path.cwd()
    env_repo = (
        os.environ.get("DARTFX_CKAN_REPOSITORY_ROOT")
        or os.environ.get("DARTFX_CKAN_REPOSITORY")
        or os.environ.get("CKAN_REPOSITORY_ROOT")
        or os.environ.get("CKAN_REPOSITORY")
    )
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
        return f"[bold green]🟢⚡ {lat:.1f}s[/bold green]"
    elif lat <= 4.0:
        return f"[green]🟢 {lat:.1f}s[/green]"
    elif lat <= 8.0:
        return f"[yellow]🟡 {lat:.1f}s[/yellow]"
    else:
        return f"[bold red]🔴 {lat:.1f}s[/bold red]"


def _is_parked_or_domain_sale(orig_host: str, resp: requests.Response) -> bool:
    """Check if the response indicates the domain has expired, is parked, or is up for sale."""
    raw_url = getattr(resp, "url", None)
    if not isinstance(raw_url, str) or not raw_url:
        return False

    final_url = raw_url.lower()
    final_host = (urllib.parse.urlparse(raw_url).hostname or "").lower()

    parking_domains = [
        "hugedomains",
        "dan.com",
        "sedo.com",
        "sedoparking",
        "godaddy",
        "afternic",
        "parkingcrew",
        "bodis",
        "domainmarket",
        "namecheap",
    ]
    if any(p in final_url for p in parking_domains):
        return True

    # Check for domain mismatch on HTTP redirect
    history = getattr(resp, "history", None)
    if history and isinstance(history, list) and final_host:
        orig_clean = orig_host.lower().strip()
        orig_parts = orig_clean.split(".")
        final_parts = final_host.split(".")
        orig_base = ".".join(orig_parts[-2:]) if len(orig_parts) >= 2 else orig_clean
        final_base = ".".join(final_parts[-2:]) if len(final_parts) >= 2 else final_host
        if orig_base != final_base:
            headers = getattr(resp, "headers", {})
            ct = headers.get("content-type", "") if isinstance(headers, dict) else ""
            if "text/html" in str(ct).lower():
                raw_text = getattr(resp, "text", "")
                content_low = raw_text[:3000].lower() if isinstance(raw_text, str) else ""
                sale_keywords = [
                    "domain is for sale",
                    "buy this domain",
                    "domain has expired",
                    "parked free",
                    "domain parking",
                    "domain name may be for sale",
                    "inquire about this domain",
                ]
                if any(k in content_low for k in sale_keywords):
                    return True
                return True

    return False


def classify_server_availability(
    status: str,
    is_ckan: bool = False,
    error: str | None = None,
    requires_token: bool = False,
) -> str:
    """Classify server into tri-state availability: accessible, restricted, or offline.

    - accessible: fully operational public CKAN catalog with accessible API.
    - restricted: active server but protected by WAF/Cloudflare, perimeter blocks, or requiring API token.
    - offline: domain dead, DNS failure, 404/410 retired, timeout, or not a CKAN server.
    """
    clean_status = (status or "").lower()
    clean_error = str(error or "").lower() if error else ""

    # 1. Check for restricted states (active server, but blocked or requiring credentials)
    if requires_token or "auth required" in clean_status or "authentication" in clean_error:
        return "restricted"

    if any(
        k in clean_status or k in clean_error
        for k in [
            "waf",
            "cloudflare",
            "bot protection",
            "perimeter",
            "forbidden",
            "403",
            "geo/ip",
            "captcha",
            "ddos-guard",
            "incapsula",
            "imperva",
            "turnstile",
        ]
    ):
        return "restricted"

    # 2. Check for fully accessible operational CKAN catalog
    if is_ckan and not clean_error:
        return "accessible"

    if is_ckan and any(s in clean_status for s in ["online", "cached", "http (ssl failed)"]):
        return "accessible"

    # 3. Otherwise, server is offline, non-CKAN, retired, or hard error
    return "offline"


def get_ca_bundle_for_host(host: str, cache_dir: Path | None = None) -> str | None:
    """Return path to cached intermediate CA bundle for host if available.

    Args:
        host: Hostname or domain of the server.
        cache_dir: Optional custom directory where CA bundles are cached.

    Returns:
        str | None: String path to the bundle file, or None if not cached.
    """
    clean_host = host.split(":")[0].strip()
    target_cache = cache_dir or (Path.home() / ".cache" / "dartfx" / "ckan" / "ca_bundles")
    bundle_path = target_cache / f"{clean_host}.pem"
    if bundle_path.exists() and bundle_path.stat().st_size > 0:
        return str(bundle_path)
    return None


def resolve_aia_intermediate_ca(
    host: str,
    port: int = 443,
    timeout: int = 5,
    cache_dir: Path | None = None,
) -> Path | None:
    """Attempt Authority Information Access (AIA) intermediate CA certificate fetching.

    When a server provides an incomplete TLS certificate chain (missing intermediate CA certificate),
    standard TLS libraries fail with SSLCertVerificationError ('unable to get local issuer certificate').
    This function connects to the server with verify_mode=CERT_NONE to inspect the leaf certificate's
    DER payload, extracts the Authority Information Access (AIA) CA Issuers URI, downloads the missing
    intermediate certificate(s), and returns the path to a combined PEM CA bundle (certifi + intermediate).

    Returns:
        Path | None: Path to the combined CA bundle file if successfully created, or None if unavailable.
    """
    clean_host = host.split(":")[0].strip()
    target_cache = cache_dir or (Path.home() / ".cache" / "dartfx" / "ckan" / "ca_bundles")
    bundle_path = target_cache / f"{clean_host}.pem"

    if bundle_path.exists() and bundle_path.stat().st_size > 0:
        return bundle_path

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        with socket.create_connection((clean_host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=clean_host) as ssock:
                der_cert = ssock.getpeercert(binary_form=True)

        if not der_cert:
            return None

        # Extract AIA CA Issuers HTTP URLs (ending in .crt or .cer) from DER
        matches = re.findall(rb"https?://[^\x00-\x20\x7f-\xff]+\.(?:crt|cer)", der_cert)
        if not matches:
            return None

        import certifi

        with open(certifi.where(), encoding="utf-8") as f:
            augmented_bundle = f.read()

        urls_to_fetch = [m.decode("ascii", errors="ignore") for m in matches]
        seen_urls = set(urls_to_fetch)
        fetched_pems: list[str] = []

        while urls_to_fetch:
            url = urls_to_fetch.pop(0)
            try:
                r = requests.get(url, timeout=timeout)
                if r.status_code == 200 and r.content:
                    content = r.content
                    if b"-----BEGIN CERTIFICATE-----" in content:
                        pem_cert = content.decode("utf-8", errors="ignore")
                    else:
                        pem_cert = ssl.DER_cert_to_PEM_cert(content)
                    fetched_pems.append(pem_cert)

                    # Look for parent intermediate AIA URLs within the intermediate DER
                    parent_matches = re.findall(rb"https?://[^\x00-\x20\x7f-\xff]+\.(?:crt|cer)", content)
                    for pm in parent_matches:
                        purl = pm.decode("ascii", errors="ignore")
                        if purl not in seen_urls:
                            seen_urls.add(purl)
                            urls_to_fetch.append(purl)
            except Exception:
                continue

        if not fetched_pems:
            return None

        augmented_bundle = f"{augmented_bundle}\n" + "\n".join(fetched_pems)
        target_cache.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(augmented_bundle, encoding="utf-8")
        return bundle_path

    except Exception:
        return None


def _probe_ckan_url(
    base_url: str,
    clean_host: str,
    headers: dict[str, str],
    timeout: int,
    query: str | None = None,
    verify: str | bool | None = None,
) -> dict[str, Any]:
    """Probe a single base URL (http or https) for CKAN API endpoints."""
    res: dict[str, Any] = {
        "is_ckan": False,
        "datasets": 0,
        "organizations": 0,
        "groups": 0,
        "version": None,
        "site_title": None,
        "extensions": [],
        "requires_token": False,
        "error": None,
        "is_ssl_error": False,
        "latency_seconds": None,
    }
    t0 = time.time()
    try:
        extra_kwargs: dict[str, Any] = {"verify": verify} if verify is not None else {}

        def _probe_status() -> requests.Response:
            return requests.get(
                f"{base_url}/api/3/action/status_show",
                headers=headers,
                timeout=timeout,
                **extra_kwargs,
            )

        def _probe_search() -> requests.Response:
            search_q = urllib.parse.quote(query) if query else "*:*"
            return requests.get(
                f"{base_url}/api/3/action/package_search?q={search_q}&rows=0",
                headers=headers,
                timeout=timeout,
                **extra_kwargs,
            )

        def _probe_orgs() -> requests.Response:
            return requests.get(
                f"{base_url}/api/3/action/organization_list",
                headers=headers,
                timeout=timeout,
                **extra_kwargs,
            )

        r_status: requests.Response | None = None
        r_search: requests.Response | None = None
        r_org: requests.Response | None = None

        with ThreadPoolExecutor(max_workers=3) as probe_executor:
            f_status = probe_executor.submit(_probe_status)
            f_search = probe_executor.submit(_probe_search)
            f_orgs = probe_executor.submit(_probe_orgs)

            # 1. Probe status_show
            try:
                r_status = f_status.result()
                if _is_parked_or_domain_sale(clean_host, r_status):
                    res["error"] = "Domain For Sale"
                elif r_status.status_code == 200:
                    s_json = r_status.json()
                    status_res = s_json.get("result", {})
                    if isinstance(status_res, dict) and (
                        "ckan_version" in status_res
                        or "installed_version" in status_res
                        or "version" in status_res
                        or "site_title" in status_res
                    ):
                        res["is_ckan"] = True
                        res["version"] = (
                            status_res.get("ckan_version")
                            or status_res.get("installed_version")
                            or status_res.get("version")
                        )
                        res["site_title"] = status_res.get("site_title")
                        raw_exts = status_res.get("extensions", [])
                        if isinstance(raw_exts, list):
                            res["extensions"] = [str(e).strip() for e in raw_exts if e]
                        elif isinstance(raw_exts, str):
                            res["extensions"] = [e.strip() for e in raw_exts.split(",") if e.strip()]
                elif r_status.status_code == 401:
                    res["is_ckan"] = True
                    res["requires_token"] = True
            except (
                requests.exceptions.SSLError,
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                RuntimeError,
            ):
                raise
            except Exception:
                pass

            # 2. Probe package_search for dataset count
            if res["error"] != "Domain For Sale":
                try:
                    r_search = f_search.result()
                    if _is_parked_or_domain_sale(clean_host, r_search):
                        res["error"] = "Domain For Sale"
                        res["is_ckan"] = False
                    elif r_search.status_code == 200:
                        try:
                            s_data = r_search.json()
                            if isinstance(s_data, dict):
                                res_dict = s_data.get("result", {})
                                if isinstance(res_dict, dict):
                                    res["is_ckan"] = True
                                    res["datasets"] = res_dict.get("count", 0)
                        except Exception:
                            pass
                    elif r_search.status_code == 401:
                        res["is_ckan"] = True
                        res["requires_token"] = True
                except (
                    requests.exceptions.SSLError,
                    requests.exceptions.Timeout,
                    requests.exceptions.ConnectionError,
                    RuntimeError,
                ):
                    raise
                except Exception:
                    pass

            # 3. Probe organization_list
            if res["error"] != "Domain For Sale":
                try:
                    r_org = f_orgs.result()
                    if _is_parked_or_domain_sale(clean_host, r_org):
                        res["error"] = "Domain For Sale"
                        res["is_ckan"] = False
                    elif r_org.status_code == 200:
                        try:
                            org_data = r_org.json()
                            if isinstance(org_data, dict):
                                org_res = org_data.get("result", [])
                                if isinstance(org_res, list):
                                    res["is_ckan"] = True
                                    res["organizations"] = len(org_res)
                        except Exception:
                            pass
                except (
                    requests.exceptions.SSLError,
                    requests.exceptions.Timeout,
                    requests.exceptions.ConnectionError,
                    RuntimeError,
                ):
                    raise
                except Exception:
                    pass

        # Handle potential rate-limiting, transient server errors (503/429/500/502/504), or concurrency issues
        transient_codes = (429, 500, 502, 503, 504)
        has_transient_failure = any(
            r is not None and r.status_code in transient_codes for r in [r_status, r_search, r_org]
        )

        if (not res["is_ckan"] or has_transient_failure) and res["error"] != "Domain For Sale":
            time.sleep(0.2)
            if not res["is_ckan"] or (r_status is not None and r_status.status_code in transient_codes):
                try:
                    r_retry_status = _probe_status()
                    if r_retry_status.status_code == 200:
                        r_status = r_retry_status
                        s_json = r_status.json()
                        status_res = s_json.get("result", {})
                        if isinstance(status_res, dict) and (
                            "ckan_version" in status_res
                            or "installed_version" in status_res
                            or "version" in status_res
                            or "site_title" in status_res
                        ):
                            res["is_ckan"] = True
                            res["version"] = (
                                status_res.get("ckan_version")
                                or status_res.get("installed_version")
                                or status_res.get("version")
                            )
                            res["site_title"] = status_res.get("site_title")
                            raw_exts = status_res.get("extensions", [])
                            if isinstance(raw_exts, list):
                                res["extensions"] = [str(e).strip() for e in raw_exts if e]
                            elif isinstance(raw_exts, str):
                                res["extensions"] = [e.strip() for e in raw_exts.split(",") if e.strip()]
                    elif r_retry_status.status_code == 401:
                        res["is_ckan"] = True
                        res["requires_token"] = True
                except Exception:
                    pass

            if (not res["is_ckan"] or res.get("datasets") == 0) and (
                r_search is not None and r_search.status_code in transient_codes
            ):
                try:
                    time.sleep(0.1)
                    r_retry_search = _probe_search()
                    if r_retry_search.status_code == 200:
                        r_search = r_retry_search
                        s_data = r_search.json()
                        if isinstance(s_data, dict):
                            res_dict = s_data.get("result", {})
                            if isinstance(res_dict, dict):
                                res["is_ckan"] = True
                                res["datasets"] = res_dict.get("count", 0)
                    elif r_retry_search.status_code == 401:
                        res["is_ckan"] = True
                        res["requires_token"] = True
                except Exception:
                    pass

        # Organization list fallback: support CKAN deployments requiring POST method
        if (
            (r_org is not None and (r_org.status_code in (400, 405) or r_org.status_code in transient_codes))
            or (res["is_ckan"] and res.get("organizations") == 0)
        ) and res["error"] != "Domain For Sale":
            try:
                post_headers = dict(headers)
                post_headers["Content-Type"] = "application/json"
                r_post_org = requests.post(
                    f"{base_url}/api/3/action/organization_list",
                    headers=post_headers,
                    json={},
                    timeout=timeout,
                    **extra_kwargs,
                )
                if r_post_org.status_code == 200:
                    r_org = r_post_org
                    org_data = r_post_org.json()
                    if isinstance(org_data, dict):
                        org_res = org_data.get("result", [])
                        if isinstance(org_res, list):
                            res["is_ckan"] = True
                            res["organizations"] = len(org_res)
            except Exception:
                pass

        # If not CKAN and any probe returned 403 (WAF / anti-bot), retry with standard browser User-Agent
        if not res["is_ckan"] and any(r is not None and r.status_code == 403 for r in [r_search, r_status, r_org]):
            try:
                browser_h = dict(headers)
                browser_h["User-Agent"] = (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
                search_q = urllib.parse.quote(query) if query else "*:*"
                r_b_search = requests.get(
                    f"{base_url}/api/3/action/package_search?q={search_q}&rows=0",
                    headers=browser_h,
                    timeout=timeout,
                    **extra_kwargs,
                )
                if r_b_search.status_code == 200:
                    res["is_ckan"] = True
                    res["error"] = None
                    try:
                        res["datasets"] = r_b_search.json().get("result", {}).get("count", 0)
                    except Exception:
                        pass
                    try:
                        r_b_status = requests.get(
                            f"{base_url}/api/3/action/status_show",
                            headers=browser_h,
                            timeout=timeout,
                            **extra_kwargs,
                        )
                        if r_b_status.status_code == 200:
                            s_res = r_b_status.json().get("result", {})
                            res["version"] = (
                                s_res.get("ckan_version") or s_res.get("installed_version") or s_res.get("version")
                            )
                            res["site_title"] = s_res.get("site_title")
                    except Exception:
                        pass
                    try:
                        r_b_org = requests.get(
                            f"{base_url}/api/3/action/organization_list",
                            headers=browser_h,
                            timeout=timeout,
                            **extra_kwargs,
                        )
                        if r_b_org.status_code == 200:
                            res["organizations"] = len(r_b_org.json().get("result", []))
                    except Exception:
                        pass
            except Exception:
                pass

        # Fallback version detection from HTML homepage if status_show was missing version
        if res["is_ckan"] and not res.get("version"):
            try:
                r_home = requests.get(base_url, headers=headers, timeout=min(timeout, 3), **extra_kwargs)
                if r_home.status_code == 200 and r_home.text:
                    m = re.search(r"CKAN[\s/]+v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)", r_home.text, re.I)
                    if m:
                        res["version"] = m.group(1)
            except Exception:
                pass

        # If not CKAN and no error yet, check status codes and bot protection signatures
        if not res["is_ckan"] and not res["error"]:
            for r_probe in [r_search, r_status, r_org]:
                if r_probe is not None:
                    p_text = r_probe.text.lower() if r_probe.text else ""
                    if any(
                        k in p_text
                        for k in [
                            "cloudflare",
                            "just a moment",
                            "challenge-platform",
                            "waf",
                            "ddos-guard",
                            "making sure you're not a bot",
                            "pardon our interruption",
                            "bot detection",
                            "anubis",
                        ]
                    ):
                        res["error"] = "Bot Protection (WAF)"
                        break
                    elif r_probe.status_code == 403:
                        res["error"] = "Forbidden (403)"
                        break
                    elif r_probe.status_code == 429:
                        res["error"] = "Rate Limited (429)"
                        break
                    elif r_probe.status_code == 503:
                        res["error"] = "Service Unavailable (503)"
                        break
                    elif r_probe.status_code == 502:
                        res["error"] = "Bad Gateway (502)"
                        break
                    elif r_probe.status_code == 504:
                        res["error"] = "Gateway Timeout (504)"
                        break
                    elif r_probe.status_code == 500:
                        res["error"] = "Server Error (500)"
                        break
                    elif r_probe.status_code >= 500:
                        res["error"] = f"Server Error ({r_probe.status_code})"
                        break
            if not res["error"]:
                res["error"] = "Not a CKAN server"

        res["latency_seconds"] = round(time.time() - t0, 2)

    except RuntimeError as re_err:
        if "interpreter shutdown" in str(re_err).lower():
            res["error"] = "Interrupted"
            return res
        raise
    except requests.exceptions.SSLError as ssl_err:
        res["latency_seconds"] = round(time.time() - t0, 2)
        res["error"] = abbreviate_error(str(ssl_err))
        res["raw_ssl_error"] = str(ssl_err)
        res["is_ssl_error"] = True
    except requests.exceptions.Timeout:
        res["latency_seconds"] = round(time.time() - t0, 2)
        res["error"] = f"Timeout ({timeout}s)"
    except Exception as e:
        res["latency_seconds"] = round(time.time() - t0, 2)
        err_str = str(e)
        if "interpreter shutdown" in err_str.lower():
            res["error"] = "Interrupted"
            return res
        abbr = abbreviate_error(err_str)
        res["error"] = abbr
        res["raw_ssl_error"] = err_str
        res["is_ssl_error"] = (
            abbr.startswith("SSL ") or "ssl" in err_str.lower() or isinstance(e, requests.exceptions.SSLError)
        )

    if res["is_ckan"]:
        exts_set = {str(e).strip().lower() for e in res.get("extensions", []) if e}
        res["has_dcat"] = any("dcat" in e for e in exts_set)
        res["has_schemaorg"] = any("structured_data" in e or "dcat" in e for e in exts_set)
        res["has_croissant"] = any("croissant" in e for e in exts_set)
        res["has_ddi"] = any("ddi" in e for e in exts_set)
    else:
        res["has_dcat"] = False
        res["has_schemaorg"] = False
        res["has_croissant"] = False
        res["has_ddi"] = False

    return res


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
    is_explicit_http = host.lower().startswith("http://")
    stripped_host = host.replace("https://", "").replace("http://", "").strip("/")
    if "/" in stripped_host:
        clean_host, subpath_part = stripped_host.split("/", 1)
        subpath = "/" + subpath_part.rstrip("/")
    else:
        clean_host = stripped_host
        subpath = ""
    headers = get_request_headers(host=clean_host, api_token=api_token, repo_root=repo_root)

    env_repo = (
        os.environ.get("DARTFX_CKAN_REPOSITORY_ROOT")
        or os.environ.get("DARTFX_CKAN_REPOSITORY")
        or os.environ.get("CKAN_REPOSITORY_ROOT")
        or os.environ.get("CKAN_REPOSITORY")
    )
    target_repo = repo_root or (Path(env_repo) if env_repo else (Path.cwd() / ".cache"))
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
                        cached_err = str(cdata.get("error") or "").lower()
                        if "interpreter shutdown" not in cached_err and "interrupted" not in cached_err:
                            cdata["cached"] = True
                            if cdata.get("has_dcat") is None:
                                c_exts = {str(e).strip().lower() for e in cdata.get("extensions", []) if e}
                                cdata["has_dcat"] = any("dcat" in e for e in c_exts)
                                cdata["has_schemaorg"] = any("structured_data" in e or "dcat" in e for e in c_exts)
                                cdata["has_croissant"] = any("croissant" in e for e in c_exts)
                                cdata["has_ddi"] = any("ddi" in e for e in c_exts)
                            return cdata
        except Exception:
            pass

    primary_scheme = "http" if is_explicit_http else "https"
    primary_url = f"{primary_scheme}://{clean_host}{subpath}"

    cached_bundle = get_ca_bundle_for_host(clean_host) if primary_scheme == "https" else None
    stats = _probe_ckan_url(primary_url, clean_host, headers, timeout, query=query, verify=cached_bundle)
    # If root returned not CKAN and no subpath was requested, check common /data subpath
    if not stats.get("is_ckan") and not subpath and not stats.get("is_ssl_error"):
        sub_url = f"{primary_scheme}://{clean_host}/data"
        sub_stats = _probe_ckan_url(
            sub_url, clean_host, headers, timeout=min(timeout, 5), query=query, verify=cached_bundle
        )
        if sub_stats.get("is_ckan"):
            stats = sub_stats
            stats["subpath"] = "/data"

    stats["server"] = clean_host
    stats["scheme"] = primary_scheme
    if cached_bundle and stats.get("is_ckan"):
        stats["aia_repaired"] = True
        stats["ca_bundle"] = cached_bundle

    # Enhancement 1: If server is on HTTP, check if HTTPS is available and recommend switching if fully functional
    if primary_scheme == "http" and stats.get("is_ckan"):
        try:
            https_url = f"https://{clean_host}"
            https_stats = _probe_ckan_url(https_url, clean_host, headers, timeout=min(5, timeout), query=query)
            if https_stats.get("is_ckan") and not https_stats.get("is_ssl_error") and not https_stats.get("error"):
                stats["https_available"] = True
                stats["https_upgrade_recommended"] = True
        except Exception:
            pass

    # Enhancement 2: If primary was HTTPS and SSL failed, attempt AIA intermediate CA chasing
    if primary_scheme == "https" and stats.get("is_ssl_error"):
        err_str = str(stats.get("raw_ssl_error") or stats.get("error") or "")
        if (
            "unable to get local issuer certificate" in err_str
            or "Incomplete Chain" in str(stats.get("error"))
            or "missing intermediate" in err_str.lower()
        ):
            try:
                aia_bundle = resolve_aia_intermediate_ca(clean_host, port=443, timeout=min(5, timeout))
                if aia_bundle:
                    aia_stats = _probe_ckan_url(
                        primary_url,
                        clean_host,
                        headers,
                        timeout=timeout,
                        query=query,
                        verify=str(aia_bundle),
                    )
                    if aia_stats.get("is_ckan"):
                        stats["is_ckan"] = True
                        stats["datasets"] = aia_stats.get("datasets", 0)
                        stats["organizations"] = aia_stats.get("organizations", 0)
                        stats["groups"] = aia_stats.get("groups", 0)
                        stats["version"] = aia_stats.get("version")
                        stats["site_title"] = aia_stats.get("site_title")
                        stats["requires_token"] = aia_stats.get("requires_token", False)
                        stats["aia_repaired"] = True
                        stats["ca_bundle"] = str(aia_bundle)
                        stats["is_ssl_error"] = False
                        stats["ssl_error"] = None
                        stats["error"] = None
                        stats["scheme"] = "https"
            except Exception:
                pass

    # Enhancement 3: If primary was HTTPS and SSL failed (and not repaired by AIA), check if we can fall back to HTTP
    if primary_scheme == "https" and not stats.get("is_ckan") and stats.get("is_ssl_error"):
        try:
            http_url = f"http://{clean_host}{subpath}"
            http_stats = _probe_ckan_url(http_url, clean_host, headers, timeout=timeout, query=query)
            if http_stats.get("is_ckan"):
                stats["is_ckan"] = True
                stats["datasets"] = http_stats.get("datasets", 0)
                stats["organizations"] = http_stats.get("organizations", 0)
                stats["groups"] = http_stats.get("groups", 0)
                stats["version"] = http_stats.get("version")
                stats["site_title"] = http_stats.get("site_title")
                stats["requires_token"] = http_stats.get("requires_token", False)
                stats["http_fallback"] = True
                stats["ssl_error"] = stats.get("error")
                stats["error"] = None
                stats["scheme"] = "http"
        except Exception:
            pass

    # Cache results (never cache transient shutdown or interruption errors)
    err_str = str(stats.get("error") or "").lower()
    if "interpreter shutdown" in err_str or "interrupted" in err_str:
        return stats

    if stats.get("is_ckan"):
        if stats.get("has_dcat") is None or not stats.get("extensions"):
            exts_set = {str(e).strip().lower() for e in stats.get("extensions", []) if e}
            if not exts_set:
                known_exts = fetch_server_extensions(clean_host, repo_root=repo_root)
                if known_exts:
                    stats["extensions"] = sorted(known_exts)
                    exts_set = known_exts
            stats["has_dcat"] = any("dcat" in e for e in exts_set)
            stats["has_schemaorg"] = any("structured_data" in e or "dcat" in e for e in exts_set)
            stats["has_croissant"] = any("croissant" in e for e in exts_set)
            stats["has_ddi"] = any("ddi" in e for e in exts_set)
    else:
        stats["has_dcat"] = False
        stats["has_schemaorg"] = False
        stats["has_croissant"] = False
        stats["has_ddi"] = False

    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        stats_to_save = dict(stats)
        stats_to_save["cached_at"] = datetime.now(UTC).isoformat()
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(stats_to_save, f, indent=2)
    except Exception:
        pass

    return stats


def fetch_server_extensions(
    host: str,
    verbose: bool = False,
    api_token: str | None = None,
    repo_root: Path | None = None,
    timeout: int = 10,
) -> set[str] | None:
    """Query CKAN status_show or ecosystem directory to discover deployed extensions.

    Returns a set of lowercase extension identifiers, or None if extensions cannot be determined.
    """
    clean_host = host.replace("https://", "").replace("http://", "").split("/")[0]

    # 1. Check stats cache if available
    env_repo = (
        os.environ.get("DARTFX_CKAN_REPOSITORY_ROOT")
        or os.environ.get("DARTFX_CKAN_REPOSITORY")
        or os.environ.get("CKAN_REPOSITORY_ROOT")
        or os.environ.get("CKAN_REPOSITORY")
    )
    target_repo = repo_root or (Path(env_repo) if env_repo else (Path.cwd() / ".cache"))
    cache_file = target_repo / clean_host / ".stats_cache.json"
    if cache_file.exists():
        try:
            with open(cache_file, encoding="utf-8") as f:
                cdata = json.load(f)
                cached_exts = cdata.get("extensions")
                if isinstance(cached_exts, list) and cached_exts:
                    exts = {str(e).strip().lower() for e in cached_exts if e}
                    if verbose:
                        console.print(
                            f"[dim]  [API] Cached extensions for {clean_host}: {', '.join(sorted(exts))}[/dim]"
                        )
                    return exts
        except Exception:
            pass

    # 2. Probe status_show
    base_host = f"https://{clean_host}" if not host.startswith("http") else host
    url = f"{base_host}/api/3/action/status_show"
    headers = get_request_headers(host=clean_host, api_token=api_token, repo_root=repo_root)

    verify: str | bool = True
    cached_bundle = get_ca_bundle_for_host(clean_host)
    if cached_bundle:
        verify = cached_bundle

    try:
        r = requests.get(url, headers=headers, timeout=timeout, verify=verify)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and data.get("success"):
                result = data.get("result", {})
                if isinstance(result, dict):
                    raw_exts = result.get("extensions", [])
                    if isinstance(raw_exts, list) and raw_exts:
                        exts = {str(e).strip().lower() for e in raw_exts if e}
                        if verbose:
                            console.print(
                                f"[dim]  [API] Discovered extensions on {clean_host}: {', '.join(sorted(exts))}[/dim]"
                            )
                        return exts
                    elif isinstance(raw_exts, str) and raw_exts:
                        exts = {e.strip().lower() for e in raw_exts.split(",") if e.strip()}
                        if verbose:
                            console.print(
                                f"[dim]  [API] Discovered extensions on {clean_host}: {', '.join(sorted(exts))}[/dim]"
                            )
                        return exts
    except Exception as e:
        if verbose:
            console.print(f"[dim]  [API] Failed probing status_show extensions on {clean_host}: {e}[/dim]")

    # 3. Fallback to ecosystem installation directory
    try:
        installations = fetch_ckan_installations()
        for inst in installations:
            if inst.clean_hostname == clean_host or inst.url == host:
                if isinstance(inst.extensions, list) and inst.extensions:
                    exts = {str(e).strip().lower() for e in inst.extensions if e}
                    if verbose:
                        console.print(
                            f"[dim]  [Ecosystem] Known extensions for {clean_host}: {', '.join(sorted(exts))}[/dim]"
                        )
                    return exts
                elif isinstance(inst.extensions, str) and inst.extensions:
                    exts = {e.strip().lower() for e in inst.extensions.split(",") if e.strip()}
                    if verbose:
                        console.print(
                            f"[dim]  [Ecosystem] Known extensions for {clean_host}: {', '.join(sorted(exts))}[/dim]"
                        )
                    return exts
                break
    except Exception:
        pass

    return None


def is_format_supported_on_server(
    fmt: str,
    server_extensions: set[str] | None,
    host: str | None = None,  # noqa: ARG001
) -> bool:
    """Check if a metadata format is supported based on server's deployed extensions.

    Returns True if format is supported, or if server capabilities are unknown (fallback to runtime).
    """
    fmt_clean = fmt.strip().lower()
    req_ext = FORMAT_EXTENSION_REQUIREMENTS.get(fmt_clean)
    if req_ext is None:
        return True

    if server_extensions is None:
        return True

    if fmt_clean in ("schemaorg", "schema", "schema.org"):
        return any("structured_data" in ext or "dcat" in ext for ext in server_extensions)
    if fmt_clean in ("croissant", "mlcroissant"):
        return any("croissant" in ext for ext in server_extensions)
    if fmt_clean in ("ddi", "ddi-xml"):
        return any("ddi" in ext for ext in server_extensions)

    target = req_ext.lower().replace("ckanext-", "").replace("ckanext_", "")
    return any(target in ext for ext in server_extensions)


def display_server_stats(
    server: str = "ALL",
    country: str | None = None,
    query: str | None = None,
    api_token: str | None = None,
    refresh_cache: bool = False,
    cache_ttl_hours: float = 24.0,
    timeout: int = 10,
    repo_root: Path | None = None,
    workers: int = 8,
    installations: list[ServerInstallation] | None = None,
    console: Console | None = None,
    sort_by: str = "name",
    descending: bool | None = None,
    format: str = "table",
    output: str | Path | None = None,
    dcat: bool = False,
    schemaorg: bool = False,
    croissant: bool = False,
    ddi: bool = False,
) -> list[dict[str, Any]]:
    """Display live dataset and organization counts for CKAN servers."""
    target_console = console or Console()
    clean_fmt = (format or "table").strip().lower()

    out_path: Path | None = None
    if output:
        out_str = str(output).strip()
        if out_str.lower() in ("auto", "__auto__", "-"):
            ext_map = {
                "json": "json",
                "markdown": "md",
                "md": "md",
                "csv": "csv",
                "table": "txt",
            }
            ext = ext_map.get(clean_fmt, "txt")
            out_path = Path(f"dartfx-ckan.stats.{ext}")
        else:
            out_path = Path(out_str)
        out_path.parent.mkdir(parents=True, exist_ok=True)

    if installations is None:
        installations = fetch_ckan_installations(
            target_server=None if server.upper() == "ALL" else server,
            country=country,
            fallback_unlisted=True,
        )

    if not installations:
        if out_path:
            if clean_fmt == "json":
                out_path.write_text("[]\n", encoding="utf-8")
            elif clean_fmt in ("markdown", "md"):
                out_path.write_text("No CKAN servers found.\n", encoding="utf-8")
            elif clean_fmt == "csv":
                out_path.write_text("", encoding="utf-8")
            else:
                out_path.write_text(f"No CKAN servers found matching filter '{server}'.\n", encoding="utf-8")
            target_console.print(f"[bold green]✓ Statistics saved to:[/] {out_path}")
        else:
            if clean_fmt == "json":
                target_console.print("[]")
            elif clean_fmt in ("markdown", "md"):
                target_console.print("No CKAN servers found.")
            elif clean_fmt == "table":
                target_console.print(f"[bold red]No CKAN servers found matching filter '{server}'.[/bold red]")
        return []

    def _query_stat(inst: ServerInstallation) -> tuple[ServerInstallation, dict[str, Any]]:
        host_to_query = inst.url if inst.url else (inst.clean_hostname or "")
        s = fetch_server_stats(
            host=host_to_query,
            query=query,
            api_token=api_token,
            timeout=timeout,
            repo_root=repo_root,
            refresh_cache=refresh_cache,
            cache_ttl_hours=cache_ttl_hours,
        )
        return inst, s

    stat_results: list[tuple[ServerInstallation, dict[str, Any]]] = []

    stderr_console = Console(stderr=True)
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold green]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        TextColumn("[dim]{task.fields[server]}[/dim]"),
        console=stderr_console,
        transient=True,
    )

    max_workers = max(1, min(workers, len(installations)))
    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        with progress:
            task_id = progress.add_task("Querying CKAN servers...", total=len(installations), server="")
            futures = [executor.submit(_query_stat, inst) for inst in installations]
            for future in as_completed(futures):
                inst, stat = future.result()
                if stat.get("error") == "Interrupted":
                    continue
                stat_results.append((inst, stat))
                progress.update(task_id, advance=1, server=inst.clean_hostname or "")
    except (KeyboardInterrupt, SystemExit):
        executor.shutdown(wait=False, cancel_futures=True)
        target_console.print("\n[yellow]Querying cancelled by user (Ctrl-C).[/yellow]")
        return []
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    if dcat:
        stat_results = [item for item in stat_results if item[1].get("has_dcat")]
    if schemaorg:
        stat_results = [item for item in stat_results if item[1].get("has_schemaorg")]
    if croissant:
        stat_results = [item for item in stat_results if item[1].get("has_croissant")]
    if ddi:
        stat_results = [item for item in stat_results if item[1].get("has_ddi")]

    def _format_count(val: Any) -> str:
        if val is None or val == "-":
            return "-"
        if isinstance(val, int | float):
            return f"{int(val):,}"
        if isinstance(val, str):
            clean = val.replace(",", "").strip()
            if clean.isdigit():
                return f"{int(clean):,}"
            return val
        return str(val)

    clean_sort = (sort_by or "name").strip().lower()
    if descending is not None:
        reverse_sort = descending
    elif clean_sort in ("datasets", "dataset", "count", "organizations", "orgs"):
        reverse_sort = True
    else:
        reverse_sort = False

    def _sort_key(item: tuple[ServerInstallation, dict[str, Any]]) -> Any:
        inst, stat = item
        if clean_sort in ("name", "server"):
            return (inst.name or inst.clean_hostname or "").lower()
        elif clean_sort in ("country", "cc"):
            return (inst.country_code or "ZZ").lower()
        elif clean_sort in ("datasets", "dataset", "count"):
            try:
                return int(stat.get("datasets") or 0)
            except (ValueError, TypeError):
                return 0
        elif clean_sort in ("organizations", "orgs"):
            try:
                return int(stat.get("organizations") or 0)
            except (ValueError, TypeError):
                return 0
        elif clean_sort in ("latency", "lat", "time"):
            lat = stat.get("latency_seconds")
            return float(lat) if lat is not None else 9999.0
        elif clean_sort in ("status", "state"):
            return str(stat.get("error") or "online").lower()
        return (inst.name or inst.clean_hostname or "").lower()

    stat_results.sort(key=_sort_key, reverse=reverse_sort)

    records: list[dict[str, Any]] = []
    for inst, stat in stat_results:
        is_err = bool(stat.get("error"))
        is_ckan = bool(stat.get("is_ckan"))
        req_tok = bool(stat.get("requires_token"))
        lat = stat.get("latency_seconds")

        if not is_ckan:
            if stat.get("error"):
                plain_status = abbreviate_error(str(stat["error"]))
            else:
                plain_status = "Not CKAN Server"
        elif stat.get("aia_repaired"):
            plain_status = "Online (AIA Fixed)"
        elif stat.get("http_fallback"):
            plain_status = "HTTP (SSL Failed)"
        elif stat.get("https_upgrade_recommended"):
            plain_status = "Online (HTTPS Avail)"
        elif req_tok:
            plain_status = "Auth Required"
        elif stat.get("cached"):
            plain_status = "Online (Cached)"
        else:
            plain_status = "Online"

        live_v = format_version(stat.get("version")) if is_ckan and stat.get("version") else "-"
        cat_v = format_version(inst.version)

        raw_datasets = stat.get("datasets") if is_ckan else None
        if raw_datasets is not None:
            try:
                datasets_int: int | None = int(str(raw_datasets).replace(",", "").strip())
            except (ValueError, TypeError):
                datasets_int = None
        else:
            datasets_int = None

        raw_orgs = stat.get("organizations") if is_ckan else None
        if raw_orgs is not None:
            try:
                orgs_int: int | None = int(str(raw_orgs).replace(",", "").strip())
            except (ValueError, TypeError):
                orgs_int = None
        else:
            orgs_int = None

        availability = classify_server_availability(
            status=plain_status,
            is_ckan=is_ckan,
            error=stat.get("error"),
            requires_token=req_tok,
        )

        record: dict[str, Any] = {
            "name": inst.name or inst.clean_hostname,
            "url": inst.url,
            "hostname": inst.clean_hostname,
            "country": inst.country,
            "country_code": inst.country_code,
            "live_version": live_v if live_v != "-" else None,
            "dataset_version": cat_v if cat_v != "-" else None,
            "datasets": datasets_int,
            "organizations": orgs_int,
            "has_dcat": bool(stat.get("has_dcat")) if is_ckan else False,
            "has_schemaorg": bool(stat.get("has_schemaorg")) if is_ckan else False,
            "has_croissant": bool(stat.get("has_croissant")) if is_ckan else False,
            "has_ddi": bool(stat.get("has_ddi")) if is_ckan else False,
            "formats": [
                fmt
                for fmt, active in [
                    ("dcat", stat.get("has_dcat")),
                    ("schemaorg", stat.get("has_schemaorg")),
                    ("croissant", stat.get("has_croissant")),
                    ("ddi", stat.get("has_ddi")),
                ]
                if active
            ]
            if is_ckan
            else [],
            "latency_seconds": lat,
            "status": plain_status,
            "availability": availability,
            "is_ckan": is_ckan,
            "cached": bool(stat.get("cached")),
            "aia_repaired": bool(stat.get("aia_repaired")),
            "error": stat.get("error"),
        }
        records.append(record)

    if clean_fmt == "json":
        if out_path:
            out_path.write_text(json.dumps(records, indent=2, default=str) + "\n", encoding="utf-8")
            target_console.print(f"[bold green]✓ Statistics saved to:[/] {out_path}")
        else:
            target_console.print_json(json.dumps(records, default=str))
        return records

    if clean_fmt in ("markdown", "md"):
        md_lines: list[str] = [
            (
                "| Repository / Server | Country | Live Ver | Dataset Ver | "
                "Datasets | Organizations | Formats | Latency | Status |"
            ),
            "|:---|:---:|:---:|:---:|---:|---:|:---:|:---:|:---|",
        ]
        for r, (_inst, stat) in zip(records, stat_results, strict=False):
            name_disp = (r["name"] or "").replace("|", "\\|")
            link_url = r["url"]
            repo_cell = f"[{name_disp}]({link_url})" if link_url else name_disp
            cc_cell = r["country_code"] or "-"
            live_cell = r["live_version"] or "-"
            cat_cell = r["dataset_version"] or "-"
            datasets_cell = f"{r['datasets']:,}" if r["datasets"] is not None else "-"
            orgs_cell = f"{r['organizations']:,}" if r["organizations"] is not None else "-"
            fmts_cell = ", ".join(r["formats"]) if r["formats"] else "-"
            lat_badge = format_response_latency(
                r["latency_seconds"],
                is_online=r["is_ckan"],
                requires_token=bool(stat.get("requires_token")),
                is_error=bool(stat.get("error")),
            )
            lat_cell = Text.from_markup(lat_badge).plain
            status_cell = r["status"]
            md_row = (
                f"| {repo_cell} | {cc_cell} | {live_cell} | {cat_cell} "
                f"| {datasets_cell} | {orgs_cell} | {fmts_cell} | {lat_cell} | {status_cell} |"
            )
            md_lines.append(md_row)

        if len(records) > 1:
            accessible_count = sum(1 for r in records if r.get("availability") == "accessible")
            restricted_count = sum(1 for r in records if r.get("availability") == "restricted")
            offline_count = sum(1 for r in records if r.get("availability") == "offline")
            total_datasets = sum(int(r.get("datasets") or 0) for r in records if r.get("is_ckan"))
            md_lines.append("")
            md_lines.append(
                f"_Summary: {accessible_count} accessible • {restricted_count} restricted • "
                f"{offline_count} offline/inactive ({len(records)} servers) • "
                f"{total_datasets:,} total datasets indexed._"
            )

        if out_path:
            out_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
            target_console.print(f"[bold green]✓ Statistics saved to:[/] {out_path}")
        else:
            print("\n".join(md_lines))
        return records

    if clean_fmt == "csv":
        fieldnames = [
            "name",
            "url",
            "hostname",
            "country",
            "country_code",
            "live_version",
            "dataset_version",
            "datasets",
            "organizations",
            "formats",
            "has_dcat",
            "has_schemaorg",
            "has_croissant",
            "has_ddi",
            "latency_seconds",
            "status",
            "availability",
        ]
        if out_path:
            with open(out_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for r in records:
                    row_dict = dict(r)
                    if isinstance(row_dict.get("formats"), list):
                        row_dict["formats"] = ", ".join(row_dict["formats"])
                    writer.writerow(row_dict)
            target_console.print(f"[bold green]✓ Statistics saved to:[/] {out_path}")
        else:
            writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in records:
                row_dict = dict(r)
                if isinstance(row_dict.get("formats"), list):
                    row_dict["formats"] = ", ".join(row_dict["formats"])
                writer.writerow(row_dict)
        return records

    # Default: Rich Table
    table = Table(
        title=f"CKAN Server Statistics ({len(installations)} servers)",
        header_style="bold cyan",
        show_header=True,
    )
    table.add_column("Server", style="cyan", no_wrap=True)
    table.add_column("Country", style="green", justify="center")
    table.add_column("Live Ver", justify="center", no_wrap=True)
    table.add_column("Dataset Ver", justify="center", no_wrap=True)
    table.add_column("Datasets", justify="right", style="cyan")
    table.add_column("Organizations", justify="right", style="yellow")
    table.add_column("Formats", justify="center")
    table.add_column("Latency", justify="center")
    table.add_column("Status", justify="left")

    if len(records) > 1:
        accessible_count = sum(1 for r in records if r.get("availability") == "accessible")
        restricted_count = sum(1 for r in records if r.get("availability") == "restricted")
        offline_count = sum(1 for r in records if r.get("availability") == "offline")
        total_datasets = sum(int(r.get("datasets") or 0) for r in records if r.get("is_ckan"))
        dcat_count = sum(1 for r in records if r.get("has_dcat"))
        schema_count = sum(1 for r in records if r.get("has_schemaorg"))
        croissant_count = sum(1 for r in records if r.get("has_croissant"))
        ddi_count = sum(1 for r in records if r.get("has_ddi"))
        table.caption = (
            f"[bold]Total:[/] [green]{accessible_count}[/green] accessible"
            f" • [yellow]{restricted_count}[/yellow] restricted"
            f" • [red]{offline_count}[/red] offline/inactive"
            f" ({len(records)} servers)"
            f" • [cyan]{total_datasets:,}[/cyan] datasets indexed\n"
            f"[dim]Capabilities:[/] [blue]{dcat_count}[/blue] DCAT"
            f" • [cyan]{schema_count}[/cyan] Schema.org"
            f" • [magenta]{croissant_count}[/magenta] Croissant"
            f" • [green]{ddi_count}[/green] DDI"
        )

    for _r, (inst, stat) in zip(records, stat_results, strict=False):
        server_disp = inst.clean_hostname or inst.name or "N/A"
        home_url = inst.url
        if stat.get("http_fallback") and home_url and home_url.startswith("https://"):
            home_url = "http://" + home_url[len("https://") :]
        elif stat.get("https_available") and home_url and home_url.startswith("http://"):
            home_url = "https://" + home_url[len("http://") :]

        clickable_host = f"[link={home_url}]{server_disp}[/link]" if home_url else server_disp
        cc = inst.country_code or "-"
        is_ckan = bool(stat.get("is_ckan"))
        live_v = format_version(stat.get("version")) if is_ckan and stat.get("version") else "-"
        cat_v = format_version(inst.version)

        if live_v != "-" and cat_v != "-":
            if live_v == cat_v:
                live_disp = f"[green]{live_v}[/green]"
                cat_disp = f"[dim]{cat_v}[/dim]"
            else:
                live_disp = f"[bold cyan]{live_v}[/bold cyan]"
                cat_disp = f"[yellow]{cat_v}[/yellow]"
        elif live_v != "-":
            live_disp = f"[green]{live_v}[/green]"
            cat_disp = "[dim]-[/dim]"
        else:
            live_disp = "[dim]-[/dim]"
            cat_disp = f"[dim]{cat_v}[/dim]" if cat_v != "-" else "[dim]-[/dim]"

        datasets_disp = _format_count(stat.get("datasets", 0)) if is_ckan else "-"
        orgs_disp = _format_count(stat.get("organizations", 0)) if is_ckan else "-"

        fmt_badges = []
        if is_ckan:
            if stat.get("has_dcat"):
                fmt_badges.append("[blue]DCAT[/blue]")
            if stat.get("has_schemaorg"):
                fmt_badges.append("[cyan]Schema[/cyan]")
            if stat.get("has_croissant"):
                fmt_badges.append("[magenta]Croissant[/magenta]")
            if stat.get("has_ddi"):
                fmt_badges.append("[green]DDI[/green]")
        formats_disp = " ".join(fmt_badges) if fmt_badges else "[dim]-[/dim]"

        lat = stat.get("latency_seconds")
        is_err = bool(stat.get("error"))
        req_tok = bool(stat.get("requires_token"))

        lat_badge = format_response_latency(lat, is_online=is_ckan, requires_token=req_tok, is_error=is_err)

        if not is_ckan:
            if stat.get("error"):
                abbr = abbreviate_error(str(stat["error"]))
                abbr_low = abbr.lower()
                if any(k in abbr_low for k in ["waf", "cloudflare", "perimeter", "auth", "token"]):
                    status_text = f"[yellow]{abbr}[/yellow]"
                elif any(k in abbr_low for k in ["retired", "for sale"]):
                    status_text = f"[magenta]{abbr}[/magenta]"
                elif "not ckan" in abbr_low or "not found" in abbr_low:
                    status_text = f"[dim red]{abbr}[/dim red]"
                else:
                    status_text = f"[red]{abbr}[/red]"
            else:
                status_text = "[red]Not CKAN Server[/red]"
        elif stat.get("aia_repaired"):
            status_text = "[cyan]Online (AIA Fixed)[/cyan]"
        elif stat.get("http_fallback"):
            status_text = "[yellow]HTTP (SSL Failed)[/yellow]"
        elif stat.get("https_upgrade_recommended"):
            status_text = "[cyan]Online (HTTPS Avail)[/cyan]"
        elif req_tok:
            status_text = "[yellow]Auth Required[/yellow]"
        elif stat.get("cached"):
            status_text = "[dim cyan]Online (Cached)[/dim cyan]"
        else:
            status_text = "[green]Online[/green]"

        table.add_row(
            clickable_host, cc, live_disp, cat_disp, datasets_disp, orgs_disp, formats_disp, lat_badge, status_text
        )

    if out_path:
        buf = io.StringIO()
        file_console = Console(file=buf, color_system=None, width=120)
        file_console.print(table)
        plain_text = buf.getvalue()
        out_path.write_text(plain_text, encoding="utf-8")
        target_console.print(f"[bold green]✓ Statistics saved to:[/] {out_path}")
    else:
        target_console.print(table)

    return records


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
    elif fmt in ("schemaorg", "schema", "schema.org"):
        url = f"{base_url}/dataset/{encoded_id}.jsonld?profiles=schemaorg"
        ext = ".schemaorg.jsonld"
    elif fmt in ("croissant", "mlcroissant"):
        url = f"{base_url}/dataset/{encoded_id}/croissant.jsonld"
        ext = ".croissant.jsonld"
    elif fmt in ("ddi", "ddi-xml"):
        url = f"{base_url}/api/3/action/package_show?id={encoded_id}"
        ext = ".ddi.xml"
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

            if fmt in ("ddi", "ddi-xml"):
                try:
                    payload = r.json().get("result", {})
                    resources_list = payload.get("resources", [])
                    ddi_res = None
                    for res in resources_list:
                        fmt_res = str(res.get("format", "")).lower()
                        mimetype = str(res.get("mimetype", "")).lower()
                        url_res = str(res.get("url", "")).lower()
                        if (
                            "ddi" in fmt_res
                            or "ddi" in url_res
                            or (fmt_res == "xml" and "ddi" in str(res.get("description", "")).lower())
                            or "ddi" in mimetype
                        ):
                            ddi_res = res
                            break
                    if not ddi_res:
                        for res in resources_list:
                            if str(res.get("format", "")).lower() == "xml" or str(res.get("url", "")).lower().endswith(
                                ".xml"
                            ):
                                ddi_res = res
                                break
                    if not ddi_res or not ddi_res.get("url"):
                        return None, ext, "No DDI XML resource attachment found in dataset"
                    ddi_url = ddi_res["url"]
                    res_r = requests.get(ddi_url, headers=headers, timeout=25)
                    if res_r.status_code == 200 and res_r.content:
                        return res_r.content, ext, None
                    return None, ext, f"Failed to download DDI XML from {ddi_url} (HTTP {res_r.status_code})"
                except Exception as e:
                    return None, ext, f"Failed to extract DDI resource: {e}"

            content = r.content
            if content and len(content.strip()) > 0:
                # If json format, pretty format it
                if ext.endswith(".json") or ext.endswith(".jsonld"):
                    try:
                        parsed = json.loads(content.decode("utf-8"))
                        content = json.dumps(parsed, indent=2).encode("utf-8")
                    except Exception:
                        pass
                return content, ext, None
            return None, ext, "Empty metadata response from server (0 bytes)"

        if r.status_code != 200 and fmt in ("schemaorg", "schema", "schema.org"):
            try:
                html_url = f"{base_url}/dataset/{encoded_id}"
                html_r = requests.get(html_url, headers=headers, timeout=20)
                if html_r.status_code == 200 and html_r.text:
                    match = re.search(
                        r'<script[^>]*type=[\'"]application/ld\+json[\'"][^>]*>(.*?)</script>',
                        html_r.text,
                        re.DOTALL | re.IGNORECASE,
                    )
                    if match:
                        snippet = match.group(1).strip()
                        if snippet:
                            parsed_json = json.loads(snippet)
                            return json.dumps(parsed_json, indent=2).encode("utf-8"), ext, None
            except Exception:
                pass

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

    def _record_download_result(
        self,
        record_key: str,
        pid: str,
        fmt: str,
        content: bytes | None,
        ext: str,
        err_msg: str | None,
        manifest_records: dict[str, Any],
        stats: dict[str, list[Any]],
    ) -> None:
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
                    "server": self.host,
                    "url": format_dataset_url(pid, host=self.host),
                }
            )
        else:
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
            if "errors" in self.manifest and record_key in self.manifest["errors"]:
                del self.manifest["errors"][record_key]

            if is_update:
                stats["updated"].append(record_key)
            else:
                stats["added"].append(record_key)

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
        workers: int = 4,
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
                        "server": self.host,
                        "url": format_dataset_url(self.host, host=self.host),
                    }
                )
                msg = f"Host '{self.host}' is unreachable or not a valid CKAN server: {err_msg}"
                console.print(f"  [bold red][!] {msg}[/bold red]")
                file_logger.log(msg, level="ERROR")
                return stats

        manifest_records = self.manifest.get("records", {})
        existing_errors = self.manifest.get("errors", {})

        # Probe deployed extensions and filter target formats
        server_extensions = fetch_server_extensions(
            self.host,
            verbose=verbose,
            api_token=api_token,
            repo_root=self.server_dir.parent,
        )
        unsupported_formats: set[str] = set()

        for fmt in target_formats:
            if not is_format_supported_on_server(fmt, server_extensions, host=self.host):
                unsupported_formats.add(fmt)
                ext_name = FORMAT_EXTENSION_REQUIREMENTS.get(fmt) or "an extension"
                available_str = (
                    f" (deployed extensions: {', '.join(sorted(server_extensions))})" if server_extensions else ""
                )
                msg = (
                    f"Format '{fmt}' requires '{ext_name}' which is not deployed on "
                    f"{self.host}{available_str} - skipping."
                )
                console.print(f"  [bold yellow][!] {msg}[/bold yellow]")
                file_logger.log(msg, level="WARNING")

        active_target_formats = [f for f in target_formats if f not in unsupported_formats]

        # Track records to download
        to_download: list[tuple[str, str, str]] = []  # (pid, fmt, reason)

        for pid, _meta in active_datasets.items():
            for fmt in active_target_formats:
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

        if dry_run:
            for pid, fmt, _reason in to_download:
                record_key = f"{pid}::{fmt}"
                stats["added"].append(record_key)
                completed_tasks += 1
                if progress_callback:
                    progress_callback(completed_tasks, total_tasks, record_key)
        elif workers <= 1 or total_tasks <= 1:
            for pid, fmt, _reason in to_download:
                record_key = f"{pid}::{fmt}"
                content, ext, err_msg = fetch_dataset_record(
                    self.host,
                    pid,
                    metadata_format=fmt,
                    verbose=verbose,
                    api_token=api_token,
                )
                self._record_download_result(
                    record_key=record_key,
                    pid=pid,
                    fmt=fmt,
                    content=content,
                    ext=ext,
                    err_msg=err_msg,
                    manifest_records=manifest_records,
                    stats=stats,
                )
                completed_tasks += 1
                if progress_callback:
                    progress_callback(completed_tasks, total_tasks, record_key)
        else:

            def _fetch_record_task(item: tuple[str, str, str]) -> tuple[str, str, bytes | None, str, str | None]:
                p, f, _ = item
                c, e, err = fetch_dataset_record(
                    self.host,
                    p,
                    metadata_format=f,
                    verbose=verbose,
                    api_token=api_token,
                )
                return p, f, c, e, err

            max_w = max(1, min(workers, total_tasks))
            with ThreadPoolExecutor(max_workers=max_w) as executor:
                futures = [executor.submit(_fetch_record_task, item) for item in to_download]
                for future in as_completed(futures):
                    p, f, content, ext, err_msg = future.result()
                    record_key = f"{p}::{f}"
                    self._record_download_result(
                        record_key=record_key,
                        pid=p,
                        fmt=f,
                        content=content,
                        ext=ext,
                        err_msg=err_msg,
                        manifest_records=manifest_records,
                        stats=stats,
                    )
                    completed_tasks += 1
                    if progress_callback:
                        progress_callback(completed_tasks, total_tasks, record_key)

        # Detect deleted datasets if full catalog sync was run
        if not target_id and not query and not since_date and not limit:
            active_keys = {f"{pid}::{fmt}" for pid in active_datasets for fmt in active_target_formats}
            for rec_key in list(manifest_records.keys()):
                fmt = rec_key.split("::")[1] if "::" in rec_key else "json"
                if fmt in active_target_formats and rec_key not in active_keys:
                    stats["deleted"].append(rec_key)
                    if not dry_run:
                        del manifest_records[rec_key]

        if not dry_run:
            self._save_manifest()

        return stats


@app.command(
    name="harvest",
    help=(
        "Harvest and incrementally sync CKAN dataset metadata records into local storage "
        "(applies strictly to metadata, not data payload files)."
    ),
)
def harvest(
    output_dir: Annotated[
        Path | None,
        typer.Argument(
            help="Repository root directory on local disk where server subdirectories will be created.",
        ),
    ] = None,
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
    package: Annotated[
        str | None,
        typer.Option(
            "--package",
            "--id",
            "--pid",
            "-p",
            help="Target specific dataset package name or ID (e.g. gdp-per-capita).",
        ),
    ] = None,
    repo_dir: Annotated[
        str | None,
        typer.Option(
            "--repo-dir",
            "-d",
            envvar=[
                "DARTFX_CKAN_REPOSITORY_ROOT",
                "DARTFX_CKAN_REPOSITORY",
                "CKAN_REPOSITORY_ROOT",
                "CKAN_REPOSITORY",
            ],
            help="Repository storage root directory (defaults to CKAN_REPOSITORY_ROOT or current dir).",
        ),
    ] = None,
    metadata_formats: Annotated[
        list[str] | None,
        typer.Option(
            "--format",
            "--formats",
            "-f",
            help="Metadata format(s) to harvest: json, dcat, jsonld, ttl, resources, or 'all' (metadata only).",
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            "-l",
            "-n",
            help="Maximum number of dataset records to harvest per server (default: 10, set to 0 for unlimited).",
        ),
    ] = 10,
    workers: Annotated[
        int,
        typer.Option(
            "--workers",
            "--threads",
            "-w",
            help="Number of concurrent worker threads for metadata downloads (default: 4).",
        ),
    ] = 4,
    since: Annotated[
        str | None,
        typer.Option(
            "--since",
            "--start-date",
            help="Harvest datasets created or modified since specified date (YYYY-MM-DD).",
        ),
    ] = None,
    query: Annotated[
        str | None,
        typer.Option(
            "--query",
            "-q",
            help="Filter datasets by keyword search query (e.g. environment, economy).",
        ),
    ] = None,
    retry_errors: Annotated[
        bool,
        typer.Option(
            "--retry-errors",
            "--retry",
            help="Retry downloading datasets previously recorded with errors in .manifest.json.",
        ),
    ] = False,
    force_verify: Annotated[
        bool,
        typer.Option(
            "--force-verify",
            "--verify-sha256",
            "--force-download",
            help="Force downloading metadata and verifying SHA-256 for all records, bypassing fast cache.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Preview additions, updates, and deletions without modifying local files.",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Enable detailed activity logging (HTTP requests, file paths, diff actions).",
        ),
    ] = False,
    refresh_catalog: Annotated[
        bool,
        typer.Option(
            "--refresh-catalog",
            "--refresh",
            "-r",
            help="Force a live catalog refresh from the CKAN API, bypassing local 24-hour cache.",
        ),
    ] = False,
    cache_ttl: Annotated[
        int,
        typer.Option(
            "--cache-ttl",
            help="Server dataset catalog cache expiration time in hours (default: 24).",
        ),
    ] = 24,
    api_token: Annotated[
        str | None,
        typer.Option(
            "--api-token",
            "--key",
            "-k",
            envvar=["DARTFX_CKAN_API_KEY", "CKAN_API_KEY", "CKAN_API_TOKEN"],
            help="CKAN API Token / Key for repositories requiring authentication.",
        ),
    ] = None,
    log_file: Annotated[
        str | None,
        typer.Option(
            "--log-file",
            help="Path to write execution activity log (default: harvester-YYYYMMDD-HHMMSS.log in repo directory).",
        ),
    ] = None,
) -> None:
    """Harvest and incrementally sync CKAN metadata records across servers into local directory structures."""
    target_repo = output_dir or (Path(repo_dir) if repo_dir else None)
    if not target_repo:
        env_repo = (
            os.environ.get("DARTFX_CKAN_REPOSITORY_ROOT")
            or os.environ.get("DARTFX_CKAN_REPOSITORY")
            or os.environ.get("CKAN_REPOSITORY_ROOT")
            or os.environ.get("CKAN_REPOSITORY")
        )
        target_repo = Path(env_repo) if env_repo else Path.cwd()
    target_repo = target_repo.resolve()
    target_repo.mkdir(parents=True, exist_ok=True)

    parsed_formats = normalize_formats(metadata_formats) or ["json"]

    timestamp_str = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    if log_file:
        log_file_path = Path(log_file).resolve()
    else:
        log_file_path = target_repo / f"harvester-{timestamp_str}.log"

    global file_logger
    file_logger = HarvesterFileLogger(log_file_path)

    effective_limit = None if limit == 0 else limit
    console = Console()

    file_logger.log("================================================================================")
    file_logger.log("CKAN Metadata Harvester & Sync Execution Started")
    file_logger.log(f"Execution Log File: {log_file_path}")
    file_logger.log("--------------------------------------------------------------------------------")
    file_logger.log(f"Repository Root Output: {target_repo}")
    file_logger.log(f"Target Server: {server}")
    file_logger.log(f"Target Dataset / Package: {package if package else '(None)'}")
    file_logger.log(f"Country Filter: {country if country else '(None)'}")
    file_logger.log(f"Metadata Formats: {', '.join(parsed_formats)}")
    file_logger.log(f"Since Date Filter: {since if since else '(All Time)'}")
    file_logger.log(f"Search Query Filter: {query if query else '(None)'}")
    file_logger.log(f"Record Limit: {effective_limit if effective_limit is not None else '(Unlimited)'}")
    file_logger.log(f"Concurrency Workers: {workers}")
    file_logger.log(f"Catalog Cache: {'Refreshed (forced)' if refresh_catalog else f'Enabled ({cache_ttl}h TTL)'}")
    file_logger.log(
        f"Incremental Verification: {'Full SHA-256 Download' if force_verify else 'Fast Timestamp/Manifest Check'}"
    )
    file_logger.log(f"Retry Manifest Errors: {retry_errors}")
    file_logger.log(f"Dry Run Mode: {dry_run}")
    file_logger.log(f"Verbose Logging: {verbose}")
    file_logger.log("================================================================================")

    console.print(
        Panel.fit(
            "[bold green]CKAN Metadata Harvester & Sync CLI[/bold green]",
            border_style="cyan",
        )
    )

    config_table = Table(show_header=False, box=None)
    config_table.add_column("Key", style="bold cyan")
    config_table.add_column("Value", style="yellow")
    config_table.add_row("Repository Root Output", str(target_repo))
    config_table.add_row("Execution Log File", str(log_file_path))
    config_table.add_row("Target Server", server)
    config_table.add_row("Target Dataset / Package", package if package else "(None)")
    config_table.add_row("Country Filter", country if country else "(None)")
    config_table.add_row("Metadata Formats", ", ".join(parsed_formats))
    config_table.add_row("Since Date Filter", since if since else "(All Time)")
    config_table.add_row("Search Query Filter", query if query else "(None)")
    config_table.add_row(
        "Record Limit / Server", str(effective_limit) if effective_limit is not None else "(Unlimited)"
    )
    config_table.add_row("Concurrency Workers", str(workers))
    config_table.add_row("Catalog Cache", "Refreshed (forced)" if refresh_catalog else f"Enabled ({cache_ttl}h TTL)")
    config_table.add_row(
        "Incremental Check", "Full SHA-256 Download Verification" if force_verify else "Fast Timestamp/Manifest Check"
    )
    config_table.add_row("Retry Manifest Errors", str(retry_errors))
    config_table.add_row("Dry Run Mode", str(dry_run))
    config_table.add_row("Verbose Logging", str(verbose))

    console.print(config_table)
    console.print()

    installations = fetch_ckan_installations(
        target_server=None if server.upper() == "ALL" else server,
        country=country,
        fallback_unlisted=True,
    )

    if not installations:
        console.print(f"[bold red]No CKAN servers found matching filter '{server}'.[/bold red]")
        raise typer.Exit(code=1)

    console.print(f"[bold green]Found {len(installations)} CKAN server(s) matching criteria.[/bold green]\n")

    overall_stats = {"datasets": 0, "added": 0, "updated": 0, "deleted": 0, "unchanged": 0, "errors": 0}
    summary_rows = []
    all_errors: list[dict[str, Any]] = []

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
        redirect_stdout=False,
        redirect_stderr=False,
    )

    with progress:
        server_task = progress.add_task("[bold cyan]Syncing Servers...", total=len(installations))

        for inst in installations:
            host = inst.clean_hostname
            country_name = inst.country or "-"
            progress.update(server_task, description=f"[bold yellow]Syncing {host}...[/bold yellow]")

            dataset_task = progress.add_task(
                f"  [dim cyan]Querying dataset catalog on {host}...[/dim cyan]", total=1, visible=True
            )

            def on_catalog_progress(retrieved_count: int, total_count: int, task_id=dataset_task, srv_host=host):
                if total_count > 0:
                    desc = f"  [cyan]Cataloging {srv_host}: {retrieved_count:,}/{total_count:,} datasets[/cyan]"
                    progress.update(
                        task_id,
                        total=total_count,
                        completed=retrieved_count,
                        description=desc,
                        visible=True,
                    )

            def on_progress(completed: int, total: int, record_name: str, task_id=dataset_task, srv_host=host):
                if total > 0:
                    display_name = (record_name[:42] + "...") if len(record_name) > 45 else record_name
                    progress.update(
                        task_id,
                        total=total,
                        completed=completed,
                        description=f"  [cyan]{srv_host}: {display_name}[/cyan]",
                        visible=True,
                    )

            try:
                if api_token:
                    save_server_token(host, api_token, target_repo)
                harvester = ServerHarvester(host, target_repo)
                stats = harvester.sync(
                    query=query,
                    since_date=since,
                    dry_run=dry_run,
                    limit=effective_limit,
                    metadata_formats=parsed_formats,
                    verbose=verbose,
                    target_id=package,
                    refresh_catalog=refresh_catalog,
                    cache_ttl_hours=float(cache_ttl),
                    retry_errors=retry_errors,
                    force_verify=force_verify,
                    api_token=api_token,
                    progress_callback=on_progress,
                    catalog_progress_callback=on_catalog_progress,
                    workers=workers,
                )
            except Exception as e:
                stats = {
                    "datasets": [],
                    "added": [],
                    "updated": [],
                    "deleted": [],
                    "unchanged": [],
                    "errors": [
                        {
                            "key": host,
                            "pid": host,
                            "format": "-",
                            "reason": str(e),
                            "server": host,
                            "url": f"https://{host}",
                        }
                    ],
                }

            num_datasets = len(stats.get("datasets", []))
            num_added = len(stats.get("added", []))
            num_updated = len(stats.get("updated", []))
            num_unchanged = len(stats.get("unchanged", []))
            num_deleted = len(stats.get("deleted", []))
            num_errors = len(stats.get("errors", []))

            overall_stats["datasets"] += num_datasets
            overall_stats["added"] += num_added
            overall_stats["updated"] += num_updated
            overall_stats["unchanged"] += num_unchanged
            overall_stats["deleted"] += num_deleted
            overall_stats["errors"] += num_errors

            all_errors.extend(stats.get("errors", []))

            summary_rows.append(
                (host, country_name, num_datasets, num_added, num_updated, num_unchanged, num_deleted, num_errors)
            )

            total_cnt = int(progress.tasks[dataset_task].total or 1)
            progress.update(dataset_task, completed=max(1, total_cnt), visible=False)
            progress.advance(server_task)

    # Render summary table
    console.print("\n[bold green]================ Sync Summary Report ================[/bold green]\n")
    results_table = Table(show_header=True, header_style="bold magenta")
    results_table.add_column("CKAN Server", style="cyan")
    results_table.add_column("Country", style="dim")
    results_table.add_column("Datasets", style="bold yellow", justify="right")
    results_table.add_column("Files Added (+)", style="green", justify="right")
    results_table.add_column("Files Updated (Δ)", style="yellow", justify="right")
    results_table.add_column("Files Unchanged (=)", style="dim cyan", justify="right")
    results_table.add_column("Files Deleted (-)", style="red", justify="right")
    results_table.add_column("Errors (!)", style="bold red", justify="right")

    file_logger.log("================ Sync Summary Report ================")
    for host, country_val, datasets_cnt, added, updated, unchanged, deleted, errors in summary_rows:
        server_url = f"https://{host}" if not host.startswith("http") else host
        clickable_host = f"[link={server_url}]{host}[/link]"
        results_table.add_row(
            clickable_host,
            country_val or "Global",
            str(datasets_cnt),
            str(added),
            str(updated),
            str(unchanged),
            str(deleted),
            str(errors),
        )
        file_logger.log(
            f"Server: {host} ({country_val or 'Global'}) | Datasets: {datasets_cnt} | Files Added: {added} | "
            f"Files Updated: {updated} | Files Unchanged: {unchanged} | Files Deleted: {deleted} | Errors: {errors}"
        )

    console.print(results_table)

    summary_panel_text = (
        f"[bold cyan]Datasets Processed: {overall_stats['datasets']}[/bold cyan]\n"
        f"[bold green]Files Added (+): {overall_stats['added']}[/bold green]  |  "
        f"[bold yellow]Files Updated (Δ): {overall_stats['updated']}[/bold yellow]  |  "
        f"[dim cyan]Files Unchanged (=): {overall_stats['unchanged']}[/dim cyan]  |  "
        f"[bold red]Files Deleted (-): {overall_stats['deleted']}[/bold red]  |  "
        f"[bold red]Total Errors (!): {overall_stats['errors']}[/bold red]"
    )

    console.print(
        Panel(
            summary_panel_text,
            title="[bold]Harvest Completed[/bold]",
            border_style="green" if overall_stats["errors"] == 0 else "yellow",
        )
    )
    file_logger.log(
        f"Datasets Processed: {overall_stats['datasets']} | Total Added (+): {overall_stats['added']} | "
        f"Total Updated (Δ): {overall_stats['updated']} | Total Unchanged (=): {overall_stats['unchanged']} | "
        f"Total Deleted (-): {overall_stats['deleted']} | Total Errors (!): {overall_stats['errors']}"
    )

    if all_errors:
        console.print(f"\n[bold red]==== Harvesting Errors Report ({len(all_errors)} Failed) ====[/bold red]\n")

        # 1. Error Type Breakdown Summary Table
        type_counts: dict[str, int] = {}
        for err in all_errors:
            reason_str = err.get("reason", "") if isinstance(err, dict) else str(err)
            etype = classify_harvest_error(reason_str)
            type_counts[etype] = type_counts.get(etype, 0) + 1

        sum_err_table = Table(
            title="Harvest Errors: Summary by Error Type",
            header_style="bold red",
            show_header=True,
        )
        sum_err_table.add_column("Error Category / Type", style="cyan", no_wrap=False)
        sum_err_table.add_column("Count", justify="right", style="bold red")
        sum_err_table.add_column("% of Total", justify="right", style="yellow")

        for etype, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
            pct = f"{(count / len(all_errors)) * 100:.1f}%"
            sum_err_table.add_row(etype, str(count), pct)

        console.print(sum_err_table)
        console.print()

        # 2. Detailed Error Table
        err_table = Table(title="Failed Records Details", show_header=True, header_style="bold yellow")
        err_table.add_column("Dataset / Package", style="cyan", no_wrap=True)
        err_table.add_column("Format", style="yellow", justify="center", no_wrap=True)
        err_table.add_column("Error Category", style="magenta")
        err_table.add_column("Error Reason / Details", style="bold red", no_wrap=False)

        file_logger.log(f"==== Harvesting Errors Report ({len(all_errors)} Failed) ====")

        for err in all_errors:
            dataset_url: str | None = None
            if isinstance(err, dict):
                pid_raw = err.get("pid") or err.get("key", "Unknown")
                fmt_display = err.get("format", "-")
                reason_display = err.get("reason", "Unknown error")
                err_server = err.get("server") or (pid_raw.split(" (")[0] if " (" in str(pid_raw) else None)
                dataset_url = str(err.get("url")) if err.get("url") else format_dataset_url(pid_raw, host=err_server)
            else:
                pid_raw = str(err)
                fmt_display = "-"
                reason_display = "Error occurred"
                dataset_url = format_dataset_url(pid_raw)

            cat_display = classify_harvest_error(reason_display)
            pid_display = (
                f"[link={dataset_url}]{pid_raw}[/link]" if dataset_url and pid_raw != "Unknown" else str(pid_raw)
            )
            err_table.add_row(pid_display, fmt_display, cat_display, reason_display)
            file_logger.log(
                f"PID: {pid_raw} | Format: {fmt_display} | Category: {cat_display} | Reason: {reason_display}",
                level="ERROR",
            )

        console.print(err_table)
        console.print()
        console.print(
            "[yellow]⚠️ Encountered harvest errors on some records. "
            "Run [bold]dartfx-ckan errors --details[/bold] to inspect failure reasons across manifests.[/yellow]\n"
        )

    file_logger.log("Harvesting process completed.")


if __name__ == "__main__":
    app()
