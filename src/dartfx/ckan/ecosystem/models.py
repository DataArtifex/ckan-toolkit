"""Pydantic models for CKAN Ecosystem datasets."""

from pydantic import BaseModel


class EcosystemSites(BaseModel):
    """Model representing a CKAN Ecosystem site record."""

    tstamp: str | None = None
    name: str | None = None
    url: str | None = None
    num_datasets: int | float | None = None
    num_groups: int | float | None = None
    num_organizations: int | float | None = None
    ckan_version: str | None = None
    extensions: str | None = None


class EcosystemExtensions(BaseModel):
    """Model representing a CKAN Ecosystem extension record."""

    tstamp: str | None = None
    repository_name: str | None = None
    url: str | None = None
    forks_count: int | float | None = None
    total_releases: int | float | None = None
    latest_release: str | None = None
    release_date: str | None = None
    stars: int | float | None = None
    open_issues: int | float | None = None
    contributors_count: int | float | None = None
    discussions: str | None = None
