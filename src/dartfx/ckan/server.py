"""High-level CKAN server abstraction."""

from __future__ import annotations

import os
from typing import Any, Protocol
from urllib.parse import urlparse

import requests
import requests_cache

from dartfx.ckan.__about__ import __version__
from dartfx.ckan.api import CKANAPIClient
from dartfx.ckan.ckan import SearchParameters, ServerInstallation, fetch_ckan_installations
from dartfx.ckan.exceptions import CKANAPIRequestError
from dartfx.ckan.models import Dataset, Organization, ServerInfo, ServerStats


class CKANClientProtocol(Protocol):
    """Protocol for CKAN client behavior consumed by :class:`CKANServer`."""

    def get_server_info(self) -> ServerInfo: ...

    def get_server_stats(self) -> ServerStats: ...

    def action(self, action_name: str, **kwargs: Any) -> Any: ...

    def search_datasets(self, *, query: str, limit: int = 100, offset: int = 0) -> list[Dataset]: ...

    def get_dataset(self, dataset_id_or_name: str) -> Dataset: ...

    def list_organizations(self, *, limit: int = 100, offset: int = 0) -> list[Organization]: ...


class CKANServer:
    """High-level, type-safe interface to a CKAN server."""

    def __init__(
        self,
        server: str | ServerInstallation | None = None,
        *,
        server_url: str | None = None,
        api_key: str | None = None,
        client: CKANClientProtocol | None = None,
        session: requests_cache.CachedSession | None = None,
        lookup_installation: bool = True,
        ssl_verify: bool | str = True,
        **kwargs: Any,  # noqa: ARG002
    ) -> None:
        """Create a CKAN server handle.

        Args:
            server: Base URL, hostname, or ServerInstallation.
            server_url: Deprecated alias for server.
            api_key: Optional API key for authenticated endpoints.
            client: Optional injected API client for testing.
            session: Optional requests_cache CachedSession.
            lookup_installation: Whether to match known registry installations.
            ssl_verify: SSL verification flag.

        Raises:
            ValueError: If the URL or server name is invalid.
        """
        raw_server = server if server is not None else server_url
        if raw_server is None:
            raw_server = os.environ.get("CKAN_SERVER") or os.environ.get("CKAN_HOSTNAME") or "demo.ckan.org"

        if api_key is None:
            api_key = (
                os.environ.get("DARTFX_CKAN_API_KEY")
                or os.environ.get("CKAN_API_KEY")
                or os.environ.get("CKAN_API_TOKEN")
            )

        if isinstance(raw_server, ServerInstallation):
            server_inst = raw_server
            if lookup_installation and not server_inst.name and server_inst.clean_hostname:
                for inst in fetch_ckan_installations(target_server=server_inst.clean_hostname, fallback_unlisted=False):
                    if inst.clean_hostname.lower() == server_inst.clean_hostname.lower():
                        server_inst = inst
                        break
            clean_url = server_inst.url
        elif isinstance(raw_server, str):
            clean_s = raw_server.strip()
            if not clean_s.startswith("http://") and not clean_s.startswith("https://"):
                if "." not in clean_s or " " in clean_s:
                    self._validate_url(clean_s)
                clean_url = f"https://{clean_s}"
            else:
                clean_url = clean_s

            self._validate_url(clean_url)
            clean_host = clean_url.replace("https://", "").replace("http://", "").strip("/")
            if "/" in clean_host:
                clean_host = clean_host.split("/", 1)[0]
            server_inst = ServerInstallation(hostname=clean_host)

            if lookup_installation:
                for inst in fetch_ckan_installations(target_server=clean_host, fallback_unlisted=False):
                    if inst.clean_hostname.lower() == clean_host.lower():
                        server_inst = inst
                        break
        else:
            raise TypeError("server must be either a hostname, a URL, or a ServerInstallation")

        self.installation = server_inst
        self.server_url = clean_url
        self.api_key = api_key
        if ssl_verify is True and clean_url.startswith("https://"):
            from dartfx.ckan.harvester import get_ca_bundle_for_host

            cached_bundle = get_ca_bundle_for_host(server_inst.clean_hostname)
            if cached_bundle:
                ssl_verify = cached_bundle
        self.ssl_verify: bool | str = ssl_verify
        self._session = session or requests_cache.CachedSession(backend="memory", cache_name="ckan")
        self._client = client or CKANAPIClient(self.server_url, api_key=api_key)
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

    def get_info_version(self) -> dict[str, Any]:
        """Get version metadata from the server.

        Attempts to retrieve live server metadata via ``status_show``; if that action
        fails or is restricted, falls back to cached ecosystem installation details.
        """
        is_live = True
        try:
            info = self.info
            version = info.ckan_version or self.installation.version or "N/A"
            site_title = info.site_title or self.installation.name or "N/A"
            site_url = info.site_url or self.installation.url or self.server_url
        except Exception:
            is_live = False
            version = self.installation.version or "N/A"
            site_title = self.installation.name or "N/A"
            site_url = self.installation.url or self.server_url
            if not self.installation.name and not self.installation.version:
                raise

        return {
            "version": version,
            "live": is_live,
            "data": {
                "version": version,
                "site_title": site_title,
                "site_url": site_url,
            },
        }

    def get_info_server(self) -> dict[str, Any]:
        """Get high-level server metadata from the server.

        Attempts to retrieve live server metadata via ``status_show``; if that action
        fails or is restricted, falls back to cached ecosystem installation details.
        """
        is_live = True
        try:
            info = self.info
            title = info.site_title or self.installation.name or "N/A"
            description = info.site_description or self.installation.description or "N/A"
            exts = info.extensions or (
                self.installation.extensions if isinstance(self.installation.extensions, list) else []
            )
        except Exception:
            is_live = False
            title = self.installation.name or "N/A"
            description = self.installation.description or "N/A"
            if isinstance(self.installation.extensions, list):
                exts = self.installation.extensions
            elif isinstance(self.installation.extensions, str):
                exts = [e.strip() for e in self.installation.extensions.split(",") if e.strip()]
            else:
                exts = []
            if not self.installation.name and not self.installation.description:
                raise

        return {
            "server": self.installation.clean_hostname,
            "live": is_live,
            "data": {
                "message": title if title != "N/A" else self.installation.clean_hostname,
                "title": title,
                "description": description,
                "extensions": exts,
            },
        }

    def get_info_export_formats(self) -> dict[str, Any]:
        """Identify available metadata export and harvest formats based on deployed extensions and capabilities."""
        clean_host = self.installation.clean_hostname
        ext_list: list[str] = []
        try:
            server_info = self.get_info_server()
            raw_exts = server_info.get("data", {}).get("extensions", [])
            if isinstance(raw_exts, list):
                ext_list = [str(e).strip().lower() for e in raw_exts if e]
            elif isinstance(raw_exts, str):
                ext_list = [e.strip().lower() for e in raw_exts.split(",") if e.strip()]
        except Exception:
            if isinstance(self.installation.extensions, list):
                ext_list = [str(e).strip().lower() for e in self.installation.extensions if e]
            elif isinstance(self.installation.extensions, str):
                ext_list = [e.strip().lower() for e in self.installation.extensions.split(",") if e.strip()]

        has_dcat: bool | None = None
        has_schemaorg: bool = False
        has_croissant: bool = False
        has_ddi: bool = False

        if ext_list:
            has_dcat = any("dcat" in e for e in ext_list)
            has_schemaorg = any("structured_data" in e or "dcat" in e for e in ext_list)
            has_croissant = any("croissant" in e for e in ext_list)
            has_ddi = any("ddi" in e for e in ext_list)
        else:
            # Fallback probe
            try:
                headers = {
                    "User-Agent": (
                        f"Mozilla/5.0 (compatible; dartfx-ckan/{__version__}; +https://github.com/DataArtifex/dartfx-ckan)"
                    )
                }
                if self.api_key:
                    headers["Authorization"] = self.api_key
                r = self._session.get(
                    f"https://{clean_host}/catalog.xml",
                    headers=headers,
                    timeout=5,
                    verify=self.ssl_verify,
                )
                if r.status_code == 200:
                    has_dcat = True
                    has_schemaorg = True
                elif r.status_code in (404, 501):
                    has_dcat = False
            except Exception:
                has_dcat = False

        dcat_available = bool(has_dcat)
        schemaorg_available = bool(has_schemaorg)
        croissant_available = bool(has_croissant)
        ddi_available = bool(has_ddi)

        formats: dict[str, dict[str, Any]] = {
            "json": {
                "displayName": "CKAN Package JSON",
                "mediaType": "application/json",
                "requiredExtension": None,
                "isHarvestable": True,
                "isVisibleInUserInterface": True,
            },
            "resources": {
                "displayName": "Dataset Resources JSON",
                "mediaType": "application/json",
                "requiredExtension": None,
                "isHarvestable": True,
                "isVisibleInUserInterface": True,
            },
            "dcat": {
                "displayName": "DCAT 2/3 RDF/XML",
                "mediaType": "application/rdf+xml",
                "requiredExtension": "ckanext-dcat",
                "isHarvestable": dcat_available,
                "isVisibleInUserInterface": dcat_available,
            },
            "jsonld": {
                "displayName": "DCAT JSON-LD",
                "mediaType": "application/ld+json",
                "requiredExtension": "ckanext-dcat",
                "isHarvestable": dcat_available,
                "isVisibleInUserInterface": dcat_available,
            },
            "ttl": {
                "displayName": "DCAT Turtle",
                "mediaType": "text/turtle",
                "requiredExtension": "ckanext-dcat",
                "isHarvestable": dcat_available,
                "isVisibleInUserInterface": dcat_available,
            },
            "schemaorg": {
                "displayName": "Schema.org Dataset JSON-LD",
                "mediaType": "application/ld+json",
                "requiredExtension": "ckanext-dcat (structured_data)",
                "isHarvestable": schemaorg_available,
                "isVisibleInUserInterface": schemaorg_available,
            },
            "croissant": {
                "displayName": "MLCommons Croissant JSON-LD",
                "mediaType": "application/ld+json",
                "requiredExtension": "ckanext-dcat (croissant)",
                "isHarvestable": croissant_available,
                "isVisibleInUserInterface": croissant_available,
            },
            "ddi": {
                "displayName": "DDI-Codebook 2.5 XML",
                "mediaType": "application/xml",
                "requiredExtension": "ckanext-ddi / Resources",
                "isHarvestable": ddi_available,
                "isVisibleInUserInterface": ddi_available,
            },
        }
        return {
            "status": "OK",
            "data": formats,
        }

    def search(self, params: SearchParameters | None = None) -> dict[str, Any]:
        """Search datasets using SearchParameters."""
        p = params or SearchParameters()
        q = p.q or "*:*"
        rows = p.rows if p.rows is not None else 25
        start = p.start if p.start is not None else 0

        kwargs: dict[str, Any] = {"q": q, "rows": rows, "start": start}
        if p.fq:
            kwargs["fq"] = p.fq
        if p.sort:
            kwargs["sort"] = p.sort

        try:
            raw = self._client.action("package_search", **kwargs)
            if isinstance(raw, dict):
                return raw
        except Exception:
            pass

        # Fallback to search_datasets
        datasets = self._client.search_datasets(query=q, limit=rows, offset=start)
        return {
            "count": len(datasets),
            "results": [d.model_dump() for d in datasets],
        }

    def list_datasets(self, *, limit: int = 100, offset: int = 0) -> list[Dataset]:
        """Return a paginated list of datasets."""
        return self._client.search_datasets(query="*:*", limit=limit, offset=offset)

    def search_datasets(self, query: str, *, limit: int = 100, offset: int = 0) -> list[Dataset]:
        """Return datasets matching a full-text query."""
        return self._client.search_datasets(query=query, limit=limit, offset=offset)

    def get_dataset(self, name_or_id: str) -> Dataset:
        """Return a single dataset by name or ID."""
        return self._client.get_dataset(name_or_id)

    def get_dataset_export(self, identifier: str, export_format: str = "json") -> str | bytes | dict[str, Any]:
        """Get dataset metadata in JSON, DCAT XML, JSON-LD, Turtle or raw format."""
        fmt = export_format.strip().lower()
        if fmt in ("json", "native", "package"):
            raw = self._client.action("package_show", id=identifier)
            return raw

        # Direct HTTP download for DCAT extensions if present
        clean_host = self.installation.clean_hostname
        headers = {
            "User-Agent": (
                f"Mozilla/5.0 (compatible; dartfx-ckan/{__version__}; +https://github.com/DataArtifex/dartfx-ckan)"
            )
        }
        if self.api_key:
            headers["Authorization"] = self.api_key

        if fmt in ("dcat", "xml", "rdf"):
            url = f"https://{clean_host}/dataset/{identifier}.xml"
        elif fmt in ("jsonld", "dcat_json"):
            url = f"https://{clean_host}/dataset/{identifier}.jsonld"
        elif fmt in ("ttl", "turtle"):
            url = f"https://{clean_host}/dataset/{identifier}.ttl"
        else:
            url = f"https://{clean_host}/dataset/{identifier}.{fmt}"

        try:
            resp = self._session.get(url, headers=headers, verify=self.ssl_verify, timeout=15)
        except requests.exceptions.SSLError as ssl_err:
            if url.startswith("https://") and "unable to get local issuer certificate" in str(ssl_err):
                try:
                    from dartfx.ckan.harvester import resolve_aia_intermediate_ca

                    bundle = resolve_aia_intermediate_ca(clean_host)
                    if bundle:
                        self.ssl_verify = str(bundle)
                        resp = self._session.get(url, headers=headers, verify=self.ssl_verify, timeout=15)
                    else:
                        raise
                except Exception:
                    raise ssl_err from None
            else:
                raise
        if resp.status_code == 200:
            return resp.text
        msg = f"Export format '{export_format}' not available for dataset '{identifier}' (HTTP {resp.status_code})"
        raise CKANAPIRequestError(msg)

    def list_organizations(self, *, limit: int = 100, offset: int = 0) -> list[Organization]:
        """Return a paginated list of organizations."""
        return self._client.list_organizations(limit=limit, offset=offset)

    def get_organizations(self, *, limit: int = 100, offset: int = 0) -> list[Organization]:
        """Alias for list_organizations."""
        return self.list_organizations(limit=limit, offset=offset)

    def get_organization(self, name_or_id: str) -> Organization:
        """Return a single organization by name or ID."""
        raw = self._client.action("organization_show", id=name_or_id)
        if not isinstance(raw, dict):
            raise CKANAPIRequestError(f"Expected dict for organization '{name_or_id}'")
        return Organization.model_validate(raw)

    @staticmethod
    def _validate_url(server_url: str) -> None:
        """Validate that the input looks like an HTTP(S) URL."""
        parsed = urlparse(server_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            msg = "server_url must be a valid HTTP(S) URL"
            raise ValueError(msg)
