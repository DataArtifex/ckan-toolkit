import json
import re
import sys
from pathlib import Path

from typer.testing import CliRunner

from dartfx.ckan.ckan import (
    ServerInstallation,
    fetch_ckan_installations,
    get_iso2_code,
    matches_country,
)
from dartfx.ckan.cli import _normalize_smart_dashes, app


def test_fetch_ckan_installations() -> None:
    installations = fetch_ckan_installations()
    assert len(installations) > 0
    demo = next((inst for inst in installations if "demo.ckan.org" in (inst.hostname or "")), None)
    assert demo is not None
    assert demo.clean_hostname == "demo.ckan.org"


def test_server_installation_country_code_derivation() -> None:
    inst1 = ServerInstallation(
        name="Data.gov",
        hostname="https://data.gov/",
        country="United States",
    )
    assert inst1.country_code == "US"
    assert inst1.clean_hostname == "data.gov"
    assert inst1.url == "https://data.gov"

    # Inferred from .es domain
    inst2 = ServerInstallation(
        name="Datos Gob ES",
        hostname="datos.gob.es",
    )
    assert inst2.country_code == "ES"


def test_country_crosswalk_and_matching() -> None:
    assert get_iso2_code("United States") == "US"
    assert get_iso2_code("United Kingdom") == "GB"
    assert get_iso2_code("Canada") == "CA"
    assert get_iso2_code("Spain") == "ES"
    assert get_iso2_code("US") == "US"

    assert matches_country("US", "United States") is True
    assert matches_country("US", "Canada") is False
    assert matches_country("GB", "United Kingdom") is True
    assert matches_country("spain", "Spain") is True


def test_fetch_ckan_installations_filtering() -> None:
    # Country filter
    us_servers = fetch_ckan_installations(country="US")
    assert len(us_servers) > 0
    for s in us_servers:
        assert s.country_code == "US"

    # Specific target server filter
    demo_list = fetch_ckan_installations(target_server="demo.ckan.org")
    assert len(demo_list) == 1
    assert demo_list[0].clean_hostname == "demo.ckan.org"

    # Unlisted fallback
    fallback_list = fetch_ckan_installations(target_server="internal.ckan.local", fallback_unlisted=True)
    assert len(fallback_list) == 1
    assert fallback_list[0].clean_hostname == "internal.ckan.local"
    assert fallback_list[0].country_code == "-"


def test_cli_installations_command(monkeypatch) -> None:
    mock_insts = [
        ServerInstallation(name="CKAN 1", hostname="ckan1.test", country="United States"),
        ServerInstallation(name="CKAN 2", hostname="ckan2.test", country="United States"),
    ]
    monkeypatch.setattr("dartfx.ckan.cli.fetch_ckan_installations", lambda **_kwargs: mock_insts)

    runner = CliRunner()
    result = runner.invoke(app, ["installations", "--country", "US", "--limit", "2", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert len(data) == 2
    assert all(d.get("country_code") == "US" for d in data)

    result_csv = runner.invoke(app, ["installations", "--country", "US", "--limit", "2", "--format", "csv"])
    assert result_csv.exit_code == 0
    assert "country_code" in result_csv.stdout
    assert "US" in result_csv.stdout


def test_cli_list_command_alias(monkeypatch) -> None:
    mock_insts = [
        ServerInstallation(name="CKAN 1", hostname="ckan1.test", country="United States"),
        ServerInstallation(name="CKAN 2", hostname="ckan2.test", country="United States"),
    ]
    monkeypatch.setattr("dartfx.ckan.cli.fetch_ckan_installations", lambda **_kwargs: mock_insts)

    runner = CliRunner()
    result_list = runner.invoke(app, ["list", "--country", "US", "--limit", "2", "--format", "json"])
    assert result_list.exit_code == 0
    data_list = json.loads(result_list.stdout)
    assert len(data_list) == 2

    result_inst = runner.invoke(app, ["installations", "--country", "US", "--limit", "2", "--format", "json"])
    assert result_inst.exit_code == 0
    data_inst = json.loads(result_inst.stdout)
    assert data_list == data_inst


def test_cli_smart_dash_normalization(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["dartfx-ckan", "stats", "-–country", "US", "—limit", "5"])
    _normalize_smart_dashes()
    assert sys.argv == ["dartfx-ckan", "stats", "--country", "US", "--limit", "5"]


def test_cli_stats_command_flags() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["stats", "--help"])
    assert result.exit_code == 0
    clean_output = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", result.stdout)
    assert "--refresh" in clean_output
    assert "-r" in clean_output
    assert "--cache-ttl" in clean_output
    assert "--timeout" in clean_output
    assert "-t" in clean_output
    assert "--workers" in clean_output
    assert "--threads" in clean_output
    assert "-w" in clean_output
    assert "--repo-dir" in clean_output
    assert "-d" in clean_output
    assert "--croissant" in clean_output
    assert "--dcat" in clean_output
    assert "--schemaorg" in clean_output
    assert "--ddi" in clean_output


def test_cli_list_json_standardized_and_file(tmp_path: Path, monkeypatch) -> None:
    mock_insts = [
        ServerInstallation(name="CKAN 1", hostname="ckan1.test", country="United States"),
    ]
    monkeypatch.setattr("dartfx.ckan.cli.fetch_ckan_installations", lambda **_kwargs: mock_insts)

    runner = CliRunner()
    res = runner.invoke(app, ["list", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert len(data) == 1
    assert data[0]["platform"] == "ckan"
    assert data[0]["hostname"] == "ckan1.test"
    assert data[0]["url"] == "https://ckan1.test"

    # Test file output
    out_file = tmp_path / "ckan_insts.json"
    res_file = runner.invoke(app, ["list", "--json", "-o", str(out_file)])
    assert res_file.exit_code == 0
    assert out_file.exists()
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved[0]["platform"] == "ckan"


def test_cli_harvest_json_output(tmp_path: Path, monkeypatch) -> None:
    mock_inst = [ServerInstallation(name="Mock CKAN", hostname="mock.ckan.org", country="Global")]
    monkeypatch.setattr("dartfx.ckan.harvester.fetch_ckan_installations", lambda **_kwargs: mock_inst)

    class MockHarvester:
        def __init__(self, *args, **kwargs):
            pass

        def sync(self, **_kwargs):
            return {
                "datasets": ["ds-1"],
                "added": ["ds-1"],
                "updated": [],
                "deleted": [],
                "unchanged": [],
                "errors": [],
            }

    monkeypatch.setattr("dartfx.ckan.harvester.ServerHarvester", MockHarvester)

    runner = CliRunner()
    res = runner.invoke(app, ["harvest", str(tmp_path), "--formats", "json", "--json"])
    assert res.exit_code == 0
    harvest_json = json.loads(res.stdout)
    assert harvest_json["platform"] == "ckan"
    assert harvest_json["status"] == "success"
    assert harvest_json["summary"]["datasets"] == 1
    assert harvest_json["summary"]["added"] == 1
    assert harvest_json["summary"]["errors"] == 0
    assert len(harvest_json["servers"]) == 1
    assert harvest_json["servers"][0]["hostname"] == "mock.ckan.org"
    assert harvest_json["parameters"]["formats"] == ["json"]
