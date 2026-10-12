# Changelog

## [0.2.0]

- Added resilient ecosystem catalog fallback to `CKANServer.get_info_version()`, `CKANServer.get_info_server()`, and `dartfx-ckan info` when live `status_show` probes are unavailable, restricted, or fail with HTTP 405/403.
- Mirrored harvester and repository discovery features from reference `dataverse-toolkit` and `nada-toolkit` implementations.
- Added worldwide CKAN installation discovery (`fetch_ckan_installations`, `ServerInstallation`) spanning 600+ CKAN repositories.
- Added ISO 3166-1 country crosswalk (`COUNTRY_TO_ISO2`, `get_iso2_code`, `matches_country`) and automatic ccTLD domain inference.
- Implemented smart incremental metadata harvester (`ServerHarvester`, `harvest` command) supporting JSON, DCAT XML, JSON-LD, Turtle, and Resources.
- Added SHA-256 verification, manifest tracking (`.manifest.json`), and change/deletion detection.
- Added 24-hour catalog and statistics caching with `--refresh` support.
- Added error classification system (`classify_harvest_error`, `analyze_harvest_errors`, `errors` command).
- Added multi-server parallel statistics probing with latency indicator badges (`stats` command, `fetch_server_stats`).
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
