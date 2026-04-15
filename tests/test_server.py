from __future__ import annotations

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

    def action(self, action_name: str) -> dict[str, str]:
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
