from datetime import UTC, datetime

from dartfx.ckan.models import Dataset, HealthCheckResponse, Organization, Resource, ServerInfo, ServerStats


def test_server_info_defaults():
    info = ServerInfo.model_validate({"ckan_version": "2.10"})

    assert info.ckan_version == "2.10"
    assert info.extensions == []


def test_server_stats_defaults():
    stats = ServerStats.model_validate({})

    assert stats.dataset_count == 0
    assert stats.organization_count == 0
    assert stats.project_count == 0


def test_dataset_nested_entities():
    dataset = Dataset.model_validate(
        {
            "id": "dataset-id",
            "name": "dataset-name",
            "organization": {"id": "org-id", "name": "org-name", "title": "Org"},
            "resources": [{"id": "res-id", "name": "Resource", "url": "https://example.com/file.csv", "format": "CSV"}],
        }
    )

    assert dataset.organization is not None
    assert isinstance(dataset.organization, Organization)
    assert dataset.organization.name == "org-name"
    assert len(dataset.resources) == 1
    assert isinstance(dataset.resources[0], Resource)
    assert dataset.resources[0].format == "CSV"


def test_health_check_model():
    now = datetime.now(UTC)
    health = HealthCheckResponse(healthy=True, checked_at=now, message="ok")

    assert health.healthy is True
    assert health.message == "ok"
