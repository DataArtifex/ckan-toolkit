# Technical Implementation Notes

## Architecture Overview

`dartfx-ckan` provides a type-safe, resilient Python toolkit and CLI for interacting with CKAN repositories, modeled after the reference architectures established in `dataverse-toolkit` and `nada-toolkit`.

The codebase is organized into modular layers:
1. **Repository Discovery & Models** (`ckan.py`, `models.py`)
2. **Core Server Interface** (`server.py`, `api.py`)
3. **Resilient Metadata Harvester & Sync Engine** (`harvester.py`)
4. **Ecosystem Analytics** (`ecosystem/`)
5. **Command Line Interface** (`cli.py`)

---

## 1. Global Repository Discovery (`ckan.py`)

- **`ServerInstallation`**: Represents a CKAN server with sanitized hostname, display name, version, dataset counts, and country codes.
- **Country Resolution**:
  - `COUNTRY_TO_ISO2`: Standardized ISO 3166-1 Alpha-2 dictionary.
  - `get_iso2_code`: Normalizes raw country strings into 2-letter codes.
  - `infer_country_from_hostname`: Resolves country code top-level domains (ccTLDs like `.uk`, `.ca`, `.es`, `.gov`) to ISO2 codes when metadata does not specify a country.
  - `matches_country`: Flexible matching supporting ISO-2 codes and substring name queries.
- **Discovery Strategy**:
  - Aggregates over 600 unique worldwide CKAN instances from local/remote ecosystem Parquet data (`ckan-sites-metadata.parquet`).
  - Merges with known major national/international default CKAN installations.
  - Supports synthesizing a fallback `ServerInstallation` for private or unlisted servers.

---

## 2. Server Abstraction (`server.py` & `api.py`)

- **`CKANServer`**:
  - Accepts a hostname, full URL, or `ServerInstallation`.
  - Automatically loads credentials from environment variables (`CKAN_API_KEY`, `DARTFX_CKAN_API_KEY`, `CKAN_API_TOKEN`).
  - Integrated with `requests_cache.CachedSession` for fast in-memory response caching.
  - Provides typed methods:
    - `search(params: SearchParameters)`: Structured querying with Solr syntax, filters (`fq`), and sorting.
    - `get_info_version()` & `get_info_server()`: Standardized server info and installed extension inspection with automatic ecosystem directory fallback when live `status_show` is restricted or unavailable.
    - `get_dataset(name_or_id)`: Typed `Dataset` retrieval.
    - `get_dataset_export(identifier, export_format)`: Formats including JSON, DCAT XML, JSON-LD, and Turtle.
    - `list_organizations()` / `get_organizations()`.

---

## 3. Resilient Metadata Harvester (`harvester.py`)

- **Incremental Synchronization**:
  - Compares remote dataset state against local manifest records (`.manifest.json`).
  - Computes SHA-256 hashes of downloaded content to detect additions, updates, and unchanged datasets.
  - Detects deletions when datasets are removed from the remote catalog.
  - Local file organization: `<repo_root>/<server_hostname>/<sanitized_pid>/metadata/<file_name>` (resolved via positional argument `OUTPUT_DIR`, `--repo-dir`, `DARTFX_CKAN_REPOSITORY_ROOT`, `DARTFX_CKAN_REPOSITORY`, `CKAN_REPOSITORY_ROOT`, `CKAN_REPOSITORY`, or current working directory).
- **Flexible Invocation & Parity**:
  - Supports both positional `OUTPUT_DIR` and `--repo-dir` / `-d` for storage paths.
  - Supports targeting single datasets/packages via `--package`, `--id`, `--pid`, `-p`.
  - Full flag aliases matching Dataverse and NADA: `--start-date` (`--since`), `--formats` (`--format`), `-n` (`--limit`), `--threads` (`--workers`), `--refresh` (`--refresh-catalog`), `--retry` (`--retry-errors`), `--verify-sha256` / `--force-download` (`--force-verify`), and `--key` (`--api-token`).
  - Automatic timestamped file logging (`harvester-YYYYMMDD-HHMMSS.log`) inside repository directory or `--log-file`.
  - Upfront execution configuration panel and parameter table prior to harvesting.
  - Two-level progress bars showing catalog pagination discovery followed by multi-threaded record downloads.
  - Per-server summary report table with clickable portal URLs, dataset counts, and addition/update/deletion/error statistics.
  - Automatic error diagnostic reporting on failures: summary by error category (% of total) and detailed records table with clickable links and failure reasons.
- **Supported Metadata Formats & Extension Requirements**:
  - The harvest engine applies strictly to metadata records (never downloading raw data payloads or file attachments).
  - Format requirements:
    - `json`: Standard CKAN package JSON (`.ckan.json`) — Core CKAN API (`package_show`).
    - `resources`: Dataset resource list (`.resources.json`) — Core CKAN API (`package_show`).
    - `dcat`: DCAT 2/3 RDF/XML (`.dcat.xml`) — Requires `ckanext-dcat` extension.
    - `jsonld`: DCAT JSON-LD (`.dcat.jsonld`) — Requires `ckanext-dcat` extension.
    - `ttl`: DCAT Turtle (`.dcat.ttl`) — Requires `ckanext-dcat` extension.
    - `schemaorg`: Schema.org Dataset JSON-LD (`.schemaorg.jsonld`) — Requires `ckanext-dcat` (`structured_data` plugin or `schemaorg` profile). Includes automatic HTML `<script type="application/ld+json">` scraping fallback.
    - `croissant`: MLCommons Croissant JSON-LD (`.croissant.jsonld`) — Requires `ckanext-dcat >= 2.3.0` (`croissant` plugin).
    - `ddi`: DDI-Codebook 2.5 XML (`.ddi.xml`) — Requires `ckanext-ddi` or DDI/XML resource attachments in the dataset.
  - Upfront extension verification: `fetch_server_extensions()` inspects the cached or live `extensions` list from `status_show`. `is_format_supported_on_server()` determines if each requested format is enabled on the server. If an extension is not installed (e.g. `dcat` without `ckanext-dcat`), the format is cleanly skipped with a clear warning and excluded from target sync sets to avoid false deletions.
  - `CKANServer.get_info_export_formats()`: Returns structured metadata on export formats, media types, required extensions, and harvestability. Displayed in `dartfx-ckan info` as a dedicated Rich table.
  - Format capabilities reporting in `dartfx-ckan stats`: Displays an interactive `Formats` column with color-coded badges (`[DCAT]`, `[Schema]`, `[Croissant]`, `[DDI]`), summary capability counts in the table caption, and filtering flags (`--croissant`, `--dcat`, `--schemaorg`, `--ddi`).
- **Multi-Threaded HTTP Execution**:
  - `stats`: Employs `ThreadPoolExecutor` to query installations in parallel (controlled by `--workers` / `--threads`, default: 8) and concurrently executes individual server endpoint probes (`status_show`, `package_search`, and `organization_list` via 3 parallel workers), reducing per-server latency to `max(t_probes)`.
  - `harvest`: Employs `ThreadPoolExecutor` within `ServerHarvester.sync()` to download metadata records (`fetch_dataset_record`) concurrently across worker threads (controlled by `--workers` / `--threads`, default: 4), with thread-safe result aggregation and atomic manifest persistence.
- **24-Hour Catalog & Stats Caching**:
  - Paginates `package_search` and caches catalog listings locally (`.catalog_cache.json`).
  - Stores server probe results (`.stats_cache.json`) to minimize network queries across repeated runs.
  - Bypassed on demand using `--refresh` / `--refresh-catalog`.
- **Standardized Error Classification**:
  - Categorizes harvest failures into consistent error types:
    - `Exporter Not Supported on Server`
    - `HTTP 401: Authentication Required (API Token)`
    - `HTTP 403: Restricted Dataset / Bot Protection (WAF)`
    - `HTTP 404: Dataset / Endpoint Not Found`
    - `HTTP 410: Dataset Deleted / Gone`
    - `HTTP 422: Unprocessable Entity`
    - `HTTP 5xx: Server Error`
    - `HTTP 429: Rate Limited`
    - `Request Timeout`
    - `Network / Connection Error`
    - `JSON / XML Parsing Error`
- **Error Analytics & Manifest Reporting**:
  - `analyze_harvest_errors`: Collects errors across manifests and aggregates counts by error category, format matrix, and server.
  - `render_harvest_errors`: Formats tables and breakdown matrices in Rich.

---

## 4. Token Resolution Hierarchy

API tokens are resolved dynamically without hardcoding:
1. Explicit CLI flag (`--api-token` / `-k`)
2. Server-specific directory token file (`<repo_root>/<host>/.api_token`)
3. Central repository tokens mapping (`<repo_root>/.ckan_tokens.json`)
4. Current working directory tokens (`.ckan_tokens.json` or `.tokens.json`)
5. Server-specific environment variable (`CKAN_API_TOKEN_<HOST>`)
6. Global environment variable (`CKAN_API_KEY`, `DARTFX_CKAN_API_KEY`, `CKAN_API_TOKEN`)

---

## 5. CLI Architecture (`cli.py`)

Built with `typer` and `rich`:
- **macOS Smart Dash Normalization**: Sanitizes `–` and `—` arguments to standard hyphens before parsing.
- **Output Formats**: Flexible display in interactive `table`, `json`, or `csv`.
- **Commands**:
  - `installations` (alias: `list`): Worldwide repository list with country filtering.
  - `info`: Server metadata and extension capabilities.
  - `search`: Full-text and filtered dataset search.
  - `dataset`: Metadata inspection and DCAT/JSON export.
  - `organizations`: Organization directory.
  - `stats`: Live server statistics, format capability indicators (DCAT, Schema.org, Croissant, DDI), latency indicators, and status badges with format filtering (`--croissant`, `--dcat`, `--schemaorg`, `--ddi`).
  - `harvest`: Incremental sync engine with real-time Rich progress bars.
  - `errors`: Diagnostic error report from repository manifests.
  - `ecosystem`: Management of official CKAN Ecosystem Parquet datasets.

---

## 6. Server Compatibility & API Constraints

### Apex Domain vs. Catalog Separation
- Large portal deployments frequently place CMS applications (WordPress, Drupal, Cloud.gov Pages) on apex domains (e.g. `data.gov`, `open.canada.ca`).
- Apex reverse proxies typically reject POST requests with `405 Method Not Allowed`, breaking `ckanapi.RemoteCKAN` POST calls.
- The toolkit resolves installation metadata from curated ecosystem directories and targets underlying catalog subdomains (`catalog.data.gov`) where appropriate.

### Data.gov Specific Restrictions
- Legacy CKAN Action API endpoints (`/api/3/action/package_search`, `/api/3/action/status_show`) are blocked by policy on `catalog.data.gov`.
- Public programmatic catalog access has transitioned to the GSA API Gateway (`https://api.gsa.gov/technology/datagov/v4/`) requiring `api.data.gov` API keys and proprietary REST endpoints rather than CKAN Action APIs.
- Individual US agencies maintain DCAT-US 1.1 JSON catalogs at `https://<agency>.gov/data.json`.
- The toolkit's `info` command catches `status_show` failures on `data.gov` and falls back to cached ecosystem directory records.

### `status_show` Disablement & Security Hardening
- Production servers frequently restrict `status_show` to prevent extension enumeration.
- `CKANServer.get_info_version()` and `CKANServer.get_info_server()` catch `status_show` exceptions and gracefully fall back to `ServerInstallation` metadata.

### Extension Dependencies
- Native core: `json` (`package_show`) and `resources`.
- Extensions required:
  - `ckanext-dcat`: DCAT RDF/XML (`.dcat.xml`), JSON-LD (`.dcat.jsonld`), and Turtle (`.dcat.ttl`).
  - `ckanext-spatial`: OGC CSW 2.0.2 (`/csw`) and ISO 19139 XML.
  - `ckanext-oaipmh`: OAI-PMH 2.0 (`/oai`) and Dublin Core.
  - `ckanext-datajson`: DCAT-US 1.1 `data.json`.
