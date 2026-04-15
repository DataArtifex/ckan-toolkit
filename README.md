# dartfx-ckan

[![PyPI - Version](https://img.shields.io/pypi/v/dartfx-ckan.svg)](https://pypi.org/project/dartfx-ckan)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/dartfx-ckan.svg)](https://pypi.org/project/dartfx-ckan)
[![CI](https://github.com/DataArtifex/dartfx-ckan/actions/workflows/test.yml/badge.svg)](https://github.com/DataArtifex/dartfx-ckan/actions/workflows/test.yml)
[![License](https://img.shields.io/github/license/DataArtifex/dartfx-ckan.svg)](https://github.com/DataArtifex/dartfx-ckan/blob/main/LICENSE.txt)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](code_of_conduct.md)
[![DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/DataArtifex/dartfx-ckan)

**This project is in its early development stages. Stability is not guaranteed, and documentation is limited. We welcome your feedback and contributions.**

## Overview

The purpose of this toolkit is to facilitate interactions with CKAN servers and catalogs.
It provides a high-level, type-safe Python toolkit for programmatic interaction with CKAN repositories, focusing on discovery, metadata retrieval, and dataset access.


## Bootstrapping a New Project

If you are using this repository as a template, run the included rename script to set your project and package names:

```bash
./rename.sh "my-project-name" "my_package_name"
```

2. **Register with DeepWiki**: To ensure your documentation is indexed and discoverable by AI agents, register your new repository at [DeepWiki.com](https://deepwiki.com/).

## Installation

This project recommends using [uv](https://github.com/astral-sh/uv) for fast and reliable Python package management.

### Using uv (Recommended)

To set up the development environment with `uv`:

```bash
# Install dependencies and create virtual environment
uv sync
```

### Using Hatch

You can also use [Hatch](https://hatch.pypa.io/) directly:

```bash
# Run tests
hatch run test

# Enter the default shell
hatch shell
```

### Local Installation

For traditional installation:

```bash
pip install -e .
```


## Development

### Version Management
Versions are managed dynamically in `src/dartfx/ckan/__about__.py`. You can use `hatch version` to view or bump the version.

### Secret Management
For local development, create a `.env` file in the root directory. This file is git-ignored and can be used to store local API keys or configuration. These are automatically loaded by the test suite.

### Running Tests
```bash
uv run pytest
```

### Building Documentation
```bash
hatch run docs:build
```



## Usage

```python
from dartfx.ckan import CKANServer

server = CKANServer("https://demo.ckan.org")

# Server metadata
print(server.info.ckan_version)
print(server.info.site_title)

# Server statistics
print(server.stats.dataset_count)
print(server.stats.organization_count)

# Catalog browsing and search
datasets = server.list_datasets(limit=5)
search_results = server.search_datasets("water", limit=5)
dataset = server.get_dataset("sample-dataset")
organizations = server.list_organizations(limit=5)

# CKAN Ecosystem synchronization and querying
from dartfx.ckan.ecosystem import EcosystemManager

manager = EcosystemManager()
manager.sync()  # Syncs latest site and extension metadata to local Parquet files

# Access as Polars DataFrame for fast analytics
df_sites = manager.get_sites_dataframe()
df_extensions = manager.get_extensions_dataframe()

# Access as typed Pydantic models
sites = manager.get_sites()
```

## Command Line Interface

The toolkit includes a `dartfx-ckan` CLI for administrative tasks:

```bash
# Synchronize ecosystem datasets
dartfx-ckan ecosystem sync

# Show verbose output and API calls
dartfx-ckan ecosystem sync --verbose

# Force refresh even if local data is up-to-date
dartfx-ckan ecosystem sync --force
```

## Roadmap

- [x] Create a class to describe and connect to a CKAN server
- [x] Gather server information (version, extensions, basic metadata)
- [x] Gather server statistics (#datasets, #organizations, #groups/projects)
- [x] Browse and search catalog data
- [x] Implement CKAN Ecosystem synchronization and local querying (Parquet/Polars)
- [x] Added `dartfx-ckan` CLI for ecosystem management
- [ ] Add async wrappers for parallel API operations
- [ ] Add adapter strategy for deployment-specific CKAN variations

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](./CONTRIBUTING.md) for guidelines and information on how to get started.
