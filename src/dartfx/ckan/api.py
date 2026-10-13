"""Low-level CKAN Action API client wrapper."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ckanapi import RemoteCKAN

from dartfx.ckan.__about__ import __version__
from dartfx.ckan.exceptions import CKANAPIRequestError, CKANConnectionError, CKANValidationError
from dartfx.ckan.models import Dataset, Organization, ServerInfo, ServerStats


class CKANAPIClient:
    """Thin wrapper over :class:`ckanapi.RemoteCKAN`.

    This class centralizes Action API calls and normalizes data into typed models.
    """

    def __init__(
        self,
        server_url: str,
        *,
        api_key: str | None = None,
        user_agent: str | None = None,
        remote_ckan: Any = None,
    ) -> None:
        """Initialize a CKAN API client.

        Args:
            server_url: Base URL of the CKAN server.
            api_key: Optional API key.
            user_agent: Optional user agent string.
            remote_ckan: Optional injected RemoteCKAN instance for testing.

        Raises:
            CKANConnectionError: If the RemoteCKAN client cannot be initialized.
        """
        try:
            ua = (
                user_agent
                or f"Mozilla/5.0 (compatible; dartfx-ckan/{__version__}; +https://github.com/DataArtifex/dartfx-ckan)"
            )
            self._remote = remote_ckan or RemoteCKAN(server_url, apikey=api_key, user_agent=ua)
        except Exception as exc:  # pragma: no cover - defensive guard for constructor failures
            msg = f"Failed to initialize CKAN connection for '{server_url}': {exc}"
            raise CKANConnectionError(msg) from exc

    def action(self, action_name: str, **kwargs: Any) -> Any:
        """Execute a CKAN Action API call.

        Args:
            action_name: CKAN action name, e.g. ``status_show``.
            **kwargs: Action payload parameters.

        Returns:
            Raw result from CKAN API.

        Raises:
            CKANAPIRequestError: If the action call fails.
        """
        try:
            return self._remote.call_action(action_name, data_dict=kwargs)
        except Exception as exc:
            msg = f"CKAN action '{action_name}' failed: {exc}"
            raise CKANAPIRequestError(msg) from exc

    def get_server_info(self) -> ServerInfo:
        """Fetch server metadata using the ``status_show`` action."""
        raw = self.action("status_show")
        if not isinstance(raw, dict):
            msg = "Expected a dictionary from status_show"
            raise CKANValidationError(msg)
        return ServerInfo.model_validate(raw)

    def get_server_stats(self) -> ServerStats:
        """Fetch aggregate server statistics from available actions."""
        package_search = self.action("package_search", q="*:*", rows=0)
        if not isinstance(package_search, dict):
            msg = "Expected a dictionary from package_search"
            raise CKANValidationError(msg)

        dataset_count = int(package_search.get("count", 0))

        organization_count = self._safe_len_action("organization_list")
        group_count = self._safe_len_action("group_list")
        user_count = self._safe_len_action("user_list", nullable=True)

        if organization_count is None:
            msg = "organization_list returned no usable count"
            raise CKANValidationError(msg)

        if group_count is None:
            msg = "group_list returned no usable count"
            raise CKANValidationError(msg)

        return ServerStats(
            dataset_count=dataset_count,
            organization_count=organization_count,
            group_count=group_count,
            project_count=group_count,
            user_count=user_count,
            resource_count=None,
        )

    def search_datasets(self, *, query: str, limit: int = 100, offset: int = 0) -> list[Dataset]:
        """Search datasets via ``package_search`` and return typed results."""
        raw = self.action("package_search", q=query, rows=limit, start=offset)
        if not isinstance(raw, dict):
            msg = "Expected a dictionary from package_search"
            raise CKANValidationError(msg)

        results = raw.get("results", [])
        if not isinstance(results, list):
            msg = "Expected 'results' to be a list in package_search response"
            raise CKANValidationError(msg)

        return [Dataset.model_validate(item) for item in results]

    def get_dataset(self, dataset_id_or_name: str) -> Dataset:
        """Fetch a single dataset via ``package_show``."""
        raw = self.action("package_show", id=dataset_id_or_name)
        if not isinstance(raw, dict):
            msg = "Expected a dictionary from package_show"
            raise CKANValidationError(msg)
        return Dataset.model_validate(raw)

    def list_organizations(self, *, limit: int = 100, offset: int = 0) -> list[Organization]:
        """List organizations via ``organization_list`` with ``all_fields`` enabled."""
        raw = self.action("organization_list", all_fields=True, limit=limit, offset=offset)
        if not isinstance(raw, Sequence):
            msg = "Expected a list from organization_list"
            raise CKANValidationError(msg)
        return [Organization.model_validate(item) for item in raw]

    def _safe_len_action(self, action_name: str, *, nullable: bool = False) -> int | None:
        """Return ``len(result)`` for list-like action results, with optional null fallback."""
        try:
            raw = self.action(action_name)
        except CKANAPIRequestError:
            if nullable:
                return None
            raise

        if isinstance(raw, Sequence):
            return len(raw)

        if nullable:
            return None

        msg = f"Expected a sequence from {action_name}"
        raise CKANValidationError(msg)
