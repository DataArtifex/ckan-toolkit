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
  - Local file organization: `<repo_root>/<server_hostname>/<sanitized_pid>/metadata/<file_name>` (resolved via `--repo-dir`, `DARTFX_CKAN_REPOSITORY`, `CKAN_REPOSITORY_ROOT`, `CKAN_REPOSITORY`, or current working directory).
- **Supported Formats**:
  - `json`: Standard CKAN package JSON (`.ckan.json`).
  - `dcat`: DCAT 2/3 RDF/XML (`.dcat.xml`).
  - `jsonld`: DCAT JSON-LD (`.dcat.jsonld`).
  - `ttl`: DCAT Turtle (`.dcat.ttl`).
  - `resources`: Dataset resource list (`.resources.json`).
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
  - `installations`: Worldwide repository list with country filtering.
  - `info`: Server metadata and extension capabilities.
  - `search`: Full-text and filtered dataset search.
  - `dataset`: Metadata inspection and DCAT/JSON export.
  - `organizations`: Organization directory.
  - `stats`: Live server statistics, latency indicators, and status badges.
  - `harvest`: Incremental sync engine with real-time Rich progress bars.
  - `errors`: Diagnostic error report from repository manifests.
  - `ecosystem`: Management of official CKAN Ecosystem Parquet datasets.
