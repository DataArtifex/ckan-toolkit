import json
import re
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from dartfx.ckan.cli import app
from dartfx.ckan.harvester import (
    ServerHarvester,
    analyze_harvest_errors,
    classify_harvest_error,
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
    assert normalize_formats("all") == ["json", "dcat", "jsonld", "ttl", "resources"]
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

    # With CKAN_REPOSITORY_ROOT
    monkeypatch.setenv("CKAN_REPOSITORY_ROOT", str(tmp_path))
    assert resolve_server_token(test_host) == "my-secret-token"

    # With analyze_harvest_errors
    manifest = tmp_path / test_host / ".manifest.json"
    manifest.write_text('{"records": {}}', "utf-8")
    analysis = analyze_harvest_errors(server=test_host)
    assert analysis["total_errors"] == 0


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
    assert classify_harvest_error(None) == "Unknown Error"


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

    res2 = runner.invoke(app, ["errors", "--help"])
    assert res2.exit_code == 0
    clean2 = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", res2.stdout)
    assert "--by-format" in clean2
    assert "--by-server" in clean2
    assert "--details" in clean2
