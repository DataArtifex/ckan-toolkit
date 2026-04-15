from __future__ import annotations

import pytest

from dartfx.ckan.api import CKANAPIClient
from dartfx.ckan.exceptions import CKANAPIRequestError, CKANValidationError


class FakeRemoteCKAN:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses

    def call_action(self, action_name: str, data_dict: dict[str, object]) -> object:  # noqa: ARG002
        if action_name == "raise_error":
            raise RuntimeError("boom")
        return self.responses[action_name]


def test_action_wraps_errors():
    client = CKANAPIClient("https://demo.ckan.org", remote_ckan=FakeRemoteCKAN({}))

    with pytest.raises(CKANAPIRequestError):
        client.action("raise_error")


def test_get_server_info():
    client = CKANAPIClient(
        "https://demo.ckan.org",
        remote_ckan=FakeRemoteCKAN(
            {
                "status_show": {
                    "ckan_version": "2.10",
                    "site_title": "Demo",
                    "site_description": "Demo server",
                    "site_url": "https://demo.ckan.org",
                    "extensions": ["datastore"],
                }
            }
        ),
    )

    info = client.get_server_info()

    assert info.ckan_version == "2.10"
    assert info.site_title == "Demo"


def test_get_server_stats_with_optional_user_count():
    client = CKANAPIClient(
        "https://demo.ckan.org",
        remote_ckan=FakeRemoteCKAN(
            {
                "package_search": {"count": 12, "results": []},
                "organization_list": [{"id": "o1"}, {"id": "o2"}],
                "group_list": [{"id": "g1"}],
                "user_list": [{"id": "u1"}],
            }
        ),
    )

    stats = client.get_server_stats()

    assert stats.dataset_count == 12
    assert stats.organization_count == 2
    assert stats.group_count == 1
    assert stats.project_count == 1
    assert stats.user_count == 1


def test_search_datasets_validates_results_list():
    client = CKANAPIClient(
        "https://demo.ckan.org",
        remote_ckan=FakeRemoteCKAN(
            {
                "package_search": {"count": 1, "results": [{"id": "d1", "name": "dataset-1"}]},
            }
        ),
    )

    datasets = client.search_datasets(query="water")

    assert len(datasets) == 1
    assert datasets[0].id == "d1"


def test_get_dataset_requires_dict():
    client = CKANAPIClient(
        "https://demo.ckan.org",
        remote_ckan=FakeRemoteCKAN(
            {
                "package_show": "invalid",
            }
        ),
    )

    with pytest.raises(CKANValidationError):
        client.get_dataset("dataset-id")
