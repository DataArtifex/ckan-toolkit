# AI Agent Instructions

Welcome, fellow AI. This file provides context and instructions for working on this repository effectively.

## Project Specifications

The purpose of this toolkit is to facilitate interactions with CKAN servers and catalogs.
It provides a high-level, type-safe Python toolkit for programmatic interaction with CKAN repositories.
Key capabilities include:
- Discovering and retrieving datasets from CKAN servers.
- Browsing catalogs and searching for datasets.
- Handling CKAN metadata and resources.

### Architecture

- **CKAN Python Package**: This toolkit is built on top of the CKAN Action API python package (ckanapi)
    - The Platform documentation is available at https://docs.ckan.org/
    - The Action API specific documentation is available at https://docs.ckan.org/en/latest/api/index.html
- **Pydantic Models**: All CKAN metadata and API responses are modeled using Pydantic for validation and type safety.
- **Async Support**: Where possible, asynchronous I/O is used to handle multiple API requests efficiently.
- **Adapter Pattern**: The toolkit can be extended to support different CKAN versions or customized deployments.

## Roadmap

### Server
- Create a class to describe and connect to a CKAN server
- Call the underlying API to gather information on the server
 - version, extensions, and other available characteristics
- Gather server statistics
    - #datasets, #organizations, #projects, etc.
- Browse and search the catalog



## Project Stack

- **Language**: Python 3.12+ (Strictly required)
- **Dependency Management & Workflow**: [uv](https://github.com/astral-sh/uv) (Recommended) and [Hatch](https://hatch.pypa.io/).
- **Linting & Formatting**: [Ruff](https://docs.astral.sh/ruff/) (extremely fast linter/formatter).
- **Git Hooks**: [pre-commit](https://pre-commit.com/) (ensures code quality before commits).
- **Testing**: [pytest](https://docs.pytest.org/) with [coverage](https://coverage.readthedocs.io/).
- **Documentation**: [Sphinx](https://www.sphinx-doc.org/) with [MyST-Parser](https://myst-parser.readthedocs.io/) (Markdown support) and [Read the Docs theme](https://sphinx-rtd-theme.readthedocs.io/).
- **Version Control**: Git.

## Bootstrapping a New Project

> **Note for agents**: This section applies only when using this repo as a project template to start a new project. If you are working on the existing `dartfx-ckan` codebase, skip this section.

To rename the project and package from the template defaults:
1. Run `./rename.sh "new-project-name" "new_package_name"`
2. Run `uv sync` to refresh the environment.
3. **DeepWiki**: Register the new project at [DeepWiki.com](https://deepwiki.com/) to enable AI-optimized documentation indexing.

## Environment Management

This project uses `hatch` for environment management, but `uv` is preferred for speed.

- To run tests: `uv run pytest` or `hatch run test`
- To check types: `uv run mypy src tests` or `hatch run types:check`
- To build docs: `uv run sphinx-build -b html docs/source docs/build/html` or `hatch run docs:build`

## Coding Standards

- Follow PEP 8.
- Use type hints for all public APIs.
- Docstrings should be in Google style or NumPy style (Sphinx compatible).
- Prefer `pathlib` over `os.path`.
- Prefer Pydantic for modeling over Python dataclasses or other similar packages
- Prefer Polars package for data management over Pandas or other similar packages
- **Dependency note**: Pydantic and Polars are not yet listed in `pyproject.toml`. Add them as dependencies before writing code that uses them.
- Strictly follow the project's Ruff configuration. Run `uv run ruff check .` and `uv run ruff format .` to ensure compliance before submitting changes.
- Type checking is performed with `mypy`. No `[tool.mypy]` configuration is currently defined in `pyproject.toml`; run `uv run mypy src tests` and resolve all errors before submitting.

## Testing Policy

- All new features must be accompanied by tests.
- Maintain or improve test coverage.
- Use `pytest` fixtures for setup/teardown.
- Tests are located in the `tests/` directory.

## Documentation Policy

- Documentation is located in the `docs/source` directory.
- Main documentation is in `.rst` or `.md` (via MyST).
- Keep `README.md` up to date with core installation and usage instructions.
- Keep a dedicated `IMPLEMENTATION.md` document up to date that describes the package/code technical implementation.
- Maintain `CHANGELOG.md` with every significant change, ensuring the latest version is always at the top using the version number as heading (e.g., `## [0.1.0]`). Use short, concise bullet points.


## Version Management

- This project uses **dynamic versioning** via Hatch.
- The source of truth for the version is located in: `src/dartfx/ckan/__about__.py`.
- To bump versions, modify that file manually or use `hatch version <segment>` (e.g., `hatch version minor`).
- Follow [Semantic Versioning (SemVer)](https://semver.org/).

## Secret Management

- **Local Development**: Use a `.env` file in the project root for local environment variables and secrets.
- **Loading**: Secrets are automatically loaded in tests via `tests/conftest.py` using `python-dotenv`.
- **Git Hygiene**: Never commit `.env` files. Ensure they are covered by `.gitignore`.
- **CI/CD**: Add secrets to GitHub Repository Secrets for use in GitHub Actions. Reference them in workflows as `${{ secrets.SECRET_NAME }}`.

## GitHub Actions CI/CD

- **CI**: Located in `.github/workflows/test.yml`. Runs tests and linting on push/PR to `main` across Ubuntu, macOS, and Windows.
- **Docs**: Located in `.github/workflows/sphinx.yaml`. Builds and deploys documentation to GitHub Pages on push to `main`.
- All workflows use `astral-sh/setup-uv` for fast execution and caching.

## Working with this Repo

1. **Analysis**: Always start by reviewing `pyproject.toml` and `src/` structure.
2. **Context**: Check `KIs/` (Knowledge Items) directory at the repo root if it exists — markdown files there contain domain-specific context and design decisions.
3. **Execution**: Use `uv` or `hatch` for running scripts and tests.
4. **Validation**: Always run `uv run ruff check .`, `uv run ruff format .`, and `uv run pytest` before finalizing changes.
5. **Contributions**: Follow the conventions in `CONTRIBUTING.md` and `CODE_OF_CONDUCT.md`.
