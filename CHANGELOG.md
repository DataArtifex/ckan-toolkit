# Changelog

## [0.2.0]

- **Machine-Actionable Standardized JSON Output & CLI Parity**:
  - Added `--json`, `--markdown`/`--md`, and `-o`/`--output` support to `dartfx-ckan list` and `installations`.
  - Standardized `installations`/`list` JSON schema (`platform="ckan"`, `hostname`, `url`, `country`, `country_code`).
  - Added standard `platform: "ckan"` and `version` properties to `stats` JSON records.
  - Standardized `harvest` JSON envelope (`--json`, `-o`/`--output`), emitting structured status, duration, summary counts (`datasets`, `added`, `updated`, `deleted`, `unchanged`, `errors`), server breakdowns, and error manifests with progress and banners silenced under `--json`.
  - Added `--json` flag to `errors` command for pipeline introspection.
- Fixed `tests/conftest.py` test suite execution in clean environments (such as CI runners without `click`) by safely guarding `click.testing` buffer workaround imports behind `try...except ImportError`.
- Fixed server probe false negatives on rate-limited servers (such as `transportdata.be`) by adding automatic sequential retry for transient HTTP 503/429 concurrency bursts and POST method fallback for `organization_list` endpoints requiring POST.
- Fixed HTTP error classification in `_probe_ckan_url` so 5xx and 429 response codes are properly identified as `Service Unavailable (503)`, `Rate Limited (429)`, or `Bad Gateway (502)` instead of defaulting to `Not CKAN Server`.
- Fixed format capability reporting consistency in `stats` table and exports so capability badges and format arrays are strictly gated behind verified active CKAN servers (`is_ckan`), preventing contradictory format displays for inactive or offline hosts.
- Added detection, reporting, and harvesting support for **Schema.org** (`schemaorg`), **MLCommons Croissant** (`croissant`), and **DDI** (`ddi`):
  - Expanded `CKANServer.get_info_export_formats()` to detect and report `schemaorg` (Schema.org Dataset JSON-LD via `structured_data` or `ckanext-dcat`), `croissant` (MLCommons Croissant JSON-LD via `ckanext-dcat >= 2.3.0`), and `ddi` (DDI-Codebook 2.5 XML via `ckanext-ddi` or dataset resource distributions).
  - Enhanced `dartfx-ckan info` to display availability, media types, required plugins, and harvestability status for all formats.
  - Enhanced `dartfx-ckan stats` with a dedicated `Formats` column displaying active capability badges (`[DCAT]`, `[Schema]`, `[Croissant]`, `[DDI]`).
  - Added format capability filtering options to `dartfx-ckan stats`: `--croissant`, `--dcat`, `--schemaorg`/`--schema`, and `--ddi`.
  - Added aggregated ecosystem capability metrics (`Capabilities: X DCAT • Y Schema.org • Z Croissant • W DDI`) to `stats` table caption and Markdown summary.
  - Added boolean capability flags (`has_dcat`, `has_schemaorg`, `has_croissant`, `has_ddi`) and `formats` array to JSON, Markdown, and CSV exports in `stats`.
  - Expanded `harvest` command to harvest `schemaorg` (with automatic fallback to dataset HTML `<script type="application/ld+json">` scraping), `croissant`, and `ddi` (via automatic resource attachment extraction).
- Added `list` command as an alias for `installations` in the CLI (`dartfx-ckan list`).
- Enhanced `info` command to identify and display metadata export formats supported by the target CKAN server based on deployed extensions (`ckanext-dcat` for `dcat`, `jsonld`, `ttl`; Core CKAN for `json`, `resources`), including media types and harvestability status.
- Added extension-aware metadata format verification to `harvest` (`fetch_server_extensions`, `is_format_supported_on_server`) to automatically detect missing extensions upfront and skip unsupported export formats with a clear warning instead of encountering runtime download errors.
- Clarified and enforced that the `harvest` command applies strictly to metadata records (`.ckan.json`, `.dcat.xml`, `.dcat.jsonld`, `.dcat.ttl`, `.resources.json`) and does not harvest data payload files.
- Brought CKAN `harvest` command up to par with `dataverse` and `nada` harvesters:
  - Added positional repository output directory argument (`output_dir`) alongside `--repo-dir` / `-d` with automatic fallback to environment variables and current directory.
  - Added target single dataset/package options: `--package`, `--id`, `--pid`, `-p` to sync individual records.
  - Added full CLI option aliases: `--start-date` (`--since`), `--formats` (`--format`), `-n` (`--limit`), `--threads` (`--workers`), `--refresh` (`--refresh-catalog`), `--retry` (`--retry-errors`), `--verify-sha256` and `--force-download` (`--force-verify`), and `--key` (`--api-token`).
  - Added automatic execution activity log generation (`harvester-YYYYMMDD-HHMMSS.log`) in the repository root directory (or `--log-file`).
  - Added Rich execution configuration summary panel and parameter table prior to sync.
  - Added two-level live progress tracking: per-server catalog query progress (`catalog_progress_callback`) and dataset download progress (`progress_callback`).
  - Enhanced error resiliency across servers during sync runs so individual server failures do not abort multi-server harvesting.
  - Added automatic server API token persistence via `save_server_token` when `--api-token` / `--key` is provided.
  - Added per-server summary report table displaying clickable server URLs, country, datasets, additions (+), updates (Δ), unchanged (=), deletions (-), and errors (!).
  - Added rich completion summary panel with colored status borders.
  - Added automatic error diagnostic reporting on failures: summary table by error category (% of total), detailed records table with clickable dataset URLs, error categories, and failure reasons, and a helpful inspection tip.
- Added Authority Information Access (AIA) intermediate CA certificate chasing (`resolve_aia_intermediate_ca`, `get_ca_bundle_for_host`) to automatically repair missing intermediate CA certificate chains for SSL/TLS resilience.
- Added tri-state server availability classification (`classify_server_availability`: accessible, restricted, offline) and summary metrics to `stats` command.
- Added JSON and Markdown output formats (`--format json|markdown`, `--json`, `--markdown`/`--md`) and file export (`-o`/`--output`) to `stats` command.
- Enhanced `stats` command with sorting options (`--sort`, `--desc`, `--asc`) across name, datasets, organizations, country, latency, and status.
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
