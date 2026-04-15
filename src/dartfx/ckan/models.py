"""Pydantic models for CKAN entities and server metadata."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ServerInfo(BaseModel):
    """Represents high-level metadata about a CKAN server."""

    model_config = ConfigDict(extra="ignore")

    ckan_version: str | None = None
    site_title: str | None = None
    site_description: str | None = None
    site_url: str | None = None
    extensions: list[str] = Field(default_factory=list)


class ServerStats(BaseModel):
    """Represents aggregate counts available from a CKAN server."""

    model_config = ConfigDict(extra="ignore")

    dataset_count: int = 0
    organization_count: int = 0
    group_count: int = 0
    project_count: int = 0
    resource_count: int | None = None
    user_count: int | None = None


class Tag(BaseModel):
    """Represents a CKAN tag."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    name: str
    display_name: str | None = None
    state: str | None = None
    vocabulary_id: str | None = None


class Resource(BaseModel):
    """Represents a CKAN dataset resource."""

    model_config = ConfigDict(extra="ignore")

    id: str
    package_id: str | None = Field(default=None)
    name: str | None = None
    description: str | None = None
    url: str | None = None
    format: str | None = None
    size: int | None = None
    mimetype: str | None = None
    mimetype_inner: str | None = None
    created: datetime | None = None
    last_modified: datetime | None = None
    metadata_modified: datetime | None = None
    cache_url: str | None = None
    cache_last_updated: datetime | None = None
    hash: str | None = None
    state: str | None = None
    position: int | None = None
    url_type: str | None = None
    resource_type: str | None = None
    datastore_active: bool = False
    availability: str | None = None
    license: str | None = None


class Organization(BaseModel):
    """Represents a CKAN organization."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    title: str | None = None
    description: str | None = None
    image_url: str | None = None
    created: datetime | None = None
    state: str | None = None
    approval_status: str | None = None
    is_organization: bool = True
    type: str | None = None


class Dataset(BaseModel):
    """Represents a CKAN dataset/package."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    title: str | None = None
    notes: str | None = None
    type: str | None = "dataset"
    state: str | None = None
    private: bool = False
    isopen: bool = False
    author: str | None = None
    author_email: str | None = None
    maintainer: str | None = None
    maintainer_email: str | None = None
    creator_user_id: str | None = None
    owner_org: str | None = None
    metadata_created: datetime | None = None
    metadata_modified: datetime | None = None
    license_id: str | None = None
    license_title: str | None = None
    license_url: str | None = None
    organization: Organization | None = None
    resources: list[Resource] = Field(default_factory=list)
    tags: list[Tag] = Field(default_factory=list)
    groups: list[dict] = Field(default_factory=list)
    extras: list[dict] = Field(default_factory=list)
    num_resources: int = 0
    num_tags: int = 0
    url: str | None = None
    version: str | None = None
    relationships_as_object: list[dict] = Field(default_factory=list)
    relationships_as_subject: list[dict] = Field(default_factory=list)


class HealthCheckResponse(BaseModel):
    """Represents a health check result for a CKAN server."""

    model_config = ConfigDict(extra="ignore")

    healthy: bool
    checked_at: datetime
    message: str | None = None
