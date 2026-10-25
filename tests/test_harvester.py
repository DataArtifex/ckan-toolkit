import json
import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

from rich.console import Console
from typer.testing import CliRunner

from dartfx.ckan.cli import app
from dartfx.ckan.harvester import (
    ServerHarvester,
    abbreviate_error,
    analyze_harvest_errors,
    classify_harvest_error,
    fetch_server_stats,
    format_dataset_url,
    format_response_latency,
    format_version,
    get_dataset_metadata_path,
    is_non_recoverable_error,
    normalize_formats,
    render_harvest_errors,
    resolve_server_token,
    sanitize_pid,
    save_server_token,
)


def test_sanitize_pid() -> None:
    assert sanitize_pid("gold-prices") == "gold-prices"
    assert sanitize_pid("dataset/123/v1") == "dataset_123_v1"
    assert sanitize_pid("my:package.id") == "my_package.id"


def test_format_version() -> None:
    assert format_version("2.10") == "v2.10"
    assert format_version("v2.11.3") == "v2.11.3"
    assert format_version("2.9.5-rc1") == "v2.9.5"
    assert format_version(None) == "-"


def test_normalize_formats() -> None:
    assert normalize_formats("json") == ["json"]
    assert normalize_formats("json,dcat,resources") == ["json", "dcat", "resources"]
    assert normalize_formats("all") == [
        "json",
        "dcat",
        "jsonld",
        "ttl",
        "resources",
        "schemaorg",
        "croissant",
        "ddi",
    ]
    assert normalize_formats("xml") == ["dcat"]
    assert normalize_formats("native") == ["json"]
    assert normalize_formats(None) == []


def test_get_dataset_metadata_path(tmp_path: Path) -> None:
    server_dir = tmp_path / "demo.ckan.org"
    meta_path, rel_path = get_dataset_metadata_path(server_dir, "gold-prices", ".ckan.json")
    assert rel_path == "gold-prices/metadata/ckan.json"
    assert meta_path == server_dir / "gold-prices" / "metadata" / "ckan.json"


def test_is_non_recoverable_error() -> None:
    assert is_non_recoverable_error("HTTP 404: Not Found") is True
    assert is_non_recoverable_error("Unsupported format") is True
    assert is_non_recoverable_error("HTTP 403: Forbidden") is True
    assert is_non_recoverable_error("Connection timed out") is False
    assert is_non_recoverable_error("HTTP 500") is False


def test_token_persistence_and_resolution(tmp_path: Path, monkeypatch) -> None:
    test_host = "data.gov"

    # 1. No token initially
    assert resolve_server_token(test_host, repo_root=tmp_path) is None

    # 2. Save token
    save_server_token(test_host, "ckan-secret-key-123", repo_root=tmp_path)

    # 3. Resolve from server directory and central json
    assert resolve_server_token(test_host, repo_root=tmp_path) == "ckan-secret-key-123"

    # 4. Explicit token override
    assert resolve_server_token(test_host, repo_root=tmp_path, explicit_token="override-key") == "override-key"

    # 5. Environment variable resolution
    monkeypatch.setenv("CKAN_API_TOKEN_DATA_GOV", "env-ckan-token")
    assert resolve_server_token(test_host, repo_root=tmp_path / "empty") == "env-ckan-token"


def test_repo_root_env_variable_resolution(tmp_path: Path, monkeypatch) -> None:
    test_host = "test-host.org"
    token_file = tmp_path / test_host / ".api_token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text("my-secret-token", "utf-8")

    # Clear potentially set environment variables from user or .env
    monkeypatch.delenv("DARTFX_CKAN_REPOSITORY_ROOT", raising=False)
    monkeypatch.delenv("DARTFX_CKAN_REPOSITORY", raising=False)
    monkeypatch.delenv("CKAN_REPOSITORY_ROOT", raising=False)
    monkeypatch.delenv("CKAN_REPOSITORY", raising=False)

    # With CKAN_REPOSITORY_ROOT
    monkeypatch.setenv("CKAN_REPOSITORY_ROOT", str(tmp_path))
    assert resolve_server_token(test_host) == "my-secret-token"

    # With DARTFX_CKAN_REPOSITORY_ROOT
    alt_path = tmp_path / "alt"
    alt_token_file = alt_path / test_host / ".api_token"
    alt_token_file.parent.mkdir(parents=True)
    alt_token_file.write_text("dartfx-root-token", "utf-8")
    monkeypatch.setenv("DARTFX_CKAN_REPOSITORY_ROOT", str(alt_path))
    assert resolve_server_token(test_host) == "dartfx-root-token"

    # With analyze_harvest_errors
    manifest = alt_path / test_host / ".manifest.json"
    manifest.write_text('{"records": {}}', "utf-8")
    analysis = analyze_harvest_errors(server=test_host)
    assert analysis["total_errors"] == 0

    # With fetch_server_stats
    fetch_server_stats(test_host, refresh_cache=False)
    assert (alt_path / test_host / ".stats_cache.json").exists()


def test_server_harvester_manifest(tmp_path: Path) -> None:
    harvester = ServerHarvester("demo.ckan.org", tmp_path)
    assert harvester.manifest_file.exists() is False

    # Save dummy record
    harvester.manifest["records"]["gold-prices::json"] = {
        "global_id": "gold-prices",
        "format": "json",
        "sha256": "abcdef123456",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    harvester._save_manifest()

    # Reload and verify
    reloaded = ServerHarvester("demo.ckan.org", tmp_path)
    assert "gold-prices::json" in reloaded.manifest["records"]


def test_classify_harvest_error() -> None:
    assert classify_harvest_error("HTTP 404: Not Found") == "HTTP 404: Dataset / Endpoint Not Found"
    assert classify_harvest_error("HTTP 401: Unauthorized") == "HTTP 401: Authentication Required (API Token)"
    assert classify_harvest_error("Cloudflare WAF Blocked") == "HTTP 403: Forbidden / Bot Protection (WAF)"
    assert classify_harvest_error("Exporter Not Found on server") == "Exporter Not Supported on Server"
    assert classify_harvest_error("Connection timeout") == "Request Timeout"
    assert (
        classify_harvest_error("certificate verify failed: certificate has expired")
        == "Network: SSL Certificate Expired"
    )
    assert (
        classify_harvest_error("Hostname mismatch: certificate is not valid for 'ckan.org'")
        == "Network: SSL Hostname Mismatch"
    )
    assert (
        classify_harvest_error("certificate verify failed: self-signed certificate")
        == "Network: SSL Self-Signed Certificate"
    )
    assert (
        classify_harvest_error(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: UNEXPECTED_EOF_WHILE_READING"
        )
        == "Network: SSL Handshake Failed (Unexpected EOF)"
    )
    assert classify_harvest_error(None) == "Unknown Error"


def test_abbreviate_error() -> None:
    wrapped_ssl_err = (
        "HTTPSConnectionPool(host='ckanprod-alma.ucar.edu', port=443): Max retries exceeded "
        "with url: /api/3/action/status_show (Caused by SSLError(SSLError(1, "
        "'[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: UNEXPECTED_EOF_WHILE_READING (_ssl.c:1000)')))"
    )
    assert abbreviate_error(wrapped_ssl_err) == "SSL Handshake Failed"

    wrapped_mismatch = (
        "HTTPSConnectionPool(host='data.example.org', port=443): Max retries exceeded "
        "with url: /api/3/action/status_show (Caused by SSLError(SSLCertVerificationError(1, "
        '"[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Hostname mismatch, '
        "certificate is not valid for 'data.example.org'. (_ssl.c:1010)\")))"
    )
    assert abbreviate_error(wrapped_mismatch) == "SSL Hostname Mismatch"

    assert (
        abbreviate_error("HTTPSConnectionPool(host='ckanprod-alma.ucar.edu', port=443): Max retries exceeded")
        == "Connection Failure"
    )
    assert abbreviate_error("[SSL: CERTIFICATE_VERIFY_FAILED]") == "SSL Certificate Error"
    assert abbreviate_error("UNEXPECTED_EOF_WHILE_READING") == "SSL Handshake Failed"
    assert abbreviate_error("Timeout (10s)") == "Timeout (10s)"
    assert abbreviate_error("Connection timed out (ReadTimeout)") == "Request Timeout"
    assert abbreviate_error("Connection refused") == "Connection Refused"
    assert abbreviate_error("certificate has expired") == "SSL Certificate Expired"
    assert abbreviate_error("unable to get local issuer certificate") == "SSL Incomplete Chain"
    assert abbreviate_error("self-signed certificate") == "SSL Self-Signed Cert"
    assert abbreviate_error("nodename nor servname provided, or not known") == "DNS Resolution Failure"
    assert abbreviate_error("HTTP 401: Unauthorized") == "Auth Required (401)"
    assert abbreviate_error("HTTP 403: Forbidden") == "Forbidden (403)"
    assert abbreviate_error("Cloudflare challenge") == "Bot Protection (WAF)"
    assert abbreviate_error("HTTP 404: Not Found") == "Not Found (404)"
    assert abbreviate_error("HTTP 500: Server Error") == "Server Error (500)"
    assert abbreviate_error("HTTP 502: Bad Gateway") == "Bad Gateway (502)"
    assert abbreviate_error("HugeDomains.com is for sale") == "Domain For Sale"
    assert abbreviate_error("Not a CKAN server") == "Not CKAN Server"
    assert abbreviate_error(None) == "Unknown Error"


def test_analyze_and_render_harvest_errors(tmp_path: Path) -> None:
    server_dir = tmp_path / "demo.ckan.org"
    server_dir.mkdir(parents=True, exist_ok=True)
    mfile = server_dir / ".manifest.json"

    manifest_data = {
        "server": "demo.ckan.org",
        "records": {},
        "errors": {
            "pkg-1::dcat": {
                "pid": "pkg-1",
                "format": "dcat",
                "reason": "HTTP 404: Not Found",
                "failed_at": datetime.now(UTC).isoformat(),
            },
            "pkg-2::json": {
                "pid": "pkg-2",
                "format": "json",
                "reason": "HTTP 500: Server Error",
                "failed_at": datetime.now(UTC).isoformat(),
            },
        },
    }
    mfile.write_text(json.dumps(manifest_data), "utf-8")

    analysis = analyze_harvest_errors(repo_dir=tmp_path)
    assert analysis["total_errors"] == 2
    assert analysis["total_datasets"] == 2
    assert "demo.ckan.org" in analysis["by_server"]

    # Verify rendering functions don't raise
    render_harvest_errors(analysis, by_format=True)
    render_harvest_errors(analysis, by_server=True)
    render_harvest_errors(analysis, details=True)


def test_format_response_latency() -> None:
    assert "⚡" in format_response_latency(0.8)
    assert "🟢" in format_response_latency(2.5)
    assert "🟡" in format_response_latency(6.0)
    assert "🔴" in format_response_latency(12.0)
    assert "🔒" in format_response_latency(1.0, requires_token=True)
    assert "❌" in format_response_latency(1.0, is_error=True)
    assert format_response_latency(None) == "-"


def test_format_dataset_url() -> None:
    assert format_dataset_url("my-dataset", "demo.ckan.org") == "https://demo.ckan.org/dataset/my-dataset"


def test_cli_harvest_and_errors_help() -> None:
    runner = CliRunner()
    res1 = runner.invoke(app, ["harvest", "--help"])
    assert res1.exit_code == 0
    clean1 = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", res1.stdout)
    assert "--server" in clean1
    assert "--format" in clean1
    assert "--limit" in clean1
    assert "--workers" in clean1
    assert "--threads" in clean1
    assert "-w" in clean1
    assert "--package" in clean1
    assert "--since" in clean1
    assert "--query" in clean1
    assert "--refresh" in clean1
    assert "--retry" in clean1
    assert "--force-verify" in clean1
    assert "--key" in clean1

    res2 = runner.invoke(app, ["errors", "--help"])
    assert res2.exit_code == 0
    clean2 = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", res2.stdout)
    assert "--by-format" in clean2
    assert "--by-server" in clean2
    assert "--details" in clean2


def test_cli_harvest_dry_run_positional_and_target_package(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    repo_dir = tmp_path / "harvest_repo"

    from dartfx.ckan.ckan import ServerInstallation

    inst = ServerInstallation(
        name="Demo CKAN",
        hostname="demo.ckan.org",
        url="https://demo.ckan.org",
        country="Global",
    )
    monkeypatch.setattr("dartfx.ckan.harvester.fetch_ckan_installations", lambda **_kw: [inst])
    monkeypatch.setattr("dartfx.ckan.harvester.fetch_server_extensions", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(
        "dartfx.ckan.harvester.fetch_active_datasets",
        lambda *_args, **_kwargs: {"sample-dataset": {"name": "sample-dataset", "id": "id-sample"}},
    )

    # Run harvest with positional directory and specific package
    res = runner.invoke(
        app,
        [
            "harvest",
            str(repo_dir),
            "--server",
            "demo.ckan.org",
            "--package",
            "sample-dataset",
            "--format",
            "json",
            "--dry-run",
        ],
    )
    assert res.exit_code == 0
    clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", res.stdout)
    assert "CKAN Metadata Harvester & Sync CLI" in clean
    assert "Repository Root Output" in clean
    assert "sample-dataset" in clean

    # Verify log file was automatically created in the repository root directory
    log_files = list(repo_dir.glob("harvester-*.log"))
    assert len(log_files) == 1
    log_content = log_files[0].read_text(encoding="utf-8")
    assert "CKAN Metadata Harvester & Sync Execution Started" in log_content
    assert "Target Server: demo.ckan.org" in log_content
    assert "Target Dataset / Package: sample-dataset" in log_content
    assert "Sync Summary Report" in log_content


def test_cli_harvest_error_reporting(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    repo_dir = tmp_path / "err_repo"

    from dartfx.ckan.ckan import ServerInstallation

    inst = ServerInstallation(
        name="Test CKAN",
        hostname="test.ckan.org",
        url="https://test.ckan.org",
        country="Canada",
    )
    monkeypatch.setattr("dartfx.ckan.harvester.fetch_ckan_installations", lambda **_kw: [inst])
    monkeypatch.setattr("dartfx.ckan.harvester.fetch_server_extensions", lambda *_args, **_kwargs: set())

    # Mock fetch_active_datasets to return 1 dataset
    monkeypatch.setattr(
        "dartfx.ckan.harvester.fetch_active_datasets",
        lambda *_args, **_kwargs: {"failing-dataset": {"name": "failing-dataset", "id": "id-err"}},
    )

    # Mock fetch_dataset_record to fail with 404
    monkeypatch.setattr(
        "dartfx.ckan.harvester.fetch_dataset_record",
        lambda *_args, **_kwargs: (None, ".ckan.json", "HTTP 404: Not Found"),
    )

    res = runner.invoke(
        app,
        [
            "harvest",
            str(repo_dir),
            "--server",
            "test.ckan.org",
            "--format",
            "json",
        ],
    )
    assert res.exit_code == 0
    clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", res.stdout)
    assert "CKAN Metadata Harvester & Sync CLI" in clean
    assert "Repository Root Output" in clean

    log_files = list(repo_dir.glob("harvester-*.log"))
    assert len(log_files) == 1
    log_content = log_files[0].read_text(encoding="utf-8")
    assert "Harvesting Errors Report (1 Failed)" in log_content
    assert "failing-dataset" in log_content


def test_cli_harvest_no_matching_servers(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("dartfx.ckan.harvester.fetch_ckan_installations", lambda **_kw: [])

    res = runner.invoke(app, ["harvest", "--server", "nonexistent.example.org"])
    assert res.exit_code == 1
    clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", res.stdout)
    assert "No CKAN servers found matching filter 'nonexistent.example.org'" in clean


def test_server_harvester_sync_multithreaded(tmp_path: Path, monkeypatch) -> None:
    harvester = ServerHarvester("demo.ckan.org", tmp_path)

    # Mock fetch_active_datasets to return 3 datasets
    monkeypatch.setattr(
        "dartfx.ckan.harvester.fetch_active_datasets",
        lambda *_args, **_kwargs: {
            "pkg-1": {"name": "pkg-1", "id": "id-1"},
            "pkg-2": {"name": "pkg-2", "id": "id-2"},
            "pkg-3": {"name": "pkg-3", "id": "id-3"},
        },
    )

    # Mock fetch_dataset_record to return dummy json content
    def mock_fetch_dataset_record(host, identifier, metadata_format="json", verbose=False, api_token=None):
        del host, metadata_format, verbose, api_token
        return json.dumps({"name": identifier, "title": f"Title {identifier}"}).encode("utf-8"), ".ckan.json", None

    monkeypatch.setattr("dartfx.ckan.harvester.fetch_dataset_record", mock_fetch_dataset_record)

    # Run sync with 3 workers
    stats = harvester.sync(limit=3, metadata_formats="json", workers=3)
    assert len(stats["added"]) == 3
    assert "pkg-1::json" in stats["added"]
    assert "pkg-2::json" in stats["added"]
    assert "pkg-3::json" in stats["added"]

    # Verify files created on disk
    assert (tmp_path / "demo.ckan.org" / "pkg-1" / "metadata" / "ckan.json").exists()
    assert (tmp_path / "demo.ckan.org" / "pkg-2" / "metadata" / "ckan.json").exists()
    assert (tmp_path / "demo.ckan.org" / "pkg-3" / "metadata" / "ckan.json").exists()

    # Re-running sync without force_verify should report unchanged
    stats2 = harvester.sync(limit=3, metadata_formats="json", workers=2)
    assert len(stats2["unchanged"]) == 3


def test_fetch_server_stats_concurrent_probe(tmp_path: Path, monkeypatch) -> None:
    class DummyResponse:
        def __init__(self, data: dict, status_code: int = 200) -> None:
            self._data = data
            self.status_code = status_code

        def json(self):
            return self._data

    def mock_get(url, headers=None, timeout=None):
        del headers, timeout
        if "status_show" in url:
            return DummyResponse({"result": {"ckan_version": "2.10.1", "site_title": "My CKAN Portal"}})
        if "package_search" in url:
            return DummyResponse({"result": {"count": 42, "results": []}})
        if "organization_list" in url:
            return DummyResponse({"result": ["org1", "org2", "org3"]})
        return DummyResponse({}, status_code=404)

    monkeypatch.setattr("requests.get", mock_get)

    stats = fetch_server_stats("fake.ckan.org", repo_root=tmp_path, refresh_cache=True)
    assert stats["is_ckan"] is True
    assert stats["version"] == "2.10.1"
    assert stats["site_title"] == "My CKAN Portal"
    assert stats["datasets"] == 42
    assert stats["organizations"] == 3
    assert stats["error"] is None


def test_fetch_server_stats_shutdown_handling(tmp_path: Path, monkeypatch) -> None:
    # When RuntimeError('cannot schedule new futures after interpreter shutdown') occurs
    def mock_get_shutdown(*_args, **_kwargs):
        raise RuntimeError("cannot schedule new futures after interpreter shutdown")

    monkeypatch.setattr("requests.get", mock_get_shutdown)

    stats = fetch_server_stats("shutdown.ckan.org", repo_root=tmp_path, refresh_cache=True)
    assert stats["error"] == "Interrupted"
    # Ensure this error is NOT written to cache
    cache_file = tmp_path / "shutdown.ckan.org" / ".stats_cache.json"
    assert not cache_file.exists()

    # If a cache file previously contained an interpreter shutdown error, it should be ignored
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {
                "server": "shutdown.ckan.org",
                "cached_at": datetime.now(UTC).isoformat(),
                "error": "cannot schedule new futures after interpreter shutdown",
            }
        ),
        encoding="utf-8",
    )
    # With requests.get working again
    monkeypatch.setattr(
        "requests.get",
        lambda *_args, **_kwargs: type("Resp", (), {"status_code": 404, "json": lambda _self: {}})(),
    )
    stats2 = fetch_server_stats("shutdown.ckan.org", repo_root=tmp_path, refresh_cache=False)
    # Should not use the corrupted cached entry
    assert stats2.get("cached") is not True


def test_fetch_server_stats_ssl_fallback(tmp_path: Path, monkeypatch) -> None:
    import requests

    class DummyResponse:
        def __init__(self, data: dict, status_code: int = 200) -> None:
            self._data = data
            self.status_code = status_code

        def json(self):
            return self._data

    def mock_get(url, headers=None, timeout=None):
        del headers, timeout
        if url.startswith("https://"):
            raise requests.exceptions.SSLError(
                "HTTPSConnectionPool(host='ssl-fail.ckan.org', port=443): Max retries exceeded "
                "(Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] "
                "certificate verify failed: Hostname mismatch')))"
            )
        if url.startswith("http://"):
            if "status_show" in url:
                return DummyResponse({"result": {"ckan_version": "2.9.7", "site_title": "HTTP Fallback Portal"}})
            if "package_search" in url:
                return DummyResponse({"result": {"count": 15, "results": []}})
            if "organization_list" in url:
                return DummyResponse({"result": ["org1"]})
        return DummyResponse({}, status_code=404)

    monkeypatch.setattr("requests.get", mock_get)

    stats = fetch_server_stats("ssl-fail.ckan.org", repo_root=tmp_path, refresh_cache=True)
    assert stats["is_ckan"] is True
    assert stats["http_fallback"] is True
    assert stats["ssl_error"] == "SSL Hostname Mismatch"
    assert stats["error"] is None
    assert stats["scheme"] == "http"
    assert stats["datasets"] == 15
    assert stats["version"] == "2.9.7"


def test_fetch_server_stats_waf_retry_browser_ua(tmp_path: Path, monkeypatch) -> None:
    class DummyResponse:
        def __init__(self, data: dict, status_code: int = 200) -> None:
            self._data = data
            self.status_code = status_code
            self.text = json.dumps(data)

        def json(self):
            return self._data

    def mock_get(url, headers=None, timeout=None):
        del timeout
        ua = (headers or {}).get("User-Agent", "")
        # If bot UA without Chrome/Safari, simulate a WAF 403 block
        if "Chrome" not in ua:
            return DummyResponse({"error": "Forbidden"}, status_code=403)
        if "status_show" in url:
            return DummyResponse({"result": {"ckan_version": "2.6.9", "site_title": "Agri Portal"}})
        if "package_search" in url:
            return DummyResponse({"result": {"count": 13, "results": []}})
        if "organization_list" in url:
            return DummyResponse({"result": ["org1", "org2"]})
        return DummyResponse({}, status_code=404)

    monkeypatch.setattr("requests.get", mock_get)

    stats = fetch_server_stats("dados.agricultura.gov.br", repo_root=tmp_path, refresh_cache=True)
    assert stats["is_ckan"] is True
    assert stats["datasets"] == 13
    assert stats["organizations"] == 2
    assert stats["version"] == "2.6.9"
    assert stats["error"] is None


def test_display_server_stats_version_comparison(tmp_path: Path, monkeypatch) -> None:
    from rich.console import Console

    from dartfx.ckan.ckan import ServerInstallation
    from dartfx.ckan.harvester import display_server_stats

    # Create dummy installations
    inst1 = ServerInstallation(hostname="online-upgraded.org", country="Australia", version="2.9.0")
    inst2 = ServerInstallation(hostname="not-ckan.org", country="United States", version="2.11.2")

    def mock_fetch(host, **_kwargs):
        if "online-upgraded.org" in host:
            return {
                "is_ckan": True,
                "version": "2.11.0",
                "datasets": 100,
                "organizations": 10,
                "latency_seconds": 0.4,
                "error": None,
            }
        return {
            "is_ckan": False,
            "version": None,
            "datasets": 0,
            "organizations": 0,
            "latency_seconds": 0.2,
            "error": "Not a CKAN server",
        }

    monkeypatch.setattr("dartfx.ckan.harvester.fetch_server_stats", mock_fetch)

    captured_console = Console(record=True, width=120)
    display_server_stats(
        installations=[inst1, inst2],
        console=captured_console,
        workers=1,
        repo_root=tmp_path,
        refresh_cache=True,
    )
    output = captured_console.export_text()
    assert "Live Ver" in output
    assert "Dataset Ver" in output
    assert "v2.11.0" in output
    assert "v2.9.0" in output
    assert "v2.11.2" in output


def test_classify_server_availability() -> None:
    from dartfx.ckan.harvester import classify_server_availability

    # Accessible
    assert classify_server_availability(status="Online", is_ckan=True) == "accessible"
    assert classify_server_availability(status="Online (AIA Fixed)", is_ckan=True) == "accessible"
    assert classify_server_availability(status="Online (Cached)", is_ckan=True) == "accessible"
    assert classify_server_availability(status="HTTP (SSL Failed)", is_ckan=True) == "accessible"

    # Restricted
    assert classify_server_availability(status="Auth Required", is_ckan=True, requires_token=True) == "restricted"
    assert classify_server_availability(status="Cloudflare Challenge", error="Cloudflare Challenge") == "restricted"
    assert (
        classify_server_availability(status="Perimeter Block (Geo/IP)", error="Perimeter Block (Geo/IP)")
        == "restricted"
    )
    assert classify_server_availability(status="Forbidden (403)", error="Forbidden (403)") == "restricted"

    # Offline / Inactive
    assert classify_server_availability(status="Timeout (10s)", error="Timeout (10s)") == "offline"
    assert classify_server_availability(status="DNS Resolution Failure", error="DNS Resolution Failure") == "offline"
    assert classify_server_availability(status="Domain For Sale", error="Domain For Sale") == "offline"
    assert classify_server_availability(status="Catalog Retired (410)", error="Catalog Retired (410)") == "offline"
    assert classify_server_availability(status="Not CKAN Server") == "offline"


def test_get_ca_bundle_for_host(tmp_path: Path) -> None:
    from dartfx.ckan.harvester import get_ca_bundle_for_host

    # When file does not exist
    assert get_ca_bundle_for_host("test.ckan.org", cache_dir=tmp_path) is None

    # When file exists and non-empty
    bundle_file = tmp_path / "test.ckan.org.pem"
    bundle_file.write_text("-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----", encoding="utf-8")
    assert get_ca_bundle_for_host("test.ckan.org", cache_dir=tmp_path) == str(bundle_file)


def test_resolve_aia_intermediate_ca(tmp_path: Path, monkeypatch) -> None:
    from dartfx.ckan.harvester import resolve_aia_intermediate_ca

    mock_der = b"some_der_bytes\x00http://pki.example.org/intermediate.crt\x00more_bytes"

    mock_sock = MagicMock()
    mock_ssock = MagicMock()
    mock_ssock.getpeercert.return_value = mock_der
    mock_sock.__enter__.return_value = mock_sock
    mock_ssock.__enter__.return_value = mock_ssock

    monkeypatch.setattr("socket.create_connection", lambda *_args, **_kwargs: mock_sock)
    mock_ctx = MagicMock()
    mock_ctx.wrap_socket.return_value = mock_ssock
    monkeypatch.setattr("ssl.create_default_context", lambda: mock_ctx)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"-----BEGIN CERTIFICATE-----\nMOCK_INTERMEDIATE\n-----END CERTIFICATE-----"
    monkeypatch.setattr("requests.get", lambda _url, **_kwargs: mock_resp)

    bundle_path = resolve_aia_intermediate_ca("test.ckan.org", cache_dir=tmp_path)
    assert bundle_path is not None
    assert bundle_path.exists()
    content = bundle_path.read_text(encoding="utf-8")
    assert "MOCK_INTERMEDIATE" in content


def test_display_server_stats_shows_aia_fixed(monkeypatch) -> None:
    from dartfx.ckan.ckan import ServerInstallation
    from dartfx.ckan.harvester import display_server_stats

    inst = ServerInstallation(
        name="Test AIA CKAN Server",
        hostname="data.example.gov",
        url="https://data.example.gov",
        country="United States",
        country_code="US",
    )

    stat = {
        "is_ckan": True,
        "datasets": 120,
        "organizations": 5,
        "version": "2.10",
        "latency_seconds": 1.2,
        "aia_repaired": True,
        "error": None,
    }

    monkeypatch.setattr("dartfx.ckan.harvester.fetch_ckan_installations", lambda **_kwargs: [inst])
    monkeypatch.setattr("dartfx.ckan.harvester.fetch_server_stats", lambda *_args, **_kwargs: stat)

    records = display_server_stats(server="data.example.gov", format="json")
    assert len(records) == 1
    assert records[0]["status"] == "Online (AIA Fixed)"
    assert records[0]["aia_repaired"] is True


def test_display_server_stats_json_and_markdown(monkeypatch, capsys) -> None:
    from dartfx.ckan.ckan import ServerInstallation
    from dartfx.ckan.harvester import display_server_stats

    inst1 = ServerInstallation(name="US Data", hostname="data.gov", country_code="US")
    inst2 = ServerInstallation(name="UK Data", hostname="data.gov.uk", country_code="GB")

    mock_stats = {
        "https://data.gov": {
            "is_ckan": True,
            "datasets": 250000,
            "organizations": 100,
            "latency_seconds": 1.1,
            "version": "2.10",
        },
        "https://data.gov.uk": {
            "is_ckan": True,
            "datasets": 50000,
            "organizations": 80,
            "latency_seconds": 2.2,
            "version": "2.9",
        },
    }

    monkeypatch.setattr("dartfx.ckan.harvester.fetch_ckan_installations", lambda **_kwargs: [inst1, inst2])
    monkeypatch.setattr(
        "dartfx.ckan.harvester.fetch_server_stats",
        lambda host, **_kwargs: mock_stats.get(host, {"is_ckan": False, "error": "Unknown"}),
    )

    # 1. Test JSON output
    records = display_server_stats(format="json", sort_by="datasets", descending=True)
    captured = capsys.readouterr()
    assert len(records) == 2
    assert records[0]["name"] == "US Data"
    assert records[1]["name"] == "UK Data"
    parsed_json = json.loads(captured.out)
    assert len(parsed_json) == 2
    assert parsed_json[0]["datasets"] == 250000

    # 2. Test Markdown output
    records_md = display_server_stats(format="markdown")
    captured_md = capsys.readouterr()
    assert len(records_md) == 2
    assert (
        "| Repository / Server | Country | Live Ver | Dataset Ver | "
        "Datasets | Organizations | Formats | Latency | Status |" in captured_md.out
    )
    assert "|:---|:---:|:---:|:---:|---:|---:|:---:|:---:|:---|" in captured_md.out
    assert "[US Data](https://data.gov)" in captured_md.out
    assert "250,000" in captured_md.out
    assert "300,000 total datasets indexed" in captured_md.out


def test_is_format_supported_on_server() -> None:
    from dartfx.ckan.harvester import is_format_supported_on_server

    # Unknown server extensions -> returns True (runtime attempt)
    assert is_format_supported_on_server("json", None) is True
    assert is_format_supported_on_server("dcat", None) is True
    assert is_format_supported_on_server("schemaorg", None) is True
    assert is_format_supported_on_server("croissant", None) is True
    assert is_format_supported_on_server("ddi", None) is True

    # Server without extensions
    no_dcat_exts = {"datastore", "datapusher", "resource_proxy"}
    assert is_format_supported_on_server("json", no_dcat_exts) is True
    assert is_format_supported_on_server("resources", no_dcat_exts) is True
    assert is_format_supported_on_server("dcat", no_dcat_exts) is False
    assert is_format_supported_on_server("jsonld", no_dcat_exts) is False
    assert is_format_supported_on_server("ttl", no_dcat_exts) is False
    assert is_format_supported_on_server("schemaorg", no_dcat_exts) is False
    assert is_format_supported_on_server("croissant", no_dcat_exts) is False
    assert is_format_supported_on_server("ddi", no_dcat_exts) is False

    # Server with ckanext-dcat, croissant, and ddi
    all_exts = {"ckanext-dcat", "croissant", "ddi_theme", "datastore"}
    assert is_format_supported_on_server("json", all_exts) is True
    assert is_format_supported_on_server("dcat", all_exts) is True
    assert is_format_supported_on_server("jsonld", all_exts) is True
    assert is_format_supported_on_server("ttl", all_exts) is True
    assert is_format_supported_on_server("schemaorg", all_exts) is True
    assert is_format_supported_on_server("croissant", all_exts) is True
    assert is_format_supported_on_server("ddi", all_exts) is True


def test_fetch_server_extensions_from_status_show(monkeypatch) -> None:
    from dartfx.ckan.harvester import fetch_server_extensions

    class DummyResponse:
        status_code = 200

        def json(self):
            return {"success": True, "result": {"extensions": ["ckanext-dcat", "stats"]}}

    monkeypatch.setattr("requests.get", lambda *_args, **_kwargs: DummyResponse())

    exts = fetch_server_extensions("mock.ckan.org")
    assert exts == {"ckanext-dcat", "stats"}


def test_server_harvester_skips_unsupported_formats(tmp_path: Path, monkeypatch) -> None:
    from dartfx.ckan.harvester import ServerHarvester

    harvester = ServerHarvester("mock.ckan.org", tmp_path)

    # Server only has core extensions (no dcat)
    monkeypatch.setattr("dartfx.ckan.harvester.fetch_server_extensions", lambda *_args, **_kwargs: {"datastore"})
    monkeypatch.setattr(
        "dartfx.ckan.harvester.fetch_active_datasets",
        lambda *_args, **_kwargs: {"pkg-alpha": {"name": "pkg-alpha", "id": "id-alpha"}},
    )

    downloaded_formats = []

    def mock_fetch_dataset_record(host, identifier, metadata_format="json", verbose=False, api_token=None):
        del host, identifier, verbose, api_token
        downloaded_formats.append(metadata_format)
        return b"{}", f".{metadata_format}", None

    monkeypatch.setattr("dartfx.ckan.harvester.fetch_dataset_record", mock_fetch_dataset_record)

    # Request both json and dcat
    stats = harvester.sync(limit=1, metadata_formats=["json", "dcat"])

    # json was downloaded
    assert "pkg-alpha::json" in stats["added"]
    assert "json" in downloaded_formats

    # dcat was skipped upfront without calling download or producing error
    assert "pkg-alpha::dcat" not in stats["added"]
    assert "dcat" not in downloaded_formats
    assert len(stats["errors"]) == 0


def test_normalize_formats_extended() -> None:
    from dartfx.ckan.harvester import normalize_formats

    res = normalize_formats("schemaorg,croissant,ddi")
    assert "schemaorg" in res
    assert "croissant" in res
    assert "ddi" in res

    res_alias = normalize_formats("schema.org,mlcroissant,ddi-xml")
    assert "schemaorg" in res_alias
    assert "croissant" in res_alias
    assert "ddi" in res_alias


def test_display_server_stats_format_capabilities_and_filtering(capsys, monkeypatch) -> None:
    from dartfx.ckan.ckan import ServerInstallation
    from dartfx.ckan.harvester import display_server_stats

    inst1 = ServerInstallation(name="DCAT & Croissant Portal", hostname="dcat.croissant.org", country_code="US")
    inst2 = ServerInstallation(name="Plain Portal", hostname="plain.org", country_code="CA")

    def mock_fetch_server_stats(host, **_kwargs):
        if "dcat" in host:
            return {
                "server": host,
                "is_ckan": True,
                "version": "2.10.1",
                "datasets": 500,
                "organizations": 10,
                "has_dcat": True,
                "has_schemaorg": True,
                "has_croissant": True,
                "has_ddi": False,
                "extensions": ["dcat", "structured_data", "croissant"],
            }
        return {
            "server": host,
            "is_ckan": True,
            "version": "2.9.0",
            "datasets": 100,
            "organizations": 2,
            "has_dcat": False,
            "has_schemaorg": False,
            "has_croissant": False,
            "has_ddi": False,
            "extensions": [],
        }

    monkeypatch.setattr("dartfx.ckan.harvester.fetch_server_stats", mock_fetch_server_stats)

    # 1. Unfiltered table output includes Formats column and badges
    capsys.readouterr()
    wide_console = Console(width=200)
    records = display_server_stats(installations=[inst1, inst2], format="table", console=wide_console)
    captured = capsys.readouterr()
    assert len(records) == 2
    assert "Formats" in captured.out
    assert "DCAT" in captured.out
    assert "Schema" in captured.out
    assert "Croissant" in captured.out
    assert "Capabilities: 1 DCAT • 1 Schema.org • 1 Croissant • 0 DDI" in captured.out
    assert records[0]["formats"] == ["dcat", "schemaorg", "croissant"]
    assert records[0]["has_croissant"] is True
    assert records[1]["formats"] == []

    # 2. Filtered with croissant=True
    records_croissant = display_server_stats(
        installations=[inst1, inst2], croissant=True, format="table", console=wide_console
    )
    assert len(records_croissant) == 1
    assert records_croissant[0]["hostname"] == "dcat.croissant.org"


def test_fetch_dataset_record_schemaorg_and_croissant(monkeypatch) -> None:
    from dartfx.ckan.harvester import fetch_dataset_record

    class MockResp:
        def __init__(self, status_code, content):
            self.status_code = status_code
            self.content = content
            self.text = content.decode("utf-8") if isinstance(content, bytes) else str(content)

        def json(self):
            return json.loads(self.content.decode("utf-8"))

    def mock_get(url, **_kwargs):
        if "croissant.jsonld" in url:
            return MockResp(200, b'{"@context": "croissant", "title": "ML Data"}')
        if "profiles=schemaorg" in url:
            return MockResp(200, b'{"@context": "https://schema.org", "@type": "Dataset"}')
        return MockResp(404, b"Not found")

    monkeypatch.setattr("requests.get", mock_get)

    cr_bytes, cr_ext, cr_err = fetch_dataset_record("demo.ckan.org", "sample-dataset", metadata_format="croissant")
    assert cr_err is None
    assert cr_ext == ".croissant.jsonld"
    assert cr_bytes is not None
    assert b"croissant" in cr_bytes

    so_bytes, so_ext, so_err = fetch_dataset_record("demo.ckan.org", "sample-dataset", metadata_format="schemaorg")
    assert so_err is None
    assert so_ext == ".schemaorg.jsonld"
    assert so_bytes is not None
    assert b"schema.org" in so_bytes


def test_probe_ckan_url_transient_retry_and_post_fallback(monkeypatch) -> None:
    from dartfx.ckan.harvester import _probe_ckan_url

    attempts = {"status": 0, "search": 0, "org": 0}

    class MockResp:
        def __init__(self, status_code: int, data: dict | None = None, text: str = ""):
            self.status_code = status_code
            self._data = data or {}
            self.text = text or json.dumps(self._data)

        def json(self):
            return self._data

    def mock_get(url, **_kwargs):
        if "status_show" in url:
            attempts["status"] += 1
            # First attempt fails with 503 (e.g. concurrency limit), second succeeds
            if attempts["status"] == 1:
                return MockResp(503, text="Temporarily unavailable")
            return MockResp(
                200,
                {
                    "success": True,
                    "result": {
                        "ckan_version": "2.11.6",
                        "site_title": "Test CKAN",
                        "extensions": ["dcat", "harvest"],
                    },
                },
            )
        elif "package_search" in url:
            attempts["search"] += 1
            if attempts["search"] == 1:
                return MockResp(503, text="Temporarily unavailable")
            return MockResp(200, {"success": True, "result": {"count": 150}})
        elif "organization_list" in url:
            attempts["org"] += 1
            # GET returns 400 Bad Request requiring POST
            return MockResp(400, text="Bad request - JSON Error: Invalid request. Please use POST method")
        return MockResp(404)

    def mock_post(url, **_kwargs):
        if "organization_list" in url:
            return MockResp(200, {"success": True, "result": ["org1", "org2", "org3"]})
        return MockResp(404)

    monkeypatch.setattr("requests.get", mock_get)
    monkeypatch.setattr("requests.post", mock_post)

    res = _probe_ckan_url("https://test.ckan.org", "test.ckan.org", {}, timeout=5)
    assert res["is_ckan"] is True
    assert res["version"] == "2.11.6"
    assert res["datasets"] == 150
    assert res["organizations"] == 3
    assert res["has_dcat"] is True
    assert res["error"] is None


def test_probe_ckan_url_status_code_error_classification(monkeypatch) -> None:
    from dartfx.ckan.harvester import _probe_ckan_url

    class MockResp:
        def __init__(self, status_code: int, text: str = ""):
            self.status_code = status_code
            self.text = text

        def json(self):
            return {}

    # Test 503
    monkeypatch.setattr("requests.get", lambda _url, **_kwargs: MockResp(503, text="Service Unavailable"))
    res_503 = _probe_ckan_url("https://err.ckan.org", "err.ckan.org", {}, timeout=5)
    assert res_503["is_ckan"] is False
    assert res_503["error"] == "Service Unavailable (503)"
    assert res_503["has_dcat"] is False

    # Test 429
    monkeypatch.setattr("requests.get", lambda _url, **_kwargs: MockResp(429, text="Too Many Requests"))
    res_429 = _probe_ckan_url("https://err.ckan.org", "err.ckan.org", {}, timeout=5)
    assert res_429["is_ckan"] is False
    assert res_429["error"] == "Rate Limited (429)"


def test_display_server_stats_offline_server_hides_formats(monkeypatch, capsys) -> None:
    from rich.console import Console

    from dartfx.ckan.ckan import ServerInstallation
    from dartfx.ckan.harvester import display_server_stats

    inst = ServerInstallation(
        id="offline.ckan.org",
        url="https://offline.ckan.org",
        hostname="offline.ckan.org",
        name="Offline CKAN",
        country_code="BE",
        version="2.11.4",
        extensions='["dcat", "structured_data"]',
    )

    def mock_fetch_stats(*_args, **_kwargs):
        return {
            "server": "offline.ckan.org",
            "is_ckan": False,
            "error": "Service Unavailable (503)",
            "datasets": 0,
            "organizations": 0,
            "version": None,
            "has_dcat": False,
            "has_schemaorg": False,
            "has_croissant": False,
            "has_ddi": False,
        }

    monkeypatch.setattr("dartfx.ckan.harvester.fetch_server_stats", mock_fetch_stats)

    console = Console(width=200)
    records = display_server_stats(installations=[inst], format="table", console=console)
    captured = capsys.readouterr()

    # Formats should be empty for offline / non-ckan server
    assert len(records) == 1
    assert records[0]["has_dcat"] is False
    assert records[0]["formats"] == []
    # Table should show '-' for formats, not 'DCAT' or 'Schema'
    assert "DCAT" not in captured.out
    assert "Schema" not in captured.out
