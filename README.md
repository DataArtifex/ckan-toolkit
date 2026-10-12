# dartfx-ckan

[![Development Status](https://img.shields.io/badge/status-early%20release-orange.svg)](https://github.com/DataArtifex/ckan-toolkit)
[![Documentation](https://img.shields.io/badge/docs-blue)](https://www.dataartifex.org/ckan-toolkit/)
[![Ask DeepWiki](https://img.shields.io/badge/Ask%20DeepWiki-AI%20Docs-5C54E5)](https://deepwiki.com/DataArtifex/ckan-toolkit)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Package Status](https://img.shields.io/badge/PyPI-not%20published-lightgrey)](https://github.com/DataArtifex/ckan-toolkit)
[![CI](https://github.com/DataArtifex/ckan-toolkit/actions/workflows/test.yml/badge.svg)](https://github.com/DataArtifex/ckan-toolkit/actions/workflows/test.yml)
[![Code style: Ruff](https://img.shields.io/badge/code%20style-ruff-261230.svg?logo=ruff&logoColor=D7FF64)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.txt)
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](CODE_OF_CONDUCT.md)

A high-level, type-safe Python toolkit and CLI for discovering, harvesting, and interacting with CKAN repositories worldwide.

## Overview

The purpose of this toolkit is to facilitate programmatic interactions with CKAN servers, catalogs, and ecosystems:
- **Global Repository Discovery**: Discover 600+ CKAN installations worldwide with metadata, versions, and country crosswalks.
- **Resilient Metadata Harvester**: Incremental harvesting engine with SHA-256 verification, manifest tracking, 24-hour catalog caching, and standardized error classification.
- **Multiple Metadata Formats**: Fetch and export CKAN package metadata in JSON (`json`), DCAT RDF/XML (`dcat`), JSON-LD (`jsonld`), Turtle (`ttl`), and dataset resources (`resources`).
- **Live Statistics & Health Monitoring**: Query server statistics, dataset counts, latency, and extensions across worldwide instances.
- **Ecosystem Data Analytics**: Native synchronization and local querying of CKAN Ecosystem datasets via Polars and Parquet.

## Installation

This project recommends using [uv](https://github.com/astral-sh/uv) for fast and reliable Python package management.

### Using uv (Recommended)

```bash
uv add dartfx-ckan
```

For development:
```bash
uv sync --all-groups
```

### Traditional Installation

```bash
pip install -e .
```

## Command Line Interface (CLI)

The package provides the `dartfx-ckan` CLI tool:

### 1. Global Installation Discovery

List and filter worldwide CKAN repositories:

```bash
# List top 10 CKAN installations
dartfx-ckan installations --limit 10

# Filter by country (ISO-2 code or country name)
dartfx-ckan installations --country ES
dartfx-ckan installations --country "United States"

# Export discovered servers to JSON or CSV
dartfx-ckan installations --country GB --format json
dartfx-ckan installations --limit 20 --format csv
```

### 2. Server Information & Capabilities

Inspect metadata, version, and active extensions:

```bash
# Inspect a live CKAN instance (via status_show)
dartfx-ckan info demo.ckan.org
dartfx-ckan info data.humdata.org

# Inspect instances where live status_show is restricted (falls back to ecosystem catalog)
dartfx-ckan info data.gov
```

### 3. Catalog Search & Dataset Inspection

Search for datasets and export records:

```bash
# Full-text dataset search
dartfx-ckan search "climate" --hostname demo.ckan.org --limit 10

# Inspect dataset metadata
dartfx-ckan dataset gold-prices --hostname demo.ckan.org

# Export in DCAT XML, JSON-LD, or Turtle
dartfx-ckan dataset my-dataset --hostname demo.ckan.org --export dcat
dartfx-ckan dataset my-dataset --hostname demo.ckan.org --export jsonld
```

### 4. Server Statistics & Monitoring

Check live latency, status badges, and dataset counts:

```bash
# Query all known CKAN installations
dartfx-ckan stats

# Query specific server with forced cache refresh
dartfx-ckan stats --server demo.ckan.org --refresh

# Filter stats by country
dartfx-ckan stats --country CA
```

### 5. Resilient Metadata Harvester

Incrementally harvest and synchronize datasets into structured local storage:

```bash
# Harvest datasets from a single server (default: JSON metadata)
dartfx-ckan harvest --server demo.ckan.org --limit 50 --repo-dir ./data

# Harvest multiple formats simultaneously (JSON, DCAT, Resources)
dartfx-ckan harvest --server demo.ckan.org --format json,dcat,resources

# Harvest with keyword filter and date filter
dartfx-ckan harvest --server demo.ckan.org --query "environment" --since 2024-01-01

# Dry-run mode
dartfx-ckan harvest --server demo.ckan.org --dry-run
```

### 6. Harvest Error Analytics

Inspect and breakdown errors recorded in repository manifests:

```bash
# Summary table of error categories
dartfx-ckan errors --repo-dir ./data

# Matrix breakdown by format
dartfx-ckan errors --repo-dir ./data --by-format

# Breakdown by server
dartfx-ckan errors --repo-dir ./data --by-server

# Detailed failed dataset IDs and HTTP snippets
dartfx-ckan errors --repo-dir ./data --details
```

### 7. Ecosystem Synchronization

```bash
# Synchronize CKAN Ecosystem catalog to local Parquet files
dartfx-ckan ecosystem sync
```

## Python API Usage

```python
from dartfx.ckan import (
    CKANServer,
    SearchParameters,
    fetch_ckan_installations,
    ServerHarvester,
    fetch_server_stats,
)

# 1. Discover worldwide installations
installations = fetch_ckan_installations(country="US")
for inst in installations[:5]:
    print(inst.name, inst.clean_hostname, inst.url)

# 2. Connect to a CKAN Server
server = CKANServer("demo.ckan.org")
print("Version:", server.info.ckan_version)
print("Title:", server.info.site_title)
print("Datasets:", server.stats.dataset_count)

# 3. Search datasets with typed parameters
params = SearchParameters(q="climate", rows=5, sort="metadata_modified desc")
results = server.search(params)
for pkg in results.get("results", []):
    print(pkg["title"], pkg["name"])

# 4. Programmatic Harvesting
harvester = ServerHarvester("demo.ckan.org", repo_root="./harvested_data")
sync_stats = harvester.sync(limit=10, metadata_formats=["json", "dcat"])
print(f"Added: {len(sync_stats['added'])}, Unchanged: {len(sync_stats['unchanged'])}")
```

## Server Compatibility & API Constraints

When interacting with worldwide CKAN servers, keep in mind several architectural and administrative constraints:

### 1. Apex Domains vs. Catalog Endpoints
Portals like `data.gov` or `open.canada.ca` host a static or CMS frontend (WordPress, Drupal, Cloud.gov Pages) on the apex domain, with CKAN hosted on a subdomain (e.g. `catalog.data.gov`) or subpath.
- Cloud.gov Pages and reverse proxies often restrict allowed HTTP methods to `GET` and `HEAD` (`access-control-allow-methods: GET, HEAD`).
- Standard CKAN client calls (which use HTTP `POST` for Action API endpoints) sent to the apex domain fail with **`HTTP 405 Method Not Allowed`**.

### 2. Data.gov Restrictions & Gateway Migration
- **Action API Lockdown**: Data.gov actively blocks direct anonymous requests to legacy CKAN Action API endpoints on `catalog.data.gov` (`package_search`, `status_show`) with policy restriction errors (`"Request not allowed by policy"`).
- **GSA API Gateway (v4)**: Data.gov has migrated programmatic catalog access to the GSA API Gateway (`https://api.gsa.gov/technology/datagov/v4/`), requiring an API key from [api.data.gov](https://api.data.gov). It does not expose standard open CKAN Action API endpoints for harvesting.
- **Federal Data Inventories**: Individual US federal agencies publish their public DCAT-US inventories at `https://<agency>.gov/data.json`.
- **Toolkit Fallback**: `dartfx-ckan info data.gov` transparently falls back to cached ecosystem directory metadata.

### 3. `status_show` Disablement & Security Hardening
Many enterprise and government CKAN instances intentionally disable or firewall `status_show` to prevent extension enumeration and version disclosure.
- `dartfx-ckan` automatically detects when `status_show` returns HTTP 405, 403, or 404, falling back to curated ecosystem installation metadata with an informative notice.

### 4. Metadata Formats: Native vs. Extensions
- **Native (Core CKAN)**: `json` (CKAN package JSON via `package_show`) and `resources` are supported out of the box on all standard CKAN instances.
- **Extension-Dependent**:
  - `dcat` (RDF/XML), `jsonld`, and `ttl` (Turtle) require [`ckanext-dcat`](https://github.com/ckan/ckanext-dcat) on the remote server.
  - OGC CSW and ISO 19139 require [`ckanext-spatial`](https://github.com/ckan/ckanext-spatial).
  - OAI-PMH (Dublin Core) requires [`ckanext-oaipmh`](https://github.com/geosolutions-it/ckanext-oaipmh).
  - Project Open Data `data.json` requires [`ckanext-datajson`](https://github.com/GSA/ckanext-datajson).

### 5. Rate Limiting, Bot Protection & Authentication
- **Bot Mitigation / WAF**: Deployments behind Cloudflare or AWS CloudFront may return `HTTP 403 Forbidden` or `HTTP 429 Too Many Requests` during rapid crawling. Use the `--workers` option (default: 4) to control concurrency.
- **Authentication**: Servers returning `HTTP 401 Unauthorized` require an API token, resolved via `DARTFX_CKAN_REPOSITORY_ROOT`, `.api_token`, or `CKAN_API_KEY`.

## Testing & Quality Assurance

```bash
# Run pytest test suite
uv run pytest

# Check static typing with Pyrefly
uv run pyrefly check src tests

# Run linter and formatter checks with Ruff
uv run ruff check .
uv run ruff format .
```

## License

This project is licensed under the MIT License. See [LICENSE.txt](./LICENSE.txt) for details.
