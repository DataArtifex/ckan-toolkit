"""High-level CKAN server abstraction."""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlparse

from dartfx.ckan.api import CKANAPIClient
from dartfx.ckan.models import Dataset, Organization, ServerInfo, ServerStats


class CKANClientProtocol(Protocol):
    """Protocol for CKAN client behavior consumed by :class:`CKANServer`."""

    def get_server_info(self) -> ServerInfo: ...

    def get_server_stats(self) -> ServerStats: ...

    def action(self, action_name: str) -> dict[str, str]: ...

    def search_datasets(self, *, query: str, limit: int = 100, offset: int = 0) -> list[Dataset]: ...

    def get_dataset(self, dataset_id_or_name: str) -> Dataset: ...

    def list_organizations(self, *, limit: int = 100, offset: int = 0) -> list[Organization]: ...


class CKANServer:
    """High-level, type-safe interface to a CKAN server."""

    def __init__(
        self,
        server_url: str,
        *,
        api_key: str | None = None,
        client: CKANClientProtocol | None = None,
    ) -> None:
        """Create a CKAN server handle.

        Args:
            server_url: Base URL of the CKAN server.
            api_key: Optional API key for authenticated endpoints.
            client: Optional injected API client for testing.

        Raises:
            ValueError: If the URL is invalid.
        """
        self._validate_url(server_url)
        self.server_url = server_url
        self._client = client or CKANAPIClient(server_url, api_key=api_key)
        self._info_cache: ServerInfo | None = None
        self._stats_cache: ServerStats | None = None

    @property
    def info(self) -> ServerInfo:
        """Return server metadata, cached after first fetch."""
        if self._info_cache is None:
            self._info_cache = self._client.get_server_info()
        return self._info_cache

    @property
    def stats(self) -> ServerStats:
        """Return server statistics, cached after first fetch."""
        if self._stats_cache is None:
            self._stats_cache = self._client.get_server_stats()
        return self._stats_cache

    def refresh_info(self) -> ServerInfo:
        """Refresh cached server metadata and return it."""
        self._info_cache = self._client.get_server_info()
        return self._info_cache

    def refresh_stats(self) -> ServerStats:
        """Refresh cached server stats and return them."""
        self._stats_cache = self._client.get_server_stats()
        return self._stats_cache

    def is_healthy(self) -> bool:
        """Return ``True`` when ``status_show`` succeeds."""
        try:
            self._client.action("status_show")
            return True
        except Exception:
            return False

    def list_datasets(self, *, limit: int = 100, offset: int = 0) -> list[Dataset]:
        """Return a paginated list of datasets."""
        return self._client.search_datasets(query="*:*", limit=limit, offset=offset)

    def search_datasets(self, query: str, *, limit: int = 100, offset: int = 0) -> list[Dataset]:
        """Return datasets matching a full-text query."""
        return self._client.search_datasets(query=query, limit=limit, offset=offset)

    def get_dataset(self, name_or_id: str) -> Dataset:
        """Return a single dataset by name or ID."""
        return self._client.get_dataset(name_or_id)

    def list_organizations(self, *, limit: int = 100, offset: int = 0) -> list[Organization]:
        """Return a paginated list of organizations."""
        return self._client.list_organizations(limit=limit, offset=offset)

    @staticmethod
    def _validate_url(server_url: str) -> None:
        """Validate that the input looks like an HTTP(S) URL."""
        parsed = urlparse(server_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            msg = "server_url must be a valid HTTP(S) URL"
            raise ValueError(msg)
