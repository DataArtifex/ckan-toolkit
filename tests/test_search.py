import json
from unittest.mock import MagicMock

from typer.testing import CliRunner

from dartfx.ckan.ckan import SearchParameters
from dartfx.ckan.cli import app
from dartfx.ckan.server import CKANServer


def test_search_parameters() -> None:
    params = SearchParameters(q="climate", rows=50, per_page=10, sort="metadata_modified desc")
    # per_page overrides rows in model_post_init
    assert params.rows == 10
    assert params.q == "climate"
    assert params.sort == "metadata_modified desc"


def test_server_search_with_parameters():
    mock_client = MagicMock()
    mock_client.action.return_value = {
        "count": 1,
        "results": [{"name": "climate-data", "title": "Climate Data"}],
    }

    server = CKANServer("https://demo.ckan.org", client=mock_client)
    params = SearchParameters(q="climate", rows=10)
    res = server.search(params)
    assert res["count"] == 1
    assert len(res["results"]) == 1
    assert res["results"][0]["name"] == "climate-data"


def test_cli_search_command(monkeypatch):
    mock_server = MagicMock()
    mock_server.search.return_value = {
        "count": 1,
        "results": [
            {
                "name": "mock-dataset",
                "title": "Mock Dataset Title",
                "organization": {"title": "Mock Org"},
                "resources": [{}],
                "metadata_modified": "2026-01-01",
            }
        ],
    }
    monkeypatch.setattr("dartfx.ckan.cli.get_server", lambda *_args, **_kwargs: mock_server)

    runner = CliRunner()
    result = runner.invoke(app, ["search", "mock", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["count"] == 1
    assert data["results"][0]["name"] == "mock-dataset"

    result_csv = runner.invoke(app, ["search", "mock", "--format", "csv"])
    assert result_csv.exit_code == 0
    assert "mock-dataset" in result_csv.stdout


def test_cli_dataset_command(monkeypatch):
    mock_dataset = MagicMock()
    mock_dataset.model_dump.return_value = {"id": "ds-123", "name": "my-dataset"}

    mock_server = MagicMock()
    mock_server.get_dataset.return_value = mock_dataset
    mock_server.get_dataset_export.return_value = "<rdf:RDF>mock</rdf:RDF>"
    monkeypatch.setattr("dartfx.ckan.cli.get_server", lambda *_args, **_kwargs: mock_server)

    runner = CliRunner()
    result = runner.invoke(app, ["dataset", "my-dataset"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["name"] == "my-dataset"

    result_export = runner.invoke(app, ["dataset", "my-dataset", "--export", "dcat"])
    assert result_export.exit_code == 0
    assert "<rdf:RDF>" in result_export.stdout


def test_cli_info_command(monkeypatch):
    mock_server = MagicMock()
    mock_server.get_info_version.return_value = {"data": {"version": "2.11.0"}}
    mock_server.get_info_server.return_value = {
        "data": {
            "title": "Demo CKAN",
            "description": "Demo Portal",
            "extensions": ["dcat", "harvest"],
        }
    }
    mock_server.get_info_export_formats.return_value = {
        "status": "OK",
        "data": {
            "json": {
                "displayName": "CKAN Package JSON",
                "mediaType": "application/json",
                "requiredExtension": None,
                "isHarvestable": True,
            },
            "dcat": {
                "displayName": "DCAT 2/3 RDF/XML",
                "mediaType": "application/rdf+xml",
                "requiredExtension": "ckanext-dcat",
                "isHarvestable": True,
            },
        },
    }
    monkeypatch.setattr("dartfx.ckan.cli.get_server", lambda *_args, **_kwargs: mock_server)

    runner = CliRunner()
    result = runner.invoke(app, ["info", "demo.ckan.org"])
    assert result.exit_code == 0
    assert "Demo CKAN" in result.stdout
    assert "2.11.0" in result.stdout
    assert "dcat" in result.stdout
    assert "Metadata Export Formats" in result.stdout
    assert "CKAN Package JSON" in result.stdout
    assert "DCAT 2/3 RDF/XML" in result.stdout


def test_cli_info_command_fallback(monkeypatch):
    mock_server = MagicMock()
    mock_server.get_info_version.return_value = {"live": False, "data": {"version": "2.10"}}
    mock_server.get_info_server.return_value = {
        "live": False,
        "data": {
            "title": "Data.gov",
            "description": "US Open Data",
            "extensions": [],
        },
    }
    monkeypatch.setattr("dartfx.ckan.cli.get_server", lambda *_args, **_kwargs: mock_server)

    runner = CliRunner()
    result = runner.invoke(app, ["info", "data.gov"])
    assert result.exit_code == 0
    assert "Notice: Live status probe unavailable on data.gov" in result.stdout
    assert "Data.gov" in result.stdout
    assert "2.10" in result.stdout


def test_cli_info_command_failure_without_fallback(monkeypatch):
    mock_server = MagicMock()
    mock_server.installation = None
    mock_server.get_info_version.side_effect = RuntimeError("Connection refused")
    monkeypatch.setattr("dartfx.ckan.cli.get_server", lambda *_args, **_kwargs: mock_server)

    runner = CliRunner()
    result = runner.invoke(app, ["info", "broken.host.xyz"])
    assert result.exit_code == 1
    assert "Error:" in result.stdout
