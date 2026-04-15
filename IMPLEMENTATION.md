# Implementation Notes

## Overview

This initial implementation introduces a high-level CKAN server abstraction built on top of `ckanapi` with typed models powered by Pydantic.

The implementation follows the roadmap phases:

1. Create a class to describe and connect to a CKAN server
2. Call underlying API to gather server information
3. Gather server statistics
4. Browse and search catalog data

## Module Structure

- `src/dartfx/ckan/exceptions.py`
  - Custom exception hierarchy used across the package.
- `src/dartfx/ckan/models.py`
  - Pydantic models for server metadata, stats, datasets, organizations, and resources.
- `src/dartfx/ckan/api.py`
  - Low-level wrapper around `ckanapi.RemoteCKAN` that executes actions and validates responses.
- `src/dartfx/ckan/server.py`
  - Main `CKANServer` class exposing a simple, typed API for callers.
- `src/dartfx/ckan/ecosystem/`
  - Specialized module for interacting with the official CKAN Ecosystem catalog.
  - Implements local Parquet-based caching for high-performance querying of global CKAN site and extension metadata.
- `src/dartfx/ckan/cli.py`
  - Typer-based entrypoint for the `dartfx-ckan` command-line tool.

## Design Decisions

### Synchronous Core API

`ckanapi` is synchronous-first, so this first release keeps a synchronous core. This avoids hidden thread scheduling behavior and keeps error handling straightforward.

### Typed Boundaries

All server metadata and catalog responses are normalized through Pydantic models. This catches malformed responses early and provides stable, type-safe return values.

### Cached Server Metadata

`CKANServer.info` and `CKANServer.stats` are lazily fetched and cached. This keeps repeated access cheap while still allowing explicit refresh using `refresh_info()` and `refresh_stats()`.

### Explicit Error Surface

Low-level API failures are wrapped in custom exceptions:

- `CKANConnectionError`
- `CKANAPIRequestError`
- `CKANValidationError`

This keeps calling code independent from underlying transport exceptions.

### Ecosystem Synchronization & Local Cache

The `ecosystem` module is designed for performance and offline reliability. Rather than querying the live ecosystem catalog repeatedly, it synchronizes remote CSV datasets into local Parquet files.

- **Data Storage**: Uses `polars` for fast I/O and efficient Parquet storage.
- **Caching Strategy**: Primary storage is within the package directory (`.../ecosystem/data/`). A fallback mechanism redirects to `~/.dartfx/` if the package environment is read-only.
- **Validation**: Uses Pydantic models for individual record access while providing Polars DataFrames for analytical tasks.

## Future Work

- Add optional TTL-based cache expiry for `info` and `stats`
- Add async-compatible wrappers for concurrent catalog operations
- Extend statistics support with resource-level counts when available
- Add dedicated adapter support for CKAN deployment variations
