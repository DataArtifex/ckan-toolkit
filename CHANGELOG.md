# Changelog

## [Unreleased]

- Added `dartfx.ckan.ecosystem` module for local synchronization and querying of official CKAN Ecosystem datasets.
- Implemented `EcosystemManager` with intelligent caching and local `.parquet` storage using Polars.
- Added a Typer-based CLI (`dartfx-ckan`) with `ecosystem sync` support.
- Added a fallback caching mechanism to ensure write-ability across different deployment environments.
- Enhanced API security and reliability with default `User-Agent` headers.

## [0.1.1]

- Expanded `Dataset`, `Resource`, and `Organization` Pydantic models with comprehensive fields.
- Added `Tag` Pydantic model.
- Improved model validation support for standard CKAN metadata responses.

## [0.1.0]

- Added `CKANServer` high-level class for CKAN connectivity and catalog operations.
- Added typed Pydantic models for server info, stats, datasets, organizations, and resources.
- Added `CKANAPIClient` wrapper over `ckanapi` action calls with response validation.
- Added custom exception hierarchy for connection, request, and validation errors.
- Added unit tests for models, API client, and server behavior.
- Updated package exports and dependencies (`pydantic`, `polars`).
