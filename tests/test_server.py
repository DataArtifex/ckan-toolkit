from __future__ import annotations

from typing import Any

from dartfx.ckan.models import Dataset, Organization, ServerInfo, ServerStats
from dartfx.ckan.server import CKANServer


class FakeClient:
    def __init__(self) -> None:
        self.info_calls = 0
        self.stats_calls = 0

    def get_server_info(self) -> ServerInfo:
        self.info_calls += 1
        return ServerInfo(ckan_version="2.10", site_title="Demo")

    def get_server_stats(self) -> ServerStats:
        self.stats_calls += 1
        return ServerStats(dataset_count=5, organization_count=2, group_count=1, project_count=1)

    def action(self, action_name: str, *args: Any, **kwargs: Any) -> dict[str, str]:  # noqa: ARG002
        if action_name == "status_show":
            return {"status": "ok"}
        raise RuntimeError("invalid action")

    def search_datasets(self, *, query: str, limit: int = 100, offset: int = 0) -> list[Dataset]:  # noqa: ARG002
        return [Dataset(id="d1", name="dataset-1")]

    def get_dataset(self, dataset_id_or_name: str) -> Dataset:  # noqa: ARG002
        return Dataset(id="d2", name="dataset-2")

    def list_organizations(self, *, limit: int = 100, offset: int = 0) -> list[Organization]:  # noqa: ARG002
        return [Organization(id="o1", name="org-1")]


def test_server_info_and_stats_cached():
    fake_client = FakeClient()
    server = CKANServer("https://demo.ckan.org", client=fake_client)

    first_info = server.info
    second_info = server.info
    first_stats = server.stats
    second_stats = server.stats

    assert first_info.site_title == "Demo"
    assert second_info.site_title == "Demo"
    assert first_stats.dataset_count == 5
    assert second_stats.dataset_count == 5
    assert fake_client.info_calls == 1
    assert fake_client.stats_calls == 1


def test_server_health_check():
    server = CKANServer("https://demo.ckan.org", client=FakeClient())

    assert server.is_healthy() is True


def test_server_dataset_and_organization_methods():
    server = CKANServer("https://demo.ckan.org", client=FakeClient())

    datasets = server.list_datasets(limit=10)
    searched = server.search_datasets("climate", limit=10)
    dataset = server.get_dataset("dataset-id")
    organizations = server.list_organizations(limit=10)

    assert datasets[0].id == "d1"
    assert searched[0].name == "dataset-1"
    assert dataset.id == "d2"
    assert organizations[0].id == "o1"


def test_server_get_info_fallback_when_client_fails():
    class FailingClient(FakeClient):
        def get_server_info(self) -> ServerInfo:
            raise RuntimeError("405 Method Not Allowed")

    server = CKANServer("data.gov", client=FailingClient())
    version_info = server.get_info_version()
    server_info = server.get_info_server()

    assert version_info["live"] is False
    assert version_info["data"]["version"] == "2.10"
    assert server_info["live"] is False
    assert server_info["data"]["title"] == "Data.gov"
    assert "open data" in server_info["data"]["description"]


def test_server_get_info_raises_when_no_installation_data():
    class FailingClient(FakeClient):
        def get_server_info(self) -> ServerInfo:
            raise RuntimeError("Connection failed")

    server = CKANServer("unknown-ckan-instance.xyz", client=FailingClient())
    import pytest

    with pytest.raises(RuntimeError, match="Connection failed"):
        server.get_info_version()

    with pytest.raises(RuntimeError, match="Connection failed"):
        server.get_info_server()


def test_server_get_info_export_formats():
    server = CKANServer("https://demo.ckan.org", client=FakeClient())
    formats_resp = server.get_info_export_formats()
    assert formats_resp.get("status") == "OK"
    data = formats_resp.get("data", {})
    assert "json" in data
    assert "resources" in data
    assert "dcat" in data
    assert "jsonld" in data
    assert "ttl" in data
    assert "schemaorg" in data
    assert "croissant" in data
    assert "ddi" in data
    assert data["json"]["isHarvestable"] is True
    assert data["resources"]["isHarvestable"] is True


def test_server_get_info_export_formats_with_extensions(monkeypatch):
    server = CKANServer("https://demo.ckan.org", client=FakeClient())
    monkeypatch.setattr(
        server,
        "get_info_server",
        lambda: {
            "status": "OK",
            "data": {"extensions": ["dcat", "structured_data", "croissant", "ddi_theme"]},
        },
    )
    formats_resp = server.get_info_export_formats()
    data = formats_resp.get("data", {})
    assert data["dcat"]["isHarvestable"] is True
    assert data["schemaorg"]["isHarvestable"] is True
    assert data["croissant"]["isHarvestable"] is True
    assert data["ddi"]["isHarvestable"] is True
