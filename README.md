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

...

## Roadmap

...

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](./CONTRIBUTING.md) for guidelines and information on how to get started.
