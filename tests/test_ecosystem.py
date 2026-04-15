"""Tests for the dartfx.ckan.ecosystem manager."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from dartfx.ckan.ecosystem.manager import EcosystemManager
from dartfx.ckan.ecosystem.models import EcosystemExtensions, EcosystemSites
from dartfx.ckan.models import Dataset, Resource

_DUMMY_CSV = b"tstamp,name,url,num_datasets\n2024-01-01,testsite,http://test,42\n"


@contextmanager
def fake_urlopen(_req: Any):
    """Fake urllib.request.urlopen that returns a dummy CSV response."""
    mock_response = MagicMock()
    mock_response.read.return_value = _DUMMY_CSV
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    yield mock_response


class FakeCKANServer:
    def __init__(self, *args, **kwargs):
        pass

    def get_dataset(self, name: str) -> Dataset:
        # Create a mock dataset with a CSV resource
        dt = datetime(2024, 1, 1, tzinfo=UTC)
        r = Resource(id="123", format="CSV", url="http://fake", metadata_modified=dt)
        d = Dataset(id="456", name=name, resources=[r], metadata_modified=dt)
        return d


def test_ecosystem_models() -> None:
    """Test instantiation of ecosystem Pydantic models."""
    site = EcosystemSites(name="test", num_datasets=42)
    assert site.name == "test"
    assert site.num_datasets == 42

    ext = EcosystemExtensions(repository_name="test-ext", stars=10)
    assert ext.repository_name == "test-ext"
    assert ext.stars == 10


def test_ecosystem_manager_sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test sync flow of the EcosystemManager."""
    monkeypatch.setattr("dartfx.ckan.ecosystem.manager.CKANServer", FakeCKANServer)
    monkeypatch.setattr("dartfx.ckan.ecosystem.manager.urllib.request.urlopen", fake_urlopen)

    manager = EcosystemManager(data_dir=tmp_path)

    # Run sync
    manager.sync()

    # State file should be populated
    state_file = tmp_path / "sync_state.json"
    assert state_file.exists()

    with open(state_file, encoding="utf-8") as f:
        state = json.load(f)
    assert "ckan-sites-metadata" in state

    # Parquet file should exist
    assert (tmp_path / "ckan-sites-metadata.parquet").exists()
    assert (tmp_path / "ckan-extensions-metadata.parquet").exists()

    # Query should work
    sites_df = manager.get_sites_dataframe()
    assert len(sites_df) == 1
    assert sites_df.item(0, "name") == "testsite"

    sites = manager.get_sites()
    assert len(sites) == 1
    assert sites[0].num_datasets == 42


def test_ecosystem_manager_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the fallback mechanism resolves correctly."""
    # Mock Path.mkdir to raise PermissionError when trying to write to primary dir
    original_mkdir = Path.mkdir

    def mock_mkdir(self: Path, *args, **kwargs) -> None:
        if "ecosystem/data" in str(self).replace("\\", "/"):
            raise PermissionError("Permission Denied")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mock_mkdir)

    # Set up a fake HOME so we write testing output to tmp_path instead of real home
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")

    manager = EcosystemManager()

    assert "fakehome" in str(manager.data_dir)
    assert ".dartfx" in str(manager.data_dir)
