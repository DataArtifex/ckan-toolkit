# Changelog

## [0.2.0]

- Added dual version columns (`Live Ver` and `Dataset Ver`) to `stats` command table to contrast live probed versions against ecosystem dataset versions with automatic upgrade highlighting.
- Added subpath preservation (e.g. from `inst.url`) and automatic `/data` subpath fallback probing in `fetch_server_stats`, enabling accurate stats for subpath-mounted CKAN portals such as `data.gov.au/data`, `data.overheid.nl/data`, and `data.bris.ac.uk/data`.
- Enhanced bot protection / WAF detection in `_probe_ckan_url` to detect HTML challenge signatures (Anubis, PerimeterX, Cloudflare, DDoS-Guard, etc.) across both HTTP 200 and 403 responses.
- Updated default `User-Agent` to `Mozilla/5.0 (compatible; dartfx-ckan/{version}; +https://github.com/DataArtifex/dartfx-ckan)` removing WAF/bot triggers (`Harvester`), and added automatic browser User-Agent fallback when servers return HTTP 403.
- Updated `stats` command table to display the server hostname as an active clickable link (with automatic `http`/`https` fallback awareness) to open the portal homepage.
- Aligned SSL/HTTP error message handling and diagnostics on the `nada-toolkit` implementation: added `abbreviate_error()`, enhanced `classify_harvest_error()` with SSL/TLS and network error categories, added parked/domain-for-sale detection (`_is_parked_or_domain_sale`), and added automatic HTTP fallback when HTTPS fails SSL verification in `stats` command.
- Documented server compatibility, apex domain separation, Data.gov API restrictions, `status_show` hardening, and metadata standard requirements across `README.md`, `IMPLEMENTATION.md`, and Sphinx docs.
- Added support for `DARTFX_CKAN_REPOSITORY_ROOT`, `CKAN_REPOSITORY_ROOT`, and `CKAN_REPOSITORY` environment variables alongside `DARTFX_CKAN_REPOSITORY` for harvest, errors, and stats repository root resolution.
- Added resilient ecosystem catalog fallback to `CKANServer.get_info_version()`, `CKANServer.get_info_server()`, and `dartfx-ckan info` when live `status_show` probes are unavailable, restricted, or fail with HTTP 405/403.
- Mirrored harvester and repository discovery features from reference `dataverse-toolkit` and `nada-toolkit` implementations.
- Added worldwide CKAN installation discovery (`fetch_ckan_installations`, `ServerInstallation`) spanning 600+ CKAN repositories.
- Added ISO 3166-1 country crosswalk (`COUNTRY_TO_ISO2`, `get_iso2_code`, `matches_country`) and automatic ccTLD domain inference.
- Implemented smart incremental metadata harvester (`ServerHarvester`, `harvest` command) supporting JSON, DCAT XML, JSON-LD, Turtle, and Resources.
- Added SHA-256 verification, manifest tracking (`.manifest.json`), and change/deletion detection.
- Added 24-hour catalog and statistics caching with `--refresh` support.
- Added error classification system (`classify_harvest_error`, `analyze_harvest_errors`, `errors` command).
- Added multi-server parallel statistics probing with latency indicator badges and dynamic progress bar tracking (`stats` command, `fetch_server_stats`).
- Added graceful `Ctrl-C` (`KeyboardInterrupt`) cancellation handling for `stats` and `harvest`, preventing transient `cannot schedule new futures after interpreter shutdown` errors from leaking or being saved into local cache.
- Added multi-threaded HTTP execution for `stats` (concurrent endpoint probes and server queries) and `harvest` (concurrent dataset metadata record downloads) with `--workers` / `--threads` / `-w` CLI options.
- Expanded `CKANServer` with `SearchParameters`, export formats, version inspection, and `requests-cache` session caching.
- Enhanced `dartfx-ckan` CLI with `installations`, `info`, `search`, `dataset`, `organizations`, `stats`, `harvest`, and `errors` commands.
- Migrated static analysis from Mypy to Pyrefly and updated dependencies in `pyproject.toml`.
- Added pre-commit runner script (`scripts/precommit_uv_run.sh`) and updated `.pre-commit-config.yaml`.

## [0.1.1]

- Expanded `Dataset`, `Resource`, and `Organization` Pydantic models with comprehensive fields.
- Added `Tag` Pydantic model.
- Improved model validation support for standard CKAN metadata responses.
- Added `dartfx.ckan.ecosystem` module with `EcosystemManager` for Parquet caching and querying.

## [0.1.0]

- Added `CKANServer` high-level class for CKAN connectivity and catalog operations.
- Added typed Pydantic models for server info, stats, datasets, organizations, and resources.
- Added `CKANAPIClient` wrapper over `ckanapi` action calls with response validation.
- Added custom exception hierarchy for connection, request, and validation errors.
- Added unit tests for models, API client, and server behavior.
