import pytest

from dartfx.ckan import CKANServer, Dataset, ServerInfo, ServerStats


def test_public_exports_available():
    assert CKANServer is not None
    assert ServerInfo is not None
    assert ServerStats is not None
    assert Dataset is not None


def test_server_rejects_invalid_url():
    with pytest.raises(ValueError, match=r"server_url must be a valid HTTP\(S\) URL"):
        CKANServer("not-a-url")
